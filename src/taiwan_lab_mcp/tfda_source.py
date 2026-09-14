"""TFDA medical device permit dataset: upstream discovery, raw ZIP retention, validation.

Owner confirmed the source identity on 2026-09-14 (owner-review
tfda-source-identity-confirmation-2026-09-14.md). This path keeps the fetched ZIP as an
immutable raw revision and writes a staged validation report. It never creates a
candidate, curated build or current descriptor.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .canonical import sha256_bytes, sha256_json
from .fetch import FetchedArtifact, FetchError, fetch_https_bytes
from .importers.tfda import (
    MAX_ZIP_BYTES,
    TFDA_PARSER_VERSION,
    TFDA_SCHEMA_VERSION,
    TFDA_SOURCE_ID,
    TFDAImportError,
    extract_tfda_csv,
    summarize_tfda_csv,
)

TFDA_DATASET_ID = "9576"
TFDA_SOURCE_IDENTIFIER = "A21020000I-000053"
TFDA_PUBLISHER_OID = "2.16.886.101.20003.20065.20065"
TFDA_PROVIDER = "衛生福利部食品藥物管理署"
TFDA_METADATA_URL = "https://data.gov.tw/api/v2/rest/dataset/9576"
TFDA_LANDING_URL = "https://data.gov.tw/dataset/9576"
TFDA_LICENSE_CODE = "1"
TFDA_LICENSE = "政府資料開放授權條款-第1版"
TFDA_LICENSE_URL = "https://data.gov.tw/license"
TFDA_METADATA_HOSTS = frozenset({"data.gov.tw"})
TFDA_RESOURCE_HOSTS = frozenset({"data.fda.gov.tw"})
PRIMARY_ARTIFACT_ID = "tfda-primary-zip"


def discover_tfda_resource(
    metadata_payload: bytes, *, expected_publisher_oid: str
) -> dict[str, Any]:
    try:
        document = json.loads(metadata_payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError("DISCOVERY_METADATA_INVALID") from exc
    if not isinstance(document, dict) or document.get("success") is not True:
        raise FetchError("DISCOVERY_METADATA_INVALID")
    result = document.get("result")
    if not isinstance(result, dict):
        raise FetchError("DISCOVERY_METADATA_INVALID")
    if not isinstance(expected_publisher_oid, str) or not expected_publisher_oid:
        raise FetchError("DISCOVERY_EXPECTATION_INVALID")
    if result.get("publisherOID") != expected_publisher_oid:
        raise FetchError("DISCOVERY_PUBLISHER_MISMATCH")
    if result.get("identifier") != TFDA_SOURCE_IDENTIFIER:
        raise FetchError("DISCOVERY_IDENTIFIER_MISMATCH")
    if result.get("license") != TFDA_LICENSE_CODE:
        raise FetchError("DISCOVERY_LICENSE_MISMATCH")

    distributions = result.get("distribution")
    matches = [
        item
        for item in (distributions if isinstance(distributions, list) else [])
        if isinstance(item, dict)
        and str(item.get("resourceFormat", "")).upper() == "CSV"
        and str(item.get("resourceCharacterEncoding", "")).upper() == "UTF-8"
        and isinstance(item.get("resourceDownloadUrl"), str)
        and item["resourceDownloadUrl"]
    ]
    if not matches:
        raise FetchError("DISCOVERY_RESOURCE_MISSING")
    if len(matches) != 1:
        raise FetchError("DISCOVERY_RESOURCE_AMBIGUOUS")
    resource_url = matches[0]["resourceDownloadUrl"]
    parsed = urlsplit(resource_url)
    host = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
    if parsed.scheme.lower() != "https" or host not in TFDA_RESOURCE_HOSTS:
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    modified = result.get("modifiedDate")
    return {
        "dataset_id": TFDA_DATASET_ID,
        "identifier": TFDA_SOURCE_IDENTIFIER,
        "publisher_oid": expected_publisher_oid,
        "landing_url": TFDA_LANDING_URL,
        "metadata_url": TFDA_METADATA_URL,
        "license_code": TFDA_LICENSE_CODE,
        "license_name": TFDA_LICENSE,
        "license_url": TFDA_LICENSE_URL,
        "provider": TFDA_PROVIDER,
        "resource_format": "CSV",
        "resource_url": resource_url,
        "official_modified_at_raw": modified if isinstance(modified, str) and modified else None,
        "official_modified_timezone_known": False,
    }


def tfda_raw_revision_id(
    *, payload_sha256: str, payload_size: int, discovery: dict[str, Any]
) -> str:
    """RawRevisionFingerprintV1 for one fetched TFDA ZIP plus its non-volatile discovery."""

    return sha256_json(
        {
            "fingerprint_schema": "raw-revision-v1",
            "source_id": TFDA_SOURCE_ID,
            "discovery": {
                key: discovery.get(key)
                for key in (
                    "landing_url",
                    "publisher_oid",
                    "dataset_id",
                    "identifier",
                    "license_name",
                    "license_url",
                    "official_modified_at_raw",
                    "official_modified_timezone_known",
                )
            },
            "artifacts": [
                {
                    "artifact_id": PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "media_type_verified": "application/zip",
                    "bytes": payload_size,
                    "sha256": payload_sha256,
                }
            ],
        }
    )


def _fetch_evidence(artifact: FetchedArtifact) -> dict[str, Any]:
    return {
        "requested_url": artifact.requested_url,
        "final_url": artifact.final_url,
        "status_code": artifact.status_code,
        "headers": artifact.headers,
        "redirect_trace": list(artifact.redirect_trace),
        "bytes": len(artifact.payload),
        "sha256": artifact.sha256,
        "fetched_at": artifact.fetched_at,
    }


def _write_raw_revision(
    data_root: Path, raw_revision_id: str, artifact: FetchedArtifact, discovery: dict[str, Any]
) -> tuple[str, str]:
    from .sync import SyncError, _write_immutable_json, _write_new_file

    if artifact.sha256 != sha256_bytes(artifact.payload):
        raise SyncError("RAW_ARTIFACT_HASH_MISMATCH", "fetch")
    revision_dir = PurePosixPath("raw", TFDA_SOURCE_ID, raw_revision_id)
    artifact_relative = str(revision_dir / "artifacts" / "source.zip")
    fetch_relative = str(revision_dir / "fetch.json")
    artifact_path = data_root / PurePosixPath(artifact_relative)
    if artifact_path.exists():
        if artifact_path.read_bytes() != artifact.payload:
            raise SyncError("IMMUTABLE_RAW_CONFLICT", "fetch")
    else:
        _write_new_file(artifact_path, artifact.payload)
    fetch_path = data_root / PurePosixPath(fetch_relative)
    # A later fetch of identical bytes keeps the first fetch record untouched.
    if not fetch_path.exists():
        _write_immutable_json(
            fetch_path,
            {
                "fetch_record_schema_version": 1,
                "source_id": TFDA_SOURCE_ID,
                "raw_revision_id": raw_revision_id,
                "discovery": discovery,
                "artifact": {
                    "artifact_id": PRIMARY_ARTIFACT_ID,
                    "role": "primary",
                    "data_root_relative_path": artifact_relative,
                    "media_type_verified": "application/zip",
                    **_fetch_evidence(artifact),
                },
            },
        )
    return artifact_relative, fetch_relative


def run_tfda_upstream_sync(
    data_root: Path,
    *,
    expected_publisher_oid: str,
    metadata_url: str = TFDA_METADATA_URL,
    max_zip_bytes: int = MAX_ZIP_BYTES,
    timeout_seconds: float = 60.0,
    max_redirects: int = 3,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    """Discover, fetch and validate the TFDA CSV ZIP; keep raw bytes; never publish."""

    from .sync import SyncError, _attempt_id, _utc_now, _write_immutable_json

    data_root = Path(data_root)
    started_at = _utc_now(clock)
    attempt_id = _attempt_id(TFDA_SOURCE_ID, None, started_at)
    report_relative = str(PurePosixPath("staged", TFDA_SOURCE_ID, attempt_id, "validation.json"))
    stage = "discover"
    error_code = None
    discovery = None
    artifact = None
    raw_revision_id = None
    artifact_relative = None
    fetch_relative = None
    summary = None
    try:
        metadata = fetch_https_bytes(
            metadata_url,
            allowed_hosts=TFDA_METADATA_HOSTS,
            max_bytes=2 * 1024 * 1024,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/json"},
            opener=opener,
            clock=clock,
        )
        discovery = discover_tfda_resource(
            metadata.payload, expected_publisher_oid=expected_publisher_oid
        )
        stage = "fetch"
        artifact = fetch_https_bytes(
            discovery["resource_url"],
            allowed_hosts=TFDA_RESOURCE_HOSTS,
            max_bytes=max_zip_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/zip", "application/octet-stream"},
            opener=opener,
            clock=clock,
        )
        raw_revision_id = tfda_raw_revision_id(
            payload_sha256=artifact.sha256, payload_size=len(artifact.payload), discovery=discovery
        )
        artifact_relative, fetch_relative = _write_raw_revision(
            data_root, raw_revision_id, artifact, discovery
        )
        stage = "archive"
        entry = extract_tfda_csv(artifact.payload, max_zip_bytes=max_zip_bytes)
        stage = "parse"
        summary = summarize_tfda_csv(entry)
        stage = "validate"
    except (FetchError, SyncError, TFDAImportError) as exc:
        error_code = exc.code
        if isinstance(exc, SyncError):
            raw_revision_id = None if artifact_relative is None else raw_revision_id
    except MemoryError:
        # Keep the stage and the already-saved raw ZIP; report instead of crashing.
        error_code = "RESOURCE_EXHAUSTED"
    completed_at = _utc_now(clock)
    report = {
        "sync_report_schema_version": 1,
        "attempt_id": attempt_id,
        "source_id": TFDA_SOURCE_ID,
        "input_kind": "upstream",
        "stage": stage,
        "status": "failed" if error_code else "passed",
        "error_code": error_code,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "raw_revision_id": raw_revision_id if artifact_relative else None,
        "raw_artifact_data_root_relative_path": artifact_relative,
        "raw_fetch_record_data_root_relative_path": fetch_relative,
        "discovery": discovery,
        "fetch": _fetch_evidence(artifact) if artifact is not None else None,
        "candidate_status": "none",
        "transform": {
            "parser_version": TFDA_PARSER_VERSION,
            "schema_version": TFDA_SCHEMA_VERSION,
        },
        "blocking_errors": [error_code] if error_code else [],
        "summary": summary,
        "report_data_root_relative_path": report_relative,
    }
    _write_immutable_json(data_root / PurePosixPath(report_relative), report)
    return report
