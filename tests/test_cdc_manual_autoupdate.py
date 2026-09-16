"""Automatic CDC specimen manual update (owner 2026-09-15: 「A 開始做疾管署」, OD-04).

A new manual replaces the served one only when every automated check passes: the reading rules
are unchanged, rows and diseases change by at most 10%, the golden cases pass and every stored
cell matches the Word table tags. Otherwise the served manual keeps answering, marked as having a
newer candidate. Fixtures are synthetic PDFs whose page layouts come from the layout test builder.
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.config import DataContext

HERE = Path(__file__).parent


def _module(name):
    # Load sibling test helpers by path so the tests also run from an installed wheel.
    path = HERE / f"test_cdc_manual_{name}.py"
    spec = importlib.util.spec_from_file_location(f"cdc_manual_{name}_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PAGES = _module("layout")
CHAPTER7 = _module("chapter7")
SOURCE = _module("source")
SERVING_PDF = SOURCE._pdf("manual")
REVISION_PDF = SOURCE._pdf("revision")
NEW_PDF = SOURCE._pdf("manual-reuploaded")
AUTO_REVIEWER = "automated-check:cdc-manual-auto-update"


def _now():
    return datetime.now(timezone.utc)


def _serving_layout():
    # Chapter 7 is stored in the same build, so every fixture manual carries its pages (OD-18).
    return PAGES._layout(PAGES._display_page(), *PAGES._typhoid_pages(), *CHAPTER7.chapter7_pages())


def _changed_layout():
    # The dengue row's volume changes from 「3 mL」 to 「5 mL」.
    layout = _serving_layout()
    page = next(page for page in layout["pages"] if page["page_number"] == 17)
    char = next(
        char
        for char in page["chars"]
        if char["text"] == "3" and char["y0"] > 200 and 239.3 < char["x0"] < 338.8
    )
    char["text"] = "5"
    return layout


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


@pytest.fixture
def readers(monkeypatch):
    # Word table tags cannot be produced in a test PDF; each synthetic PDF maps to a layout.
    import taiwan_lab_mcp.importers.cdc_manual as manual

    layouts = {}
    monkeypatch.setattr(manual, "extract_cdc_manual_layout", lambda payload: layouts[payload])
    return layouts


def _serve(data_root, readers):
    from taiwan_lab_mcp.importers.cdc_manual import build_cdc_manual_snapshot

    layout = _serving_layout()
    readers[SERVING_PDF] = layout
    return build_cdc_manual_snapshot(
        layout, data_root, manual_payload=SERVING_PDF, revision_payload=REVISION_PDF
    )


def _auto(data_root, manual_pdf=None, opener=None):
    from taiwan_lab_mcp.cdc_manual_autoupdate import run_cdc_manual_auto_update

    opener = opener or SOURCE._Opener(
        *SOURCE._responses(manual=SOURCE._pdf_response(manual_pdf), revision=None)
    )
    return run_cdc_manual_auto_update(
        data_root, actor="unit-test-scheduler", opener=opener, clock=_now
    )


def _adapter(data_root):
    return CDCAdapter(DataContext(mode="official_snapshot", data_root=data_root))


def test_unchanged_manual_records_a_successful_check(tmp_path, distribution, readers):
    built = _serve(tmp_path, readers)

    summary = _auto(tmp_path, SERVING_PDF)

    assert (summary["result"], summary["manual_version"], summary["generation"]) == (
        "unchanged",
        "1150826",
        2,
    )
    assert (summary["stale"], summary["published_snapshot_id"]) == (False, None)
    result = _adapter(tmp_path).search_disease("登革熱")
    assert result.provenance.curated_build_id == built["snapshot_id"]


def test_changed_manual_is_published_when_every_check_passes(tmp_path, distribution, readers):
    built = _serve(tmp_path, readers)
    readers[NEW_PDF] = _changed_layout()

    summary = _auto(tmp_path, NEW_PDF)

    assert summary["result"] == "published"
    assert summary["published_snapshot_id"] not in (None, built["snapshot_id"])
    assert (summary["rows"], summary["stale"], summary["block_reasons"]) == (4, False, [])
    diff = (tmp_path / summary["diff_summary_data_root_relative_path"]).read_text(encoding="utf-8")
    assert "內容有改的列：1" in diff
    assert "登革熱" in diff
    result = _adapter(tmp_path).search_disease("登革熱")
    assert result.provenance.curated_build_id == summary["published_snapshot_id"]
    assert result.items[0].record.volume_requirement == "5 mL"
    build_dir = tmp_path / "curated" / "cdc_specimen_manual" / summary["published_snapshot_id"]
    review = json.loads((build_dir / "audit" / "reviews" / "CDC-R1-CONTENT.json").read_bytes())
    assert (review["reviewer_id"], review["protocol_id"], review["protocol_version"]) == (
        AUTO_REVIEWER,
        "cdc-manual-r1-auto-review",
        "2",
    )
    assert "cdc-manual-tag-check" in {ref["artifact_id"] for ref in review["evidence_refs"]}


def test_large_change_is_held_back_and_reported_once(tmp_path, distribution, readers):
    from taiwan_lab_mcp.stores import read_source_status

    built = _serve(tmp_path, readers)
    readers[NEW_PDF] = PAGES._layout(PAGES._display_page())

    first = _auto(tmp_path, NEW_PDF)
    assert (first["result"], first["already_reported"]) == ("blocked", False)
    assert first["block_reasons"] == [
        "row_count_change_exceeds_10_percent",
        "disease_count_change_exceeds_10_percent",
    ]
    second = _auto(tmp_path, NEW_PDF)
    assert (second["result"], second["already_reported"]) == ("blocked", True)

    status = read_source_status(tmp_path, "cdc_manual")
    assert status.serving_curated_build_id == built["snapshot_id"]
    assert status.stale_reason_codes == ["newer_candidate_pending_review"]


def test_changed_reading_rules_hold_back_a_new_manual(tmp_path, distribution, readers, monkeypatch):
    import taiwan_lab_mcp.cdc_manual_autoupdate as autoupdate

    _serve(tmp_path, readers)
    readers[NEW_PDF] = _changed_layout()
    current = autoupdate.active_cdc_manual_transform

    def newer(layout_sha256):
        transform = current(layout_sha256)
        transform["parser"]["version"] = "cdc-manual-layout-v2"
        return transform

    monkeypatch.setattr(autoupdate, "active_cdc_manual_transform", newer)

    summary = _auto(tmp_path, NEW_PDF)
    assert (summary["result"], summary["block_reasons"]) == (
        "blocked",
        ["manual_reading_rules_changed"],
    )


def test_rows_that_differ_from_the_word_tags_are_not_published(tmp_path, distribution, readers):
    from taiwan_lab_mcp.stores import read_source_status

    built = _serve(tmp_path, readers)
    layout = _serving_layout()
    page = next(page for page in layout["pages"] if page["page_number"] == 17)
    char = next(
        char
        for char in page["chars"]
        if char["text"] == "液" and char["x0"] < 130.3 and char["y0"] < 200
    )
    char["y0"] += 62
    char["y1"] += 62
    readers[NEW_PDF] = layout

    summary = _auto(tmp_path, NEW_PDF)

    assert (summary["result"], summary["error_code"]) == (
        "auto_publish_failed",
        "LAYOUT_TAG_TEXT_MISMATCH",
    )
    assert (
        read_source_status(tmp_path, "cdc_manual").serving_curated_build_id
        == (built["snapshot_id"])
    )


def test_failed_download_keeps_serving_and_marks_it_stale(tmp_path, distribution, readers):
    built = _serve(tmp_path, readers)

    summary = _auto(tmp_path, opener=SOURCE._Opener(SOURCE._Response(503)))

    assert (summary["result"], summary["failed_stage"]) == ("failed", "discover")
    assert summary["stale_reason_codes"] == ["upstream_verification_failed"]
    result = _adapter(tmp_path).search_disease("登革熱")
    assert result.provenance.curated_build_id == built["snapshot_id"]
    assert "upstream_verification_failed" in result.warnings


def test_without_a_served_manual_nothing_is_published(tmp_path, distribution, readers):
    assert _auto(tmp_path, SERVING_PDF)["result"] == "no_serving_snapshot"
    assert not (tmp_path / "manifests" / "current" / "cdc_specimen_manual.json").exists()


def test_cli_check_runs_the_manual_auto_update(tmp_path, monkeypatch, capsys):
    from taiwan_lab_mcp import cdc_manual_autoupdate, data_cli

    calls = []

    def fake(data_dir, *, actor):
        calls.append((Path(data_dir), actor))
        return {"result": "unchanged", "failed_stage": None}

    monkeypatch.setattr(cdc_manual_autoupdate, "run_cdc_manual_auto_update", fake)
    arguments = ["check", "cdc_specimen_manual", "--actor", "scheduler"]
    code = data_cli.main([*arguments, "--data-dir", str(tmp_path), "--auto-publish", "--json"])

    assert (code, calls) == (0, [(tmp_path, "scheduler")])
    assert json.loads(capsys.readouterr().out)["result"] == "unchanged"
    with pytest.raises(SystemExit):
        data_cli.main([*arguments, "--data-dir", str(tmp_path), "--publisher-oid", "1"])
