from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from uuid import uuid4

from .canonical import canonical_json_bytes, sha256_bytes
from .fetch import FetchedArtifact, FetchError
from .importers.nhi import NHIImportError, NHIParseResult, parse_nhi_csv
from .nhi_source import (
    fetch_nhi_source,
    nhi_discovery_metadata_sha256,
    nhi_raw_revision_id,
)

SyncClock = Callable[[], datetime]


class SyncError(ValueError):
    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{stage}: {code}")


def _discovery_with_metadata(
    discovery: dict[str, Any] | None, metadata: FetchedArtifact | None
) -> dict[str, Any] | None:
    if discovery is None and metadata is None:
        return None
    result = dict(discovery or {})
    if metadata is not None:
        result.update(
            {
                "metadata_final_url": metadata.final_url,
                "metadata_sha256": metadata.sha256,
                "metadata_fetched_at": metadata.fetched_at,
            }
        )
    return result


def _utc_now(clock: SyncClock | None) -> datetime:
    value = clock() if clock else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("sync clock must include a timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _write_immutable_json(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_json_bytes(value)
    if path.exists():
        if path.read_bytes() != payload:
            raise SyncError("IMMUTABLE_REPORT_CONFLICT", "write")
        return
    _write_new_file(path, payload)


def _write_raw_revision(
    data_root: Path,
    *,
    raw_revision_id: str,
    payload: bytes,
    fetched_artifact: FetchedArtifact,
    discovery: dict[str, Any] | None,
    media_type_verified: str,
) -> tuple[str, str]:
    """Keep the fetched bytes and first fetch evidence under the immutable raw revision."""

    if fetched_artifact.sha256 != sha256_bytes(payload):
        raise SyncError("RAW_ARTIFACT_HASH_MISMATCH", "fetch")
    revision_dir = PurePosixPath("raw", "nhi_fee", raw_revision_id)
    artifact_relative = revision_dir / "artifacts" / "source.csv"
    fetch_relative = revision_dir / "fetch.json"
    artifact_path = data_root / artifact_relative
    if artifact_path.exists():
        if artifact_path.read_bytes() != payload:
            raise SyncError("IMMUTABLE_RAW_CONFLICT", "fetch")
    else:
        _write_new_file(artifact_path, payload)
        if sha256_bytes(artifact_path.read_bytes()) != fetched_artifact.sha256:
            raise SyncError("RAW_ARTIFACT_READBACK_MISMATCH", "fetch")
    fetch_path = data_root / fetch_relative
    # The same raw revision can be fetched again later; volatile evidence from later
    # attempts stays in their staged reports and never rewrites the first record.
    if not fetch_path.exists():
        _write_immutable_json(
            fetch_path,
            {
                "fetch_record_schema_version": 1,
                "source_id": "nhi_fee",
                "raw_revision_id": raw_revision_id,
                "discovery": discovery,
                "artifact": {
                    "artifact_id": "nhi-primary-csv",
                    "role": "primary",
                    "data_root_relative_path": str(artifact_relative),
                    "requested_url": fetched_artifact.requested_url,
                    "final_url": fetched_artifact.final_url,
                    "status_code": fetched_artifact.status_code,
                    "headers": fetched_artifact.headers,
                    "redirect_trace": list(fetched_artifact.redirect_trace),
                    "media_type_verified": media_type_verified,
                    "bytes": len(payload),
                    "sha256": fetched_artifact.sha256,
                    "fetched_at": fetched_artifact.fetched_at,
                },
            },
        )
    return str(artifact_relative), str(fetch_relative)


def _attempt_id(source_id: str, payload_sha256: str | None, started_at: datetime) -> str:
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid4().hex}"


def _candidate_build_id(payload_sha256: str) -> str:
    return f"nhi_fee-candidate-build-{payload_sha256}"


def _base_report(
    *,
    attempt_id: str,
    started_at: datetime,
    completed_at: datetime,
    stage: str,
    status: str,
    error_code: str | None,
    payload_sha256: str | None,
    raw_revision_id: str | None,
    candidate_build_id: str | None,
    parsed: NHIParseResult | None,
    report_relative_path: str,
    discovery: dict[str, Any] | None = None,
    fetched_artifact: FetchedArtifact | None = None,
    raw_artifact_relative_path: str | None = None,
    raw_fetch_record_relative_path: str | None = None,
) -> dict[str, Any]:
    row_count = len(parsed.rows) if parsed else 0
    warnings = list(parsed.warnings) if parsed else []
    artifact_hashes = []
    if payload_sha256:
        artifact_hashes.append(
            {
                "artifact_id": "nhi-primary-csv",
                "role": "primary",
                "sha256": payload_sha256,
                "local_artifact_available": raw_artifact_relative_path is not None,
                "data_root_relative_path": raw_artifact_relative_path,
            }
        )
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": "nhi_fee",
        "stage": stage,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "status": status,
        "error_code": error_code,
        "raw_revision_id": raw_revision_id,
        "discovery_metadata_sha256": nhi_discovery_metadata_sha256(discovery),
        "build_attempt_id": attempt_id,
        "candidate_curated_build_id": candidate_build_id,
        "candidate_status": "review_pending" if candidate_build_id else "none",
        "subject_digest": None,
        "artifact_hashes": artifact_hashes,
        "raw_fetch_record_data_root_relative_path": raw_fetch_record_relative_path,
        "transform": {
            "parser_version": "nhi-csv-v1",
            "schema_version": "nhi-7-v1",
            "normalization_version": "text-v1",
        },
        "row_counts": {
            "input_rows": row_count,
            "curated_rows": 0,
            "quarantined_rows": 0,
        },
        "header_hash": None,
        "null_rates": {},
        "status_distributions": {},
        "current_drift": None,
        "blocking_errors": [error_code] if error_code else [],
        "warnings": warnings,
        "quarantine_count": 0,
        "golden_qualification": None,
        "report_data_root_relative_path": report_relative_path,
    }
    if discovery is not None:
        report["discovery"] = discovery
    if fetched_artifact is not None:
        report["fetch"] = {
            "requested_url": fetched_artifact.requested_url,
            "final_url": fetched_artifact.final_url,
            "status_code": fetched_artifact.status_code,
            "size_bytes": len(fetched_artifact.payload),
            "sha256": fetched_artifact.sha256,
            "fetched_at": fetched_artifact.fetched_at,
            "headers": fetched_artifact.headers,
            "redirect_trace": list(fetched_artifact.redirect_trace),
        }
    return report


def run_nhi_sync(
    payload: bytes | None,
    data_root: Path,
    *,
    fail_stage: str | None = None,
    clock: SyncClock | None = None,
    initial_error: str | None = None,
    initial_stage: str = "discover",
    discovery: dict[str, Any] | None = None,
    fetched_artifact: FetchedArtifact | None = None,
) -> dict[str, Any]:
    """Run the NHI discover-to-validate path without auto-publish.

    Only bytes fetched from the upstream source are kept as an immutable raw revision;
    caller-supplied offline input has no upstream provenance and stays report-only.
    """

    data_root = Path(data_root)
    if initial_stage not in {"discover", "fetch"}:
        raise ValueError("initial_stage must be discover or fetch")
    started_at = _utc_now(clock)
    payload_sha256 = sha256_bytes(payload) if payload is not None else None
    attempt_id = _attempt_id("nhi_fee", payload_sha256, started_at)
    report_relative = str(PurePosixPath("staged", "nhi_fee", attempt_id, "validation.json"))
    parsed: NHIParseResult | None = None
    media_type_verified = "text/csv"
    if fetched_artifact is not None:
        media_type_verified = (
            fetched_artifact.headers.get("content-type", "text/csv")
            .split(";", 1)[0]
            .strip()
            .lower()
            or "text/csv"
        )
    raw_revision_id = (
        nhi_raw_revision_id(
            payload_sha256=payload_sha256,
            payload_size=len(payload),
            discovery=discovery,
            media_type_verified=media_type_verified,
        )
        if payload_sha256
        else None
    )
    candidate_build_id = _candidate_build_id(payload_sha256) if payload_sha256 else None
    raw_artifact_relative: str | None = None
    raw_fetch_record_relative: str | None = None
    stage = initial_stage
    status = "failed"
    error_code = initial_error
    if error_code is None and fail_stage == "discover":
        error_code = "DISCOVERY_INJECTED_FAILURE"
    if error_code is None and payload is None:
        error_code = "DISCOVERY_INPUT_REQUIRED"
    if error_code is None:
        stage = "fetch"
        if fail_stage == "fetch":
            error_code = "FETCH_INJECTED_FAILURE"
        elif fetched_artifact is not None and raw_revision_id is not None:
            try:
                raw_artifact_relative, raw_fetch_record_relative = _write_raw_revision(
                    data_root,
                    raw_revision_id=raw_revision_id,
                    payload=payload,
                    fetched_artifact=fetched_artifact,
                    discovery=discovery,
                    media_type_verified=media_type_verified,
                )
            except SyncError as exc:
                error_code = exc.code
    if error_code is None:
        stage = "parse"
        if fail_stage == "parse":
            error_code = "PARSE_INJECTED_FAILURE"
        else:
            try:
                parsed = parse_nhi_csv(payload)
            except NHIImportError as exc:
                error_code = exc.code
    if error_code is None:
        stage = "normalize"
        if fail_stage == "normalize":
            error_code = "NORMALIZATION_INJECTED_FAILURE"
    if error_code is None:
        stage = "validate"
        if fail_stage == "validate":
            error_code = "VALIDATION_INJECTED_FAILURE"
        elif parsed is None or not parsed.rows:
            error_code = "ZERO_ROWS"
        else:
            status = "passed"
    completed_at = _utc_now(clock)
    report = _base_report(
        attempt_id=attempt_id,
        started_at=started_at,
        completed_at=completed_at,
        stage=stage,
        status=status,
        error_code=error_code,
        payload_sha256=payload_sha256,
        raw_revision_id=raw_revision_id,
        candidate_build_id=candidate_build_id if status == "passed" else None,
        parsed=parsed,
        report_relative_path=report_relative,
        discovery=discovery,
        fetched_artifact=fetched_artifact,
        raw_artifact_relative_path=raw_artifact_relative,
        raw_fetch_record_relative_path=raw_fetch_record_relative,
    )
    _write_immutable_json(data_root / PurePosixPath(report_relative), report)
    return report


def run_nhi_upstream_sync(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    metadata_url: str | None = None,
    max_metadata_bytes: int = 2 * 1024 * 1024,
    max_csv_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 30.0,
    max_redirects: int = 3,
    opener=None,
    clock: SyncClock | None = None,
) -> dict[str, Any]:
    """Fetch NHI metadata/CSV, keep the raw revision and stop at a candidate report."""

    try:
        fetched = fetch_nhi_source(
            expected_publisher_oid=expected_publisher_oid,
            metadata_url=metadata_url or "https://data.gov.tw/api/v2/rest/dataset/174450",
            max_metadata_bytes=max_metadata_bytes,
            max_csv_bytes=max_csv_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            opener=opener,
            clock=clock,
        )
    except FetchError as exc:
        return run_nhi_sync(
            None,
            data_root,
            clock=clock,
            initial_error=exc.code,
            initial_stage=exc.stage or "fetch",
            discovery=_discovery_with_metadata(exc.discovery, exc.metadata),
        )

    metadata = fetched["metadata"]
    discovery = _discovery_with_metadata(fetched["discovery"], metadata)
    return run_nhi_sync(
        fetched["artifact"].payload,
        data_root,
        clock=clock,
        discovery=discovery,
        fetched_artifact=fetched["artifact"],
    )
