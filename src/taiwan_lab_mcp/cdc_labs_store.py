"""CDC recognized laboratory roster serving snapshot: validated read-only access and search."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import ArtifactReference, Provenance, SourceStatus
from .stores import (
    OfficialState,
    _effective_stale_reason_codes,
    _empty_status,
    _now,
    _OperationalIntegrityError,
    _read_serving,
    _status_from_descriptor,
)
from .tfda_store import connect_readonly
from .util import tfda_search_normalize

CDC_LABS_INTERNAL_SOURCE_ID = "cdc_authorized_labs"
# CDC declares no update frequency for the roster (research 2026-09-13: UNVERIFIED) and the
# project checks the page daily, so two missed daily checks mark the snapshot overdue.
CDC_LABS_CHECK_OVERDUE_AFTER = timedelta(days=2)
_TAIPEI = timezone(timedelta(hours=8))
_SEARCH_SQL = """
SELECT *, COUNT(*) OVER () AS total_matches
FROM (
    SELECT *,
        CASE
            WHEN certificate_search = :q OR disease_code_search = :q THEN 0
            WHEN institution_search = :q OR disease_name_search = :q THEN 1
            WHEN instr(certificate_search, :q) > 0
                OR instr(disease_code_search, :q) > 0
                OR instr(institution_search, :q) > 0
                OR instr(department_search, :q) > 0
                OR instr(disease_name_search, :q) > 0
                OR instr(purpose_search, :q) > 0
                OR instr(method_search, :q) > 0 THEN 2
        END AS match_tier
    FROM cdc_lab_row
    WHERE :city IS NULL OR instr(city_search, :city) > 0
)
WHERE match_tier IS NOT NULL
ORDER BY match_tier, certificate_no, expanded_row_number
LIMIT :limit OFFSET :offset
"""


@dataclass(frozen=True)
class CdcLabsState:
    availability: str
    reason: str | None
    status: SourceStatus
    provenance: Provenance | None
    db_path: Path | None = None
    latest_candidate_id: str | None = None


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
        total, numbers, lowest = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT expanded_row_number), MIN(expanded_row_number) "
            "FROM cdc_lab_row"
        ).fetchone()
    finally:
        connection.close()
    if not (total == counts["curated_rows"] == numbers and total > 0 and lowest >= 1):
        raise ValueError("curated row coverage mismatch")


def cdc_labs_attribution_text(
    source: dict[str, Any], official: dict[str, Any], retrieved_at: datetime
) -> str:
    """Attribution per the CDC open data declaration: provider, title, version, retrieval date."""

    label = official.get("label")
    version = f"{label} 版" if label else ""
    day = retrieved_at.astimezone(_TAIPEI).date().isoformat()
    return (
        f"{source['provider']}「{source['dataset_name']}」{version}（本專案擷取於 {day}）。"
        f"依{source['license_name']}利用：{source['license_url']}。"
        "本服務非疾管署官方服務，未獲疾管署推薦或認可。"
    )


def _provenance(descriptor: dict[str, Any], manifest: dict[str, Any], now: datetime) -> Provenance:
    source = manifest["source"]
    artifact = manifest["artifacts"][0]
    official = manifest.get("official_version", {})
    retrieved_at = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
    stale_reason_codes = _effective_stale_reason_codes(
        descriptor, now, CDC_LABS_CHECK_OVERDUE_AFTER
    )
    return Provenance(
        source_id="cdc_recognized_labs",
        source_name=source["dataset_name"],
        provider=source["provider"],
        landing_url=source["landing_url"],
        resource_url=source["resource_url"],
        snapshot_id=descriptor["serving_snapshot_id"],
        curated_build_id=descriptor["serving_curated_build_id"],
        official_version_raw=official.get("label"),
        official_content_date=None,
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
        rule_bundle_version="none",
        license_name=source["license_name"],
        license_url=source["license_url"],
        attribution=cdc_labs_attribution_text(source, official, retrieved_at),
        # Every row of the roster is served; no classification review is involved.
        coverage_status="complete",
        stale=bool(stale_reason_codes),
        stale_reason_codes=stale_reason_codes,
        last_check_at=(
            datetime.fromisoformat(descriptor["last_check_at"].replace("Z", "+00:00"))
            if descriptor.get("last_check_at")
            else None
        ),
        serving_review_status="approved",
    )


def read_cdc_labs_state(
    data_root: Path, *, clock: Callable[[], datetime] | None = None
) -> CdcLabsState:
    now = _now(clock)
    try:
        serving = _read_serving(Path(data_root), CDC_LABS_INTERNAL_SOURCE_ID, "source.ods")
        if isinstance(serving, OfficialState):
            return CdcLabsState(
                availability=serving.availability,
                reason=serving.reason,
                status=serving.status,
                provenance=None,
                latest_candidate_id=serving.latest_candidate_id,
            )
        descriptor, manifest, db_path = serving
        _validate_rows(db_path, manifest)
        provenance = _provenance(descriptor, manifest, now)
    except _OperationalIntegrityError:
        return CdcLabsState(
            "data_unavailable", "operational_status_integrity_failure", _empty_status(), None
        )
    except (KeyError, TypeError, ValueError, OSError, sqlite3.DatabaseError):
        return CdcLabsState("data_unavailable", "serving_integrity_failure", _empty_status(), None)
    return CdcLabsState(
        availability="available",
        reason=None,
        status=_status_from_descriptor(descriptor, True, provenance.stale_reason_codes),
        provenance=provenance,
        db_path=db_path,
    )


def search_labs(
    connection: sqlite3.Connection, *, query: str, city: str | None, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    """Exact certificate or disease code first, then exact names, then any field containing it."""

    rows = connection.execute(
        _SEARCH_SQL,
        {
            "q": tfda_search_normalize(query),
            "city": tfda_search_normalize(city) if city is not None else None,
            "limit": limit,
            "offset": offset,
        },
    ).fetchall()
    records = [dict(row) for row in rows]
    return (records[0]["total_matches"] if records else 0), records
