from taiwan_lab_mcp.adapters.cdc import CDCAdapter
from taiwan_lab_mcp.adapters.nhi import NHIAdapter
from taiwan_lab_mcp.adapters.standards import standards_status
from taiwan_lab_mcp.adapters.tfda import TFDAAdapter


def test_cdc_measles_alias():
    r = CDCAdapter().search_disease("measles")
    assert r.count == 1
    assert r.items[0].record.disease == "麻疹"
    assert r.provenance.parser_version == "sample-fixture-v1"
    assert r.sample_only is True


def test_tfda_sample_search():
    r = TFDAAdapter().search_ivd("HbA1c")
    assert r.count == 1


def test_nhi_sample_search():
    r = NHIAdapter().search_lab_code("糖化血色素")
    assert r.count == 1


def test_standard_adapters_are_reserved():
    s = standards_status()
    assert "LOINC" in s.capabilities
