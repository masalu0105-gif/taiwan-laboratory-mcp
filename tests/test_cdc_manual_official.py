"""CDC specimen manual: curated build, serving state and the six manual tools on official data.

Owner 2026-09-15 delegated every CDC review to AI (OD-04) and chose B for line breaks in cells
(OD-15): the tools answer with the display text; the database also keeps the raw cell text and
the row hash for source checks. Fixtures are synthetic page layouts; no official PDF is read.
"""

import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.config import DataContext


def _pages():
    # The synthetic page builder lives with the layout tests; load it by path so the tests also
    # run from an installed wheel outside the repository.
    path = Path(__file__).with_name("test_cdc_manual_layout.py")
    spec = importlib.util.spec_from_file_location("cdc_manual_layout_pages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _layout():
    pages = _pages()
    # Page 14: one row whose cells wrap; pages 16-17: typhoid rows and a dengue row.
    return pages._layout(pages._display_page(), *pages._typhoid_pages())


def _offline(data_root, layout=None):
    from taiwan_lab_mcp.importers.cdc_manual import build_cdc_manual_snapshot

    return build_cdc_manual_snapshot(layout or _layout(), data_root)


def _adapter(data_root, clock=None):
    return CDCAdapter(DataContext(mode="official_snapshot", data_root=data_root, clock=clock))


def test_search_disease_returns_display_text_with_pdf_row_locators(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_specimen_layout

    layout = _layout()
    parsed = parse_cdc_specimen_layout(layout)
    built = _offline(tmp_path, layout)
    assert built["rows"] == 4

    result = _adapter(tmp_path).search_disease("傷寒")

    assert (result.result_status, result.data_mode, result.sample_only) == (
        "ok",
        "official_snapshot",
        False,
    )
    # The exact disease name comes first, then names that contain it, each in page order.
    assert [item.evidence[0].locator.pdf_page for item in result.items] == [16, 17, 14]
    wrapped = result.items[2]
    assert wrapped.record.model_dump() == {
        "record_type": "cdc_specimen",
        "disease": "傷寒\n副傷寒",
        "specimen": "肛門拭子",
        "purpose": "病原體檢測；血清型別鑑定",
        "collection_time": "發病後(30日)內",
        "volume_requirement": "以無菌試管收集以無菌試管收集 3 mL 血清",
        "transport_method": "送驗前請參考說明第3.4節。",
        "retention_raw": "菌株(30日)",
        "notes": "尿液檢體(參考第3.4節)採自下列患者：\n1.確定合併感染埃及血吸蟲患者。\n2.無症狀帶菌者",
    }
    evidence = wrapped.evidence[0]
    assert evidence.artifact_id == "cdc-manual-pdf"
    assert evidence.locator.model_dump() == {
        "locator_type": "cdc_pdf_row",
        "pdf_page": 14,
        "printed_page": 4,
        "table_section": "2.2 第二類法定傳染病檢體",
        "row_bbox": [23, 150, 559, 250],
    }
    # The row hash is computed from the raw cell text, not the display text.
    assert evidence.source_row_sha256 == parsed.rows[0].source_row_sha256
    assert wrapped.safety["not_pre_submission_storage"] is True
    provenance = result.provenance
    assert (provenance.source_id, provenance.official_version_raw, provenance.coverage_status) == (
        "cdc_manual",
        "1150826",
        "complete",
    )
    assert provenance.attribution.startswith("衛生福利部疾病管制署「傳染病檢體採檢手冊」1150826 版")
    assert "非疾管署官方服務，內容以疾管署公告為準。" in result.notes

    requirement = _adapter(tmp_path).get_specimen_requirement("登革熱")
    assert (requirement.operation, requirement.query, requirement.total_matches) == (
        "get_specimen_requirement",
        {"disease": "登革熱"},
        1,
    )
    assert requirement.items[0].record.specimen == "血清"


def test_search_disease_ignores_spaces_and_line_breaks(tmp_path):
    # 「傷寒↵副傷寒」 is stored with its line break; a query with a space still finds it.
    _offline(tmp_path)
    adapter = _adapter(tmp_path)

    assert adapter.search_disease("副 傷寒").total_matches == 1
    assert adapter.search_disease("狂犬病").result_status == "not_found"


def test_database_keeps_raw_text_display_text_edition_and_row_hash(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_specimen_layout

    layout = _layout()
    parsed = parse_cdc_specimen_layout(layout)
    built = _offline(tmp_path, layout)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT * FROM cdc_specimen_requirement ORDER BY row_number"
    ).fetchall()
    connection.close()

    assert [row["row_number"] for row in rows] == [1, 2, 3, 4]
    first = rows[0]
    assert (first["purpose"], first["purpose_display"]) == (
        "病原體檢測；血清\n型別鑑定",
        "病原體檢測；血清型別鑑定",
    )
    assert (first["manual_version"], first["approved_date_raw"]) == ("1150826", "115年08月26日")
    assert first["source_row_sha256"] == parsed.rows[0].source_row_sha256
    assert json.loads(first["row_bbox"]) == [23, 150, 559, 250]
    assert [row["specimen"] for row in rows] == ["肛門拭子", "肛門拭子", "尿液", "血清"]


def test_build_fingerprint_binds_the_page_layout_in_thousandths_of_a_point(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual import cdc_layout_sha256

    layout = _layout()
    built = _offline(tmp_path, layout)
    manifest = json.loads(
        (
            tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "manifest.json"
        ).read_bytes()
    )
    qualifier = manifest["build_fingerprint"]["qualifier"]
    assert (qualifier["name"], qualifier["version"]) == ("pdfium-layout-v1", "5.13.0")
    assert qualifier["extractor_output_sha256"] == cdc_layout_sha256(layout)
    assert manifest["manual_edition"] == {
        "manual_version": "1150826",
        "approved_date_raw": "115年08月26日",
    }

    char = layout["pages"][0]["chars"][0]
    moved = json.loads(json.dumps(layout))
    moved["pages"][0]["chars"][0]["x0"] = char["x0"] + 0.0004
    assert cdc_layout_sha256(moved) == cdc_layout_sha256(layout)
    moved["pages"][0]["chars"][0]["x0"] = char["x0"] + 0.001
    assert cdc_layout_sha256(moved) != cdc_layout_sha256(layout)


def test_official_mode_without_a_manual_build_is_unavailable_without_sample_fallback(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    result = _adapter(tmp_path).search_disease("傷寒")
    assert (result.result_status, result.availability_reason_code, result.items) == (
        "data_unavailable",
        "no_serving_snapshot",
        [],
    )
    status = read_source_status(tmp_path, "cdc_manual")
    assert (status.availability, status.availability_reason_code) == (
        "data_unavailable",
        "no_serving_snapshot",
    )


def test_data_status_reports_the_served_manual_and_turns_overdue_after_two_days(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    built = _offline(tmp_path)
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "cdc_specimen_manual.json").read_bytes()
    )
    checked = datetime.fromisoformat(descriptor["last_successful_check_at"].replace("Z", "+00:00"))

    status = read_source_status(tmp_path, "cdc_manual", clock=lambda: checked)
    assert (status.availability, status.serving_curated_build_id, status.coverage_status) == (
        "available",
        built["snapshot_id"],
        "complete",
    )
    assert (status.latest_seen_version, status.freshness_policy_version) == (
        "1150826",
        "cdc-manual-v1",
    )
    later = checked + timedelta(days=2, seconds=1)
    overdue = read_source_status(tmp_path, "cdc_manual", clock=lambda: later)
    assert (overdue.stale, overdue.stale_reason_codes) == (True, ["upstream_check_overdue"])


def test_tampered_manual_database_is_not_served(tmp_path):
    from taiwan_lab_mcp.stores import read_source_status

    built = _offline(tmp_path)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"
    payload = bytearray(db_path.read_bytes())
    payload[-1] ^= 0xFF
    db_path.write_bytes(bytes(payload))

    assert read_source_status(tmp_path, "cdc_manual").availability_reason_code == (
        "serving_integrity_failure"
    )
    assert _adapter(tmp_path).search_disease("傷寒").result_status == "data_unavailable"
