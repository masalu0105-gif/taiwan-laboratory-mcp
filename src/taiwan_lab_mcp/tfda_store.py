"""TFDA serving snapshot: validated read-only access and deterministic permit-row search."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .canonical import sha256_bytes
from .models import ArtifactReference, OfficialContentDate, Provenance, SourceStatus
from .rules.tfda import TemporalEvaluation, evaluate_temporal
from .stores import (
    OfficialState,
    _contained,
    _effective_stale_reason_codes,
    _empty_status,
    _now,
    _OperationalIntegrityError,
    _read_serving,
    _status_from_descriptor,
    open_data_attribution_text,
)
from .util import tfda_search_normalize

TFDA_INTERNAL_SOURCE_ID = "tfda_devices"
# data.gov.tw declares dataset 9576 as updated every 7 days. The NHI two-cycle overdue rule
# (SDD 8.3) applies until the owner sets a TFDA-specific threshold (OD-05).
TFDA_CHECK_OVERDUE_AFTER = 2 * timedelta(days=7)
TAIPEI = timezone(timedelta(hours=8))
SEARCH_FIELDS = (
    ("license_no", "license_no_search"),
    ("name_zh", "name_zh_search"),
    ("name_en", "name_en_search"),
    ("applicant", "applicant_name_search"),
    ("manufacturer", "manufacturer_name_search"),
    ("effect", "effect_search"),
    ("classification", "classification_search"),
)
_COVERAGE_COUNT_KEYS = (
    "reviewed_codes",
    "total_codes",
    "legacy_code_rows",
    "missing_code_rows",
    "unknown_code_rows",
)


@dataclass(frozen=True)
class TFDAState:
    availability: str
    reason: str | None
    status: SourceStatus
    provenance: Provenance | None
    db_path: Path | None = None
    coverage_detail: dict[str, Any] | None = None
    latest_candidate_id: str | None = None


_CACHE_LOCK = threading.Lock()
_VALIDATED: dict[tuple[Any, ...], tuple[dict[str, Any], dict[str, Any], Path]] = {}


def _serving_signature(data_root: Path) -> tuple[Any, ...] | None:
    """Size and mtime of every file that full validation hashes.

    Hashing the ~100 MB database, the raw ZIP and each review's evidence on every tool call
    is slow, so a validated build is reused until the pointer bytes or any of these files
    change size or modification time.
    """

    try:
        descriptor_path = data_root / "manifests" / "current" / f"{TFDA_INTERNAL_SOURCE_ID}.json"
        descriptor_bytes = descriptor_path.read_bytes()
        descriptor = json.loads(descriptor_bytes.decode("utf-8"))
        build_id = descriptor["serving_curated_build_id"]
        if not isinstance(build_id, str):
            return None
        build_dir = _contained(data_root, f"curated/{TFDA_INTERNAL_SOURCE_ID}/{build_id}")
        manifest = json.loads((build_dir / "manifest.json").read_bytes().decode("utf-8"))
        raw_dir = _contained(
            data_root, f"raw/{TFDA_INTERNAL_SOURCE_ID}/{manifest['raw_revision_id']}"
        )
        paths = [path for path in (*build_dir.rglob("*"), *raw_dir.rglob("*")) if path.is_file()]
        paths.append(_contained(data_root, descriptor["latest_check_data_root_relative_path"]))
        stats = tuple(
            (str(path), path.stat().st_size, path.stat().st_mtime_ns) for path in sorted(paths)
        )
    except (KeyError, TypeError, ValueError, OSError):
        return None
    return str(data_root.resolve()), sha256_bytes(descriptor_bytes), stats


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(db_path.as_posix(), safe='/:')}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        connection.execute("PRAGMA trusted_schema=OFF")
    except sqlite3.DatabaseError:
        pass
    return connection


def _validate_rows(db_path: Path, manifest: dict[str, Any]) -> None:
    counts = manifest.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != {"input_rows", "curated_rows", "quarantined_rows"}
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["input_rows"] != counts["curated_rows"]
        or counts["quarantined_rows"] != 0
    ):
        raise ValueError("curated row coverage mismatch")
    connection = connect_readonly(db_path)
    try:
        total, hashes, numbers, low, high = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT source_row_sha256), "
            "COUNT(DISTINCT source_row_number), MIN(source_row_number), "
            "MAX(source_row_number) FROM tfda_source_row"
        ).fetchone()
    finally:
        connection.close()
    if not (
        total == counts["curated_rows"] == hashes == numbers and low == 2 and high == total + 1
    ):
        raise ValueError("curated row coverage mismatch")


def _coverage_detail(manifest: dict[str, Any]) -> dict[str, Any]:
    detail = manifest.get("ivd_coverage")
    if (
        not isinstance(detail, dict)
        or set(detail) != {*_COVERAGE_COUNT_KEYS, "rule_version"}
        or any(type(detail[key]) is not int or detail[key] < 0 for key in _COVERAGE_COUNT_KEYS)
        or not isinstance(detail["rule_version"], str)
        or not detail["rule_version"]
        or detail["reviewed_codes"] > detail["total_codes"]
    ):
        raise ValueError("IVD coverage detail invalid")
    return dict(detail)


def _coverage_status(manifest: dict[str, Any], detail: dict[str, Any]) -> str:
    approved = any(
        isinstance(item, dict)
        and item.get("gate_id") == "TFDA-R1-IVD"
        and item.get("status") == "approved"
        for item in manifest.get("review", {}).get("capability_reviews", [])
    )
    unresolved_rows = (
        detail["legacy_code_rows"] + detail["missing_code_rows"] + detail["unknown_code_rows"]
    )
    if approved and detail["reviewed_codes"] == detail["total_codes"] and unresolved_rows == 0:
        return "complete"
    return "review_incomplete"


def _ivd_rule_version(manifest: dict[str, Any]) -> str:
    for rule in manifest["transform"]["rules"]:
        version = rule.get("version") if isinstance(rule, dict) else None
        if rule.get("name") == "tfda_ivd" and isinstance(version, str) and version:
            return version
    raise ValueError("IVD rule identity missing")


def _provenance(
    descriptor: dict[str, Any], manifest: dict[str, Any], now: datetime
) -> tuple[Provenance, dict[str, Any]]:
    source = manifest["source"]
    artifact = manifest["artifacts"][0]
    official = manifest.get("official_version", {})
    official_content_date = None
    if official.get("modified_at_raw"):
        precision = official.get("modified_at_precision")
        official_content_date = OfficialContentDate(
            value_raw=official["modified_at_raw"],
            precision=precision if precision in {"day", "month", "year"} else "unknown",
            timezone_known=bool(official.get("timezone_known", False)),
        )
    retrieved_at = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
    stale_reason_codes = _effective_stale_reason_codes(descriptor, now, TFDA_CHECK_OVERDUE_AFTER)
    detail = _coverage_detail(manifest)
    provenance = Provenance(
        source_id="tfda_device",
        source_name=source["dataset_name"],
        provider=source["provider"],
        landing_url=source["landing_url"],
        resource_url=source["resource_url"],
        snapshot_id=descriptor["serving_snapshot_id"],
        curated_build_id=descriptor["serving_curated_build_id"],
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
        rule_bundle_version=_ivd_rule_version(manifest),
        license_name=source["license_name"],
        license_url=source["license_url"],
        attribution=open_data_attribution_text(
            provider=source["provider"],
            dataset_name=source["dataset_name"],
            official_modified_at_raw=official.get("modified_at_raw"),
            retrieved_at=retrieved_at,
        ),
        coverage_status=_coverage_status(manifest, detail),
        stale=bool(stale_reason_codes),
        stale_reason_codes=stale_reason_codes,
        last_check_at=(
            datetime.fromisoformat(descriptor["last_check_at"].replace("Z", "+00:00"))
            if descriptor.get("last_check_at")
            else None
        ),
        serving_review_status="approved",
    )
    return provenance, detail


def read_tfda_state(data_root: Path, *, clock: Callable[[], datetime] | None = None) -> TFDAState:
    now = _now(clock)
    data_root = Path(data_root)
    try:
        signature = _serving_signature(data_root)
        with _CACHE_LOCK:
            cached = _VALIDATED.get(signature) if signature is not None else None
        if cached is None:
            serving = _read_serving(data_root, TFDA_INTERNAL_SOURCE_ID, "source.zip")
            if isinstance(serving, OfficialState):
                return TFDAState(
                    availability=serving.availability,
                    reason=serving.reason,
                    status=serving.status,
                    provenance=None,
                    latest_candidate_id=serving.latest_candidate_id,
                )
            _validate_rows(serving[2], serving[1])
            cached = serving
            if signature is not None:
                with _CACHE_LOCK:
                    _VALIDATED.clear()
                    _VALIDATED[signature] = cached
        descriptor, manifest, db_path = cached
        provenance, detail = _provenance(descriptor, manifest, now)
    except _OperationalIntegrityError:
        return TFDAState(
            "data_unavailable", "operational_status_integrity_failure", _empty_status(), None
        )
    except (KeyError, TypeError, ValueError, OSError, sqlite3.DatabaseError):
        return TFDAState("data_unavailable", "serving_integrity_failure", _empty_status(), None)
    return TFDAState(
        availability="available",
        reason=None,
        status=_status_from_descriptor(descriptor, True, provenance.stale_reason_codes),
        provenance=provenance,
        db_path=db_path,
        coverage_detail=detail,
    )


def _parsed_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def evaluate_row(row: dict[str, Any], as_of: date) -> TemporalEvaluation:
    return evaluate_temporal(
        row["cancellation_status_raw"],
        _parsed_date(row["cancellation_date"]),
        _parsed_date(row["valid_through"]),
        as_of,
    )


@dataclass(frozen=True)
class SearchRequest:
    query: str
    fields: tuple[str, ...]
    ivd_scopes: tuple[str, ...] | None = None
    main_category: str | None = None
    manufacturer: str | None = None
    prefer_ivd: bool = False
    prefer_main_category: str | None = None
    rank_by_manufacturer: bool = False
    limit: int = 20
    offset: int = 0


# TFDA-06 match tiers: exact permit number, exact name, name prefix, name contains, other field.
_NAME_TIER_SQL = (
    "CASE WHEN license_no_search = :q THEN 0 "
    "WHEN name_zh_search = :q OR name_en_search = :q THEN 1 "
    "WHEN substr(name_zh_search, 1, :q_length) = :q "
    "OR substr(name_en_search, 1, :q_length) = :q THEN 2 "
    "WHEN instr(name_zh_search, :q) > 0 OR instr(name_en_search, :q) > 0 THEN 3 ELSE 4 END"
)
_MANUFACTURER_TIER_SQL = (
    "CASE WHEN manufacturer_name_search = :q THEN 0 "
    "WHEN substr(manufacturer_name_search, 1, :q_length) = :q THEN 1 ELSE 2 END"
)


def search_rows(
    connection: sqlite3.Connection, request: SearchRequest
) -> tuple[int, list[dict[str, Any]]]:
    """Return (total_matches, one page) in the fixed order; no score ever leaves SQLite.

    Substring matching uses instr() so two-character queries match, which an FTS5 trigram
    index would not do.
    """

    columns = dict(SEARCH_FIELDS)
    query = tfda_search_normalize(request.query)
    params: dict[str, Any] = {
        "q": query,
        "q_length": len(query),
        "limit": request.limit,
        "offset": request.offset,
    }
    conditions = [
        "(" + " OR ".join(f"instr({columns[name]}, :q) > 0" for name in request.fields) + ")"
    ]
    if request.ivd_scopes is not None:
        placeholders = []
        for index, scope in enumerate(request.ivd_scopes):
            params[f"scope_{index}"] = scope
            placeholders.append(f":scope_{index}")
        conditions.append(f"ivd_scope IN ({', '.join(placeholders)})")
    if request.main_category is not None:
        params["main_category"] = request.main_category
        conditions.append("instr(main_category_letters, :main_category) > 0")
    if request.manufacturer is not None:
        params["manufacturer"] = tfda_search_normalize(request.manufacturer)
        conditions.append("instr(manufacturer_name_search, :manufacturer) > 0")
    # A preference only reorders rows inside one match tier; it never adds or removes rows.
    misses = []
    if request.prefer_ivd:
        misses.append("(ivd_scope != 'included')")
    if request.prefer_main_category is not None:
        params["prefer_main_category"] = request.prefer_main_category
        misses.append("(instr(main_category_letters, :prefer_main_category) = 0)")
    order = ["match_tier"]
    if misses:
        order.append(" + ".join(misses))
    order.extend(["cancellation_raw_nonempty", "license_no_raw", "source_row_number"])
    tier = _MANUFACTURER_TIER_SQL if request.rank_by_manufacturer else _NAME_TIER_SQL
    where = " AND ".join(conditions)
    rows = [
        dict(row)
        for row in connection.execute(
            f"SELECT *, {tier} AS match_tier, COUNT(*) OVER () AS total_matches "
            f"FROM tfda_source_row WHERE {where} ORDER BY {', '.join(order)} "
            "LIMIT :limit OFFSET :offset",
            params,
        ).fetchall()
    ]
    if rows:
        return rows[0]["total_matches"], rows
    total = connection.execute(f"SELECT COUNT(*) FROM tfda_source_row WHERE {where}", params)
    return total.fetchone()[0], rows


def license_rows(
    connection: sqlite3.Connection, license_no: str, limit: int = 20
) -> tuple[int, list[dict[str, Any]]]:
    rows = [
        dict(row)
        for row in connection.execute(
            "SELECT *, COUNT(*) OVER () AS total_matches FROM tfda_source_row "
            "WHERE license_no_search = ? ORDER BY source_row_number LIMIT ?",
            (tfda_search_normalize(license_no), limit),
        ).fetchall()
    ]
    return (rows[0]["total_matches"] if rows else 0), rows


def matched_fields(row: dict[str, Any], query: str, fields: tuple[str, ...]) -> list[str]:
    normalized = tfda_search_normalize(query)
    return [name for name, column in SEARCH_FIELDS if name in fields and normalized in row[column]]
