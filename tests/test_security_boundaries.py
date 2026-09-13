import json
import sqlite3
from hashlib import sha256

import pytest


class _FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.offset = 0

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        pass


class _QueueOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return self.responses.pop(0)


def test_sdd_sec_01_trust_boundary_matrix(tmp_path):
    from taiwan_lab_mcp.acceptance import AcceptanceReportError, write_acceptance_report
    from taiwan_lab_mcp.fetch import FetchError, fetch_https_bytes
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS, build_nhi_snapshot

    downgrade_opener = _QueueOpener()
    with pytest.raises(FetchError, match="FETCH_HTTPS_DOWNGRADE"):
        fetch_https_bytes(
            "http://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            opener=downgrade_opener,
        )
    assert downgrade_opener.urls == []

    redirect_opener = _QueueOpener(
        _FakeResponse(302, headers={"Location": "https://evil.example/data.csv"})
    )
    with pytest.raises(FetchError, match="FETCH_HOST_NOT_ALLOWED"):
        fetch_https_bytes(
            "https://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            opener=redirect_opener,
        )
    assert redirect_opener.urls == ["https://info.nhi.gov.tw/data.csv"]

    oversized_opener = _QueueOpener(_FakeResponse(200, body=b"12345"))
    with pytest.raises(FetchError, match="FETCH_SIZE_LIMIT"):
        fetch_https_bytes(
            "https://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            max_bytes=4,
            opener=oversized_opener,
        )

    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"evidence")
    report = {
        "acceptance_report_schema_version": 1,
        "release_id": "p1.1-local",
        "requirement_id": "SDD-API-01",
        "node_id": "tests/test_mcp_stdio.py::test_sdd_api_01_public_contract_resource_matches_discovery",
        "node_status": "collected",
        "collected_node_count": 1,
        "exit_code": 0,
        "test_output_sha256": "a" * 64,
        "stdout_sha256": "b" * 64,
        "stderr_sha256": "c" * 64,
        "application_build_inventory_sha256": "d" * 64,
        "golden_qualification_sha256": "e" * 64,
        "source_review_evidence_sha256": "f" * 64,
        "evidence_refs": [{"path": "../evidence.json", "sha256": sha256(b"evidence").hexdigest()}],
        "gate_disposition": "not_closed",
    }
    with pytest.raises(AcceptanceReportError, match="INVALID_EVIDENCE_PATH"):
        write_acceptance_report(tmp_path, report)

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    build_nhi_snapshot(payload, tmp_path)
    descriptor = json.loads(
        (tmp_path / "manifests" / "current" / "nhi_fee.json").read_text(encoding="utf-8")
    )
    db_path = tmp_path / descriptor["manifest_data_root_relative_path"].replace(
        "manifest.json", "data.sqlite3"
    )
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("UPDATE nhi_fee SET points=1 WHERE code_normalized='09006C'")
    finally:
        connection.close()

    from taiwan_lab_mcp.acceptance import _node_registry

    assert (
        _node_registry()[
            (
                "SDD-SEC-01",
                "tests/test_security_boundaries.py::test_sdd_sec_01_trust_boundary_matrix",
            )
        ]
        == "executable"
    )
