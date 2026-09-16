"""CDC specimen manual: curated build, serving state and the six manual tools on official data.

Owner 2026-09-15 delegated every CDC review to AI (OD-04) and chose B for line breaks in cells
(OD-15): the tools answer with the display text; the database also keeps the raw cell text and
the row hash for source checks. Fixtures are synthetic page layouts; no official PDF is read.
"""

import hashlib
import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.config import DataContext
from taiwan_lab_mcp.util import norm

REVIEWER = "ai-reviewer:claude-opus-5"
ROLE = "ai_reviewer_delegated_by_owner"
REVIEWED_AT = "2026-09-16T09:00:00+08:00"
MANUAL_PDF = b"%PDF-1.7\n% synthetic manual for the official build test\n%%EOF\n"
REVISION_PDF = b"%PDF-1.7\n% synthetic revision table for the official build test\n%%EOF\n"


def _pages():
    # The synthetic page builder lives with the layout tests; load it by path so the tests also
    # run from an installed wheel outside the repository.
    path = Path(__file__).with_name("test_cdc_manual_layout.py")
    spec = importlib.util.spec_from_file_location("cdc_manual_layout_pages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sibling(name, module_name):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _chapter7():
    return _sibling("test_cdc_manual_chapter7.py", "cdc_manual_chapter7_pages")


def _clauses():
    return _sibling("test_cdc_manual_clauses.py", "cdc_manual_clause_pages")


def _layout():
    pages = _pages()
    # Page 14: one row whose cells wrap; pages 16-17: typhoid rows and a dengue row; pages
    # 93-121: the chapter 7 testing locations and receiving units (OD-18).
    return pages._layout(
        pages._display_page(),
        *pages._typhoid_pages(),
        *_clauses().clause_pages(),
        *_chapter7().chapter7_pages(),
    )


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


def test_search_disease_finds_the_manual_wording_through_common_aliases(tmp_path):
    # Owner 2026-09-16 (OD-16): 「COVID-19」「HIV」「猴痘」 are not how the manual writes them.
    _offline(tmp_path)
    adapter = _adapter(tmp_path)

    assert [
        item.evidence[0].locator.pdf_page for item in adapter.search_disease("typhoid").items
    ] == [
        16,
        17,
        14,
    ]
    assert adapter.search_disease("dengue").total_matches == 1
    # An alias whose disease is not in this manual still reports nothing found.
    assert adapter.search_disease("malaria").result_status == "not_found"


def test_the_alias_table_version_is_part_of_the_build_fingerprint(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual import (
        CDC_MANUAL_ALIAS_RULE_VERSION,
        cdc_disease_alias_sha256,
    )

    built = _offline(tmp_path)
    manifest = json.loads(
        (
            tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "manifest.json"
        ).read_bytes()
    )

    assert manifest["build_fingerprint"]["rules"] == [
        {
            "name": "cdc_disease_alias",
            "version": CDC_MANUAL_ALIAS_RULE_VERSION,
            "bundle_sha256": cdc_disease_alias_sha256(),
        }
    ]


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


def test_database_keeps_chapter_7_testing_locations_and_receiving_units(tmp_path):
    # Owner 2026-09-16 (OD-18): chapter 7 is stored beside chapter 2, each in its own table.
    built = _offline(tmp_path)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    locations = connection.execute(
        "SELECT * FROM cdc_testing_location ORDER BY row_number"
    ).fetchall()
    units = connection.execute("SELECT * FROM cdc_receiving_unit ORDER BY row_number").fetchall()
    connection.close()

    assert [(row["disease"], row["method"]) for row in locations] == [
        ("天花", "病原體分離、鑑定"),
        ("天花", "全基因體定序"),
        ("疑似傳染病", "病原體檢測"),
    ]
    first = locations[0]
    assert (first["turnaround_raw"], first["testing_period_raw"], first["bsl_raw"]) == (
        "4-5 工作日",
        None,
        "3",
    )
    assert first["receiving_unit_display"] == "疾病管制署南港臨時辦公室"
    assert (first["pdf_page"], first["table_section"]) == (93, "7.1 第一類法定傳染病")
    assert (first["manual_version"], first["disease_search"]) == ("1150826", "天花")
    # 7.7 prints 檢驗期間 and has no BSL column.
    autopsy = locations[2]
    assert (autopsy["turnaround_raw"], autopsy["testing_period_raw"], autopsy["bsl_raw"]) == (
        None,
        "14 個工作日",
        None,
    )
    assert [(row["unit_name"], row["phone"]) for row in units] == [
        ("疾病管制署南港臨時辦公室", "02-81735678"),
        ("疾病管制署中區實驗室", "04-24737980"),
    ]
    assert units[0]["unit_search"] == norm("疾病管制署南港臨時辦公室")


def test_get_testing_location_answers_with_the_receiving_unit_contacts(tmp_path):
    # Owner 2026-09-16 chose B: one tool, and it already carries the 7.9 contact details so
    # nobody has to ask a second question.
    _offline(tmp_path)

    result = _adapter(tmp_path).get_testing_location("天花")

    assert (result.operation, result.query, result.total_matches) == (
        "get_testing_location",
        {"disease": "天花"},
        2,
    )
    first = result.items[0]
    assert first.record.model_dump() == {
        "record_type": "cdc_testing_location",
        "disease": "天花",
        "collecting_unit": "全國各醫療院所",
        "specimen": "水疱液、膿疱內容物",
        "method": "病原體分離、鑑定",
        "turnaround_raw": "4-5 工作日",
        "testing_period_raw": None,
        "receiving_unit": "疾病管制署南港臨時辦公室",
        "bsl_raw": "3",
        "notes": "1.新增送驗單及條碼。",
        "receiving_unit_contacts": [
            {
                "unit_name": "疾病管制署南港臨時辦公室",
                "phone": "02-81735678",
                "fax": "02-27850288",
                "address": "11529 台北市南港區研究院路二段 128 號",
            }
        ],
    }
    # The row and each contact carry their own page, section and row hash.
    assert [(e.locator.pdf_page, e.locator.table_section) for e in first.evidence] == [
        (93, "7.1 第一類法定傳染病"),
        (121, "7.9 收件單位聯絡方式"),
    ]
    assert first.safety["not_pre_submission_storage"] is True
    assert "非疾管署官方服務，內容以疾管署公告為準。" in result.notes
    # 7.7 prints 檢驗期間 instead of 檢驗期限 and has no BSL column.
    autopsy = _adapter(tmp_path).get_testing_location("疑似傳染病").items[0].record
    assert (autopsy.testing_period_raw, autopsy.turnaround_raw, autopsy.bsl_raw) == (
        "14 個工作日",
        None,
        None,
    )
    assert _adapter(tmp_path).get_testing_location("狂犬病").result_status == "not_found"


def test_a_testing_location_without_a_matching_contact_still_answers(tmp_path):
    # The second 天花 row is received by 中區實驗室, which 7.9 lists with its own contact.
    _offline(tmp_path)

    second = _adapter(tmp_path).get_testing_location("天花").items[1].record

    # The fixture's cell breaks the unit name over two lines; matching ignores the break.
    assert second.receiving_unit == "疾病管制署" + chr(10) + "中區實驗室"
    assert [contact.unit_name for contact in second.receiving_unit_contacts] == [
        "疾病管制署中區實驗室"
    ]
    assert second.receiving_unit_contacts[0].phone == "04-24737980"


def test_database_keeps_chapters_3_to_6_as_numbered_clauses(tmp_path):
    # Owner 2026-09-16: chapters 3-6 are the numbered steps, stored beside the tables.
    built = _offline(tmp_path)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT * FROM cdc_manual_clause ORDER BY row_number").fetchall()
    connection.close()

    assert [(row["clause_number"], row["block_kind"]) for row in rows][:4] == [
        ("3", "clause"),
        ("3.1", "clause"),
        ("3.1.1", "clause"),
        ("3.1.1.1", "clause"),
    ]
    first = rows[2]
    assert first["text"].startswith("3.1.1.適用傳染病項目：傷寒")
    assert (first["chapter"], first["table_section"]) == ("3", "3 傳染病檢體採檢步驟")
    assert (first["pdf_page"], first["printed_page"]) == (69, 59)
    assert first["text_search"] == norm(first["text_display"])


def test_the_clause_coverage_check_compares_every_character(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual import verify_cdc_manual_clause_coverage

    layout = _layout()
    built = _offline(tmp_path, layout)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"

    _, name, payload = verify_cdc_manual_clause_coverage(layout, db_path)
    report = json.loads(payload)

    assert name == "clause-coverage.json"
    assert (report["check"], report["mismatches"]) == ("cdc-manual-clause-coverage-v1", [])
    assert report["pages_compared"] == [69, 70]
    assert report["characters_compared"] > 100


def test_a_manual_without_chapter_7_is_not_built(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual_layout import CdcManualLayoutError

    pages = _pages()
    chapter2_only = pages._layout(pages._display_page(), *pages._typhoid_pages())

    with pytest.raises(CdcManualLayoutError) as error:
        _offline(tmp_path, chapter2_only)
    assert error.value.code == "LAYOUT_NO_TABLE"


def test_the_word_tag_check_covers_every_stored_table(tmp_path):
    from taiwan_lab_mcp.importers.cdc_manual import verify_cdc_manual_rows_against_tags

    layout = _layout()
    built = _offline(tmp_path, layout)
    db_path = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"] / "data.sqlite3"

    _, name, payload = verify_cdc_manual_rows_against_tags(layout, db_path)
    report = json.loads(payload)

    assert name == "word-tag-check.json"
    assert report["mismatches"] == []
    assert report["tables"] == {
        "cdc_specimen_requirement": {"rows_compared": 4, "cells_compared": 32},
        "cdc_testing_location": {"rows_compared": 3, "cells_compared": 27},
        "cdc_receiving_unit": {"rows_compared": 2, "cells_compared": 8},
    }


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


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


def _revision_layout():
    path = Path(__file__).with_name("test_cdc_manual_revision.py")
    spec = importlib.util.spec_from_file_location("cdc_manual_revision_pages", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._layout(module._first_page())


@pytest.fixture
def pdf_reader(monkeypatch):
    # Word table tags cannot be produced in a test PDF, so the reader returns a synthetic layout.
    import taiwan_lab_mcp.importers.cdc_manual as manual

    layouts = {MANUAL_PDF: _layout(), REVISION_PDF: _revision_layout()}
    monkeypatch.setattr(manual, "extract_cdc_manual_layout", lambda payload: layouts[payload])
    return layouts[MANUAL_PDF]


def _fetched(data_root, *, version="1150826", manual=MANUAL_PDF):
    from taiwan_lab_mcp.cdc_manual_source import (
        CDC_MANUAL_LANDING_URL,
        _write_raw_revision,
        cdc_manual_raw_revision_id,
    )
    from taiwan_lab_mcp.cdc_source import CDC_LICENSE_NAME, CDC_LICENSE_URL, CDC_PROVIDER
    from taiwan_lab_mcp.fetch import FetchedArtifact

    documents = [
        (
            "manual",
            f"衛生福利部疾病管制署傳染病檢體採檢手冊-{version}版.pdf",
            "https://www.cdc.gov.tw/Uploads/manual.pdf",
            manual,
        ),
        (
            "revision_table",
            f"傳染病檢體採檢手冊修訂對照表-{version}.pdf",
            "https://www.cdc.gov.tw/Uploads/revision.pdf",
            REVISION_PDF,
        ),
    ]
    discovery = {
        "provider": CDC_PROVIDER,
        "dataset_name": "傳染病檢體採檢手冊",
        "landing_url": CDC_MANUAL_LANDING_URL,
        "manual_version_raw": version,
        "documents": [
            {"role": role, "attachment_label": label, "pdf_url": url}
            for role, label, url, _ in documents
        ],
        "license_name": CDC_LICENSE_NAME,
        "license_url": CDC_LICENSE_URL,
    }
    artifacts = {
        role: FetchedArtifact(
            requested_url=url,
            final_url=url,
            status_code=200,
            payload=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
            fetched_at="2026-09-16T01:00:00Z",
            headers={"Content-Type": "application/pdf"},
            redirect_trace=(),
        )
        for role, _, url, payload in documents
    }
    raw_revision_id = cdc_manual_raw_revision_id(discovery=discovery, artifacts=artifacts)
    paths, _ = _write_raw_revision(data_root, raw_revision_id, artifacts, discovery)
    return raw_revision_id, paths["manual"]


def _cases(layout, artifact_relative, count=10):
    from taiwan_lab_mcp.cdc_manual_source import CDC_MANUAL_LANDING_URL
    from taiwan_lab_mcp.importers.cdc_manual import (
        active_cdc_manual_transform,
        cdc_layout_sha256,
    )
    from taiwan_lab_mcp.importers.cdc_manual_layout import parse_cdc_specimen_layout

    rows = parse_cdc_specimen_layout(layout).rows
    transform = active_cdc_manual_transform(cdc_layout_sha256(layout))
    cases = []
    for number in range(count):
        row = rows[number % len(rows)]
        cases.append(
            {
                "golden_case_schema_version": 1,
                "case_id": f"CDC-G-{number + 1:03d}",
                "source_id": "cdc_specimen_manual",
                "acceptance_id": "CDC-01",
                "source_title": "傳染病檢體採檢手冊",
                "official_landing_url": CDC_MANUAL_LANDING_URL,
                "official_version_or_modified_at": "1150826",
                "official_source": True,
                "artifact_id": "cdc-manual-pdf",
                "raw_artifact_sha256": hashlib.sha256(MANUAL_PDF).hexdigest(),
                "evidence_data_root_relative_path": artifact_relative,
                "fixture_file": None,
                "fixture_sha256": None,
                "transform": transform,
                "input": {"disease": row.display_fields()["disease"].split("\n")[-1]},
                "source_locator": row.locator,
                "source_row_sha256": row.source_row_sha256,
                "expected_status": "ok",
                "expected_fields": {
                    "specimen": row.fields()["specimen"],
                    "purpose_display": row.display_fields()["purpose"],
                },
                "expected_warnings": [],
                "reviewer_id": REVIEWER,
                "reviewer_role": ROLE,
                "identity_assurance": "local_asserted",
                "reviewed_at": REVIEWED_AT,
                "review_status": "approved",
            }
        )
    return cases


def _chapter7_case(layout, artifact_relative, *, case_id, parse, input_key, field):
    from taiwan_lab_mcp.cdc_manual_source import CDC_MANUAL_LANDING_URL
    from taiwan_lab_mcp.importers.cdc_manual import (
        active_cdc_manual_transform,
        cdc_layout_sha256,
    )

    row = parse(layout).rows[0]
    return {
        "golden_case_schema_version": 1,
        "case_id": case_id,
        "source_id": "cdc_specimen_manual",
        "acceptance_id": "CDC-01",
        "source_title": "傳染病檢體採檢手冊",
        "official_landing_url": CDC_MANUAL_LANDING_URL,
        "official_version_or_modified_at": "1150826",
        "official_source": True,
        "artifact_id": "cdc-manual-pdf",
        "raw_artifact_sha256": hashlib.sha256(MANUAL_PDF).hexdigest(),
        "evidence_data_root_relative_path": artifact_relative,
        "fixture_file": None,
        "fixture_sha256": None,
        "transform": active_cdc_manual_transform(cdc_layout_sha256(layout)),
        "input": {input_key: row.display_fields()[field].split(chr(10))[-1]},
        "source_locator": row.locator,
        "source_row_sha256": row.source_row_sha256,
        "expected_status": "ok",
        "expected_fields": {
            field: row.fields()[field],
            f"{field}_display": row.display_fields()[field],
        },
        "expected_warnings": [],
        "reviewer_id": REVIEWER,
        "reviewer_role": ROLE,
        "identity_assurance": "local_asserted",
        "reviewed_at": REVIEWED_AT,
        "review_status": "approved",
    }


def test_golden_cases_can_check_chapter_7_rows_and_receiving_units(tmp_path):
    # Owner 2026-09-16 (OD-18): protocol 3 asks for chapter 7 rows among the golden cases.
    from taiwan_lab_mcp.importers.cdc_manual import evaluate_cdc_manual_golden_cases
    from taiwan_lab_mcp.importers.cdc_manual_layout import (
        parse_cdc_receiving_units,
        parse_cdc_testing_locations,
    )

    layout = _layout()
    digest = hashlib.sha256(MANUAL_PDF).hexdigest()
    location = _chapter7_case(
        layout,
        "raw/manual.pdf",
        case_id="CDC-G7-001",
        parse=parse_cdc_testing_locations,
        input_key="disease",
        field="disease",
    )
    unit = _chapter7_case(
        layout,
        "raw/manual.pdf",
        case_id="CDC-G7-002",
        parse=parse_cdc_receiving_units,
        input_key="unit",
        field="unit_name",
    )

    results = evaluate_cdc_manual_golden_cases(layout, [location, unit], raw_artifact_sha256=digest)

    assert [result["failure_codes"] for result in results] == [[], []]
    # A receiving-unit row is not found by a disease name.
    wrong = {**unit, "case_id": "CDC-G7-003", "input": {"disease": "天花"}}
    (result,) = evaluate_cdc_manual_golden_cases(layout, [wrong], raw_artifact_sha256=digest)
    assert result["failure_codes"] == ["STATUS_MISMATCH"]


def _reviews(**changes):
    from taiwan_lab_mcp.importers.cdc_manual import CDC_MANUAL_SERVING_GATES

    return [
        {
            "gate_id": gate_id,
            "reviewer_id": REVIEWER,
            "reviewer_role": ROLE,
            "reviewed_at": REVIEWED_AT,
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "Synthetic delegated review for the unit test.",
            **changes,
        }
        for gate_id in CDC_MANUAL_SERVING_GATES
    ]


def _official(data_root, layout, *, version="1150826", **overrides):
    from taiwan_lab_mcp.importers.cdc_manual import build_official_cdc_manual_snapshot

    raw_revision_id, artifact_relative = _fetched(data_root, version=version)
    arguments = {
        "raw_revision_id": raw_revision_id,
        "approved_golden_cases": _cases(layout, artifact_relative),
        "owner_reviews": _reviews(),
        "publisher_actor_id": "unit-test-publisher",
    }
    arguments.update({key: value(layout, artifact_relative) for key, value in overrides.items()})
    return build_official_cdc_manual_snapshot(data_root, **arguments)


def test_official_build_uses_the_delegated_ai_review(tmp_path, distribution, pdf_reader):
    built = _official(tmp_path, pdf_reader)

    assert (built["rows"], built["generation"]) == (4, 1)
    build_dir = tmp_path / "curated" / "cdc_specimen_manual" / built["snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "CDC-R1-CONTENT.json").read_bytes())
    assert (review["reviewer_id"], review["reviewer_role"]) == (REVIEWER, ROLE)
    # Version 3 adds chapter 7 and the revision table to the reviewed scope (OD-18).
    assert (review["protocol_id"], review["protocol_version"]) == ("cdc-manual-r1-ai-review", "4")
    # The revision table stays in the same raw revision and is listed as review evidence.
    references = {reference["artifact_id"]: reference for reference in review["evidence_refs"]}
    assert {"cdc-manual-pdf", "cdc-manual-revision-pdf", "cdc-manual-fetch-record"} <= set(
        references
    )
    # Before the pointer switched, every stored row was compared with the Word table tags.
    tag_check = json.loads((tmp_path / references["cdc-manual-tag-check"]["path"]).read_bytes())
    assert tag_check == {
        "check": "cdc-manual-word-tag-text-v1",
        "rows_compared": 9,
        "cells_compared": 67,
        "tables": {
            "cdc_specimen_requirement": {"rows_compared": 4, "cells_compared": 32},
            "cdc_testing_location": {"rows_compared": 3, "cells_compared": 27},
            "cdc_receiving_unit": {"rows_compared": 2, "cells_compared": 8},
        },
        "mismatches": [],
    }
    # The revision table's change list travels with the build for the content review (OD-18).
    changes = json.loads(
        (tmp_path / references["cdc-manual-revision-changes"]["path"]).read_bytes()
    )
    assert changes["check"] == "cdc-manual-revision-change-list-v1"
    assert (changes["compiled_date_raw"], changes["approved_date_raw"]) == (
        "115年08月26日",
        "115年08月26日",
    )
    assert changes["entries"] == [
        {
            "page_reference_raw": "6",
            "subject_raw": "傷寒、副傷寒",
            "explanation_raw": "修訂採檢項目、採檢目的",
            "pdf_page": 1,
            "continues_on_pages": [],
        }
    ]
    certificate = json.loads((build_dir / "audit" / "golden-qualification.json").read_bytes())
    assert certificate["official_qualification_status"] == "approved"
    assert len(certificate["approved_distinct_case_ids"]) == 10
    result = _adapter(tmp_path).search_disease("登革熱")
    assert (result.result_status, result.provenance.curated_build_id) == (
        "ok",
        built["snapshot_id"],
    )
    assert result.provenance.resource_url == "https://www.cdc.gov.tw/Uploads/manual.pdf"


def _nine_cases(layout, artifact_relative):
    return _cases(layout, artifact_relative, count=9)


def _wrong_expected_value(layout, artifact_relative):
    cases = _cases(layout, artifact_relative)
    cases[0]["expected_fields"]["purpose_display"] = "病原體檢測；血清\n型別鑑定"
    return cases


def _disease_the_row_does_not_name(layout, artifact_relative):
    # Searching this disease would not return the row, so the case cannot pass.
    cases = _cases(layout, artifact_relative)
    cases[0]["input"] = {"disease": "登革熱"}
    return cases


def _other_reviewer(layout, artifact_relative):
    return _reviews(reviewer_id="someone-else")


def _major_finding(layout, artifact_relative):
    return _reviews(finding_counts={"critical": 0, "major": 1, "minor": 0})


@pytest.mark.parametrize(
    ("argument", "factory", "expected_code"),
    [
        ("approved_golden_cases", _nine_cases, "GOLDEN_CASES_INSUFFICIENT"),
        ("approved_golden_cases", _wrong_expected_value, "GOLDEN_CASE_FAILED"),
        ("approved_golden_cases", _disease_the_row_does_not_name, "GOLDEN_CASE_FAILED"),
        ("owner_reviews", _other_reviewer, "OWNER_REVIEW_REVIEWER_MISMATCH"),
        ("owner_reviews", _major_finding, "OWNER_REVIEW_REJECTED"),
    ],
)
def test_official_build_rejects_insufficient_evidence_before_writing(
    tmp_path, distribution, pdf_reader, argument, factory, expected_code
):
    from taiwan_lab_mcp.cdc_manual_source import CdcManualImportError

    with pytest.raises(CdcManualImportError) as error:
        _official(tmp_path, pdf_reader, **{argument: factory})
    assert error.value.code == expected_code
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()


def test_official_build_rejects_rows_that_differ_from_the_word_table_tags(
    tmp_path, distribution, pdf_reader
):
    from taiwan_lab_mcp.cdc_manual_source import CdcManualImportError

    # Move 「液」 of 「尿液」 down into the dengue row below: the ruling lines now read 「尿」 and
    # 「液血清」, while the Word tags still keep 「液」 in the urine cell.
    page = next(page for page in pdf_reader["pages"] if page["page_number"] == 17)
    char = next(
        char
        for char in page["chars"]
        if char["text"] == "液" and char["x0"] < 130.3 and char["y0"] < 200
    )
    char["y0"] += 62
    char["y1"] += 62

    with pytest.raises(CdcManualImportError) as error:
        _official(tmp_path, pdf_reader)
    assert error.value.code == "LAYOUT_TAG_TEXT_MISMATCH"
    assert not (tmp_path / "manifests" / "current" / "cdc_specimen_manual.json").exists()


def test_official_build_rejects_a_manual_whose_pages_print_another_edition(
    tmp_path, distribution, pdf_reader
):
    from taiwan_lab_mcp.cdc_manual_source import CdcManualImportError

    # The attachment says 1150827 but every table page header prints 1150826.
    with pytest.raises(CdcManualImportError) as error:
        _official(tmp_path, pdf_reader, version="1150827")
    assert error.value.code == "MANUAL_VERSION_MISMATCH"
    assert not (tmp_path / "curated").exists()


def test_official_build_rejects_raw_pdfs_that_no_longer_match_the_fetch_record(
    tmp_path, distribution, pdf_reader
):
    from taiwan_lab_mcp.cdc_manual_source import CdcManualImportError
    from taiwan_lab_mcp.importers.cdc_manual import build_official_cdc_manual_snapshot

    raw_revision_id, artifact_relative = _fetched(tmp_path)
    (tmp_path / artifact_relative).write_bytes(MANUAL_PDF.replace(b"synthetic", b"edited!!!"))

    with pytest.raises(CdcManualImportError) as error:
        build_official_cdc_manual_snapshot(
            tmp_path,
            raw_revision_id=raw_revision_id,
            approved_golden_cases=_cases(pdf_reader, artifact_relative),
            owner_reviews=_reviews(),
            publisher_actor_id="unit-test-publisher",
        )
    assert error.value.code == "RAW_REVISION_INTEGRITY"
    assert not (tmp_path / "curated").exists()


def test_official_build_requires_an_installed_distribution(tmp_path, monkeypatch, pdf_reader):
    from taiwan_lab_mcp.cdc_manual_source import CdcManualImportError

    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )
    with pytest.raises(CdcManualImportError) as error:
        _official(tmp_path, pdf_reader)
    assert error.value.code == "APPLICATION_BUILD_IDENTITY_MISSING"
    assert not (tmp_path / "curated").exists()
