import pytest

from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, NHIImportError, parse_nhi_csv


def _payload(row: str) -> bytes:
    return ("\ufeff" + ",".join(NHI_COLUMNS) + "\r\n" + row + "\r\n").encode("utf-8")


def test_nhi_01_exact_code_preserves_raw_fields_and_locator():
    result = parse_nhi_csv(_payload("09006C,12,20120101,29101231,HbA1c,醣化血紅素,完整備註"))

    row = result.rows[0]
    assert row.source_row_number == 2
    assert row.source_row_sha256
    assert row.code_raw == "09006C"
    assert row.code_normalized == "09006c"
    assert row.points_raw == "12"
    assert row.effective_start_raw == "20120101"
    assert row.effective_end_raw == "29101231"
    assert row.name_en_raw == "HbA1c"
    assert row.name_zh_raw == "醣化血紅素"
    assert row.note_raw == "完整備註"


def test_nhi_03_zero_points_and_full_note_are_preserved():
    result = parse_nhi_csv(_payload('09007C,0,20200101,29101231,Glucose,葡萄糖,"第一行\r\n第二行"'))

    row = result.rows[0]
    assert row.points == 0
    assert row.points_raw == "0"
    assert row.note_raw == "第一行\r\n第二行"
    assert row.to_record().points == 0
    assert row.to_record().note_raw == "第一行\r\n第二行"


def test_nhi_05_sentinel_stays_raw_inference_and_not_permanent():
    result = parse_nhi_csv(_payload("09008C,1,20200101,29101231,TSH,甲狀腺刺激素,"))

    row = result.rows[0]
    assert row.effective_end_raw == "29101231"
    assert row.effective_end == "2910-12-31"
    assert row.possible_open_end_sentinel is True
    assert "permanent" not in row.to_record().model_dump(mode="json")


def test_sdd_nhi_01_contract_bundle():
    result = parse_nhi_csv(_payload("09009C,3,20240101,20251231,Albumin,白蛋白,只保留來源原文"))

    assert len(result.rows) == 1
    assert len(NHI_COLUMNS) == 7
    assert result.rows[0].to_record().model_dump(mode="json")["points"] == 3


def test_nhi_points_overflow_returns_stable_import_error():
    huge_points = "9" * 5000

    with pytest.raises(NHIImportError, match="POINTS_INVALID"):
        parse_nhi_csv(_payload(f"09010C,{huge_points},20240101,20251231,Albumin,白蛋白,"))


def test_nhi_points_require_ascii_decimal_digits():
    with pytest.raises(NHIImportError, match="POINTS_INVALID"):
        parse_nhi_csv(_payload("09011C,１２,20240101,20251231,Albumin,白蛋白,"))


def _golden_payload() -> bytes:
    rows = [
        "00101A,0,20120101,29101231,,前導零零點合成項目,",
        '09006C,12,20120101,29101231,HbA1c,"醣化\r\n血紅素",完整備註',
        "09007C,5,20240229,20251231,Glucose,葡萄糖,",
    ]
    return ("\ufeff" + ",".join(NHI_COLUMNS) + "\r\n" + "\r\n".join(rows) + "\r\n").encode("utf-8")


def _synthetic_case(
    payload: bytes, case_id: str, code: str, expected_fields: dict, **overrides
) -> dict:
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.importers.nhi import active_nhi_transform

    row = next(row for row in parse_nhi_csv(payload).rows if row.code_raw == code)
    case = {
        "golden_case_schema_version": 1,
        "case_id": case_id,
        "source_id": "nhi_fee",
        "acceptance_id": "NHI-01",
        "source_title": "synthetic NHI golden fixture; not official evidence",
        "official_landing_url": "https://example.invalid/synthetic-nhi-fixture",
        "official_version_or_modified_at": None,
        "official_source": False,
        "artifact_id": "nhi-primary-csv",
        "raw_artifact_sha256": sha256_bytes(payload),
        "evidence_data_root_relative_path": None,
        "fixture_file": None,
        "fixture_sha256": None,
        "transform": active_nhi_transform(),
        "input": {"code": code},
        "source_locator": {"locator_type": "nhi_row", "source_row_number": row.source_row_number},
        "source_row_sha256": row.source_row_sha256,
        "expected_status": "ok",
        "expected_fields": expected_fields,
        "expected_warnings": ["coverage_review_incomplete"],
        "reviewer_id": None,
        "reviewer_role": None,
        "identity_assurance": None,
        "reviewed_at": None,
        "review_status": "review_pending",
    }
    case.update(overrides)
    return case


def test_nhi_golden_cases_record_per_case_results_without_official_approval(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.importers.nhi import build_nhi_snapshot, evaluate_nhi_golden_cases

    payload = _golden_payload()
    cases = [
        _synthetic_case(
            payload,
            "SYN-NHI-G-001",
            "00101A",
            {"code_raw": "00101A", "points_raw": "0", "points": 0, "name_en_raw": None},
        ),
        _synthetic_case(
            payload,
            "SYN-NHI-G-002",
            "09006C",
            {"name_zh_raw": "醣化\r\n血紅素", "note_raw": "完整備註"},
        ),
        _synthetic_case(
            payload,
            "SYN-NHI-G-003",
            "09007C",
            {
                "effective_start": "2024-02-29",
                "effective_end_raw": "20251231",
                "possible_open_end_sentinel": False,
                "scope_status": "review_pending",
            },
        ),
    ]

    built = build_nhi_snapshot(payload, tmp_path, golden_cases=cases)
    build_dir = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"]
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    evidence = manifest["audit_evidence"]
    candidate = json.loads(
        (tmp_path / Path(evidence["qualification_candidate"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    certificate = json.loads(
        (tmp_path / Path(evidence["golden_qualification"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )

    assert candidate["case_ids"] == [case["case_id"] for case in cases]
    assert candidate["case_count"] == 3
    assert [result["evaluation_status"] for result in candidate["cases"]] == ["passed"] * 3
    assert all(result["failure_codes"] == [] for result in candidate["cases"])
    assert candidate["official_qualification_status"] == "not_qualified"
    assert certificate["official_qualification_status"] == "not_qualified"
    assert certificate["approved_distinct_case_ids"] == []

    raw_path = tmp_path / Path(manifest["artifacts"][0]["data_root_relative_path"])
    rerun = evaluate_nhi_golden_cases(
        raw_path.read_bytes(), [result["golden_case"] for result in candidate["cases"]]
    )
    assert rerun == candidate["cases"]

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    served = NHIAdapter().get_points("00101A")
    assert served.result_status == "ok"
    assert served.warnings == cases[0]["expected_warnings"]


def test_nhi_golden_case_mismatch_blocks_build_before_any_write(tmp_path):
    from taiwan_lab_mcp.importers.nhi import build_nhi_snapshot

    payload = _golden_payload()
    case = _synthetic_case(payload, "SYN-NHI-G-001", "00101A", {"points": 1})

    with pytest.raises(NHIImportError, match="GOLDEN_CASE_FAILED"):
        build_nhi_snapshot(payload, tmp_path, golden_cases=[case])
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"raw_artifact_sha256": "0" * 64}, "ARTIFACT_MISMATCH"),
        ({"source_row_sha256": "0" * 64}, "LOCATOR_MISMATCH"),
        ({"expected_fields": {"name_en_search": "x"}}, "EXPECTED_FIELD_UNSUPPORTED:name_en_search"),
        ({"expected_fields": {"name_en_raw": "Translated name"}}, "FIELD_MISMATCH:name_en_raw"),
        ({"expected_warnings": []}, "WARNINGS_MISMATCH"),
        ({"input": {"code": "99999Z"}}, "STATUS_MISMATCH"),
    ],
)
def test_nhi_golden_case_evaluation_reports_stable_failure_codes(override, expected_code):
    from taiwan_lab_mcp.importers.nhi import evaluate_nhi_golden_cases

    payload = _golden_payload()
    override = dict(override)
    expected_fields = override.pop("expected_fields", {"points": 0})
    case = _synthetic_case(payload, "SYN-NHI-G-001", "00101A", expected_fields, **override)

    [result] = evaluate_nhi_golden_cases(payload, [case])
    assert result["evaluation_status"] == "failed"
    assert expected_code in result["failure_codes"]


def test_nhi_golden_case_bound_to_stale_transform_fails():
    from taiwan_lab_mcp.importers.nhi import evaluate_nhi_golden_cases

    payload = _golden_payload()
    case = _synthetic_case(payload, "SYN-NHI-G-001", "00101A", {"points": 0})
    case["transform"]["parser"] = {**case["transform"]["parser"], "version": "nhi-csv-v0"}

    [result] = evaluate_nhi_golden_cases(payload, [case])
    assert result["evaluation_status"] == "failed"
    assert "TRANSFORM_MISMATCH" in result["failure_codes"]


def test_nhi_golden_case_schema_errors_fail_closed():
    from taiwan_lab_mcp.importers.nhi import evaluate_nhi_golden_cases

    payload = _golden_payload()
    valid = _synthetic_case(payload, "SYN-NHI-G-001", "00101A", {"points": 0})
    unknown_key = {**valid, "unexpected": True}

    with pytest.raises(NHIImportError, match="GOLDEN_CASE_SCHEMA_INVALID"):
        evaluate_nhi_golden_cases(payload, [unknown_key])
    with pytest.raises(NHIImportError, match="GOLDEN_CASE_SCHEMA_INVALID"):
        evaluate_nhi_golden_cases(payload, [valid, valid])


def _official_fixture_payload() -> bytes:
    rows = [
        f"9{index:04d}C,{index * 10},20240101,29101231,Unit test {index},單元測試項目{index},"
        for index in range(1, 11)
    ]
    return (chr(0xFEFF) + ",".join(NHI_COLUMNS) + "\r\n" + "\r\n".join(rows) + "\r\n").encode(
        "utf-8"
    )


def _write_official_raw_revision(data_root, payload: bytes) -> str:
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.fetch import FetchedArtifact
    from taiwan_lab_mcp.sync import run_nhi_sync

    discovery = {
        "dataset_id": "174450",
        "identifier": "A21030000I-D20021",
        "publisher_oid": "2.16.886.101.20003.20065.20022",
        "landing_url": "https://data.gov.tw/dataset/174450",
        "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/174450",
        "license_code": "1",
        "license_name": "政府資料開放授權條款-第1版",
        "license_url": "https://data.gov.tw/license",
        "resource_format": "CSV",
        "resource_character_encoding": "UTF-8",
        "resource_url": "https://info.nhi.gov.tw/data.csv",
        "official_modified_at_raw": "2026-09-14 07:05:47",
        "official_modified_at_precision": "second",
        "official_modified_timezone_known": False,
    }
    artifact = FetchedArtifact(
        requested_url="https://info.nhi.gov.tw/data.csv",
        final_url="https://info.nhi.gov.tw/data.csv",
        status_code=200,
        payload=payload,
        sha256=sha256_bytes(payload),
        fetched_at="2026-09-14T03:42:43Z",
        headers={"content-type": "application/csv"},
        redirect_trace=("https://info.nhi.gov.tw/data.csv",),
    )
    report = run_nhi_sync(payload, data_root, discovery=discovery, fetched_artifact=artifact)
    assert report["status"] == "passed"
    return report["raw_revision_id"]


def _approved_official_cases(payload: bytes, raw_revision_id: str) -> list[dict]:
    cases = []
    for index, row in enumerate(parse_nhi_csv(payload).rows, start=1):
        cases.append(
            _synthetic_case(
                payload,
                f"UNIT-OFFICIAL-G-{index:03d}",
                row.code_raw,
                {"points": row.points, "name_zh_raw": row.name_zh_raw},
                official_source=True,
                evidence_data_root_relative_path=(
                    f"raw/nhi_fee/{raw_revision_id}/artifacts/source.csv"
                ),
                reviewer_id="unit-test-only-reviewer",
                reviewer_role="unit_test_role",
                identity_assurance="local_asserted",
                reviewed_at="2026-09-14T18:09:42+08:00",
                review_status="approved",
            )
        )
    return cases


def _owner_reviews(gates=("NHI-R1-SOURCE", "NHI-R1-SCHEMA", "PUB-R1-OWNER")) -> list[dict]:
    return [
        {
            "gate_id": gate_id,
            "reviewer_id": "unit-test-only-reviewer",
            "reviewer_role": "project_owner",
            "reviewed_at": "2026-09-14T18:30:00+08:00",
            "finding_counts": {"critical": 0, "major": 0, "minor": 0},
            "comments": "unit test only",
        }
        for gate_id in gates
    ]


def test_official_build_publishes_owner_reviewed_raw_revision(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    import taiwan_lab_mcp.importers.nhi as nhi_importer
    from taiwan_lab_mcp.adapters.nhi import NHIAdapter
    from taiwan_lab_mcp.audit import validate_audit_evidence

    payload = _official_fixture_payload()
    raw_revision_id = _write_official_raw_revision(tmp_path, payload)
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )

    built = nhi_importer.build_official_nhi_snapshot(
        tmp_path,
        raw_revision_id=raw_revision_id,
        approved_golden_cases=_approved_official_cases(payload, raw_revision_id),
        owner_reviews=_owner_reviews(),
        publisher_actor_id="unit-test-only-publisher",
    )

    build_dir = tmp_path / "curated" / "nhi_fee" / built["snapshot_id"]
    manifest = json.loads((build_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_revision_id"] == raw_revision_id
    assert manifest["review"]["required_gates"] == [
        "NHI-R1-SOURCE",
        "NHI-R1-SCHEMA",
        "PUB-R1-OWNER",
    ]
    assert manifest["review"]["completed_gates"] == manifest["review"]["required_gates"]
    assert manifest["source"]["license_name"] == "政府資料開放授權條款-第1版"
    assert manifest["official_version"]["modified_at_raw"] == "2026-09-14 07:05:47"
    evidence = manifest["audit_evidence"]
    certificate = json.loads(
        (tmp_path / Path(evidence["golden_qualification"]["data_root_relative_path"])).read_text(
            encoding="utf-8"
        )
    )
    assert certificate["official_qualification_status"] == "approved"
    assert len(certificate["approved_distinct_case_ids"]) == 10
    reviews = [
        json.loads((tmp_path / Path(item["data_root_relative_path"])).read_text(encoding="utf-8"))
        for item in evidence["reviews"]
    ]
    assert [review["gate_id"] for review in reviews] == manifest["review"]["required_gates"]
    assert {review["reviewer_id"] for review in reviews} == {"unit-test-only-reviewer"}
    assert {review["protocol_id"] for review in reviews} == {"nhi-r1-owner-review"}
    validate_audit_evidence(tmp_path, manifest)

    monkeypatch.setenv("TAIWAN_LAB_DATA_MODE", "official_snapshot")
    monkeypatch.setenv("TAIWAN_LAB_DATA_DIR", str(tmp_path))
    result = NHIAdapter().get_points("90001C")
    assert result.result_status == "ok"
    assert result.items[0].record.points == 10
    assert result.provenance.snapshot_id == built["snapshot_id"]


def test_official_build_refuses_development_install_identity(tmp_path, monkeypatch):
    import taiwan_lab_mcp.importers.nhi as nhi_importer

    payload = _official_fixture_payload()
    raw_revision_id = _write_official_raw_revision(tmp_path, payload)
    # Force the identity so the test means the same thing in an editable checkout and
    # when CI runs the suite against the installed wheel.
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("development", "d" * 64)
    )

    with pytest.raises(NHIImportError, match="APPLICATION_BUILD_IDENTITY_MISSING"):
        nhi_importer.build_official_nhi_snapshot(
            tmp_path,
            raw_revision_id=raw_revision_id,
            approved_golden_cases=_approved_official_cases(payload, raw_revision_id),
            owner_reviews=_owner_reviews(),
            publisher_actor_id="unit-test-only-publisher",
        )
    assert not (tmp_path / "curated").exists()


def _unapproved_first_case(cases, reviews):
    first = {
        **cases[0],
        "review_status": "review_pending",
        "reviewer_id": None,
        "reviewer_role": None,
        "identity_assurance": None,
        "reviewed_at": None,
    }
    return [first, *cases[1:]], reviews


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda cases, reviews: (cases[:9], reviews), "GOLDEN_CASES_INSUFFICIENT"),
        (_unapproved_first_case, "GOLDEN_CASE_NOT_APPROVED"),
        (lambda cases, reviews: (cases, reviews[:2]), "OWNER_REVIEW_GATES_INVALID"),
        (
            lambda cases, reviews: (
                cases,
                [{**reviews[0], "finding_counts": {"critical": 0, "major": 1, "minor": 0}}]
                + reviews[1:],
            ),
            "OWNER_REVIEW_REJECTED",
        ),
    ],
)
def test_official_build_requires_approved_golden_cases_and_all_owner_gates(
    tmp_path, monkeypatch, mutate, expected_code
):
    import taiwan_lab_mcp.importers.nhi as nhi_importer

    payload = _official_fixture_payload()
    raw_revision_id = _write_official_raw_revision(tmp_path, payload)
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )
    cases, reviews = mutate(_approved_official_cases(payload, raw_revision_id), _owner_reviews())

    with pytest.raises(NHIImportError, match=expected_code):
        nhi_importer.build_official_nhi_snapshot(
            tmp_path,
            raw_revision_id=raw_revision_id,
            approved_golden_cases=cases,
            owner_reviews=reviews,
            publisher_actor_id="unit-test-only-publisher",
        )
    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "manifests").exists()


def test_official_build_rejects_tampered_raw_revision(tmp_path, monkeypatch):
    import taiwan_lab_mcp.importers.nhi as nhi_importer

    payload = _official_fixture_payload()
    raw_revision_id = _write_official_raw_revision(tmp_path, payload)
    monkeypatch.setattr(
        nhi_importer, "_application_build_identity", lambda: ("distribution", "d" * 64)
    )
    raw_path = tmp_path / "raw" / "nhi_fee" / raw_revision_id / "artifacts" / "source.csv"
    raw_path.write_bytes(payload + b"tampered")

    with pytest.raises(NHIImportError, match="RAW_REVISION_INTEGRITY"):
        nhi_importer.build_official_nhi_snapshot(
            tmp_path,
            raw_revision_id=raw_revision_id,
            approved_golden_cases=_approved_official_cases(payload, raw_revision_id),
            owner_reviews=_owner_reviews(),
            publisher_actor_id="unit-test-only-publisher",
        )
    assert not (tmp_path / "curated").exists()
