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


NHI_NOT_OFFICIAL_NOTE = "非健保署官方服務，內容以健保署公告為準。"


def test_official_nhi_results_state_the_service_is_not_official(tmp_path, monkeypatch):
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "sample")
    sample = NHIAdapter().get_points("SAMPLE001")
    assert NHI_NOT_OFFICIAL_NOTE not in sample.notes

    payload = (
        chr(0xFEFF)
        + ",".join(NHI_COLUMNS)
        + "\n"
        + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode("utf-8")
    build_nhi_snapshot(payload, tmp_path)
    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    adapter = NHIAdapter()

    for result in (
        adapter.get_points("09006C"),
        adapter.search_payment_items("醣化"),
        adapter.get_payment_rule("09006C"),
        adapter.get_points("09006C", "2026-09-13"),
    ):
        assert NHI_NOT_OFFICIAL_NOTE in result.notes, result.operation
