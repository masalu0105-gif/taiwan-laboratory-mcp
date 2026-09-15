from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from .canonical import canonical_json_bytes, sha256_bytes
from .models import QualificationCandidateV1, QualificationCertificateV1


class AuditIntegrityError(ValueError):
    """Raised when a curated audit bundle is missing or not hash-bound."""


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


# Serving gates per internal source id (PRD 8.2); PUB-R1-OWNER is shared.
_SERVING_GATES = {
    "nhi_fee": frozenset({"NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER"}),
    "tfda_devices": frozenset({"TFDA-R1-SOURCE", "TFDA-R1-SCHEMA", "PUB-R1-OWNER"}),
}


def _sha256_file(path: Path) -> str:
    # The TFDA curated database is about 100 MB; hash it without holding it in memory.
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_REVIEW_KEYS = frozenset(
    {
        "review_schema_version",
        "gate_id",
        "decision",
        "source_id",
        "curated_build_id",
        "subject_digest",
        "reviewer_id",
        "reviewer_role",
        "identity_assurance",
        "reviewed_at",
        "protocol_id",
        "protocol_version",
        "protocol_sha256",
        "review_scope",
        "evidence_refs",
        "finding_counts",
        "comments",
        "signature",
    }
)


def compute_review_subject_digest(
    manifest: dict[str, Any],
    *,
    curated_db_sha256: str,
    validation_report_sha256: str,
    qualification_candidate_sha256: str,
) -> str:
    """Compute the non-circular ReviewSubjectV1 digest."""

    artifacts = [
        {
            "artifact_id": artifact["artifact_id"],
            "role": artifact["role"],
            "sha256": artifact["sha256"],
        }
        for artifact in manifest["artifacts"]
    ]
    artifacts.sort(key=lambda item: (item["role"], item["artifact_id"]))
    subject = {
        "subject_schema": "review-subject-v1",
        "source_id": manifest["source_id"],
        "raw_revision_id": manifest["raw_revision_id"],
        "curated_build_id": manifest["curated_build_id"],
        "artifacts": artifacts,
        "curated_db_sha256": curated_db_sha256,
        "curated_build_fingerprint": manifest["build_fingerprint"],
        "validation_report_sha256": validation_report_sha256,
        "qualification_candidate_sha256": qualification_candidate_sha256,
    }
    return sha256_bytes(canonical_json_bytes(subject))


def _read_ref(
    data_root: Path,
    source_id: str,
    build_id: str,
    ref: dict[str, Any],
    *,
    label: str,
) -> tuple[dict[str, Any], Path]:
    if not isinstance(ref, dict) or set(ref) != {"data_root_relative_path", "sha256"}:
        raise AuditIntegrityError(f"{label} reference schema invalid")
    relative = ref.get("data_root_relative_path")
    digest = ref.get("sha256")
    if not isinstance(relative, str) or not _is_hex64(digest):
        raise AuditIntegrityError(f"{label} reference invalid")
    path = PurePosixPath(relative)
    prefix = PurePosixPath("curated", source_id, build_id, "audit")
    if path.is_absolute() or ".." in path.parts or path.parts[: len(prefix.parts)] != prefix.parts:
        raise AuditIntegrityError(f"{label} path outside audit bundle")
    candidate = (Path(data_root) / Path(*path.parts)).resolve()
    root = Path(data_root).resolve()
    if root not in candidate.parents:
        raise AuditIntegrityError(f"{label} path escapes data root")
    if not candidate.is_file():
        raise AuditIntegrityError(f"{label} artifact missing")
    try:
        raw = candidate.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise AuditIntegrityError(f"{label} artifact unreadable") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise AuditIntegrityError(f"{label} artifact not canonical")
    if sha256_bytes(raw) != digest:
        raise AuditIntegrityError(f"{label} artifact hash mismatch")
    return value, candidate


def _validate_review(
    data_root: Path,
    source_id: str,
    build_id: str,
    subject_digest: str,
    review: dict[str, Any],
) -> None:
    if set(review) != _REVIEW_KEYS:
        raise AuditIntegrityError("review schema invalid")
    if (
        review["review_schema_version"] != 1
        or not isinstance(review["gate_id"], str)
        or review["gate_id"] not in _SERVING_GATES.get(source_id, frozenset())
        or not isinstance(review["decision"], str)
        or review["decision"] != "approved"
        or review["source_id"] != source_id
        or review["curated_build_id"] != build_id
        or review["subject_digest"] != subject_digest
        or not isinstance(review["identity_assurance"], str)
        or review["identity_assurance"] not in {"local_asserted", "cryptographically_signed"}
        or not isinstance(review["protocol_id"], str)
        or not isinstance(review["protocol_version"], str)
        or not _is_hex64(review["protocol_sha256"])
    ):
        raise AuditIntegrityError("review identity or decision invalid")
    if not isinstance(review["reviewer_id"], str) or not review["reviewer_id"]:
        raise AuditIntegrityError("reviewer id invalid")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise AuditIntegrityError("review timestamp invalid") from exc
    if reviewed_at.utcoffset() is None:
        raise AuditIntegrityError("review timestamp lacks timezone")
    if not isinstance(review["evidence_refs"], list):
        raise AuditIntegrityError("review evidence refs invalid")
    for index, evidence in enumerate(review["evidence_refs"]):
        if not isinstance(evidence, dict) or set(evidence) != {
            "artifact_id",
            "path",
            "locator",
            "sha256",
        }:
            raise AuditIntegrityError(f"review evidence {index} invalid")
        artifact_path = evidence["path"]
        digest = evidence["sha256"]
        if not isinstance(artifact_path, str) or not _is_hex64(digest):
            raise AuditIntegrityError(f"review evidence {index} malformed")
        path = PurePosixPath(artifact_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or path.parts[:1]
            not in {
                ("raw",),
                ("curated",),
            }
        ):
            raise AuditIntegrityError(f"review evidence {index} path invalid")
        candidate = (Path(data_root) / Path(*path.parts)).resolve()
        root = Path(data_root).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise AuditIntegrityError(f"review evidence {index} path unavailable")
        if _sha256_file(candidate) != digest:
            raise AuditIntegrityError(f"review evidence {index} hash mismatch")
    finding_counts = review["finding_counts"]
    if not isinstance(finding_counts, dict) or set(finding_counts) != {
        "critical",
        "major",
        "minor",
    }:
        raise AuditIntegrityError("review finding counts invalid")
    if any(type(value) is not int or value < 0 for value in finding_counts.values()):
        raise AuditIntegrityError("review finding counts invalid")
    if finding_counts["critical"] != 0:
        raise AuditIntegrityError("approved review has critical findings")


def _validate_approved_qualification(
    manifest: dict[str, Any], candidate: dict[str, Any], golden: dict[str, Any]
) -> None:
    """Require countable, source-bound cases before accepting a final certificate."""

    if golden.get("official_qualification_status") != "approved":
        return
    review_meta = manifest.get("review")
    if not isinstance(review_meta, dict) or "PUB-R1-OWNER" not in review_meta.get(
        "completed_gates", []
    ):
        raise AuditIntegrityError("approved qualification requires owner gate")

    case_ids = candidate.get("case_ids")
    cases = candidate.get("cases")
    approved_case_ids = golden.get("approved_distinct_case_ids")
    case_id_lists_are_valid = all(
        isinstance(values, list)
        and all(isinstance(case_id, str) and bool(case_id) for case_id in values)
        for values in (case_ids, approved_case_ids)
    )
    if (
        not isinstance(case_ids, list)
        or not isinstance(cases, list)
        or not isinstance(approved_case_ids, list)
        or not case_id_lists_are_valid
        or len(case_ids) != len(set(case_ids))
        or len(approved_case_ids) != len(set(approved_case_ids))
        or len(approved_case_ids) < 10
        or len(cases) != len(case_ids)
    ):
        raise AuditIntegrityError("approved qualification cases invalid")
    if set(approved_case_ids) - set(case_ids):
        raise AuditIntegrityError("approved qualification case coverage incomplete")
    cases_by_id: dict[str, dict[str, Any]] = {}
    for result in cases:
        golden_case = result.get("golden_case") if isinstance(result, dict) else None
        if not isinstance(golden_case, dict) or not isinstance(golden_case.get("case_id"), str):
            raise AuditIntegrityError("approved qualification case record invalid")
        case_id = golden_case["case_id"]
        if case_id in cases_by_id:
            raise AuditIntegrityError("approved qualification case ids duplicated")
        cases_by_id[case_id] = result
    if set(cases_by_id) != set(case_ids):
        raise AuditIntegrityError("qualification case id registry mismatch")

    manifest_artifacts = manifest.get("artifacts")
    if not isinstance(manifest_artifacts, list):
        raise AuditIntegrityError("qualification artifact registry invalid")
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in manifest_artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = artifact.get("artifact_id")
        if isinstance(artifact_id, str):
            artifacts[artifact_id] = artifact
    expected_transform = _active_transform(manifest)
    source_id = manifest.get("source_id")
    raw_prefix = f"raw/{source_id}/{manifest.get('raw_revision_id')}/"
    for case_id in approved_case_ids:
        result = cases_by_id[case_id]
        case = result["golden_case"]
        if result.get("evaluation_status") != "passed" or result.get("failure_codes") != []:
            raise AuditIntegrityError("approved qualification case did not pass evaluation")
        if case.get("transform") != expected_transform:
            raise AuditIntegrityError("approved qualification case transform is stale")
        artifact_id = case.get("artifact_id")
        raw_digest = case.get("raw_artifact_sha256")
        artifact = artifacts.get(artifact_id) if isinstance(artifact_id, str) else None
        if (
            case.get("source_id") != source_id
            or not isinstance(artifact_id, str)
            or not isinstance(raw_digest, str)
            or not _is_hex64(raw_digest)
            or not isinstance(artifact, dict)
            or artifact.get("sha256") != raw_digest
            or artifact.get("storage_scope") != "data_root"
            or artifact.get("local_artifact_available") is not True
            or not isinstance(artifact.get("data_root_relative_path"), str)
            or not artifact["data_root_relative_path"].startswith(raw_prefix)
            or case.get("evidence_data_root_relative_path") != artifact["data_root_relative_path"]
            or case.get("official_source") is not True
            or case.get("review_status") != "approved"
            or not isinstance(case.get("source_locator"), dict)
            or not case["source_locator"]
            or not isinstance(case.get("reviewer_id"), str)
            or not case["reviewer_id"]
            or not isinstance(case.get("reviewer_role"), str)
            or not case["reviewer_role"]
            or not isinstance(case.get("identity_assurance"), str)
            or case.get("identity_assurance") not in {"local_asserted", "cryptographically_signed"}
        ):
            raise AuditIntegrityError(
                "approved qualification case is not official reviewed evidence"
            )
        try:
            reviewed_at = datetime.fromisoformat(case["reviewed_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError) as exc:
            raise AuditIntegrityError("approved qualification case timestamp invalid") from exc
        if reviewed_at.utcoffset() is None:
            raise AuditIntegrityError("approved qualification case timestamp lacks timezone")


def _active_transform(manifest: dict[str, Any]) -> dict[str, Any]:
    fingerprint = manifest.get("build_fingerprint")
    if not isinstance(fingerprint, dict):
        raise AuditIntegrityError("build fingerprint missing")
    return {
        key: fingerprint.get(key)
        for key in ("parser", "schema", "normalization", "rules", "qualifier")
    }


def validate_audit_evidence(data_root: Path, manifest: dict[str, Any]) -> None:
    """Validate all audit references and the manifest's non-circular subject digest."""

    try:
        source_id = manifest["source_id"]
        build_id = manifest["curated_build_id"]
        evidence = manifest["audit_evidence"]
        publication = manifest["publication"]
        review_meta = manifest["review"]
    except (KeyError, TypeError) as exc:
        raise AuditIntegrityError("audit metadata missing") from exc
    if not isinstance(source_id, str) or not isinstance(build_id, str):
        raise AuditIntegrityError("audit identity invalid")
    if not isinstance(evidence, dict) or set(evidence) != {
        "validation",
        "qualification_candidate",
        "golden_qualification",
        "reviews",
    }:
        raise AuditIntegrityError("audit evidence registry invalid")
    refs = {}
    values = {}
    for label in ("validation", "qualification_candidate", "golden_qualification"):
        value, _ = _read_ref(Path(data_root), source_id, build_id, evidence[label], label=label)
        refs[label] = evidence[label]
        values[label] = value
    validation = values["validation"]
    candidate = values["qualification_candidate"]
    golden = values["golden_qualification"]
    if (
        validation.get("validation_schema_version") != 1
        or validation.get("source_id") != source_id
        or validation.get("raw_revision_id") != manifest.get("raw_revision_id")
        or validation.get("curated_build_id") != build_id
        or validation.get("automated_status") != "passed"
        or validation.get("blocking_errors") != []
        or validation.get("curated_db_sha256") != publication.get("curated_sha256")
        or validation.get("build_fingerprint_sha256") != manifest.get("build_fingerprint_sha256")
    ):
        raise AuditIntegrityError("validation evidence identity invalid")
    manifest_validation = manifest.get("validation")
    if (
        not isinstance(manifest_validation, dict)
        or manifest_validation.get("automated_validation_status") != "passed"
        or manifest_validation.get("blocking_errors") != []
        or manifest_validation.get("warnings") != validation.get("warnings")
    ):
        raise AuditIntegrityError("manifest validation status invalid")
    manifest_counts = manifest.get("counts")
    validation_counts = validation.get("row_counts")
    if (
        not isinstance(manifest_counts, dict)
        or not isinstance(validation_counts, dict)
        or validation_counts != manifest_counts
        or set(manifest_counts) != {"input_rows", "curated_rows", "quarantined_rows"}
        or any(type(value) is not int or value < 0 for value in manifest_counts.values())
        or manifest_counts["input_rows"] != manifest_counts["curated_rows"]
        or manifest_counts["quarantined_rows"] != 0
    ):
        raise AuditIntegrityError("validation row coverage invalid")
    expected_artifacts = sorted(
        [
            {
                "artifact_id": artifact["artifact_id"],
                "role": artifact["role"],
                "sha256": artifact["sha256"],
            }
            for artifact in manifest["artifacts"]
        ],
        key=lambda item: (item["role"], item["artifact_id"]),
    )
    if validation.get("artifact_hashes") != expected_artifacts:
        raise AuditIntegrityError("validation artifact coverage invalid")
    try:
        QualificationCandidateV1.model_validate_json(canonical_json_bytes(candidate))
    except ValidationError as exc:
        raise AuditIntegrityError("qualification candidate invalid") from exc
    if (
        candidate["source_id"] != source_id
        or candidate["raw_revision_id"] != manifest.get("raw_revision_id")
        or candidate["curated_build_id"] != build_id
        or candidate["automated_status"] != "passed"
        or candidate["input_artifact_hashes"] != expected_artifacts
        or candidate["curated_db_sha256"] != publication.get("curated_sha256")
        or candidate["active_transform"] != _active_transform(manifest)
        or any(
            sha256_bytes(canonical_json_bytes(result["golden_case"]))
            != result["golden_case_sha256"]
            for result in candidate["cases"]
        )
    ):
        raise AuditIntegrityError("qualification candidate invalid")
    expected_subject = compute_review_subject_digest(
        manifest,
        curated_db_sha256=publication["curated_sha256"],
        validation_report_sha256=refs["validation"]["sha256"],
        qualification_candidate_sha256=refs["qualification_candidate"]["sha256"],
    )
    if manifest.get("review_subject_digest") != expected_subject:
        raise AuditIntegrityError("review subject digest mismatch")
    try:
        QualificationCertificateV1.model_validate_json(canonical_json_bytes(golden))
    except ValidationError as exc:
        raise AuditIntegrityError("qualification certificate invalid") from exc
    if (
        golden.get("qualification_certificate_schema_version") != 1
        or golden.get("source_id") != source_id
        or golden.get("curated_build_id") != build_id
        or golden.get("subject_digest") != expected_subject
        or golden.get("candidate_report_sha256") != refs["qualification_candidate"]["sha256"]
        or not isinstance(golden.get("official_qualification_status"), str)
        or golden.get("official_qualification_status") not in {"not_qualified", "approved"}
    ):
        raise AuditIntegrityError("qualification certificate invalid")
    _validate_approved_qualification(manifest, candidate, golden)
    if not isinstance(evidence["reviews"], list) or not isinstance(review_meta, dict):
        raise AuditIntegrityError("review registry invalid")
    if golden.get("accepted_review_hashes") != [
        item.get("sha256") for item in evidence["reviews"] if isinstance(item, dict)
    ]:
        raise AuditIntegrityError("qualification review hashes invalid")
    required_gates = review_meta.get("required_gates")
    completed_gates = review_meta.get("completed_gates")
    if (
        not isinstance(required_gates, list)
        or not isinstance(completed_gates, list)
        or not all(isinstance(gate_id, str) and gate_id for gate_id in required_gates)
        or not all(isinstance(gate_id, str) and gate_id for gate_id in completed_gates)
        or len(required_gates) != len(set(required_gates))
        or required_gates != completed_gates
        or len(evidence["reviews"]) != len(completed_gates)
        or review_meta.get("human_review_status") != "approved"
        or source_id not in _SERVING_GATES
        or not _SERVING_GATES[source_id].issubset(set(required_gates))
    ):
        raise AuditIntegrityError("review gate set invalid")
    seen_gates: set[str] = set()
    for item in evidence["reviews"]:
        if not isinstance(item, dict) or set(item) != {
            "gate_id",
            "data_root_relative_path",
            "sha256",
        }:
            raise AuditIntegrityError("review reference invalid")
        gate_id = item["gate_id"]
        if gate_id in seen_gates or gate_id not in completed_gates:
            raise AuditIntegrityError("review gate reference invalid")
        review, _ = _read_ref(
            Path(data_root),
            source_id,
            build_id,
            {
                "data_root_relative_path": item["data_root_relative_path"],
                "sha256": item["sha256"],
            },
            label=f"review {gate_id}",
        )
        if review.get("gate_id") != gate_id:
            raise AuditIntegrityError("review gate mismatch")
        _validate_review(Path(data_root), source_id, build_id, expected_subject, review)
        seen_gates.add(gate_id)
    if seen_gates != set(completed_gates):
        raise AuditIntegrityError("review gate coverage incomplete")
