"""CDC manual PDF read with PDFium into CdcLayoutV1 (ADR 0003, SDD 10.3).

The PDFs here are generated in the test with pypdfium2 (lines and plain text); the official
manual stays out of the repository. Word table tags cannot be generated this way, so the tag
reading is covered by the real-manual comparison recorded in docs/implementation-notes.md.
"""

import ctypes
import io
import json
from importlib.resources import files

import pytest

pypdfium2 = pytest.importorskip("pypdfium2")
raw = pytest.importorskip("pypdfium2.raw")


def _pdf(draw):
    document = pypdfium2.PdfDocument.new()
    page = document.new_page(595.0, 842.0)
    draw(document, page)
    raw.FPDFPage_GenerateContent(page.raw)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _rect(page, x, y, width, height, color):
    rect = raw.FPDFPageObj_CreateNewRect(x, y, width, height)
    raw.FPDFPageObj_SetFillColor(rect, *color, 255)
    raw.FPDFPath_SetDrawMode(rect, raw.FPDF_FILLMODE_WINDING, False)
    raw.FPDFPage_InsertObject(page.raw, rect)


def _text(document, page, text, x, y):
    obj = raw.FPDFPageObj_NewTextObj(document.raw, b"Helvetica", ctypes.c_float(12))
    value = text.encode("utf-16-le") + b"\x00\x00"
    raw.FPDFText_SetText(
        obj, ctypes.cast(ctypes.create_string_buffer(value), ctypes.POINTER(ctypes.c_ushort))
    )
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y)
    raw.FPDFPage_InsertObject(page.raw, obj)


def _drawing(document, page):
    _rect(page, 100, 700, 200, 0.5, (0, 0, 0))
    _rect(page, 100, 650, 150, 0.5, (255, 0, 0))
    _rect(page, 100, 600, 0.5, 120, (0, 0, 0))
    _text(document, page, "2-8oC P650", 110, 710)


def test_sdd_qual_01_pdfium_identity_and_resource_resolution(monkeypatch):
    from taiwan_lab_mcp.importers import cdc_manual_pdf
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        CDC_MANUAL_LAYOUT_RULES_VERSION,
        CdcManualLayoutError,
    )

    resource = files("taiwan_lab_mcp").joinpath("qualifier_specs", "pdfium-layout-v1.json")
    spec = json.loads(resource.read_text(encoding="utf-8"))
    assert spec == cdc_manual_pdf.load_pdfium_qualifier_spec()
    assert (spec["python_package"], spec["package_version"], spec["pdfium_build"]) == (
        "pypdfium2",
        "5.13.0",
        "153.0.7999.0",
    )
    assert spec["rules_version"] == CDC_MANUAL_LAYOUT_RULES_VERSION
    assert cdc_manual_pdf.cdc_manual_extractor_identity() == {
        "extractor": "pdfium",
        "python_package": "pypdfium2",
        "package_version": "5.13.0",
        "pdfium_build": "153.0.7999.0",
        "rules_version": CDC_MANUAL_LAYOUT_RULES_VERSION,
        "spec_sha256": cdc_manual_pdf.pdfium_qualifier_spec_sha256(),
    }

    monkeypatch.setattr(cdc_manual_pdf, "_installed_package_version", lambda: "5.12.0")
    with pytest.raises(CdcManualLayoutError) as mismatch:
        cdc_manual_pdf.cdc_manual_extractor_identity()
    assert mismatch.value.code == "QUALIFIER_IDENTITY_MISMATCH"

    def missing():
        raise CdcManualLayoutError("QUALIFIER_DEPENDENCY_MISSING")

    monkeypatch.setattr(cdc_manual_pdf, "_installed_package_version", missing)
    with pytest.raises(CdcManualLayoutError) as absent:
        cdc_manual_pdf.extract_cdc_manual_layout(_pdf(_drawing))
    assert absent.value.code == "QUALIFIER_DEPENDENCY_MISSING"


def test_generated_pdf_becomes_a_layout_with_coloured_lines_and_character_boxes():
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.cdc_manual_pdf import (
        cdc_manual_extractor_identity,
        extract_cdc_manual_layout,
    )

    payload = _pdf(_drawing)
    layout = extract_cdc_manual_layout(payload)

    assert layout["layout_schema_version"] == 1
    assert layout["extractor"] == cdc_manual_extractor_identity()
    assert layout["document"] == {"sha256": sha256_bytes(payload), "page_count": 1}
    (page,) = layout["pages"]
    assert (page["page_number"], page["width"], page["height"]) == (1, 595.0, 842.0)
    lines = sorted(
        (round(s["x0"]), round(s["y0"]), round(s["x1"]), round(s["y1"]), s["color"])
        for s in page["segments"]
    )
    # Page coordinates run from the top-left corner like the parser expects.
    assert lines == [
        (100, 122, 100, 242, [0, 0, 0]),
        (100, 142, 300, 142, [0, 0, 0]),
        (100, 192, 250, 192, [255, 0, 0]),
    ]
    assert "".join(char["text"] for char in page["chars"]) == "2-8oC P650"
    first = page["chars"][0]
    assert 109 < first["x0"] < first["x1"] < 120 and 120 < first["y0"] < first["y1"] < 135
    assert (page["table_rows"], page["marked_content"]) == ([], [])


def test_bytes_that_are_not_a_pdf_are_rejected():
    from taiwan_lab_mcp.importers.cdc_manual_layout import CdcManualLayoutError
    from taiwan_lab_mcp.importers.cdc_manual_pdf import extract_cdc_manual_layout

    with pytest.raises(CdcManualLayoutError) as error:
        extract_cdc_manual_layout(b"%PDF-1.7 but not really a document")
    assert error.value.code == "PDF_UNREADABLE"
