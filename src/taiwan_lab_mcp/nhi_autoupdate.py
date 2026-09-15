"""Automatic NHI updates (owner 2026-09-15: 「好，那健保新版也改成自動更新」).

A new upstream CSV replaces the served version only when every automated check passes.
Otherwise the approved version keeps serving, marked as having a newer candidate, and the
daily schedule emails the owner. The checks below parse the CSV with their own code instead
of the importer, so a parser bug cannot confirm itself.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .canonical import canonical_json_bytes
from .importers.nhi import (
    AUTO_REVIEW_PROTOCOL_ID,
    AUTO_REVIEW_PROTOCOL_VERSION,
    OWNER_SERVING_GATES,
    _packaged_rule_bundles,
    active_nhi_transform,
    build_official_nhi_snapshot,
)
from .sync import _read_hashed_raw, _read_serving_state, run_nhi_upstream_check

AUTO_REVIEWER_ID = "automated-check:nhi-auto-update"
AUTO_REVIEWER_ROLE = "automated_checker_delegated_by_owner"
MINIMUM_GOLDEN_CASES = 10
_TAIPEI = timezone(timedelta(hours=8))
_HEADER = [
    "診療項目代碼",
    "健保支付點數",
    "生效起日",
    "生效迄日",
    "英文項目名稱",
    "中文項目名稱",
    "備註",
]
_SENTINEL = "29101231"
_COMMENTS = {
    "NHI-R1-SOURCE": (
        "自動檢查（專案負責人 2026-09-15 選擇自動更新）：metadata 發布機關代號、識別碼、授權代碼"
        "與確認值相同；CSV 由 data.gov.tw metadata 指到的 info.nhi.gov.tw HTTPS 網址下載，"
        "fetch.json 的大小與 SHA-256 與 raw 檔相符。"
    ),
    "NHI-R1-SCHEMA": (
        "自動檢查：7 欄 header 與逐列格式檢查通過；資料列數與代碼數變動不超過 10%；英文名稱空白比例"
        "上升不超過 2 個百分點；獨立解析挑出的驗收題全部通過；換版前以獨立解析逐列比對資料庫 0 筆不符"
        "（nhi-auto-roundtrip）。"
    ),
    "PUB-R1-OWNER": (
        "自動發布：只限本機 MCP 服務，由正式安裝版執行；任何檢查沒過就不換版、繼續服務原版並寄信通知；"
        "沒有檢驗範圍判定的新代碼維持未判定並列在通知信；不更動 GitHub Release 下載包。"
    ),
}


class AutoUpdateError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold().strip())


def _independent_rows(payload: bytes) -> Iterator[tuple[int, list[str]]]:
    try:
        reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""), strict=True)
        if next(reader) != _HEADER:
            raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "header")
        for number, values in enumerate(reader, start=2):
            if len(values) != len(_HEADER):
                raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", f"row {number}")
            yield number, values
    except (UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise AutoUpdateError("INDEPENDENT_PARSE_FAILED") from exc


def _row_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _scope_statuses(scope_bundle_bytes: bytes) -> dict[str, str]:
    bundle = json.loads(scope_bundle_bytes.decode("utf-8-sig"))
    return {
        _normalize(entry["code"]): entry["scope_status"]
        for entry in bundle["entries"]
        if entry["decision_status"] == "approved"
    }


def verify_nhi_roundtrip(
    db_path: Path, payload: bytes, scope_bundle_bytes: bytes
) -> dict[str, Any]:
    """Compare every curated row with an independent parse of the raw CSV; raise on any difference."""

    scopes = _scope_statuses(scope_bundle_bytes)
    connection = sqlite3.connect(f"file:{quote(db_path.as_posix(), safe='/:')}?mode=ro", uri=True)
    mismatched_rows: list[int] = []
    compared = 0
    try:
        cursor = connection.execute(
            "SELECT source_row_number, source_row_sha256, code_raw, points_raw, points, "
            "effective_start_raw, effective_end_raw, name_en_raw, name_zh_raw, note_raw, "
            "scope_status FROM nhi_fee ORDER BY source_row_number"
        )
        for number, values in _independent_rows(payload):
            compared += 1
            code, points, start, end, name_en, name_zh, note = values
            expected = (
                number,
                _row_hash(values),
                code,
                points,
                int(points, 10),
                start,
                end,
                name_en or None,
                name_zh or None,
                note or None,
                scopes.get(_normalize(code), "review_pending"),
            )
            stored = cursor.fetchone()
            if stored is None or tuple(stored) != expected:
                mismatched_rows.append(number)
                if len(mismatched_rows) >= 20:
                    break
        extra_rows = cursor.fetchone() is not None
    finally:
        connection.close()
    if mismatched_rows or extra_rows or compared == 0:
        raise AutoUpdateError("ROUNDTRIP_MISMATCH", str(mismatched_rows[:5]))
    return {
        "report": "nhi-auto-roundtrip-v1",
        "rows_compared": compared,
        "mismatches": 0,
        "csv_sha256": hashlib.sha256(payload).hexdigest(),
        "scope_rules_sha256": hashlib.sha256(scope_bundle_bytes).hexdigest(),
        "result": "passed",
    }


def select_nhi_golden_cases(
    payload: bytes,
    *,
    artifact_relative: str,
    official_modified_at: str | None,
    scope_bundle_bytes: bytes,
    reviewed_at: datetime,
) -> list[dict[str, Any]]:
    """Pick at least ten rows (coverage list first, then evenly spaced rows) with expected values."""

    scopes = _scope_statuses(scope_bundle_bytes)
    rows = list(_independent_rows(payload))
    if len(rows) < MINIMUM_GOLDEN_CASES:
        raise AutoUpdateError("GOLDEN_CASES_UNAVAILABLE")

    def scope(values: list[str]) -> str:
        return scopes.get(_normalize(values[0]), "review_pending")

    criteria = [
        lambda v: v[0].startswith("0"),
        lambda v: v[1] == "0",
        lambda v: "\n" in v[6],
        lambda v: v[3] == _SENTINEL,
        lambda v: v[3] != _SENTINEL,
        lambda v: scope(v) == "in_scope",
        lambda v: scope(v) == "out_of_scope",
        lambda v: scope(v) == "review_pending",
        lambda v: v[4] == "",
    ]
    chosen: dict[int, list[str]] = {}
    for test in criteria:
        match = next(((n, v) for n, v in rows if n not in chosen and test(v)), None)
        if match is not None:
            chosen[match[0]] = match[1]
    for index in range(len(rows)):
        if len(chosen) >= MINIMUM_GOLDEN_CASES:
            break
        number, values = rows[index * len(rows) // MINIMUM_GOLDEN_CASES % len(rows)]
        chosen.setdefault(number, values)
    for number, values in rows:
        if len(chosen) >= MINIMUM_GOLDEN_CASES:
            break
        chosen.setdefault(number, values)

    warnings = (
        ["coverage_review_incomplete"]
        if any(scope(values) == "review_pending" for _, values in rows)
        else []
    )
    transform = active_nhi_transform()
    csv_sha256 = hashlib.sha256(payload).hexdigest()
    cases = []
    for serial, number in enumerate(sorted(chosen), start=1):
        code, points, start, end, name_en, name_zh, note = chosen[number]
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"NHI-AUTO-{serial:03d}",
                "source_id": "nhi_fee",
                "acceptance_id": "NHI-01",
                "source_title": "醫療服務給付項目及支付標準(csv檔)",
                "official_landing_url": "https://data.gov.tw/dataset/174450",
                "official_version_or_modified_at": official_modified_at,
                "official_source": True,
                "artifact_id": "nhi-primary-csv",
                "raw_artifact_sha256": csv_sha256,
                "evidence_data_root_relative_path": artifact_relative,
                "fixture_file": None,
                "fixture_sha256": None,
                "transform": transform,
                "input": {"code": code},
                "source_locator": {"locator_type": "nhi_row", "source_row_number": number},
                "source_row_sha256": _row_hash(chosen[number]),
                "expected_status": "ok",
                "expected_fields": {
                    "code_raw": code,
                    "points_raw": points,
                    "points": int(points, 10),
                    "effective_start_raw": start,
                    "effective_end_raw": end,
                    "possible_open_end_sentinel": end == _SENTINEL,
                    "name_zh_raw": name_zh or None,
                    "name_en_raw": name_en or None,
                    "note_raw": note or None,
                    "scope_status": scopes.get(_normalize(code), "review_pending"),
                },
                "expected_warnings": warnings,
                "reviewer_id": AUTO_REVIEWER_ID,
                "reviewer_role": AUTO_REVIEWER_ROLE,
                "identity_assurance": "local_asserted",
                "reviewed_at": reviewed_at.astimezone(_TAIPEI).isoformat(),
                "review_status": "approved",
            }
        )
    return cases


def nhi_drift_block_reasons(serving_payload: bytes, candidate_payload: bytes) -> list[str]:
    """Reasons a new version is too different from the served one to publish unattended."""

    def counts(payload: bytes) -> tuple[int, int, int]:
        rows = 0
        codes: set[str] = set()
        blank_english = 0
        for _, values in _independent_rows(payload):
            rows += 1
            codes.add(_normalize(values[0]))
            blank_english += values[4] == ""
        return rows, len(codes), blank_english

    def exceeds_ten_percent(before: int, after: int) -> bool:
        return abs(after - before) * 10 > before

    serving_rows, serving_codes, serving_blank = counts(serving_payload)
    candidate_rows, candidate_codes, candidate_blank = counts(candidate_payload)
    reasons = []
    if exceeds_ten_percent(serving_rows, candidate_rows):
        reasons.append("row_count_change_exceeds_10_percent")
    if exceeds_ten_percent(serving_codes, candidate_codes):
        reasons.append("code_count_change_exceeds_10_percent")
    # candidate_blank/candidate_rows - serving_blank/serving_rows > 2 percentage points.
    if (candidate_blank * serving_rows - serving_blank * candidate_rows) * 50 > (
        serving_rows * candidate_rows
    ):
        reasons.append("blank_rate_increase:英文項目名稱")
    return reasons


def run_nhi_auto_update(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    actor: str,
    metadata_url: str | None = None,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Run the daily NHI check and publish a changed version when every check passes."""

    data_root = Path(data_root)
    before = _read_serving_state(data_root)
    previous_candidate = before["descriptor"]["latest_candidate_id"] if before else None
    summary = run_nhi_upstream_check(
        data_root,
        expected_publisher_oid=expected_publisher_oid,
        actor=actor,
        metadata_url=metadata_url,
        opener=opener,
        clock=clock,
    )
    summary.update(
        already_reported=False,
        block_reasons=[],
        published_snapshot_id=None,
        new_codes_without_scope=[],
    )
    if summary["result"] != "changed":
        return summary
    candidate_id = summary["candidate_raw_revision_id"]
    # The same held-back candidate shows up every day until the next upstream version.
    summary["already_reported"] = candidate_id == previous_candidate
    try:
        serving = _read_serving_state(data_root)
        serving_payload = _read_hashed_raw(
            data_root, serving["artifact_relative"], serving["artifact_sha256"]
        )
        candidate_relative = f"raw/nhi_fee/{candidate_id}/artifacts/source.csv"
        candidate_payload = (data_root / PurePosixPath(candidate_relative)).read_bytes()
        scope_bundle_bytes, _ = _packaged_rule_bundles()
        scopes = _scope_statuses(scope_bundle_bytes)
        serving_codes = {_normalize(values[0]) for _, values in _independent_rows(serving_payload)}
        summary["new_codes_without_scope"] = [
            values[0]
            for _, values in _independent_rows(candidate_payload)
            if _normalize(values[0]) not in serving_codes and _normalize(values[0]) not in scopes
        ]
        reasons = nhi_drift_block_reasons(serving_payload, candidate_payload)
        if reasons:
            summary.update(result="blocked", block_reasons=reasons)
            return summary
        fetch = json.loads(
            (data_root / PurePosixPath(f"raw/nhi_fee/{candidate_id}/fetch.json")).read_bytes()
        )
        now = (clock() if clock else datetime.now(timezone.utc)).replace(microsecond=0)
        cases = select_nhi_golden_cases(
            candidate_payload,
            artifact_relative=candidate_relative,
            official_modified_at=(fetch.get("discovery") or {}).get("official_modified_at_raw"),
            scope_bundle_bytes=scope_bundle_bytes,
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
            for gate_id in OWNER_SERVING_GATES
        ]

        def roundtrip(db_path: Path) -> tuple[str, str, bytes]:
            report = verify_nhi_roundtrip(db_path, candidate_payload, scope_bundle_bytes)
            return "nhi-auto-roundtrip", "nhi-auto-roundtrip.json", canonical_json_bytes(report)

        built = build_official_nhi_snapshot(
            data_root,
            raw_revision_id=candidate_id,
            approved_golden_cases=cases,
            owner_reviews=reviews,
            publisher_actor_id=actor,
            review_protocol=(AUTO_REVIEW_PROTOCOL_ID, AUTO_REVIEW_PROTOCOL_VERSION),
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
        stale=False,
        stale_reason_codes=[],
    )
    return summary
