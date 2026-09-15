"""Owner review of a newer NHI upstream candidate, then publish it as the serving build.

``prepare_nhi_review_packet`` is read-only on the data root: it re-binds the golden cases
approved for the serving build to the pending candidate raw revision and writes a review
packet, a plain-language review page and a decision template to an output directory.

``publish_reviewed_nhi_candidate`` accepts a decision file written after the owner
reviewed that exact packet (bound by SHA-256) and hands the approved cases and gate
reviews to ``build_official_nhi_snapshot``, which re-checks every precondition.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import canonical_json_bytes, sha256_bytes
from .importers.nhi import (
    OWNER_REVIEW_PROTOCOL_ID,
    OWNER_REVIEW_PROTOCOL_VERSION,
    OWNER_SERVING_GATES,
    _curated_row,
    _load_official_raw_revision,
    _owner_review_protocol,
    _packaged_rule_bundles,
    _same_json_value,
    _serving_warnings,
    active_nhi_transform,
    build_official_nhi_snapshot,
    parse_nhi_csv,
)
from .models import GoldenCaseV1
from .rules.nhi import parse_scope_bundle
from .stores import read_nhi_state
from .util import search_normalize

REVIEW_PACKET_ARTIFACT_ID = "nhi-review-packet"
REVIEW_DECISION_ARTIFACT_ID = "nhi-review-decision"
_DECISION_KEYS = frozenset(
    {
        "review_decision_schema_version",
        "source_id",
        "candidate_raw_revision_id",
        "packet_sha256",
        "decision",
        "reviewer_id",
        "reviewer_role",
        "reviewed_at",
        "approved_case_ids",
        "gate_reviews",
    }
)
_GATE_REVIEW_KEYS = frozenset({"gate_id", "finding_counts", "comments"})


class NHIReviewError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{(': ' + detail) if detail else ''}")


def _read_json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON document must be an object")
    return value


def _current_descriptor(data_root: Path) -> dict[str, Any]:
    path = data_root / "manifests" / "current" / "nhi_fee.json"
    if not path.is_file():
        raise NHIReviewError("NO_SERVING_SNAPSHOT")
    try:
        return _read_json_file(path)
    except (OSError, ValueError) as exc:
        raise NHIReviewError("SERVING_INTEGRITY_FAILURE") from exc


def _hashed_json(data_root: Path, reference: dict[str, Any]) -> dict[str, Any]:
    payload = (data_root / PurePosixPath(reference["data_root_relative_path"])).read_bytes()
    if sha256_bytes(payload) != reference["sha256"]:
        raise NHIReviewError("SERVING_INTEGRITY_FAILURE", "audit hash mismatch")
    return json.loads(payload.decode("utf-8"))


def _serving_cases(data_root: Path, descriptor: dict[str, Any]) -> tuple[dict, list[dict]]:
    try:
        manifest_path = data_root / PurePosixPath(descriptor["manifest_data_root_relative_path"])
        manifest_bytes = manifest_path.read_bytes()
        if sha256_bytes(manifest_bytes) != descriptor["manifest_sha256"]:
            raise NHIReviewError("SERVING_INTEGRITY_FAILURE", "manifest hash mismatch")
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        candidate = _hashed_json(data_root, manifest["audit_evidence"]["qualification_candidate"])
        cases = [copy.deepcopy(result["golden_case"]) for result in candidate["cases"]]
    except NHIReviewError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise NHIReviewError("SERVING_INTEGRITY_FAILURE") from exc
    return manifest, cases


def _latest_diff(data_root: Path, descriptor: dict[str, Any], candidate_id: str):
    matches = []
    for diff_path in (data_root / "staged" / "nhi_fee").glob("*/diff.json"):
        try:
            diff = _read_json_file(diff_path)
        except (OSError, ValueError):
            continue
        if (
            diff.get("candidate_raw_revision_id") == candidate_id
            and diff.get("serving_snapshot_id") == descriptor["serving_snapshot_id"]
        ):
            matches.append(diff_path)
    if not matches:
        return None, None, None
    diff_path = max(matches, key=lambda path: path.parent.name)
    summary_path = diff_path.parent / "diff-summary.md"
    summary_text = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else None
    relative = diff_path.relative_to(data_root).as_posix()
    return relative, sha256_bytes(diff_path.read_bytes()), summary_text


def _display(value: Any) -> str:
    if value is None:
        return "（空白）"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = " ".join(str(value).split())
    return text if text else "（空白）"


def _review_page(packet: dict[str, Any], packet_sha256: str, diff_summary: str | None) -> str:
    counts = packet["case_counts"]
    status_labels = {"unchanged": "沒變", "changed": "有變", "missing": "新版找不到"}
    lines = [
        "# 健保支付標準表新版審核包",
        "",
        "這份資料給 owner 審核新版用。核准並發布之前，MCP 會繼續回答目前服務中的版本。",
        "",
        f"- 目前服務中的版本：`{packet['serving_snapshot_id']}`"
        f"（{packet['serving_row_count']:,} 筆）",
        f"- 新版原始檔：{packet['candidate_row_count']:,} 筆，"
        f"SHA-256 `{packet['candidate_raw_artifact_sha256']}`",
        "- 健保署標示的更新時間：" + (packet["candidate_official_modified_at_raw"] or "（未標示）"),
        f"- 審核包編號（packet SHA-256）：`{packet_sha256}`",
        "",
        f"## {len(packet['case_comparisons'])} 題正確答案在新版的結果",
        "",
        f"沒變 {counts['unchanged']} 題、有變 {counts['changed']} 題、"
        f"新版找不到 {counts['missing']} 題。",
        "",
        "| 題號 | 代碼 | 結果 | 變動內容 |",
        "| --- | --- | --- | --- |",
    ]
    for item in packet["case_comparisons"]:
        changes = "；".join(
            f"{change['field']}：{_display(change['before'])} → {_display(change['after'])}"
            for change in item["changes"]
        )
        lines.append(
            f"| {item['case_id']} | `{item['code']}` | {status_labels[item['status']]} | "
            f"{changes or '—'} |"
        )
    lines.extend(
        [
            "",
            "- 有變的題目：新版的值會成為這題新的正確答案，請到健保署網站確認新值正確。",
            "- 新版找不到的題目：不能沿用。請確認這個代碼真的被刪除，並另外補一題；"
            "發布至少需要 10 題。",
            "",
            "## 上游差異摘要",
            "",
        ]
    )
    lines.append(diff_summary.strip() if diff_summary else "（找不到這個新版的差異摘要檔）")
    protocol = json.loads(
        files("taiwan_lab_mcp")
        .joinpath(
            "review_protocols",
            OWNER_REVIEW_PROTOCOL_ID,
            f"{OWNER_REVIEW_PROTOCOL_VERSION}.json",
        )
        .read_text(encoding="utf-8")
    )
    lines.extend(
        [
            "",
            f"## 審核清單（{OWNER_REVIEW_PROTOCOL_ID} 第 {OWNER_REVIEW_PROTOCOL_VERSION} 版）",
            "",
        ]
    )
    for gate_id in OWNER_SERVING_GATES:
        gate = protocol["gates"][gate_id]
        lines.append(f"### {gate_id}：{gate['purpose']}")
        lines.extend(f"- {item}" for item in gate["checklist"])
        lines.append("")
    lines.extend(
        [
            "## 怎麼核准",
            "",
            "1. 看完上面內容，在 Claude 對話中說「核准」，或指出哪裡有問題。",
            "2. 核准後，把 decision template 填上審核人、審核時間、每一關的問題數，"
            "`decision` 填 `approved`，另存成 decision 檔。",
            "3. 執行 `taiwan-lab-data publish nhi_fee --packet <審核包 json> "
            "--decision <decision 檔> --actor <發布者代號> --data-dir <data root>`。",
            "",
            "發布指令會重新檢查原始檔、10 題答案與三關審核；任何一項不符都不會切換版本。",
            "",
        ]
    )
    return "\n".join(lines)


def prepare_nhi_review_packet(data_root: Path, *, output_dir: Path) -> dict[str, Any]:
    data_root = Path(data_root)
    output_dir = Path(output_dir)
    descriptor = _current_descriptor(data_root)
    if descriptor.get("serving_snapshot_id") is None:
        raise NHIReviewError("NO_SERVING_SNAPSHOT")
    candidate_id = descriptor.get("latest_candidate_id")
    if descriptor.get("latest_candidate_status") != "review_pending" or not candidate_id:
        raise NHIReviewError("NO_PENDING_CANDIDATE")
    if read_nhi_state(data_root).availability != "available":
        raise NHIReviewError("SERVING_INTEGRITY_FAILURE")
    manifest, previous_cases = _serving_cases(data_root, descriptor)

    payload, _, fetch_record, artifact_relative, _ = _load_official_raw_revision(
        data_root, candidate_id
    )
    parsed = parse_nhi_csv(payload)
    scope_rules = parse_scope_bundle(_packaged_rule_bundles()[0])
    scope_rules_by_code = {search_normalize(code): rule for code, rule in scope_rules.items()}
    rows_by_code = {
        row.code_normalized: _curated_row(row, scope_rules_by_code, unreviewed_in_scope=True)
        for row in parsed.rows
    }
    raw_sha256 = sha256_bytes(payload)
    candidate_warnings = _serving_warnings(rows_by_code.values())
    transform = active_nhi_transform()
    modified_at_raw = fetch_record["discovery"].get("official_modified_at_raw")

    comparisons = []
    proposed_cases = []
    for previous in previous_cases:
        code = previous["input"].get("code", "")
        row = rows_by_code.get(search_normalize(code))
        if row is None:
            comparisons.append(
                {"case_id": previous["case_id"], "code": code, "status": "missing", "changes": []}
            )
            continue
        changes = [
            {"field": field, "before": before, "after": row[field]}
            for field, before in sorted(previous["expected_fields"].items())
            if field in row and not _same_json_value(before, row[field])
        ]
        if previous.get("expected_warnings") != candidate_warnings:
            changes.append(
                {
                    "field": "expected_warnings",
                    "before": previous.get("expected_warnings"),
                    "after": candidate_warnings,
                }
            )
        comparisons.append(
            {
                "case_id": previous["case_id"],
                "code": code,
                "status": "changed" if changes else "unchanged",
                "changes": changes,
            }
        )
        case = copy.deepcopy(previous)
        case.update(
            {
                "raw_artifact_sha256": raw_sha256,
                "evidence_data_root_relative_path": artifact_relative,
                "official_version_or_modified_at": modified_at_raw,
                "transform": transform,
                "source_locator": {
                    "locator_type": "nhi_row",
                    "source_row_number": row["source_row_number"],
                },
                "source_row_sha256": row["source_row_sha256"],
                "expected_warnings": candidate_warnings,
                "expected_fields": {
                    field: row[field] if field in row else before
                    for field, before in previous["expected_fields"].items()
                },
                "reviewer_id": None,
                "reviewer_role": None,
                "identity_assurance": None,
                "reviewed_at": None,
                "review_status": "review_pending",
            }
        )
        try:
            GoldenCaseV1.model_validate_json(canonical_json_bytes(case))
        except ValueError as exc:
            raise NHIReviewError("REVIEW_PACKET_CASE_INVALID", previous["case_id"]) from exc
        proposed_cases.append(case)

    diff_relative, diff_sha256, diff_summary = _latest_diff(data_root, descriptor, candidate_id)
    protocol_id, protocol_version, protocol_sha256 = _owner_review_protocol()
    case_counts = {
        status: sum(1 for item in comparisons if item["status"] == status)
        for status in ("unchanged", "changed", "missing")
    }
    packet = {
        "review_packet_schema_version": 1,
        "source_id": "nhi_fee",
        "serving_snapshot_id": descriptor["serving_snapshot_id"],
        "serving_raw_artifact_sha256": manifest["artifacts"][0]["sha256"],
        "serving_row_count": manifest["counts"]["curated_rows"],
        "candidate_raw_revision_id": candidate_id,
        "candidate_raw_artifact_sha256": raw_sha256,
        "candidate_raw_artifact_data_root_relative_path": artifact_relative,
        "candidate_official_modified_at_raw": modified_at_raw,
        "candidate_row_count": len(parsed.rows),
        "diff_data_root_relative_path": diff_relative,
        "diff_sha256": diff_sha256,
        "review_protocol": {
            "protocol_id": protocol_id,
            "protocol_version": protocol_version,
            "protocol_sha256": protocol_sha256,
        },
        "case_counts": case_counts,
        "case_comparisons": comparisons,
        "proposed_cases": proposed_cases,
    }
    packet_bytes = canonical_json_bytes(packet)
    packet_sha256 = sha256_bytes(packet_bytes)
    stem = f"nhi-review-{candidate_id[:12]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / f"{stem}.json"
    page_path = output_dir / f"{stem}.md"
    template_path = output_dir / f"{stem}-decision-template.json"
    packet_path.write_bytes(packet_bytes)
    page_path.write_text(_review_page(packet, packet_sha256, diff_summary), encoding="utf-8")
    template = {
        "review_decision_schema_version": 1,
        "source_id": "nhi_fee",
        "candidate_raw_revision_id": candidate_id,
        "packet_sha256": packet_sha256,
        "decision": None,
        "reviewer_id": None,
        "reviewer_role": "project_owner",
        "reviewed_at": None,
        "approved_case_ids": [case["case_id"] for case in proposed_cases],
        "gate_reviews": [
            {
                "gate_id": gate_id,
                "finding_counts": {"critical": 0, "major": 0, "minor": 0},
                "comments": "",
            }
            for gate_id in OWNER_SERVING_GATES
        ],
    }
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "result": "packet_ready",
        "candidate_raw_revision_id": candidate_id,
        "packet_path": str(packet_path),
        "packet_sha256": packet_sha256,
        "review_page_path": str(page_path),
        "decision_template_path": str(template_path),
        "case_counts": case_counts,
    }


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validated_decision(decision: Any) -> dict[str, Any]:
    def invalid(detail: str) -> NHIReviewError:
        return NHIReviewError("REVIEW_DECISION_SCHEMA_INVALID", detail)

    if not isinstance(decision, dict) or set(decision) != _DECISION_KEYS:
        raise invalid("decision keys")
    if (
        type(decision["review_decision_schema_version"]) is not int
        or decision["review_decision_schema_version"] != 1
        or decision["source_id"] != "nhi_fee"
    ):
        raise invalid("schema version or source")
    if decision["decision"] not in {"approved", "rejected"}:
        raise invalid("decision")
    for key in ("candidate_raw_revision_id", "packet_sha256", "reviewer_id", "reviewer_role"):
        if not _non_empty_text(decision[key]):
            raise invalid(key)
    try:
        reviewed_at = datetime.fromisoformat(str(decision["reviewed_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise invalid("reviewed_at") from exc
    if not isinstance(decision["reviewed_at"], str) or reviewed_at.utcoffset() is None:
        raise invalid("reviewed_at")
    case_ids = decision["approved_case_ids"]
    if (
        not isinstance(case_ids, list)
        or not case_ids
        or not all(_non_empty_text(case_id) for case_id in case_ids)
        or len(set(case_ids)) != len(case_ids)
    ):
        raise invalid("approved_case_ids")
    gate_reviews = decision["gate_reviews"]
    if not isinstance(gate_reviews, list) or [
        review.get("gate_id") if isinstance(review, dict) else None for review in gate_reviews
    ] != list(OWNER_SERVING_GATES):
        raise invalid("gate_reviews")
    for review in gate_reviews:
        counts = review.get("finding_counts")
        if (
            set(review) != _GATE_REVIEW_KEYS
            or not isinstance(review["comments"], str)
            or not isinstance(counts, dict)
            or set(counts) != {"critical", "major", "minor"}
            or any(type(value) is not int or value < 0 for value in counts.values())
        ):
            raise invalid(f"gate review {review.get('gate_id')}")
    return decision


def publish_reviewed_nhi_candidate(
    data_root: Path, *, packet_path: Path, decision_path: Path, actor: str
) -> dict[str, Any]:
    data_root = Path(data_root)
    packet_path = Path(packet_path)
    decision_path = Path(decision_path)
    try:
        packet_bytes = packet_path.read_bytes()
        decision_bytes = decision_path.read_bytes()
    except OSError as exc:
        raise NHIReviewError("REVIEW_INPUT_UNREADABLE") from exc
    try:
        decision = json.loads(decision_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NHIReviewError("REVIEW_DECISION_SCHEMA_INVALID", "not JSON") from exc
    decision = _validated_decision(decision)
    if sha256_bytes(packet_bytes) != decision["packet_sha256"]:
        raise NHIReviewError("REVIEW_DECISION_PACKET_MISMATCH")
    try:
        packet = json.loads(packet_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise NHIReviewError("REVIEW_PACKET_INVALID") from exc
    if (
        not isinstance(packet, dict)
        or canonical_json_bytes(packet) != packet_bytes
        or packet.get("review_packet_schema_version") != 1
        or packet.get("source_id") != "nhi_fee"
    ):
        raise NHIReviewError("REVIEW_PACKET_INVALID")
    if decision["candidate_raw_revision_id"] != packet["candidate_raw_revision_id"]:
        raise NHIReviewError("REVIEW_DECISION_PACKET_MISMATCH", "candidate")
    if decision["decision"] != "approved":
        raise NHIReviewError("REVIEW_DECISION_NOT_APPROVED")
    proposed = {case["case_id"]: case for case in packet["proposed_cases"]}
    unknown = [case_id for case_id in decision["approved_case_ids"] if case_id not in proposed]
    if unknown:
        raise NHIReviewError("REVIEW_DECISION_CASE_UNKNOWN", ", ".join(unknown))

    descriptor = _current_descriptor(data_root)
    if (
        descriptor.get("serving_snapshot_id") != packet["serving_snapshot_id"]
        or descriptor.get("latest_candidate_status") != "review_pending"
        or descriptor.get("latest_candidate_id") != packet["candidate_raw_revision_id"]
    ):
        raise NHIReviewError("REVIEW_PACKET_STALE")

    approved_cases = []
    for case_id in decision["approved_case_ids"]:
        case = copy.deepcopy(proposed[case_id])
        case.update(
            {
                "reviewer_id": decision["reviewer_id"],
                "reviewer_role": decision["reviewer_role"],
                "identity_assurance": "local_asserted",
                "reviewed_at": decision["reviewed_at"],
                "review_status": "approved",
            }
        )
        approved_cases.append(case)
    owner_reviews = [
        {
            "gate_id": review["gate_id"],
            "reviewer_id": decision["reviewer_id"],
            "reviewer_role": decision["reviewer_role"],
            "reviewed_at": decision["reviewed_at"],
            "finding_counts": review["finding_counts"],
            "comments": review["comments"],
        }
        for review in decision["gate_reviews"]
    ]
    built = build_official_nhi_snapshot(
        data_root,
        raw_revision_id=packet["candidate_raw_revision_id"],
        approved_golden_cases=approved_cases,
        owner_reviews=owner_reviews,
        publisher_actor_id=actor,
        evidence_files=[
            {"artifact_id": REVIEW_PACKET_ARTIFACT_ID, "path": str(packet_path)},
            {"artifact_id": REVIEW_DECISION_ARTIFACT_ID, "path": str(decision_path)},
        ],
    )
    return {"result": "published", **built}
