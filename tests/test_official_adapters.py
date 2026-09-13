import taiwan_lab_mcp.adapters.nhi as nhi_module


def test_nhi_02_name_and_reviewed_alias_search_returns_scoped_candidates(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    payload = (
        "\ufeff"
        + ",".join(NHI_COLUMNS)
        + "\n"
        + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
        + "09007C,12,20200101,29101231,Glucose,葡萄糖,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    monkeypatch.setattr(
        nhi_module,
        "load_aliases",
        lambda: {"糖化血色素": ("09006C", "09007C")},
    )
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))

    result = NHIAdapter().search_payment_items("糖化血色素")
    assert result.result_status == "ok"
    assert result.coverage_status == "review_incomplete"
    assert [item.record.code_raw for item in result.items] == ["09006C", "09007C"]
    assert all(item.record.matched_by == ["alias"] for item in result.items)
    assert all(item.record.scope_status == "review_pending" for item in result.items)
