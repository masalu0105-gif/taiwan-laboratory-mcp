import copy
import json
from datetime import datetime, timezone
from importlib.resources import files

import pytest
from pydantic import ValidationError

from taiwan_lab_mcp.adapters.base import load_sample
from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.adapters.eqa import eqa_status
from taiwan_lab_mcp.adapters.nhi import NHIAdapter
from taiwan_lab_mcp.adapters.tfda import TFDAAdapter
from taiwan_lab_mcp.models import DataRecord


@pytest.mark.parametrize("query", ["", "  ", "---", "x" * 201])
@pytest.mark.parametrize(
    "adapter,method",
    [
        (CDCAdapter, "search_disease"),
        (NHIAdapter, "search_lab_code"),
        (TFDAAdapter, "search_ivd"),
    ],
)
def test_empty_or_oversized_queries_are_rejected(adapter, method, query):
    with pytest.raises(ValueError):
        getattr(adapter(), method)(query)


@pytest.mark.parametrize(
    "adapter,method",
    [
        (CDCAdapter, "search_disease"),
        (CDCAdapter, "find_authorized_lab"),
        (NHIAdapter, "get_points"),
        (TFDAAdapter, "get_license"),
    ],
)
def test_no_match_retains_sample_warning(adapter, method):
    result = getattr(adapter(), method)("SAMPLE-NO-MATCH-123").model_dump(mode="json")
    assert result["count"] == 0
    assert result["status"] == "not_found"
    assert result["sample_only"] is True
    assert result["data_mode"] == "sample"
    assert "sample_only" in result["notes"][0]
    assert result["provenance"][0]["method"] == "synthetic"


def test_filters_preserve_roles_and_normalize_unicode():
    cdc = CDCAdapter()
    assert cdc.search_disease("ＭＥＡＳＬＥＳ").count == 1
    assert cdc.find_authorized_lab("麻疹", "高雄").count == 0
    assert cdc.find_authorized_lab("麻疹", "台北").count == 1
    tfda = TFDAAdapter()
    assert tfda.find_manufacturer("Sample Manufacturer").count == 1
    assert tfda.find_manufacturer("Sample Taiwan Applicant").count == 0
    assert NHIAdapter().get_points("sample001").items[0]["points"] is None


@pytest.mark.parametrize("limit", [0, -1, 51, True, 1.5])
def test_compare_rejects_invalid_limits(limit):
    with pytest.raises(ValueError):
        TFDAAdapter().compare_products("HbA1c", limit)


def test_compare_count_and_provenance_survive_truncation():
    tfda = TFDAAdapter()
    tfda.devices.append(copy.deepcopy(tfda.devices[0]))
    result = tfda.compare_products("HbA1c", 1).model_dump(mode="json")
    assert result["count"] == len(result["items"]) == 1
    assert result["items"][0]["provenance"]["version"] == "sample-v0.1"
    assert "1 / 2" in result["notes"][-1]


@pytest.mark.parametrize("mode", ["official", "live", "", "sampl"])
def test_unimplemented_modes_cannot_fall_back_to_samples(monkeypatch, mode):
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", mode)
    with pytest.raises(ValueError, match="Only sample mode"):
        CDCAdapter()


@pytest.mark.parametrize(
    "filename",
    [
        "cdc_specimen.sample.json",
        "cdc_labs.sample.json",
        "nhi_fee.sample.json",
        "tfda_devices.sample.json",
    ],
)
def test_bundled_fixtures_have_complete_sample_metadata(filename):
    for record in load_sample(filename):
        assert record["sample_only"] is True
        for key in ("source_url", "version", "updated_at"):
            assert record[key] == record["provenance"][key]
        assert record["provenance"]["updated_at_note"]


@pytest.mark.parametrize(
    "field", ["provenance", "source_url", "version", "updated_at", "sample_only"]
)
def test_loader_rejects_missing_metadata(tmp_path, monkeypatch, field):
    record = load_sample("nhi_fee.sample.json")[0]
    del record[field]
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "invalid.json").write_text(json.dumps([record]), encoding="utf-8")
    monkeypatch.setattr("taiwan_lab_mcp.adapters.base.files", lambda _: tmp_path)
    with pytest.raises(ValidationError):
        load_sample("invalid.json")


def official_contract_record():
    # Synthetic test of metadata shape only; never published as an official fixture.
    record = load_sample("nhi_fee.sample.json")[0]
    record["sample_only"] = False
    record["source_url"] = "https://data.gov.tw/dataset/174450"
    record["version"] = "test-snapshot-shape-only"
    record["provenance"].update(
        source_name="NHI contract test",
        source_url=record["source_url"],
        version=record["version"],
        method="structured_import",
        retrieved_at=datetime(2026, 9, 12, tzinfo=timezone.utc).isoformat(),
        license="政府資料開放授權條款-第1版",
        license_url="https://data.gov.tw/license",
        locator="test row 1",
        updated_at_note="Publisher date absent in this contract test",
    )
    return record


def test_official_contract_preserves_unknown_date_and_domain_fields():
    record = official_contract_record()
    parsed = DataRecord.model_validate(record).model_dump(mode="json")
    assert parsed["updated_at"] is None
    assert parsed["code"] == "SAMPLE001"
    assert parsed["provenance"]["retrieved_at"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("method", "synthetic"),
        ("retrieved_at", None),
        ("license", " "),
        ("license_url", None),
        ("locator", ""),
        ("updated_at_note", ""),
        ("retrieved_at", "2026-09-12T00:00:00"),
    ],
)
def test_official_contract_rejects_untraceable_metadata(field, value):
    record = official_contract_record()
    record["provenance"][field] = value
    with pytest.raises(ValidationError):
        DataRecord.model_validate(record)


def test_mismatched_metadata_and_fake_sample_flag_are_rejected():
    row = load_sample("nhi_fee.sample.json")[0]
    row["version"] = "different"
    with pytest.raises(ValidationError):
        DataRecord.model_validate(row)
    row = load_sample("nhi_fee.sample.json")[0]
    row["sample_only"] = "true"
    with pytest.raises(ValidationError):
        DataRecord.model_validate(row)


def test_official_record_cannot_enter_bundled_sample_loader(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    (folder / "official.json").write_text(
        json.dumps([official_contract_record()]), encoding="utf-8"
    )
    monkeypatch.setattr("taiwan_lab_mcp.adapters.base.files", lambda _: tmp_path)
    with pytest.raises(ValueError, match="Bundled data"):
        load_sample("official.json")


def test_no_catalog_files_and_eqa_has_no_active_provider():
    assert eqa_status()["catalog_access_enabled"] is False
    assert not any(
        "cap" in p.name.lower() for p in files("taiwan_lab_mcp").joinpath("data").iterdir()
    )
