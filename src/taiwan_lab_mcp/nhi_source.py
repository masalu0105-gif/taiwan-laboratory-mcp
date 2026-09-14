from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .canonical import sha256_json
from .fetch import FetchError, fetch_https_bytes

NHI_DATASET_ID = "174450"
NHI_SOURCE_IDENTIFIER = "A21030000I-D20021"
NHI_METADATA_URL = "https://data.gov.tw/api/v2/rest/dataset/174450"
NHI_LANDING_URL = "https://data.gov.tw/dataset/174450"
# data.gov.tw metadata exposes the license as a code; the landing page shows the name.
NHI_LICENSE_CODE = "1"
NHI_LICENSE = "政府資料開放授權條款-第1版"
NHI_LICENSE_URL = "https://data.gov.tw/license"
NHI_METADATA_HOSTS = frozenset({"data.gov.tw"})
NHI_RESOURCE_HOSTS = frozenset({"info.nhi.gov.tw"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _normalize_identity_url(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("discovery identity URL must be a non-empty string")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("discovery identity URL is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("discovery identity URL is not safe")
    host = parsed.hostname.rstrip(".").lower()
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit(("https", netloc, parsed.path, parsed.query, ""))


def nhi_discovery_identity(discovery: dict[str, Any] | None) -> dict[str, Any]:
    """Return the non-volatile discovery object defined by RawRevisionFingerprintV1."""

    if discovery is None:
        return {
            "landing_url": None,
            "provider_id": None,
            "dataset_id": None,
            "license_name": None,
            "license_url": None,
            "official_version_label_raw": None,
            "official_modified_at_raw": None,
            "official_modified_at_precision": None,
            "official_modified_timezone_known": False,
        }
    if not isinstance(discovery, dict):
        raise ValueError("discovery identity must be an object")

    identity = {
        "landing_url": _normalize_identity_url(discovery.get("landing_url")),
        "provider_id": discovery.get("publisher_oid"),
        "dataset_id": discovery.get("dataset_id"),
        "license_name": discovery.get("license_name"),
        "license_url": _normalize_identity_url(discovery.get("license_url")),
        "official_version_label_raw": discovery.get("official_version_label_raw"),
        "official_modified_at_raw": discovery.get("official_modified_at_raw"),
        "official_modified_at_precision": discovery.get("official_modified_at_precision"),
        "official_modified_timezone_known": discovery.get(
            "official_modified_timezone_known", False
        ),
    }
    for key in (
        "provider_id",
        "dataset_id",
        "license_name",
        "official_version_label_raw",
        "official_modified_at_raw",
        "official_modified_at_precision",
    ):
        if identity[key] is not None and not isinstance(identity[key], str):
            raise ValueError(f"discovery identity {key} must be a string or null")
    if type(identity["official_modified_timezone_known"]) is not bool:
        raise ValueError("discovery identity timezone flag must be a boolean")
    return identity


def nhi_discovery_metadata_sha256(discovery: dict[str, Any] | None) -> str | None:
    if discovery is None or not {
        "landing_url",
        "publisher_oid",
        "dataset_id",
        "license_name",
        "license_url",
    }.issubset(discovery):
        return None
    return sha256_json(nhi_discovery_identity(discovery))


def nhi_raw_revision_id(
    *,
    payload_sha256: str,
    payload_size: int,
    discovery: dict[str, Any] | None,
    media_type_verified: str = "text/csv",
) -> str:
    if not isinstance(payload_sha256, str) or _SHA256.fullmatch(payload_sha256) is None:
        raise ValueError("payload hash is invalid")
    if type(payload_size) is not int or payload_size < 0:
        raise ValueError("payload size is invalid")
    if not isinstance(media_type_verified, str) or not media_type_verified:
        raise ValueError("media type is required")
    return sha256_json(
        {
            "fingerprint_schema": "raw-revision-v1",
            "source_id": "nhi_fee",
            "discovery": nhi_discovery_identity(discovery),
            "artifacts": [
                {
                    "artifact_id": "nhi-primary-csv",
                    "role": "primary",
                    "media_type_verified": media_type_verified,
                    "bytes": payload_size,
                    "sha256": payload_sha256,
                }
            ],
        }
    )


def discover_nhi_resource(
    metadata_payload: bytes,
    *,
    expected_publisher_oid: str,
    expected_identifier: str = NHI_SOURCE_IDENTIFIER,
    expected_license_code: str = NHI_LICENSE_CODE,
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
    if result.get("identifier") != expected_identifier:
        raise FetchError("DISCOVERY_IDENTIFIER_MISMATCH")
    if result.get("license") != expected_license_code:
        raise FetchError("DISCOVERY_LICENSE_MISMATCH")

    distributions = result.get("distribution")
    if not isinstance(distributions, list):
        raise FetchError("DISCOVERY_RESOURCE_MISSING")
    matches = []
    for distribution in distributions:
        if not isinstance(distribution, dict):
            continue
        if str(distribution.get("resourceFormat", "")).upper() != "CSV":
            continue
        if str(distribution.get("resourceCharacterEncoding", "")).upper() != "UTF-8":
            continue
        resource_url = distribution.get("resourceDownloadUrl")
        if isinstance(resource_url, str) and resource_url:
            matches.append(distribution)
    if not matches:
        raise FetchError("DISCOVERY_RESOURCE_MISSING")
    if len(matches) != 1:
        raise FetchError("DISCOVERY_RESOURCE_AMBIGUOUS")
    resource_url = matches[0]["resourceDownloadUrl"]
    parsed = urlsplit(resource_url)
    resource_host = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
    if parsed.scheme.lower() != "https" or resource_host not in NHI_RESOURCE_HOSTS:
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    return {
        "dataset_id": NHI_DATASET_ID,
        "identifier": expected_identifier,
        "publisher_oid": expected_publisher_oid,
        "landing_url": NHI_LANDING_URL,
        "metadata_url": NHI_METADATA_URL,
        "license_code": expected_license_code,
        "license_name": NHI_LICENSE,
        "license_url": NHI_LICENSE_URL,
        "resource_format": "CSV",
        "resource_character_encoding": "UTF-8",
        "resource_url": resource_url,
        "official_modified_at_raw": result.get("modifiedDate")
        if isinstance(result.get("modifiedDate"), str)
        else None,
        "official_modified_at_precision": "second"
        if isinstance(result.get("modifiedDate"), str) and result.get("modifiedDate")
        else None,
        "official_modified_timezone_known": False,
    }


def fetch_nhi_source(
    *,
    expected_publisher_oid: str,
    metadata_url: str = NHI_METADATA_URL,
    max_metadata_bytes: int = 2 * 1024 * 1024,
    max_csv_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 30.0,
    max_redirects: int = 3,
    opener=None,
    clock=None,
) -> dict[str, Any]:
    try:
        metadata = fetch_https_bytes(
            metadata_url,
            allowed_hosts=NHI_METADATA_HOSTS,
            max_bytes=max_metadata_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/json"},
            opener=opener,
            clock=clock,
        )
    except FetchError as exc:
        raise FetchError(exc.code, stage="discover") from exc
    try:
        discovery = discover_nhi_resource(
            metadata.payload,
            expected_publisher_oid=expected_publisher_oid,
        )
    except FetchError as exc:
        raise FetchError(exc.code, stage="discover", metadata=metadata) from exc
    try:
        artifact = fetch_https_bytes(
            discovery["resource_url"],
            allowed_hosts=NHI_RESOURCE_HOSTS,
            max_bytes=max_csv_bytes,
            timeout_seconds=timeout_seconds,
            max_redirects=max_redirects,
            allowed_content_types={"application/csv", "text/csv", "application/octet-stream"},
            opener=opener,
            clock=clock,
        )
    except FetchError as exc:
        raise FetchError(exc.code, stage="fetch", discovery=discovery, metadata=metadata) from exc
    return {"discovery": discovery, "metadata": metadata, "artifact": artifact}
