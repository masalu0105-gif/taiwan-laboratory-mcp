"""Automatic CDC roster update (owner 2026-09-15: 「A 開始做疾管署」, A being automatic like NHI/TFDA).

A new roster version replaces the served one only when every automated check passes. Otherwise
the served version keeps serving, marked as having a newer candidate, and the daily schedule
emails the owner. The golden cases and the full-table comparison read the ODS with their own DOM
parser instead of the importer, so an importer bug cannot confirm itself.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

from .canonical import canonical_json_bytes
from .cdc_source import (
    CDC_LABS_LANDING_URL,
    _read_cdc_labs_serving,
    _read_hashed_raw,
    run_cdc_labs_upstream_check,
)
from .importers.cdc_labs import (
    CDC_LABS_AUTO_REVIEW_PROTOCOL_ID,
    CDC_LABS_AUTO_REVIEW_PROTOCOL_VERSION,
    CDC_LABS_DATASET_NAME,
    CDC_LABS_PRIMARY_ARTIFACT_ID,
    CDC_LABS_SERVING_GATES,
    CDC_LABS_TABLE,
    active_cdc_labs_transform,
    build_official_cdc_labs_snapshot,
)
from .importers.cdc_ods import (
    CDC_LABS_COLUMNS,
    CDC_LABS_FIELD_NAMES,
    CDC_LABS_SOURCE_ID,
    ODS_MIMETYPE,
    parse_cdc_labs_ods,
)

AUTO_REVIEWER_ID = "automated-check:cdc-labs-auto-update"
AUTO_REVIEWER_ROLE = "automated_checker_delegated_by_owner"
MINIMUM_GOLDEN_CASES = 10
TARGET_GOLDEN_CASES = 12
_TAIPEI = timezone(timedelta(hours=8))
_TABLE = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
_WIDTH = len(CDC_LABS_COLUMNS)
# The yearly proficiency testing review column changes by design; its blank rate is no drift signal.
_DRIFT_COLUMNS = CDC_LABS_COLUMNS[:-1]
_COMMENTS = {
    "ODS-R1-SOURCE": (
        "自動檢查（專案負責人 2026-09-15 選 A：疾管署新版照健保、食藥署自動換版）：附件由官方認可機構頁"
        "以名稱挑選，下載檔名與附件名稱相同，工作表名稱帶同一個名冊版本；fetch.json 的大小與 SHA-256 "
        "與原始檔相符。"
    ),
    "ODS-R1-STRUCTURE": (
        "自動檢查：12 欄表頭相符；資料列數與證號數變動不超過 10%；主要欄位空白比例上升不超過 2 個百分點；"
        "另寫的解析器挑出的驗收題全部通過；換版前以另寫的解析器逐列比對資料庫 0 筆不符"
        "（cdc-labs-auto-roundtrip）。"
    ),
    "ODS-R1-CONTENT": (
        "自動檢查：讀名冊的規則（解析、欄位、正規化）與服務中版本相同，沿用 cdc-labs-r1-ai-review/1 "
        "審過的呈現方式；查詢結果照舊帶顯名、名冊版本與「非疾管署官方服務」說明。"
    ),
    "PUB-R1-OWNER": (
        "自動發布：只限本機 MCP 服務，由正式安裝版執行；任何檢查沒過就不換版、繼續服務原版並寄信通知。"
        "GitHub 下載包不含疾管署資料。"
    ),
}


class AutoUpdateError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _row_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _cell_text(cell: ElementTree.Element) -> str:
    def inline(node: ElementTree.Element) -> str:
        parts = [node.text or ""]
        for child in node:
            if child.tag == _TEXT + "s":
                parts.append(" " * int(child.get(_TEXT + "c", "1")))
            elif child.tag == _TEXT + "tab":
                parts.append("\t")
            elif child.tag == _TEXT + "line-break":
                parts.append("\n")
            else:
                parts.append(inline(child))
            parts.append(child.tail or "")
        return "".join(parts)

    return "\n".join(inline(paragraph) for paragraph in cell.findall(_TEXT + "p"))


def independent_roster_rows(payload: bytes) -> tuple[str, list[dict[str, Any]]]:
    """Whole-DOM reading of the roster sheet; a covered cell takes the value of its anchor above."""

    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.read("mimetype") != ODS_MIMETYPE:
                raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "mimetype")
            content = archive.read("content.xml")
        # The importer already parsed this file within its limits; entity declarations stay out.
        if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
            raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "doctype")
        root = ElementTree.fromstring(content)
        sheets = [
            sheet
            for sheet in root.iter(_TABLE + "table")
            if sheet.get(_TABLE + "name", "").endswith("名冊")
        ]
        if len(sheets) != 1:
            raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "roster sheet count")
        sheet = sheets[0]
        grid: list[tuple[int, list[tuple[bool, str, int]]]] = []
        row_number = 0
        for row in sheet.findall(_TABLE + "table-row"):
            repeat = int(row.get(_TABLE + "number-rows-repeated", "1"))
            cells: list[tuple[bool, str, int]] = []
            for cell in row:
                count = int(cell.get(_TABLE + "number-columns-repeated", "1"))
                covered = cell.tag == _TABLE + "covered-table-cell"
                value = "" if covered else _cell_text(cell)
                span = int(cell.get(_TABLE + "number-rows-spanned", "1"))
                cells.extend([(covered, value, span)] * min(count, _WIDTH - len(cells)))
                if len(cells) >= _WIDTH:
                    break
            cells.extend([(False, "", 1)] * (_WIDTH - len(cells)))
            if all(not covered and not value for covered, value, _ in cells):
                row_number += repeat
                continue
            for _ in range(repeat):
                row_number += 1
                grid.append((row_number, cells))
        headers = [
            index
            for index, (_, cells) in enumerate(grid)
            if tuple(value for _, value, _ in cells) == CDC_LABS_COLUMNS
        ]
        if not headers:
            raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "header")
        anchors: dict[int, tuple[str, int]] = {}
        rows = []
        for number, cells in grid[headers[0] + 1 :]:
            values = []
            for column, (covered, value, span) in enumerate(cells):
                if covered:
                    anchor_value, remaining = anchors.get(column, ("", 0))
                    if remaining <= 0:
                        raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", f"row {number}")
                    anchors[column] = (anchor_value, remaining - 1)
                    values.append(anchor_value)
                else:
                    anchors[column] = (value, span - 1)
                    values.append(value)
            rows.append(
                {
                    "expanded_row_number": number,
                    "values": values,
                    "inherited_columns": [i for i, (covered, _, _) in enumerate(cells) if covered],
                    "row_sha256": _row_hash(values),
                }
            )
    except (zipfile.BadZipFile, KeyError, ValueError, ElementTree.ParseError) as exc:
        if isinstance(exc, AutoUpdateError):
            raise
        raise AutoUpdateError("INDEPENDENT_PARSE_FAILED") from exc
    return sheet.get(_TABLE + "name", ""), rows


def verify_cdc_labs_roundtrip(db_path: Path, payload: bytes) -> dict[str, Any]:
    """Compare every curated row with an independent parse of the raw ODS; raise on any difference."""

    sheet_name, rows = independent_roster_rows(payload)
    connection = sqlite3.connect(f"file:{quote(db_path.as_posix(), safe='/:')}?mode=ro", uri=True)
    try:
        stored = connection.execute(
            "SELECT expanded_row_number, sheet_name, source_row_sha256, "
            + ", ".join(CDC_LABS_FIELD_NAMES)
            + f" FROM {CDC_LABS_TABLE} ORDER BY expanded_row_number"
        ).fetchall()
    finally:
        connection.close()
    expected = [
        (row["expanded_row_number"], sheet_name, row["row_sha256"], *row["values"]) for row in rows
    ]
    mismatched = [want[0] for want, have in zip(expected, stored) if tuple(have) != want]
    if mismatched or len(expected) != len(stored) or not expected:
        raise AutoUpdateError("ROUNDTRIP_MISMATCH", str(mismatched[:5]))
    return {
        "report": "cdc-labs-auto-roundtrip-v1",
        "rows_compared": len(expected),
        "mismatches": 0,
        "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "result": "passed",
    }


def select_cdc_labs_golden_cases(
    payload: bytes,
    *,
    artifact_relative: str,
    discovery: dict[str, Any],
    reviewed_at: datetime,
) -> list[dict[str, Any]]:
    """Pick rows for the reviewed coverage list first, then evenly spaced rows, up to twelve."""

    sheet_name, rows = independent_roster_rows(payload)
    if len(rows) < MINIMUM_GOLDEN_CASES:
        raise AutoUpdateError("GOLDEN_CASES_UNAVAILABLE")
    certificates = Counter(row["values"][0] for row in rows)
    keys = Counter(tuple(row["values"][i] for i in (0, 4, 6, 7)) for row in rows)
    criteria = [
        lambda row: certificates[row["values"][0]] > 1,
        lambda row: bool(row["inherited_columns"]),
        lambda row: row["values"][11][4:5] == "/",
        lambda row: row["values"][11] == "無需能力試驗",
        lambda row: row["values"][11] == "",
        lambda row: keys[tuple(row["values"][i] for i in (0, 4, 6, 7))] > 1,
        lambda row: row["values"][4].startswith("0") or not row["values"][4].isdigit(),
    ]
    chosen: dict[int, dict[str, Any]] = {}
    for test in criteria:
        match = next(
            (row for row in rows if row["expanded_row_number"] not in chosen and test(row)), None
        )
        if match is not None:
            chosen[match["expanded_row_number"]] = match
    for row in rows[:: max(len(rows) // TARGET_GOLDEN_CASES, 1)]:
        if len(chosen) >= TARGET_GOLDEN_CASES:
            break
        chosen.setdefault(row["expanded_row_number"], row)

    transform = active_cdc_labs_transform()
    raw_sha256 = hashlib.sha256(payload).hexdigest()
    return [
        {
            "golden_case_schema_version": 1,
            "case_id": f"CDC-LABS-AUTO-{serial:03d}",
            "source_id": CDC_LABS_SOURCE_ID,
            "acceptance_id": "LAB-02",
            "source_title": CDC_LABS_DATASET_NAME,
            "official_landing_url": discovery["landing_url"],
            "official_version_or_modified_at": discovery["roster_version_raw"],
            "official_source": True,
            "artifact_id": CDC_LABS_PRIMARY_ARTIFACT_ID,
            "raw_artifact_sha256": raw_sha256,
            "evidence_data_root_relative_path": artifact_relative,
            "fixture_file": None,
            "fixture_sha256": None,
            "transform": transform,
            "input": {"certificate_no": row["values"][0]},
            "source_locator": {
                "locator_type": "ods_row",
                "sheet_name": sheet_name,
                "expanded_row_number": number,
            },
            "source_row_sha256": row["row_sha256"],
            "expected_status": "ok",
            "expected_fields": dict(zip(CDC_LABS_FIELD_NAMES, row["values"])),
            "expected_warnings": [],
            "reviewer_id": AUTO_REVIEWER_ID,
            "reviewer_role": AUTO_REVIEWER_ROLE,
            "identity_assurance": "local_asserted",
            "reviewed_at": reviewed_at.astimezone(_TAIPEI).isoformat(),
            "review_status": "approved",
        }
        for serial, (number, row) in enumerate(sorted(chosen.items()), start=1)
    ]


def summarize_roster(payload: bytes) -> dict[str, Any]:
    parsed = parse_cdc_labs_ods(payload)
    blanks: Counter[str] = Counter()
    for row in parsed.rows:
        blanks.update(
            column for column, value in zip(CDC_LABS_COLUMNS, row.values) if not value.strip()
        )
    return {
        "rows": len(parsed.rows),
        "distinct_certificates": len({row.values[0] for row in parsed.rows}),
        "empty_value_counts": {column: blanks[column] for column in CDC_LABS_COLUMNS},
    }


def drift_block_reasons(serving: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Reasons a new roster is too different from the served one to publish unattended."""

    def exceeds_ten_percent(before: int, after: int) -> bool:
        return abs(after - before) * 10 > before

    reasons = []
    if exceeds_ten_percent(serving["rows"], candidate["rows"]):
        reasons.append("row_count_change_exceeds_10_percent")
    if exceeds_ten_percent(serving["distinct_certificates"], candidate["distinct_certificates"]):
        reasons.append("certificate_count_change_exceeds_10_percent")
    for column in _DRIFT_COLUMNS:
        before_blank = serving["empty_value_counts"][column]
        after_blank = candidate["empty_value_counts"][column]
        # after/candidate_rows - before/serving_rows > 2 percentage points, in integers.
        if (after_blank * serving["rows"] - before_blank * candidate["rows"]) * 50 > (
            serving["rows"] * candidate["rows"]
        ):
            reasons.append(f"blank_rate_increase:{column}")
    return reasons


def run_cdc_labs_auto_update(
    data_root: Path,
    *,
    actor: str,
    landing_url: str = CDC_LABS_LANDING_URL,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Run the daily roster check and publish a changed version when every check passes."""

    data_root = Path(data_root)
    before = _read_cdc_labs_serving(data_root)
    previous_candidate = before["descriptor"]["latest_candidate_id"] if before else None
    summary = run_cdc_labs_upstream_check(
        data_root, actor=actor, landing_url=landing_url, opener=opener, clock=clock
    )
    summary.update(already_reported=False, block_reasons=[], published_snapshot_id=None)
    if summary["result"] != "changed":
        return summary
    candidate_id = summary["candidate_raw_revision_id"]
    # The same held-back candidate shows up every day until the next roster version.
    summary["already_reported"] = candidate_id == previous_candidate
    try:
        serving = _read_cdc_labs_serving(data_root)
        serving_payload = _read_hashed_raw(
            data_root, serving["artifact_relative"], serving["artifact_sha256"]
        )
        candidate_relative = f"raw/{CDC_LABS_SOURCE_ID}/{candidate_id}/artifacts/source.ods"
        candidate_payload = (data_root / PurePosixPath(candidate_relative)).read_bytes()
        reasons = drift_block_reasons(
            summarize_roster(serving_payload), summarize_roster(candidate_payload)
        )
        serving_transform = dict(serving["transform"])
        serving_transform.pop("application_build_sha256", None)
        if serving_transform != active_cdc_labs_transform():
            reasons.append("roster_reading_rules_changed")
        if reasons:
            summary.update(result="blocked", block_reasons=reasons)
            return summary
        fetch = json.loads(
            (
                data_root / PurePosixPath(f"raw/{CDC_LABS_SOURCE_ID}/{candidate_id}/fetch.json")
            ).read_bytes()
        )
        now = (clock() if clock else datetime.now(timezone.utc)).replace(microsecond=0)
        cases = select_cdc_labs_golden_cases(
            candidate_payload,
            artifact_relative=candidate_relative,
            discovery=fetch["discovery"],
            reviewed_at=now,
        )
        reviewed_at = now.astimezone(_TAIPEI).isoformat()
        reviews = [
            {
                "gate_id": gate_id,
                "reviewer_id": AUTO_REVIEWER_ID,
                "reviewer_role": AUTO_REVIEWER_ROLE,
                "reviewed_at": reviewed_at,
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": _COMMENTS[gate_id],
            }
            for gate_id in CDC_LABS_SERVING_GATES
        ]

        def roundtrip(db_path: Path) -> tuple[str, str, bytes]:
            report = verify_cdc_labs_roundtrip(db_path, candidate_payload)
            return (
                "cdc-labs-auto-roundtrip",
                "cdc-labs-auto-roundtrip.json",
                canonical_json_bytes(report),
            )

        built = build_official_cdc_labs_snapshot(
            data_root,
            raw_revision_id=candidate_id,
            approved_golden_cases=cases,
            owner_reviews=reviews,
            publisher_actor_id=actor,
            review_protocol=(
                CDC_LABS_AUTO_REVIEW_PROTOCOL_ID,
                CDC_LABS_AUTO_REVIEW_PROTOCOL_VERSION,
            ),
            pre_publish_check=roundtrip,
        )
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        summary.update(
            result="auto_publish_failed", error_code=getattr(exc, "code", type(exc).__name__)
        )
        return summary
    summary.update(
        result="published",
        published_snapshot_id=built["snapshot_id"],
        generation=built["generation"],
        rows=built["rows"],
        stale=False,
        stale_reason_codes=[],
    )
    return summary
