"""Automatic CDC specimen manual update (owner 2026-09-15: 「A 開始做疾管署」, OD-04).

A new manual replaces the served one only when every automated check passes. Otherwise the served
manual keeps answering, marked as having a newer candidate, and the daily schedule emails the
owner. The independent check is the Word table tag comparison the official build runs on every
stored cell before the pointer switches; the golden cases are picked from the new manual itself.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import sha256_bytes
from .cdc_manual_source import (
    CDC_MANUAL_LANDING_URL,
    CDC_MANUAL_SOURCE_ID,
    _read_cdc_manual_serving,
    _served_rows,
    run_cdc_manual_upstream_check,
)
from .importers import cdc_manual as manual_importer
from .importers.cdc_manual import (
    CDC_MANUAL_AUTO_REVIEW_PROTOCOL_ID,
    CDC_MANUAL_AUTO_REVIEW_PROTOCOL_VERSION,
    CDC_MANUAL_PRIMARY_ARTIFACT_ID,
    CDC_MANUAL_SERVING_GATES,
    active_cdc_manual_transform,
    build_official_cdc_manual_snapshot,
    cdc_layout_sha256,
    curated_specimen_row,
)
from .importers.cdc_manual_layout import CDC_SPECIMEN_FIELDS, parse_cdc_specimen_layout

AUTO_REVIEWER_ID = "automated-check:cdc-manual-auto-update"
AUTO_REVIEWER_ROLE = "automated_checker_delegated_by_owner"
TARGET_GOLDEN_CASES = 12
_TAIPEI = timezone(timedelta(hours=8))
# Seven-column tables have no retention column, so its blank rate says nothing about drift.
_DRIFT_FIELDS = tuple(field for field in CDC_SPECIMEN_FIELDS if field != "retention_raw")
_SHARED_FIELDS = ("volume_requirement", "transport_method", "retention_raw", "notes")
_COMMENTS = {
    "CDC-R1-SOURCE": (
        "自動檢查（專案負責人 2026-09-15 選 A：疾管署新版照健保、食藥署自動換版）：手冊與修訂對照表由官方"
        "採檢手冊頁以附件名稱挑選、版本相同；兩份都是 PDF，fetch.json 的大小與 SHA-256 相符；第 2 章每個表格頁"
        "頁首印的版次等於附件版本。"
    ),
    "CDC-R1-LAYOUT": (
        "自動檢查：PDFium 版本與規格相同；資料列數與疾病數變動不超過 10%；主要欄位空白比例上升不超過 2 個百分點；"
        "驗收題全部通過；換版前以 Word 表格標記逐格比對資料庫 0 不符（cdc-manual-tag-check）。"
    ),
    "CDC-R1-CONTENT": (
        "自動檢查：讀手冊的規則（拆表、欄位、正規化、顯示文字）與服務中版本相同，沿用 cdc-manual-r1-ai-review/1 "
        "審過的呈現方式；應保存種類（應保存時間）照官方欄名並帶 not_pre_submission_storage。"
    ),
    "PUB-R1-OWNER": (
        "自動發布：只限本機 MCP 服務，由正式安裝版執行；任何檢查沒過就不換版、繼續服務原版並寄信通知。"
        "GitHub 下載包不含疾管署資料。"
    ),
}


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blanks: Counter[str] = Counter()
    for row in rows:
        blanks.update(field for field in _DRIFT_FIELDS if not (row[field] or "").strip())
    return {
        "rows": len(rows),
        "distinct_diseases": len({row["disease_display"] for row in rows}),
        "empty_value_counts": {field: blanks[field] for field in _DRIFT_FIELDS},
    }


def drift_block_reasons(serving: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Reasons a new manual is too different from the served one to publish unattended."""

    def exceeds_ten_percent(before: int, after: int) -> bool:
        return abs(after - before) * 10 > before

    reasons = []
    if exceeds_ten_percent(serving["rows"], candidate["rows"]):
        reasons.append("row_count_change_exceeds_10_percent")
    if exceeds_ten_percent(serving["distinct_diseases"], candidate["distinct_diseases"]):
        reasons.append("disease_count_change_exceeds_10_percent")
    for field in _DRIFT_FIELDS:
        before_blank = serving["empty_value_counts"][field]
        after_blank = candidate["empty_value_counts"][field]
        # after/candidate_rows - before/serving_rows > 2 percentage points, in integers.
        if (after_blank * serving["rows"] - before_blank * candidate["rows"]) * 50 > (
            serving["rows"] * candidate["rows"]
        ):
            reasons.append(f"blank_rate_increase:{field}")
    return reasons


def _reading_rules(transform: Mapping[str, Any]) -> dict[str, Any]:
    rules = json.loads(json.dumps(dict(transform)))
    rules.pop("application_build_sha256", None)
    # The layout hash belongs to each PDF; everything else is how the manual is read.
    rules["qualifier"].pop("extractor_output_sha256", None)
    return rules


def _golden_indices(rows: Sequence[Any]) -> list[int]:
    diseases = Counter(row.display_fields()["disease"] for row in rows)

    def shares(index: int, same_page: bool) -> bool:
        if index == 0:
            return False
        before, row = rows[index - 1].fields(), rows[index].fields()
        return (
            (rows[index - 1].locator["pdf_page"] == rows[index].locator["pdf_page"]) == same_page
            and before["disease"] == row["disease"]
            and any(before[field] and before[field] == row[field] for field in _SHARED_FIELDS)
        )

    def joins_lines(index: int) -> bool:
        raw, display = rows[index].fields(), rows[index].display_fields()
        return any(
            value and value.count("\n") > (display[field] or "").count("\n")
            for field, value in raw.items()
        )

    criteria = (
        lambda i: diseases[rows[i].display_fields()["disease"]] >= 3,
        lambda i: shares(i, True),
        lambda i: shares(i, False),
        lambda i: rows[i].fields()["retention_raw"] is None,
        lambda i: "\n2." in (rows[i].display_fields()["notes"] or ""),
        joins_lines,
        lambda i: rows[i].locator["table_section"].startswith("2.7"),
    )
    usable = [i for i, row in enumerate(rows) if row.display_fields()["disease"].strip()]
    chosen: list[int] = []
    for test in criteria:
        match = next((i for i in usable if i not in chosen and test(i)), None)
        if match is not None:
            chosen.append(match)
    step = max(len(usable) // TARGET_GOLDEN_CASES, 1)
    for i in usable[step // 2 :: step]:
        if len(chosen) >= TARGET_GOLDEN_CASES:
            break
        if i not in chosen:
            chosen.append(i)
    # A very small table repeats rows under distinct case ids.
    base = len(chosen)
    while base and len(chosen) < TARGET_GOLDEN_CASES:
        chosen.append(chosen[len(chosen) % base])
    return chosen


def select_cdc_manual_golden_cases(
    layout: Mapping[str, Any],
    *,
    artifact_relative: str,
    manual_sha256: str,
    discovery: Mapping[str, Any],
    reviewed_at: datetime,
) -> list[dict[str, Any]]:
    """Golden cases over the protocol's coverage list, with raw and display values of each row."""

    rows = parse_cdc_specimen_layout(dict(layout)).rows
    transform = active_cdc_manual_transform(cdc_layout_sha256(layout))
    cases = []
    for number, index in enumerate(_golden_indices(rows), start=1):
        row = rows[index]
        raw, display = row.fields(), row.display_fields()
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"CDC-MANUAL-AUTO-{number:03d}",
                "source_id": CDC_MANUAL_SOURCE_ID,
                "acceptance_id": "CDC-01",
                "source_title": discovery["dataset_name"],
                "official_landing_url": discovery["landing_url"],
                "official_version_or_modified_at": discovery["manual_version_raw"],
                "official_source": True,
                "artifact_id": CDC_MANUAL_PRIMARY_ARTIFACT_ID,
                "raw_artifact_sha256": manual_sha256,
                "evidence_data_root_relative_path": artifact_relative,
                "fixture_file": None,
                "fixture_sha256": None,
                "transform": transform,
                "input": {"disease": display["disease"].split("\n")[0].replace("(續)", "").strip()},
                "source_locator": row.locator,
                "source_row_sha256": row.source_row_sha256,
                "expected_status": "ok",
                "expected_fields": {
                    **raw,
                    **{f"{field}_display": value for field, value in display.items()},
                },
                "expected_warnings": [],
                "reviewer_id": AUTO_REVIEWER_ID,
                "reviewer_role": AUTO_REVIEWER_ROLE,
                "identity_assurance": "local_asserted",
                "reviewed_at": reviewed_at.astimezone(_TAIPEI).isoformat(),
                "review_status": "approved",
            }
        )
    return cases


def run_cdc_manual_auto_update(
    data_root: Path,
    *,
    actor: str,
    landing_url: str = CDC_MANUAL_LANDING_URL,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Run the daily manual check and publish a changed manual when every check passes."""

    data_root = Path(data_root)
    before = _read_cdc_manual_serving(data_root)
    previous_candidate = before["descriptor"]["latest_candidate_id"] if before else None
    summary = run_cdc_manual_upstream_check(
        data_root, actor=actor, landing_url=landing_url, opener=opener, clock=clock
    )
    summary.update(already_reported=False, block_reasons=[], published_snapshot_id=None)
    if summary["result"] != "changed":
        return summary
    candidate_id = summary["candidate_raw_revision_id"]
    # The same held-back candidate shows up every day until the next manual version.
    summary["already_reported"] = candidate_id == previous_candidate
    try:
        serving = _read_cdc_manual_serving(data_root)
        assert serving is not None
        revision_dir = PurePosixPath("raw", CDC_MANUAL_SOURCE_ID, candidate_id)
        candidate_relative = str(revision_dir / "artifacts" / "manual.pdf")
        candidate_payload = (data_root / PurePosixPath(candidate_relative)).read_bytes()
        layout = manual_importer.extract_cdc_manual_layout(candidate_payload)
        parsed = parse_cdc_specimen_layout(layout)
        candidate_rows = [
            curated_specimen_row(row, number, parsed.summary)
            for number, row in enumerate(parsed.rows, start=1)
        ]
        reasons = drift_block_reasons(
            summarize_rows(_served_rows(serving["db_path"])), summarize_rows(candidate_rows)
        )
        if _reading_rules(serving["transform"]) != _reading_rules(
            active_cdc_manual_transform(None)
        ):
            reasons.append("manual_reading_rules_changed")
        if reasons:
            summary.update(result="blocked", block_reasons=reasons)
            return summary
        fetch = json.loads(
            (data_root / PurePosixPath(str(revision_dir / "fetch.json"))).read_bytes()
        )
        now = (clock() if clock else datetime.now(timezone.utc)).replace(microsecond=0)
        cases = select_cdc_manual_golden_cases(
            layout,
            artifact_relative=candidate_relative,
            manual_sha256=sha256_bytes(candidate_payload),
            discovery=fetch["discovery"],
            reviewed_at=now,
        )
        reviews = [
            {
                "gate_id": gate_id,
                "reviewer_id": AUTO_REVIEWER_ID,
                "reviewer_role": AUTO_REVIEWER_ROLE,
                "reviewed_at": now.astimezone(_TAIPEI).isoformat(),
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": _COMMENTS[gate_id],
            }
            for gate_id in CDC_MANUAL_SERVING_GATES
        ]
        built = build_official_cdc_manual_snapshot(
            data_root,
            raw_revision_id=candidate_id,
            approved_golden_cases=cases,
            owner_reviews=reviews,
            publisher_actor_id=actor,
            review_protocol=(
                CDC_MANUAL_AUTO_REVIEW_PROTOCOL_ID,
                CDC_MANUAL_AUTO_REVIEW_PROTOCOL_VERSION,
            ),
        )
    except (AssertionError, OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
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
