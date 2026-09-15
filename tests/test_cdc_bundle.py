"""Owner 2026-09-16 (OD-19): the GitHub Release download bundle also carries the CDC data.

The roster bundle holds the official ODS; the manual bundle holds both PDFs of one raw revision
(the manual and its revision table). Installing re-verifies every byte and serves the same rows.
"""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

import taiwan_lab_mcp.importers.nhi as nhi_importer
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.config import DataContext


def _module(name):
    # Load the sibling tests' fixtures by path so these tests also run from an installed wheel.
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"{path.stem}_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LABS = _module("test_cdc_labs_official.py")
MANUAL = _module("test_cdc_manual_official.py")


@pytest.fixture
def distribution(monkeypatch):
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )


@pytest.fixture
def manual_reader(monkeypatch):
    import taiwan_lab_mcp.importers.cdc_manual as manual

    layout = MANUAL._layout()
    monkeypatch.setattr(manual, "extract_cdc_manual_layout", lambda payload: layout)
    return layout


def _export(data_root, source_id, output_dir):
    from taiwan_lab_mcp.snapshot_bundle import export_snapshot_bundle

    return export_snapshot_bundle(data_root, source_id, output_dir=output_dir)


def _install(data_root, source_id, exported):
    from taiwan_lab_mcp.snapshot_bundle import install_snapshot_bundle

    return install_snapshot_bundle(
        data_root,
        source_id=source_id,
        bundle_path=Path(exported["bundle_path"]),
        expected_sha256=exported["bundle_sha256"],
        actor="unit-test-installer",
        # Windows temp folders push these paths past the MAX_PATH guard, which
        # tests/test_snapshot_bundle.py covers on its own.
        max_path_length=None,
    )


def _adapter(data_root):
    return CDCAdapter(DataContext(mode="official_snapshot", data_root=data_root))


def test_roster_bundle_carries_the_official_ods_and_serves_the_same_rows(tmp_path, distribution):
    from taiwan_lab_mcp.stores import read_source_status

    source_root = tmp_path
    built = LABS._official(source_root)

    exported = _export(source_root, "cdc_authorized_labs", tmp_path / "r")

    with zipfile.ZipFile(exported["bundle_path"]) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("bundle-manifest.json"))
    raw_prefix = f"raw/cdc_authorized_labs/{built['raw_revision_id']}"
    assert {f"{raw_prefix}/artifacts/source.ods", f"{raw_prefix}/fetch.json"} <= names
    assert f"curated/cdc_authorized_labs/{built['snapshot_id']}/data.sqlite3" in names
    assert manifest["attribution"] == "資料提供機關：衛生福利部疾病管制署"
    assert "非疾管署官方服務" in manifest["notice"]

    user_root = tmp_path / "u"
    installed = _install(user_root, "cdc_authorized_labs", exported)

    assert (installed["result"], installed["snapshot_id"]) == ("installed", built["snapshot_id"])
    assert _adapter(user_root).find_authorized_lab("傷寒").total_matches == 2
    status = read_source_status(user_root, "cdc_recognized_labs")
    assert (status.availability, status.freshness_policy_version) == ("available", "cdc-labs-v1")


def test_manual_bundle_carries_both_pdfs_and_serves_the_same_rows(
    tmp_path, distribution, manual_reader
):
    from taiwan_lab_mcp.stores import read_source_status

    source_root = tmp_path
    built = MANUAL._official(source_root, manual_reader)

    exported = _export(source_root, "cdc_specimen_manual", tmp_path / "r")

    with zipfile.ZipFile(exported["bundle_path"]) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("bundle-manifest.json"))
    raw_prefix = f"raw/cdc_specimen_manual/{built['raw_revision_id']}"
    assert {
        f"{raw_prefix}/artifacts/manual.pdf",
        f"{raw_prefix}/artifacts/revision.pdf",
        f"{raw_prefix}/fetch.json",
    } <= names
    assert f"curated/cdc_specimen_manual/{built['snapshot_id']}/data.sqlite3" in names
    assert manifest["attribution"] == "資料提供機關：衛生福利部疾病管制署"

    user_root = tmp_path / "u"
    installed = _install(user_root, "cdc_specimen_manual", exported)

    assert (installed["result"], installed["snapshot_id"]) == ("installed", built["snapshot_id"])
    result = _adapter(user_root).search_disease("登革熱")
    assert (result.total_matches, result.items[0].record.specimen) == (1, "血清")
    status = read_source_status(user_root, "cdc_manual")
    assert (status.availability, status.freshness_policy_version) == ("available", "cdc-manual-v1")


def test_cli_exports_the_cdc_bundles_and_accepts_them_for_install(
    tmp_path, distribution, manual_reader, capsys
):
    from taiwan_lab_mcp import data_cli

    source_root = tmp_path
    MANUAL._official(source_root, manual_reader)
    LABS._official(source_root)
    release = tmp_path / "r"

    for source_id in ("cdc_specimen_manual", "cdc_authorized_labs"):
        code = data_cli.main(
            [
                "export-snapshot",
                source_id,
                "--data-dir",
                str(source_root),
                "--output-dir",
                str(release),
                "--json",
            ]
        )
        exported = json.loads(capsys.readouterr().out)
        assert (code, exported["result"], exported["source_id"]) == (0, "exported", source_id)

    # The install command accepts the CDC sources; a missing bundle fails on the file, not on
    # the source name.
    code = data_cli.main(
        [
            "install-snapshot",
            "cdc_specimen_manual",
            "--bundle",
            str(tmp_path / "missing.zip"),
            "--actor",
            "unit-test-installer",
            "--data-dir",
            str(tmp_path / "u"),
            "--json",
        ]
    )
    assert (code, json.loads(capsys.readouterr().out)["error_code"]) == (2, "BUNDLE_UNREADABLE")
