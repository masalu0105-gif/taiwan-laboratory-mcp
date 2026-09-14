from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .audit import validate_audit_evidence
from .canonical import canonical_json_bytes, sha256_bytes
from .models import (
    ArtifactReference,
    OfficialContentDate,
    Provenance,
    SourceDataStatus,
    SourceStatus,
)
from .publish import PublishError, has_successful_publish_event


@dataclass(frozen=True)
class OfficialState:
    availability: str
    reason: str | None
    status: SourceStatus
    provenance: Provenance | None
    rows: tuple[dict[str, Any], ...]
    currently_reproducible_from_upstream: bool = False
    latest_candidate_id: str | None = None


class _OperationalIntegrityError(ValueError):
    """The serving data may be intact, but its operational status is not bound."""


# data.gov.tw declares the NHI dataset as updated every 1 day (updateFrequency).
# SDD 8.3: NHI is stale after more than two declared cycles without a successful check.
# Owner decision 2026-09-14 (D-008): no hard-stop; keep serving with the warning.
NHI_DECLARED_UPDATE_CYCLE = timedelta(days=1)
NHI_CHECK_OVERDUE_AFTER = 2 * NHI_DECLARED_UPDATE_CYCLE
_STALE_REASON_ORDER = (
    "upstream_check_overdue",
    "upstream_verification_failed",
    "newer_candidate_pending_review",
    "newer_candidate_rejected",
    "newer_candidate_awaiting_publish",
)


def _now(clock: Callable[[], datetime] | None) -> datetime:
    value = clock() if clock else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("freshness clock must include a timezone")
    return value


def _effective_stale_reason_codes(descriptor: dict[str, Any], now: datetime) -> list[str]:
    stored = list(descriptor["stale_reason_codes"])
    codes = set(stored)
    last_success = descriptor["last_successful_check_at"]
    if (
        last_success is None
        or now - datetime.fromisoformat(last_success.replace("Z", "+00:00"))
        > NHI_CHECK_OVERDUE_AFTER
    ):
        codes.add("upstream_check_overdue")
    ordered = [code for code in _STALE_REASON_ORDER if code in codes]
    return ordered + [code for code in stored if code not in _STALE_REASON_ORDER]


def _empty_status() -> SourceStatus:
    return SourceStatus(
        serving_validation_status="not_applicable",
        serving_review_status="not_applicable",
        latest_candidate_status="none",
        stale=False,
        stale_reason_codes=[],
    )


def _read_json(path: Path) -> dict[str, Any]:
    pairs: list[tuple[str, Any]] = []

    def collect(items: list[tuple[str, Any]]) -> dict[str, Any]:
        keys = [key for key, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate JSON key")
        result = dict(items)
        pairs.append((str(path), result))
        return result

    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=collect)
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise ValueError("non-canonical JSON descriptor")
    return value


def _file_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _contained(root: Path, relative: str) -> Path:
    candidate = (root / Path(relative)).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("path escapes data root")
    return candidate


def _unavailable(
    reason: str, status: SourceStatus | None = None, latest_candidate_id: str | None = None
) -> OfficialState:
    return OfficialState(
        availability="data_unavailable",
        reason=reason,
        status=status or _empty_status(),
        provenance=None,
        rows=(),
        latest_candidate_id=latest_candidate_id,
    )


def _status_from_descriptor(
    descriptor: dict[str, Any], available: bool, stale_reason_codes: list[str] | None = None
) -> SourceStatus:
    codes = list(stale_reason_codes or []) if available else []
    return SourceStatus(
        serving_validation_status="passed" if available else "not_applicable",
        serving_review_status="approved" if available else "not_applicable",
        latest_candidate_status=descriptor.get("latest_candidate_status", "none"),
        stale=bool(codes),
        stale_reason_codes=codes,
    )


_DESCRIPTOR_KEYS = frozenset(
    {
        "descriptor_schema_version",
        "source_id",
        "generation",
        "serving_snapshot_id",
        "serving_curated_build_id",
        "manifest_data_root_relative_path",
        "manifest_sha256",
        "parent_snapshot_id",
        "last_successful_publish_at",
        "publisher_actor_id",
        "last_check_at",
        "last_successful_check_at",
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
        "latest_check_data_root_relative_path",
        "latest_check_sha256",
    }
)
_CHECK_KEYS = frozenset(
    {
        "check_schema_version",
        "check_id",
        "source_id",
        "generation",
        "serving_snapshot_id",
        "serving_curated_build_id",
        "checked_at",
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
    }
)
_OPERATIONAL_KEYS = frozenset(
    {
        "last_check_at",
        "last_successful_check_at",
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
        "latest_check_data_root_relative_path",
        "latest_check_sha256",
    }
)


def _validate_descriptor_shape(descriptor: dict[str, Any]) -> None:
    missing = _DESCRIPTOR_KEYS - descriptor.keys()
    if missing & _OPERATIONAL_KEYS:
        raise _OperationalIntegrityError("descriptor operational fields missing")
    if set(descriptor) != _DESCRIPTOR_KEYS:
        raise ValueError("descriptor schema mismatch")
    if descriptor["descriptor_schema_version"] != 1 or descriptor["source_id"] != "nhi_fee":
        raise ValueError("descriptor schema/source mismatch")
    if type(descriptor["generation"]) is not int or descriptor["generation"] < 1:
        raise ValueError("descriptor generation mismatch")
    serving_fields = (
        descriptor["serving_snapshot_id"],
        descriptor["serving_curated_build_id"],
        descriptor["manifest_data_root_relative_path"],
        descriptor["manifest_sha256"],
    )
    if any(value is None for value in serving_fields) and not all(
        value is None for value in serving_fields
    ):
        raise ValueError("serving pointer must be all-null or all-present")
    if type(descriptor["stale"]) is not bool:
        raise ValueError("stale must be a strict boolean")
    if descriptor["stale"] != bool(descriptor["stale_reason_codes"]):
        raise ValueError("stale reason mismatch")
    serving_is_absent = all(value is None for value in serving_fields)
    if serving_is_absent and (descriptor["stale"] or descriptor["stale_reason_codes"]):
        raise ValueError("unavailable descriptor cannot be stale")
    candidate_status = descriptor["latest_candidate_status"]
    if candidate_status == "none" and descriptor["latest_candidate_id"] is not None:
        raise ValueError("candidate id must be null when status is none")
    if candidate_status != "none" and not descriptor["latest_candidate_id"]:
        raise ValueError("candidate id is required for a candidate status")
    check_fields = (
        descriptor["latest_check_data_root_relative_path"],
        descriptor["latest_check_sha256"],
    )
    if any(value is None for value in check_fields) and not all(
        value is None for value in check_fields
    ):
        raise _OperationalIntegrityError("check reference must be paired")
    if not serving_is_absent and all(value is None for value in check_fields):
        raise _OperationalIntegrityError("serving descriptor requires a check reference")


def _validate_check_record(
    data_root: Path, descriptor: dict[str, Any], check: dict[str, Any]
) -> None:
    if set(check) != _CHECK_KEYS:
        raise _OperationalIntegrityError("check schema mismatch")
    if check["check_schema_version"] != 1 or check["source_id"] != "nhi_fee":
        raise _OperationalIntegrityError("check source/schema mismatch")
    if type(check["generation"]) is not int or check["generation"] != descriptor["generation"]:
        raise _OperationalIntegrityError("check generation mismatch")
    if (
        check["serving_snapshot_id"] != descriptor["serving_snapshot_id"]
        or check["serving_curated_build_id"] != descriptor["serving_curated_build_id"]
    ):
        raise _OperationalIntegrityError("check serving identity mismatch")
    try:
        datetime.fromisoformat(check["checked_at"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise _OperationalIntegrityError("check timestamp invalid") from exc
    for key in (
        "latest_seen_version",
        "latest_seen_artifact_sha256",
        "latest_candidate_id",
        "latest_candidate_status",
        "check_result",
        "failed_stage",
        "error_code",
        "stale",
        "stale_reason_codes",
        "freshness_policy_version",
        "content_age_status",
        "content_age_evidence",
    ):
        if check[key] != descriptor[key]:
            raise _OperationalIntegrityError(f"check field mismatch: {key}")
    if descriptor["last_check_at"] != check["checked_at"]:
        raise _OperationalIntegrityError("last check timestamp mismatch")
    if (
        descriptor["check_result"] == "success"
        and descriptor["last_successful_check_at"] != check["checked_at"]
    ):
        raise _OperationalIntegrityError("successful check timestamp mismatch")
    relative = descriptor["latest_check_data_root_relative_path"]
    posix_path = PurePosixPath(relative)
    if (
        posix_path.is_absolute()
        or posix_path.parts[:2] != ("checks", "nhi_fee")
        or len(posix_path.parts) != 3
    ):
        raise _OperationalIntegrityError("check path outside source checks")
    if posix_path.stem != check["check_id"]:
        raise _OperationalIntegrityError("check id/path mismatch")
    check_path = _contained(data_root, relative)
    if not check_path.is_file() or _file_hash(check_path) != descriptor["latest_check_sha256"]:
        raise _OperationalIntegrityError("check hash mismatch")


def read_nhi_state(
    data_root: Path, *, clock: Callable[[], datetime] | None = None
) -> OfficialState:
    return _read_nhi_state(data_root, _now(clock))


def _read_nhi_state(data_root: Path, now: datetime) -> OfficialState:
    descriptor_path = Path(data_root) / "manifests" / "current" / "nhi_fee.json"
    if not descriptor_path.is_file():
        try:
            if has_successful_publish_event(Path(data_root), "nhi_fee"):
                return _unavailable("serving_integrity_failure")
        except PublishError:
            return _unavailable("serving_integrity_failure")
        return _unavailable("no_serving_snapshot")
    try:
        descriptor = _read_json(descriptor_path)
        _validate_descriptor_shape(descriptor)
        snapshot_id = descriptor.get("serving_snapshot_id")
        build_id = descriptor.get("serving_curated_build_id")
        check_relative = descriptor["latest_check_data_root_relative_path"]
        if check_relative is not None:
            check_posix = PurePosixPath(check_relative)
            if (
                check_posix.is_absolute()
                or check_posix.parts[:2] != ("checks", "nhi_fee")
                or len(check_posix.parts) != 3
            ):
                raise _OperationalIntegrityError("check path outside source checks")
            check_path = _contained(Path(data_root), check_relative)
            if not check_path.is_file():
                raise _OperationalIntegrityError("check record missing")
            try:
                check = _read_json(check_path)
            except (KeyError, TypeError, ValueError, OSError) as exc:
                raise _OperationalIntegrityError("check record cannot be read") from exc
            _validate_check_record(Path(data_root), descriptor, check)
        if snapshot_id is None or build_id is None:
            return _unavailable(
                "no_serving_snapshot",
                _status_from_descriptor(descriptor, available=False),
                descriptor["latest_candidate_id"],
            )
        manifest_rel = descriptor["manifest_data_root_relative_path"]
        if manifest_rel != f"curated/nhi_fee/{build_id}/manifest.json":
            raise ValueError("manifest path outside curated source")
        manifest_path = _contained(Path(data_root), manifest_rel)
        if (
            not manifest_path.is_file()
            or _file_hash(manifest_path) != descriptor["manifest_sha256"]
        ):
            raise ValueError("manifest hash mismatch")
        manifest = _read_json(manifest_path)
        if (
            manifest.get("state") != "approved"
            or manifest.get("source_id") != "nhi_fee"
            or manifest.get("snapshot_id") != snapshot_id
            or manifest.get("curated_build_id") != build_id
        ):
            raise ValueError("manifest identity mismatch")
        validate_audit_evidence(Path(data_root), manifest)
        fingerprint = manifest["build_fingerprint"]
        fingerprint_hash = manifest["build_fingerprint_sha256"]
        if (
            sha256_bytes(canonical_json_bytes(fingerprint)) != fingerprint_hash
            or build_id != f"nhi_fee-build-{fingerprint_hash}"
            or fingerprint.get("source_id") != "nhi_fee"
            or fingerprint.get("raw_revision_id") != manifest.get("raw_revision_id")
        ):
            raise ValueError("build fingerprint mismatch")
        publication = manifest["publication"]
        expected_db_relative = f"curated/nhi_fee/{build_id}/data.sqlite3"
        if publication.get("curated_build_relative_path") != expected_db_relative:
            raise ValueError("database path outside curated source")
        db_path = _contained(Path(data_root), publication["curated_build_relative_path"])
        if not db_path.is_file() or _file_hash(db_path) != publication["curated_sha256"]:
            raise ValueError("database hash mismatch")

        uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA query_only=ON")
            try:
                connection.execute("PRAGMA trusted_schema=OFF")
            except sqlite3.DatabaseError:
                pass
            rows = tuple(
                dict(row)
                for row in connection.execute(
                    "SELECT source_row_sha256, source_row_number, code_raw, code_normalized, "
                    "points_raw, points, effective_start_raw, effective_start, effective_end_raw, "
                    "effective_end, possible_open_end_sentinel, name_zh_raw, name_zh_search, "
                    "name_en_raw, name_en_search, note_raw, note_search, scope_status, "
                    "scope_rule_version, scope_basis_locator FROM nhi_fee ORDER BY source_row_number"
                ).fetchall()
            )
        finally:
            connection.close()

        counts = manifest.get("counts")
        if (
            not isinstance(counts, dict)
            or set(counts) != {"input_rows", "curated_rows", "quarantined_rows"}
            or any(type(value) is not int or value < 0 for value in counts.values())
            or counts["input_rows"] != counts["curated_rows"]
            or counts["quarantined_rows"] != 0
            or len(rows) != counts["curated_rows"]
            or len({row["source_row_sha256"] for row in rows}) != len(rows)
            or sorted(row["source_row_number"] for row in rows)
            != list(range(2, counts["curated_rows"] + 2))
        ):
            raise ValueError("curated row coverage mismatch")

        source = manifest["source"]
        artifact = manifest["artifacts"][0]
        expected_raw_relative = f"raw/nhi_fee/{manifest['raw_revision_id']}/artifacts/source.csv"
        if (
            artifact.get("storage_scope") != "data_root"
            or artifact.get("data_root_relative_path") != expected_raw_relative
        ):
            raise ValueError("raw artifact path outside raw source")
        if artifact.get("local_artifact_available"):
            raw_path = _contained(Path(data_root), artifact["data_root_relative_path"])
            if not raw_path.is_file() or _file_hash(raw_path) != artifact["sha256"]:
                raise ValueError("raw artifact hash mismatch")
        official_content_date = None
        official = manifest.get("official_version", {})
        if official.get("modified_at_raw"):
            # The manifest keeps the raw precision (for example "second"); the public
            # contract only allows day/month/year/unknown, so never claim more than that.
            precision = official.get("modified_at_precision")
            official_content_date = OfficialContentDate(
                value_raw=official["modified_at_raw"],
                precision=precision if precision in {"day", "month", "year"} else "unknown",
                timezone_known=bool(official.get("timezone_known", False)),
            )
        retrieved_at = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
        stale_reason_codes = _effective_stale_reason_codes(descriptor, now)
        provenance = Provenance(
            source_id="nhi_fee",
            source_name=source["dataset_name"],
            provider=source["provider"],
            landing_url=source["landing_url"],
            resource_url=source["resource_url"],
            snapshot_id=snapshot_id,
            curated_build_id=build_id,
            official_version_raw=official.get("label"),
            official_content_date=official_content_date,
            retrieved_at=retrieved_at,
            artifacts=[
                ArtifactReference(
                    artifact_id=artifact["artifact_id"],
                    role=artifact["role"],
                    storage_scope=artifact["storage_scope"],
                    data_root_relative_path=artifact["data_root_relative_path"],
                    official_url=artifact["resource_url"],
                    sha256=artifact["sha256"],
                    local_artifact_available=artifact["local_artifact_available"],
                )
            ],
            parser_version=manifest["transform"]["parser"]["version"],
            schema_version=manifest["transform"]["schema"]["version"],
            rule_bundle_version="nhi-lab-scope-v1",
            license_name=source["license_name"],
            license_url=source["license_url"],
            attribution=source["attribution"],
            coverage_status="review_incomplete",
            stale=bool(stale_reason_codes),
            stale_reason_codes=stale_reason_codes,
            last_check_at=(
                datetime.fromisoformat(descriptor["last_check_at"].replace("Z", "+00:00"))
                if descriptor.get("last_check_at")
                else None
            ),
            serving_review_status="approved",
        )
        return OfficialState(
            availability="available",
            reason=None,
            status=_status_from_descriptor(descriptor, True, stale_reason_codes),
            provenance=provenance,
            rows=rows,
        )
    except _OperationalIntegrityError:
        return _unavailable("operational_status_integrity_failure")
    except (KeyError, TypeError, ValueError, OSError, sqlite3.DatabaseError):
        return _unavailable("serving_integrity_failure")


def read_source_status(
    data_root: Path, source_id: str, *, clock: Callable[[], datetime] | None = None
) -> SourceDataStatus:
    now = _now(clock)
    if source_id == "nhi_fee":
        state = _read_nhi_state(data_root, now)
        descriptor_path = Path(data_root) / "manifests" / "current" / "nhi_fee.json"
    else:
        state = _unavailable("no_serving_snapshot")
        descriptor_path = Path(data_root) / "manifests" / "current" / f"{source_id}.json"
    if not descriptor_path.is_file() or state.availability == "data_unavailable":
        candidate_id = state.latest_candidate_id if state.reason == "no_serving_snapshot" else None
        candidate_status = (
            state.status.latest_candidate_status
            if state.reason == "no_serving_snapshot"
            else "none"
        )
        return SourceDataStatus(
            source_id=source_id,
            availability="data_unavailable",
            availability_reason_code=state.reason or "no_serving_snapshot",
            serving_snapshot_id=None,
            serving_curated_build_id=None,
            serving_validation_status="not_applicable",
            serving_review_status="not_applicable",
            latest_candidate_id=candidate_id,
            latest_candidate_status=candidate_status,
            coverage_status="review_incomplete" if source_id == "nhi_fee" else "unknown",
            last_check_at=None,
            last_successful_check_at=None,
            last_successful_publish_at=None,
            official_content_date=None,
            latest_seen_version=None,
            stale=False,
            stale_reason_codes=[],
            content_age_status="unknown",
            freshness_policy_version=f"{source_id}-v1",
            content_age_evidence=None,
        )
    try:
        descriptor = _read_json(descriptor_path)

        def parse_time(key: str) -> datetime | None:
            if not descriptor.get(key):
                return None
            return datetime.fromisoformat(descriptor[key].replace("Z", "+00:00"))

        return SourceDataStatus(
            source_id=source_id,
            availability="available",
            availability_reason_code=None,
            serving_snapshot_id=descriptor["serving_snapshot_id"],
            serving_curated_build_id=descriptor["serving_curated_build_id"],
            serving_validation_status="passed",
            serving_review_status="approved",
            latest_candidate_id=descriptor.get("latest_candidate_id"),
            latest_candidate_status=descriptor.get("latest_candidate_status", "none"),
            coverage_status=state.provenance.coverage_status if state.provenance else "unknown",
            last_check_at=parse_time("last_check_at"),
            last_successful_check_at=parse_time("last_successful_check_at"),
            last_successful_publish_at=parse_time("last_successful_publish_at"),
            official_content_date=state.provenance.official_content_date
            if state.provenance
            else None,
            latest_seen_version=descriptor.get("latest_seen_version"),
            stale=state.status.stale,
            stale_reason_codes=list(state.status.stale_reason_codes),
            content_age_status=descriptor.get("content_age_status", "unknown"),
            freshness_policy_version=descriptor.get("freshness_policy_version", f"{source_id}-v1"),
            content_age_evidence=descriptor.get("content_age_evidence"),
        )
    except (KeyError, TypeError, ValueError, OSError):
        return SourceDataStatus(
            source_id=source_id,
            availability="data_unavailable",
            availability_reason_code="serving_integrity_failure",
            serving_snapshot_id=None,
            serving_curated_build_id=None,
            serving_validation_status="not_applicable",
            serving_review_status="not_applicable",
            latest_candidate_id=None,
            latest_candidate_status="none",
            coverage_status="unknown",
            last_check_at=None,
            last_successful_check_at=None,
            last_successful_publish_at=None,
            official_content_date=None,
            latest_seen_version=None,
            stale=False,
            stale_reason_codes=[],
            content_age_status="unknown",
            freshness_policy_version=f"{source_id}-v1",
            content_age_evidence=None,
        )
