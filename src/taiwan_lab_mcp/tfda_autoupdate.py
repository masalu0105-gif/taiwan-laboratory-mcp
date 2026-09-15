"""Automatic TFDA weekly update (owner 2026-09-15: 「A變成成自動化 我不想花太多心力維護」).

A new upstream version replaces the served one only when every automated check passes.
Otherwise the approved version keeps serving, marked as having a newer candidate, and the
daily schedule emails the owner. The checks below parse the ZIP with their own code instead
of the importer, so a parser bug cannot confirm itself.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from .canonical import canonical_json_bytes
from .importers.tfda import (
    TFDA_AUTO_REVIEW_PROTOCOL_ID,
    TFDA_AUTO_REVIEW_PROTOCOL_VERSION,
    TFDA_SERVING_GATES,
    TFDA_SOURCE_ID,
    active_tfda_transform,
    build_official_tfda_snapshot,
    extract_tfda_csv,
    summarize_tfda_csv,
)
from .rules.tfda import packaged_ivd_registry_bytes
from .tfda_source import _read_hashed_raw, _read_tfda_serving, run_tfda_upstream_check

AUTO_REVIEWER_ID = "automated-check:tfda-auto-update"
AUTO_REVIEWER_ROLE = "automated_checker_delegated_by_owner"
MINIMUM_GOLDEN_CASES = 10
_TAIPEI = timezone(timedelta(hours=8))
_ALLOWED_STATUSES = frozenset({"", "已註銷", "已廢止"})
# Columns whose blank rate may not jump; permit number and validity date are already required.
_KEY_COLUMNS = (
    "中文品名",
    "英文品名",
    "申請商名稱",
    "製造商名稱",
    "醫器主類別一",
    "醫器次類別一",
    "醫療器材級數",
    "製造廠國別",
)
_COLUMNS = (
    ("許可證字號", "license_no_raw"),
    ("註銷狀態", "cancellation_status_raw"),
    ("註銷日期", "cancellation_date_raw"),
    ("註銷理由", "cancellation_reason_raw"),
    ("有效日期", "valid_through_raw"),
    ("發證日期", "issued_on_raw"),
    ("許可證種類", "license_kind_raw"),
    ("舊證字號", "legacy_license_no_raw"),
    ("醫療器材級數", "risk_class_raw"),
    ("通關簽審文件編號", "customs_document_no_raw"),
    ("中文品名", "name_zh_raw"),
    ("英文品名", "name_en_raw"),
    ("效能", "effect_raw"),
    ("劑型", "dosage_form_raw"),
    ("包裝", "package_raw"),
    ("醫器主類別一", "main_category_1_raw"),
    ("醫器次類別一", "sub_category_1_raw"),
    ("醫器主類別二", "main_category_2_raw"),
    ("醫器次類別二", "sub_category_2_raw"),
    ("醫器主類別三", "main_category_3_raw"),
    ("醫器次類別三", "sub_category_3_raw"),
    ("主成分略述", "main_ingredient_raw"),
    ("醫器規格", "specification_raw"),
    ("限制項目", "restriction_raw"),
    ("申請商名稱", "applicant_name_raw"),
    ("申請商地址", "applicant_address_raw"),
    ("申請商統一編號", "applicant_tax_id_raw"),
    ("製造商名稱", "manufacturer_name_raw"),
    ("製造廠廠址", "factory_address_raw"),
    ("製造廠公司地址", "manufacturer_company_address_raw"),
    ("製造廠國別", "manufacturer_country_raw"),
    ("製程", "process_raw"),
    ("異動日期", "changed_on_raw"),
    ("製造許可登錄編號", "manufacturing_registration_no_raw"),
)
_HEADER = [chinese for chinese, _ in _COLUMNS]
_FIELDS = [english for _, english in _COLUMNS]
_CODE = re.compile(r"^([A-P])\.([0-9]{4})(?![0-9])")
_LETTER = re.compile(r"^([A-P])(?![A-Za-z0-9])")
_COMMENTS = {
    "TFDA-R1-SOURCE": (
        "自動檢查（專案負責人 2026-09-15 選擇自動更新）：metadata 發布機關代號、識別碼、授權代碼"
        "與 2026-09-14 確認值相同；ZIP 由 data.gov.tw metadata 指到的 data.fda.gov.tw HTTPS 網址下載，"
        "fetch.json 的大小與 SHA-256 與 raw 檔相符。"
    ),
    "TFDA-R1-SCHEMA": (
        "自動檢查：34 欄 header 相符；資料列數與許可證字號數變動不超過 10%；主要欄位空白比例上升"
        "不超過 2 個百分點；沒有新的註銷狀態值；獨立解析挑出的驗收題全部通過；換版前以獨立解析逐列"
        "比對資料庫 0 筆不符（tfda-auto-roundtrip）。"
    ),
    "PUB-R1-OWNER": (
        "自動發布：只限本機 MCP 服務，由正式安裝版執行；任何檢查沒過就不換版、繼續服務原版並寄信通知。"
    ),
}


class AutoUpdateError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _independent_rows(payload: bytes) -> Iterator[tuple[int, list[str]]]:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = archive.infolist()
            if len(entries) != 1:
                raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "entry count")
            text = archive.read(entries[0]).decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        if next(reader) != _HEADER:
            raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", "header")
        for number, values in enumerate(reader, start=2):
            if len(values) != len(_HEADER):
                raise AutoUpdateError("INDEPENDENT_PARSE_FAILED", f"row {number}")
            yield number, values
    except (zipfile.BadZipFile, UnicodeDecodeError, csv.Error, StopIteration) as exc:
        raise AutoUpdateError("INDEPENDENT_PARSE_FAILED") from exc


def _codes(values: list[str]) -> list[str]:
    found: list[str] = []
    for value in (values[16], values[18], values[20]):
        match = _CODE.match(value.strip())
        if match and f"{match.group(1)}.{match.group(2)}" not in found:
            found.append(f"{match.group(1)}.{match.group(2)}")
    return found


def _letters(values: list[str]) -> str:
    return "".join(
        sorted(
            {
                match.group(1)
                for value in (values[15], values[17], values[19])
                if (match := _LETTER.match(value.strip()))
            }
        )
    )


def _scope(codes: list[str], decisions: dict[str, str]) -> str:
    scopes = [decisions.get(code) for code in codes]
    if not scopes:
        return "unknown"
    if "ambiguous" in scopes or ("included" in scopes and "excluded" in scopes):
        return "ambiguous"
    if "included" in scopes:
        return "included"
    if all(scope == "excluded" for scope in scopes):
        return "excluded"
    return "unknown"


def _row_hash(values: list[str]) -> str:
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _decisions(registry_bytes: bytes) -> dict[str, str]:
    registry = json.loads(registry_bytes.decode("utf-8"))
    return {entry["classification_code"]: entry["ivd_scope"] for entry in registry["entries"]}


def verify_curated_roundtrip(
    db_path: Path, payload: bytes, registry_bytes: bytes
) -> dict[str, Any]:
    """Compare every curated row with an independent parse of the raw ZIP; raise on any difference."""

    decisions = _decisions(registry_bytes)
    columns = ", ".join(
        (
            "source_row_number",
            "source_row_sha256",
            *_FIELDS,
            "classification_codes",
            "main_category_letters",
            "ivd_scope",
        )
    )
    connection = sqlite3.connect(f"file:{quote(db_path.as_posix(), safe='/:')}?mode=ro", uri=True)
    mismatched_rows: list[int] = []
    labels: Counter[str] = Counter()
    compared = 0
    try:
        cursor = connection.execute(
            f"SELECT {columns} FROM tfda_source_row ORDER BY source_row_number"
        )
        for number, values in _independent_rows(payload):
            compared += 1
            codes = _codes(values)
            scope = _scope(codes, decisions)
            labels[scope] += 1
            expected = (
                number,
                _row_hash(values),
                *values,
                json.dumps(codes),
                _letters(values),
                scope,
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
        "report": "tfda-auto-roundtrip-v1",
        "rows_compared": compared,
        "mismatches": 0,
        "ivd_scope_counts": dict(sorted(labels.items())),
        "zip_sha256": hashlib.sha256(payload).hexdigest(),
        "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "result": "passed",
    }


def _consistency_warnings(values: list[str]) -> list[str]:
    status = values[1].strip()
    if status == "":
        return ["cancellation_date_without_status"] if values[2] else []
    if status in {"已註銷", "已廢止"}:
        return [] if values[2] else ["cancellation_status_without_date"]
    return ["unknown_cancellation_status"]


def select_golden_cases(
    payload: bytes,
    *,
    raw_revision_id: str,
    artifact_relative: str,
    official_modified_at: str | None,
    registry_bytes: bytes,
    reviewed_at: datetime,
) -> dict[str, Any]:
    """Pick at least ten rows (coverage list first, then evenly spaced rows) with expected values."""

    decisions = _decisions(registry_bytes)
    as_of = reviewed_at.astimezone(_TAIPEI).date()
    total = 0
    permit_rows: Counter[str] = Counter()
    permit_makers: dict[str, set[str]] = {}
    for _, values in _independent_rows(payload):
        total += 1
        permit_rows[values[0]] += 1
        permit_makers.setdefault(values[0], set()).add(values[27])
    if total < MINIMUM_GOLDEN_CASES:
        raise AutoUpdateError("GOLDEN_CASES_UNAVAILABLE")

    def valid_through(values: list[str]) -> date:
        return datetime.strptime(values[4], "%Y/%m/%d").date()

    def legacy(values: list[str]) -> bool:
        return not _codes(values) and any(
            values[index].strip()[:1].isdigit() for index in (15, 16, 17, 18)
        )

    criteria = [
        lambda v: (
            not v[1].strip()
            and not v[2]
            and valid_through(v) >= as_of
            and _scope(_codes(v), decisions) == "included"
        ),
        lambda v: v[1] == "已註銷" and bool(v[2]),
        lambda v: v[1] == "已廢止" and bool(v[2]),
        lambda v: not v[1].strip() and bool(v[2]),
        lambda v: bool(v[1].strip()) and not v[2],
        lambda v: not v[1].strip() and not v[2] and valid_through(v) < as_of,
        lambda v: _scope(_codes(v), decisions) == "excluded",
        legacy,
        lambda v: not _codes(v) and not legacy(v) and bool(v[15].strip()),
        lambda v: bool(_codes(v)) and _codes(v)[0][0] not in "ABC",
        lambda v: v[26].startswith("0") and not v[8],
        lambda v: v[11] != v[11].rstrip(),
    ]
    spacing = [
        2 + index * (total - 1) // MINIMUM_GOLDEN_CASES for index in range(MINIMUM_GOLDEN_CASES)
    ]
    pending = list(range(len(criteria)))
    chosen: dict[int, list[str]] = {}
    spaced: dict[int, list[str]] = {}
    multi_permit = None
    unreviewed: set[str] = set()
    for number, values in _independent_rows(payload):
        unreviewed.update(
            code for code in _codes(values) if code[0] in "ABC" and code not in decisions
        )
        for index in list(pending):
            if number not in chosen and criteria[index](values):
                chosen[number] = values
                pending.remove(index)
                break
        permit = values[0]
        if multi_permit is None and permit_rows[permit] == 2 and len(permit_makers[permit]) == 2:
            multi_permit = permit
        if permit == multi_permit:
            chosen[number] = values
        if number in spacing:
            spaced[number] = values
    for number in sorted(spaced):
        if len(chosen) >= MINIMUM_GOLDEN_CASES:
            break
        chosen.setdefault(number, spaced[number])

    transform = active_tfda_transform()
    zip_sha256 = hashlib.sha256(payload).hexdigest()
    cases = []
    for serial, number in enumerate(sorted(chosen), start=1):
        values = chosen[number]
        codes = _codes(values)
        expected = dict(zip(_FIELDS, values))
        expected.update(
            classification_codes=codes,
            main_category_letters=list(_letters(values)),
            ivd_scope=_scope(codes, decisions),
        )
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"TFDA-AUTO-{serial:03d}",
                "source_id": TFDA_SOURCE_ID,
                "acceptance_id": "TFDA-01",
                "source_title": "醫療器材許可證資料集",
                "official_landing_url": "https://data.gov.tw/dataset/9576",
                "official_version_or_modified_at": official_modified_at,
                "official_source": True,
                "artifact_id": "tfda-primary-zip",
                "raw_artifact_sha256": zip_sha256,
                "evidence_data_root_relative_path": artifact_relative,
                "fixture_file": None,
                "fixture_sha256": None,
                "transform": transform,
                "input": {"license_no": values[0]},
                "source_locator": {"locator_type": "tfda_row", "source_row_number": number},
                "source_row_sha256": _row_hash(values),
                "expected_status": "ok",
                "expected_fields": expected,
                "expected_warnings": _consistency_warnings(values),
                "reviewer_id": AUTO_REVIEWER_ID,
                "reviewer_role": AUTO_REVIEWER_ROLE,
                "identity_assurance": "local_asserted",
                "reviewed_at": reviewed_at.astimezone(_TAIPEI).isoformat(),
                "review_status": "approved",
            }
        )
    return {"cases": cases, "unreviewed_annex_codes": sorted(unreviewed)}


def drift_block_reasons(serving: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Reasons a new version is too different from the served one to publish unattended."""

    def exceeds_ten_percent(before: int, after: int) -> bool:
        return abs(after - before) * 10 > before

    reasons = []
    if exceeds_ten_percent(serving["rows"], candidate["rows"]):
        reasons.append("row_count_change_exceeds_10_percent")
    if exceeds_ten_percent(
        serving["distinct_license_numbers"], candidate["distinct_license_numbers"]
    ):
        reasons.append("permit_count_change_exceeds_10_percent")
    for column in _KEY_COLUMNS:
        before_blank = serving["empty_value_counts"][column]
        after_blank = candidate["empty_value_counts"][column]
        # after/candidate_rows - before/serving_rows > 2 percentage points, in integers.
        if (after_blank * serving["rows"] - before_blank * candidate["rows"]) * 50 > (
            serving["rows"] * candidate["rows"]
        ):
            reasons.append(f"blank_rate_increase:{column}")
    for status in sorted(candidate["cancellation_status_counts"]):
        if (
            status.strip() not in _ALLOWED_STATUSES
            and status not in serving["cancellation_status_counts"]
        ):
            reasons.append(f"new_cancellation_status:{status}")
    return reasons


def run_tfda_auto_update(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    actor: str,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Run the daily TFDA check and publish a changed version when every check passes."""

    data_root = Path(data_root)
    before = _read_tfda_serving(data_root)
    previous_candidate = before["descriptor"]["latest_candidate_id"] if before else None
    summary = run_tfda_upstream_check(
        data_root,
        expected_publisher_oid=expected_publisher_oid,
        actor=actor,
        opener=opener,
        clock=clock,
    )
    summary.update(
        already_reported=False,
        block_reasons=[],
        published_snapshot_id=None,
        unreviewed_annex_codes=[],
    )
    if summary["result"] != "changed":
        return summary
    candidate_id = summary["candidate_raw_revision_id"]
    # The same held-back candidate shows up every day until the next upstream version.
    summary["already_reported"] = candidate_id == previous_candidate
    try:
        serving = _read_tfda_serving(data_root)
        serving_payload = _read_hashed_raw(
            data_root, serving["artifact_relative"], serving["artifact_sha256"]
        )
        candidate_relative = f"raw/{TFDA_SOURCE_ID}/{candidate_id}/artifacts/source.zip"
        candidate_payload = (data_root / PurePosixPath(candidate_relative)).read_bytes()
        reasons = drift_block_reasons(
            summarize_tfda_csv(extract_tfda_csv(serving_payload)),
            summarize_tfda_csv(extract_tfda_csv(candidate_payload)),
        )
        if reasons:
            summary.update(result="blocked", block_reasons=reasons)
            return summary
        fetch = json.loads(
            (
                data_root / PurePosixPath(f"raw/{TFDA_SOURCE_ID}/{candidate_id}/fetch.json")
            ).read_bytes()
        )
        now = (clock() if clock else datetime.now(timezone.utc)).replace(microsecond=0)
        registry_bytes = packaged_ivd_registry_bytes()
        selection = select_golden_cases(
            candidate_payload,
            raw_revision_id=candidate_id,
            artifact_relative=candidate_relative,
            official_modified_at=fetch["discovery"].get("official_modified_at_raw"),
            registry_bytes=registry_bytes,
            reviewed_at=now,
        )
        summary["unreviewed_annex_codes"] = selection["unreviewed_annex_codes"]
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
            for gate_id in TFDA_SERVING_GATES
        ]

        def roundtrip(db_path: Path) -> tuple[str, str, bytes]:
            report = verify_curated_roundtrip(db_path, candidate_payload, registry_bytes)
            return "tfda-auto-roundtrip", "tfda-auto-roundtrip.json", canonical_json_bytes(report)

        built = build_official_tfda_snapshot(
            data_root,
            raw_revision_id=candidate_id,
            approved_golden_cases=selection["cases"],
            owner_reviews=reviews,
            publisher_actor_id=actor,
            review_protocol=(TFDA_AUTO_REVIEW_PROTOCOL_ID, TFDA_AUTO_REVIEW_PROTOCOL_VERSION),
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
        ivd_coverage=built["ivd_coverage"],
    )
    return summary
