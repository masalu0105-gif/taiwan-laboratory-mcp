"""CDC specimen manual serving snapshot: validated read-only access and disease search."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .cdc_labs_store import cdc_labs_attribution_text
from .importers.cdc_manual_layout import CDC_MANUAL_TABLE_NAMES
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
from .util import norm

CDC_MANUAL_INTERNAL_SOURCE_ID = "cdc_specimen_manual"
# The manual page declares no update schedule; the project checks it daily, so two missed daily
# checks mark the snapshot overdue (same as the roster).
CDC_MANUAL_CHECK_OVERDUE_AFTER = timedelta(days=2)
# The exact disease name first, then names starting with the query, then names containing it.
_SEARCH_SQL = """SELECT * FROM (
    SELECT *, CASE
        WHEN disease_search = :query THEN 0
        WHEN instr(disease_search, :query) = 1 THEN 1
        WHEN instr(disease_search, :query) > 0 THEN 2
    END AS tier
    FROM cdc_specimen_requirement
) WHERE tier IS NOT NULL ORDER BY tier, row_number"""


@dataclass(frozen=True)
class CdcManualState:
    availability: str
    reason: str | None
    status: SourceStatus
    provenance: Provenance | None
    db_path: Path | None = None
    latest_candidate_id: str | None = None


def _validate_rows(db_path: Path, manifest: dict[str, Any]) -> None:
    counts = manifest.get("counts")
    # `counts` is the primary table (chapter 2); `table_counts` covers every stored table.
    table_counts = manifest.get("table_counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != {"input_rows", "curated_rows", "quarantined_rows"}
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["input_rows"] != counts["curated_rows"]
        or counts["quarantined_rows"] != 0
        or not isinstance(table_counts, dict)
        or set(table_counts) != set(CDC_MANUAL_TABLE_NAMES)
        or any(type(value) is not int or value <= 0 for value in table_counts.values())
        or table_counts[CDC_MANUAL_TABLE_NAMES[0]] != counts["curated_rows"]
    ):
        raise ValueError("curated row coverage mismatch")
    connection = connect_readonly(db_path)
    try:
        for name in CDC_MANUAL_TABLE_NAMES:
            total, numbers, lowest, highest = connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT row_number), MIN(row_number), MAX(row_number) "
                f"FROM {name}"
            ).fetchone()
            if not (
                total == table_counts[name] == numbers == highest and total > 0 and lowest == 1
            ):
                raise ValueError("curated row coverage mismatch")
    finally:
        connection.close()


def _provenance(descriptor: dict[str, Any], manifest: dict[str, Any], now: datetime) -> Provenance:
    source = manifest["source"]
    artifact = manifest["artifacts"][0]
    official = manifest.get("official_version", {})
    retrieved_at = datetime.fromisoformat(manifest["fetched_at"].replace("Z", "+00:00"))
    stale_reason_codes = _effective_stale_reason_codes(
        descriptor, now, CDC_MANUAL_CHECK_OVERDUE_AFTER
    )
    return Provenance(
        source_id="cdc_manual",
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
        # Every chapter 2 row of the manual is served.
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


def read_cdc_manual_state(
    data_root: Path, *, clock: Callable[[], datetime] | None = None
) -> CdcManualState:
    now = _now(clock)
    try:
        serving = _read_serving(Path(data_root), CDC_MANUAL_INTERNAL_SOURCE_ID, "manual.pdf")
        if isinstance(serving, OfficialState):
            return CdcManualState(
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
        return CdcManualState(
            "data_unavailable", "operational_status_integrity_failure", _empty_status(), None
        )
    except (KeyError, TypeError, ValueError, OSError, sqlite3.DatabaseError):
        return CdcManualState(
            "data_unavailable", "serving_integrity_failure", _empty_status(), None
        )
    return CdcManualState(
        availability="available",
        reason=None,
        status=_status_from_descriptor(descriptor, True, provenance.stale_reason_codes),
        provenance=provenance,
        db_path=db_path,
    )


def search_specimen_rows(connection: sqlite3.Connection, *, query: str) -> list[dict[str, Any]]:
    """Chapter 2 rows whose disease name matches, ignoring spaces, line breaks and brackets.

    A common name the manual does not use (「COVID-19」, 「HIV」, 「猴痘」) is replaced by the
    manual's own wording through the packaged alias table (OD-16).
    """

    from .importers.cdc_manual import load_cdc_disease_aliases

    term = norm(query)
    term = load_cdc_disease_aliases().get(term, term)
    return [dict(row) for row in connection.execute(_SEARCH_SQL, {"query": term})]
