"""CDC specimen collection manual: read a PDF with PDFium into CdcLayoutV1 (ADR 0003, SDD 10.3).

pypdfium2 is the optional extra ``cdc-manual``; only building the manual data needs it. Before
reading, the installed pypdfium2 and PDFium must equal the packaged qualifier spec. Coordinates
run from the top-left corner. Each page keeps its path boxes with colour, every character box in
PDF stream order with its marked-content id, marked-content boxes and the Word TR/TD tags. No OCR.
"""

from __future__ import annotations

import ctypes
import json
from importlib import metadata
from importlib.resources import files
from typing import Any

from ..canonical import sha256_bytes
from .cdc_manual_layout import CDC_MANUAL_LAYOUT_RULES_VERSION, CdcManualLayoutError

_SPEC_KEYS = frozenset(
    {
        "spec_id",
        "extractor",
        "python_package",
        "package_version",
        "pdfium_build",
        "rules_version",
        "adr",
    }
)
_DIGITS = 3


def _spec_bytes() -> bytes:
    resource = files("taiwan_lab_mcp").joinpath("qualifier_specs", "pdfium-layout-v1.json")
    try:
        return resource.read_bytes()
    except OSError as exc:
        raise CdcManualLayoutError("QUALIFIER_SPEC_INVALID") from exc


def load_pdfium_qualifier_spec() -> dict[str, Any]:
    try:
        spec = json.loads(_spec_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CdcManualLayoutError("QUALIFIER_SPEC_INVALID") from exc
    if (
        not isinstance(spec, dict)
        or set(spec) != _SPEC_KEYS
        or spec["rules_version"] != CDC_MANUAL_LAYOUT_RULES_VERSION
    ):
        raise CdcManualLayoutError("QUALIFIER_SPEC_INVALID")
    return spec


def pdfium_qualifier_spec_sha256() -> str:
    return sha256_bytes(_spec_bytes())


def _installed_package_version() -> str:
    try:
        return metadata.version("pypdfium2")
    except metadata.PackageNotFoundError as exc:
        raise CdcManualLayoutError("QUALIFIER_DEPENDENCY_MISSING") from exc


def _pdfium() -> tuple[Any, Any]:
    try:
        import pypdfium2
        import pypdfium2.raw as raw
    except ImportError as exc:
        raise CdcManualLayoutError("QUALIFIER_DEPENDENCY_MISSING") from exc
    return pypdfium2, raw


def cdc_manual_extractor_identity() -> dict[str, Any]:
    """Return the extractor identity, or raise when pypdfium2 or PDFium differ from the spec."""

    spec = load_pdfium_qualifier_spec()
    version = _installed_package_version()
    pypdfium2, _ = _pdfium()
    build = str(pypdfium2.version.PDFIUM_INFO)
    if version != spec["package_version"] or build != spec["pdfium_build"]:
        raise CdcManualLayoutError("QUALIFIER_IDENTITY_MISMATCH", f"{version} {build}")
    return {
        "extractor": spec["extractor"],
        "python_package": spec["python_package"],
        "package_version": version,
        "pdfium_build": build,
        "rules_version": spec["rules_version"],
        "spec_sha256": pdfium_qualifier_spec_sha256(),
    }


def _number(value: float) -> float:
    return round(float(value), _DIGITS)


def _wide_text(raw: Any, function: Any, element: Any) -> str:
    size = function(element, None, 0)
    if size <= 2:
        return ""
    buffer = ctypes.create_string_buffer(size)
    function(element, buffer, size)
    return buffer.raw[: size - 2].decode("utf-16-le", "replace")


def _read_page(pypdfium2: Any, raw: Any, page: Any, number: int) -> dict[str, Any]:
    width, height = page.get_size()
    segments: list[dict[str, Any]] = []
    marked: dict[int, list[float]] = {}

    def bounds(handle: Any) -> tuple[float, float, float, float]:
        left, bottom, right, top = (ctypes.c_float() for _ in range(4))
        raw.FPDFPageObj_GetBounds(handle, left, bottom, right, top)
        return left.value, height - top.value, right.value, height - bottom.value

    def color(getter: Any, handle: Any) -> list[int] | None:
        r, g, b, a = (ctypes.c_uint() for _ in range(4))
        return [r.value, g.value, b.value] if getter(handle, r, g, b, a) else None

    def walk(count: Any, get: Any, parent: Any) -> None:
        for index in range(count(parent)):
            handle = get(parent, index)
            kind = raw.FPDFPageObj_GetType(handle)
            if kind == raw.FPDF_PAGEOBJ_PATH:
                x0, y0, x1, y1 = bounds(handle)
                segments.append(
                    {
                        "x0": _number(x0),
                        "y0": _number(y0),
                        "x1": _number(x1),
                        "y1": _number(y1),
                        "color": color(raw.FPDFPageObj_GetFillColor, handle)
                        or color(raw.FPDFPageObj_GetStrokeColor, handle),
                    }
                )
            elif kind == raw.FPDF_PAGEOBJ_TEXT:
                mcid = raw.FPDFPageObj_GetMarkedContentID(handle)
                if mcid >= 0:
                    x0, y0, x1, y1 = bounds(handle)
                    box = marked.setdefault(mcid, [x0, y0, x1, y1])
                    box[:] = [min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1)]
            elif kind == raw.FPDF_PAGEOBJ_FORM:
                walk(raw.FPDFFormObj_CountObjects, raw.FPDFFormObj_GetObject, handle)

    walk(raw.FPDFPage_CountObjects, raw.FPDFPage_GetObject, page.raw)

    chars = []
    textpage = page.get_textpage()
    try:
        for index in range(textpage.count_chars()):
            text = textpage.get_text_range(index, 1)
            if text in ("", "\r", "\n"):
                continue
            left, bottom, right, top = textpage.get_charbox(index)
            handle = raw.FPDFText_GetTextObject(textpage.raw, index)
            mcid = raw.FPDFPageObj_GetMarkedContentID(handle) if handle else -1
            chars.append(
                {
                    "text": text,
                    "x0": _number(left),
                    "y0": _number(height - top),
                    "x1": _number(right),
                    "y1": _number(height - bottom),
                    "mcid": mcid if mcid >= 0 else None,
                }
            )
    finally:
        textpage.close()

    table_rows: list[list[list[int] | None]] = []

    def mcids(element: Any) -> list[int]:
        found = [
            raw.FPDF_StructElement_GetMarkedContentIdAtIndex(element, i)
            for i in range(raw.FPDF_StructElement_GetMarkedContentIdCount(element))
        ]
        for i in range(raw.FPDF_StructElement_CountChildren(element)):
            child = raw.FPDF_StructElement_GetChildAtIndex(element, i)
            if child:
                found.extend(mcids(child))
        return [value for value in found if value >= 0]

    def walk_tags(element: Any) -> None:
        if _wide_text(raw, raw.FPDF_StructElement_GetType, element) == "TR":
            row = []
            for i in range(raw.FPDF_StructElement_CountChildren(element)):
                child = raw.FPDF_StructElement_GetChildAtIndex(element, i)
                row.append(mcids(child) if child else None)
            table_rows.append(row)
            return
        for i in range(raw.FPDF_StructElement_CountChildren(element)):
            child = raw.FPDF_StructElement_GetChildAtIndex(element, i)
            if child:
                walk_tags(child)

    tree = raw.FPDF_StructTree_GetForPage(page.raw)
    if tree:
        try:
            for i in range(raw.FPDF_StructTree_CountChildren(tree)):
                element = raw.FPDF_StructTree_GetChildAtIndex(tree, i)
                if element:
                    walk_tags(element)
        finally:
            raw.FPDF_StructTree_Close(tree)
    return {
        "page_number": number,
        "width": _number(width),
        "height": _number(height),
        "segments": segments,
        "chars": chars,
        "marked_content": [
            {
                "mcid": mcid,
                "x0": _number(box[0]),
                "y0": _number(box[1]),
                "x1": _number(box[2]),
                "y1": _number(box[3]),
            }
            for mcid, box in sorted(marked.items())
        ],
        "table_rows": table_rows,
    }


def extract_cdc_manual_layout(payload: bytes) -> dict[str, Any]:
    """Read every page of a manual PDF into CdcLayoutV1; no network, no OCR, no writes."""

    identity = cdc_manual_extractor_identity()
    pypdfium2, raw = _pdfium()
    try:
        document = pypdfium2.PdfDocument(payload)
    except pypdfium2.PdfiumError as exc:
        raise CdcManualLayoutError("PDF_UNREADABLE") from exc
    try:
        pages = []
        for index in range(len(document)):
            page = document[index]
            try:
                pages.append(_read_page(pypdfium2, raw, page, index + 1))
            finally:
                page.close()
    finally:
        document.close()
    return {
        "layout_schema_version": 1,
        "extractor": identity,
        "document": {"sha256": sha256_bytes(payload), "page_count": len(pages)},
        "pages": pages,
    }
