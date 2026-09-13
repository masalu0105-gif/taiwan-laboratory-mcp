import json
from datetime import datetime, timezone

import pytest


class FakeHeaders(dict):
    def get_content_type(self):
        return self.get("Content-Type", "").split(";", 1)[0].strip().lower()


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = FakeHeaders(headers or {})
        self.offset = 0
        self.closed = False

    def getcode(self):
        return self.status

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class QueueOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        return self.responses.pop(0)


def test_fetch_rejects_https_downgrade_before_open():
    from taiwan_lab_mcp.fetch import FetchError, fetch_https_bytes

    opener = QueueOpener()
    with pytest.raises(FetchError, match="FETCH_HTTPS_DOWNGRADE"):
        fetch_https_bytes(
            "http://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            opener=opener,
        )
    assert opener.urls == []


def test_fetch_rejects_redirect_to_unallowed_host():
    from taiwan_lab_mcp.fetch import FetchError, fetch_https_bytes

    opener = QueueOpener(FakeResponse(302, headers={"Location": "https://evil.example/data.csv"}))
    with pytest.raises(FetchError, match="FETCH_HOST_NOT_ALLOWED"):
        fetch_https_bytes(
            "https://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            opener=opener,
        )
    assert opener.urls == ["https://info.nhi.gov.tw/data.csv"]


def test_fetch_enforces_declared_and_streamed_size_limits():
    from taiwan_lab_mcp.fetch import FetchError, fetch_https_bytes

    declared = QueueOpener(FakeResponse(200, body=b"12345", headers={"Content-Length": "5"}))
    with pytest.raises(FetchError, match="FETCH_SIZE_LIMIT"):
        fetch_https_bytes(
            "https://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            max_bytes=4,
            opener=declared,
        )

    streamed = QueueOpener(FakeResponse(200, body=b"12345"))
    with pytest.raises(FetchError, match="FETCH_SIZE_LIMIT"):
        fetch_https_bytes(
            "https://info.nhi.gov.tw/data.csv",
            allowed_hosts={"info.nhi.gov.tw"},
            max_bytes=4,
            opener=streamed,
        )


def test_fetch_returns_hash_headers_and_redirect_trace():
    from taiwan_lab_mcp.canonical import sha256_bytes
    from taiwan_lab_mcp.fetch import fetch_https_bytes

    opener = QueueOpener(
        FakeResponse(302, headers={"Location": "https://info.nhi.gov.tw/data-v2.csv"}),
        FakeResponse(
            200,
            body=b"csv-bytes",
            headers={"Content-Type": "application/csv", "Content-Length": "9"},
        ),
    )
    result = fetch_https_bytes(
        "https://info.nhi.gov.tw/data.csv",
        allowed_hosts={"info.nhi.gov.tw"},
        allowed_content_types={"application/csv"},
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
        opener=opener,
    )
    assert result.payload == b"csv-bytes"
    assert result.sha256 == sha256_bytes(b"csv-bytes")
    assert result.final_url == "https://info.nhi.gov.tw/data-v2.csv"
    assert result.redirect_trace == (
        "https://info.nhi.gov.tw/data.csv",
        "https://info.nhi.gov.tw/data-v2.csv",
    )
    assert result.fetched_at == "2026-09-13T01:00:00Z"
    assert result.headers["content-type"] == "application/csv"


def test_nhi_discovery_requires_exact_metadata_and_selects_one_csv():
    from taiwan_lab_mcp.nhi_source import NHI_SOURCE_IDENTIFIER, discover_nhi_resource

    payload = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": "A21030000I",
                "identifier": NHI_SOURCE_IDENTIFIER,
                "license": "政府資料開放授權條款－第 1 版",
                "modifiedDate": "2026-09-12 07:06:04",
                "distribution": [
                    {
                        "resourceFormat": "JSON",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/ignored.json",
                    },
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    },
                ],
            },
        },
        ensure_ascii=False,
    ).encode()

    discovery = discover_nhi_resource(payload, expected_publisher_oid="A21030000I")

    assert discovery["identifier"] == NHI_SOURCE_IDENTIFIER
    assert discovery["resource_url"] == "https://info.nhi.gov.tw/data.csv"
    assert discovery["official_modified_at_raw"] == "2026-09-12 07:06:04"


def test_nhi_source_fetches_metadata_then_allowed_csv_without_publishing():
    from taiwan_lab_mcp.nhi_source import fetch_nhi_source

    metadata = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": "A21030000I",
                "identifier": "A21030000I-D20021",
                "license": "政府資料開放授權條款－第 1 版",
                "modifiedDate": "2026-09-12 07:06:04",
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    }
                ],
            },
        },
        ensure_ascii=False,
    ).encode()
    opener = QueueOpener(
        FakeResponse(200, metadata, {"Content-Type": "application/json"}),
        FakeResponse(200, b"header\nrow\n", {"Content-Type": "application/csv"}),
    )

    fetched = fetch_nhi_source(
        expected_publisher_oid="A21030000I",
        opener=opener,
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )

    assert fetched["discovery"]["resource_url"] == "https://info.nhi.gov.tw/data.csv"
    assert fetched["artifact"].payload == b"header\nrow\n"
    assert opener.urls == [
        "https://data.gov.tw/api/v2/rest/dataset/174450",
        "https://info.nhi.gov.tw/data.csv",
    ]


def test_upstream_nhi_sync_records_transport_evidence_and_stays_candidate_only(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS
    from taiwan_lab_mcp.sync import run_nhi_upstream_sync

    metadata = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": "A21030000I",
                "identifier": "A21030000I-D20021",
                "license": "政府資料開放授權條款－第 1 版",
                "modifiedDate": "2026-09-12 07:06:04",
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    }
                ],
            },
        },
        ensure_ascii=False,
    ).encode()
    csv_payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    opener = QueueOpener(
        FakeResponse(200, metadata, {"Content-Type": "application/json"}),
        FakeResponse(200, csv_payload, {"Content-Type": "application/csv"}),
    )

    report = run_nhi_upstream_sync(
        tmp_path,
        expected_publisher_oid="A21030000I",
        opener=opener,
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "passed"
    assert report["stage"] == "validate"
    assert report["candidate_status"] == "review_pending"
    assert report["discovery"]["identifier"] == "A21030000I-D20021"
    assert report["fetch"]["sha256"]
    assert not (tmp_path / "manifests" / "current" / "nhi_fee.json").exists()


def test_upstream_nhi_raw_revision_binds_nonvolatile_discovery_identity(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS
    from taiwan_lab_mcp.sync import run_nhi_upstream_sync

    def metadata(modified_at):
        return json.dumps(
            {
                "success": True,
                "result": {
                    "publisherOID": "A21030000I",
                    "identifier": "A21030000I-D20021",
                    "license": "政府資料開放授權條款－第 1 版",
                    "modifiedDate": modified_at,
                    "distribution": [
                        {
                            "resourceFormat": "CSV",
                            "resourceCharacterEncoding": "UTF-8",
                            "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ).encode()

    csv_payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()

    first = run_nhi_upstream_sync(
        tmp_path / "first",
        expected_publisher_oid="A21030000I",
        opener=QueueOpener(
            FakeResponse(
                200, metadata("2026-09-12 07:06:04"), {"Content-Type": "application/json"}
            ),
            FakeResponse(200, csv_payload, {"Content-Type": "application/csv"}),
        ),
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )
    second = run_nhi_upstream_sync(
        tmp_path / "second",
        expected_publisher_oid="A21030000I",
        opener=QueueOpener(
            FakeResponse(
                200, metadata("2026-09-13 07:06:04"), {"Content-Type": "application/json"}
            ),
            FakeResponse(200, csv_payload, {"Content-Type": "application/csv"}),
        ),
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )

    assert first["status"] == second["status"] == "passed"
    assert first["raw_revision_id"] != second["raw_revision_id"]
    assert first["discovery_metadata_sha256"] != second["discovery_metadata_sha256"]


def test_upstream_nhi_discovery_failure_keeps_partial_metadata_evidence(tmp_path):
    from taiwan_lab_mcp.sync import run_nhi_upstream_sync

    metadata = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": "unexpected-publisher",
                "identifier": "A21030000I-D20021",
                "license": "政府資料開放授權條款－第 1 版",
                "distribution": [],
            },
        },
        ensure_ascii=False,
    ).encode()
    report = run_nhi_upstream_sync(
        tmp_path,
        expected_publisher_oid="A21030000I",
        opener=QueueOpener(FakeResponse(200, metadata, {"Content-Type": "application/json"})),
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "failed"
    assert report["stage"] == "discover"
    assert report["error_code"] == "DISCOVERY_PUBLISHER_MISMATCH"
    assert report["discovery_metadata_sha256"] is None
    assert report["discovery"]["metadata_sha256"]
    report_path = tmp_path / report["report_data_root_relative_path"]
    assert report_path.is_file()


def test_nhi_raw_revision_excludes_fetch_volatile_discovery_fields(tmp_path):
    from taiwan_lab_mcp.importers.nhi import NHI_COLUMNS
    from taiwan_lab_mcp.sync import run_nhi_sync

    payload = (
        "\ufeff" + ",".join(NHI_COLUMNS) + "\n" + "09006C,0,20120101,29101231,HbA1c,醣化血紅素,\n"
    ).encode()
    discovery = {
        "landing_url": "https://DATA.GOV.TW/dataset/174450#fragment",
        "publisher_oid": "A21030000I",
        "dataset_id": "174450",
        "license_name": "政府資料開放授權條款－第 1 版",
        "license_url": "https://data.gov.tw/license#license",
        "official_version_label_raw": None,
        "official_modified_at_raw": "2026-09-12 07:06:04",
        "official_modified_at_precision": "second",
        "official_modified_timezone_known": False,
        "metadata_final_url": "https://data.gov.tw/api/v2/rest/dataset/174450?run=one",
        "metadata_sha256": "one",
        "metadata_fetched_at": "2026-09-13T01:00:00Z",
    }
    changed_volatile = dict(discovery)
    changed_volatile.update(
        {
            "metadata_final_url": "https://data.gov.tw/api/v2/rest/dataset/174450?run=two",
            "metadata_sha256": "two",
            "metadata_fetched_at": "2026-09-13T02:00:00Z",
        }
    )

    first = run_nhi_sync(payload, tmp_path / "first", discovery=discovery)
    second = run_nhi_sync(payload, tmp_path / "second", discovery=changed_volatile)

    assert first["raw_revision_id"] == second["raw_revision_id"]
    assert first["discovery_metadata_sha256"] == second["discovery_metadata_sha256"]


def test_nhi_raw_revision_rejects_malformed_artifact_hash():
    from taiwan_lab_mcp.nhi_source import nhi_raw_revision_id

    with pytest.raises(ValueError, match="payload hash is invalid"):
        nhi_raw_revision_id(
            payload_sha256="not-a-sha256",
            payload_size=1,
            discovery=None,
        )


def test_upstream_nhi_fetch_failure_preserves_verified_discovery_evidence(tmp_path):
    from taiwan_lab_mcp.sync import run_nhi_upstream_sync

    metadata = json.dumps(
        {
            "success": True,
            "result": {
                "publisherOID": "A21030000I",
                "identifier": "A21030000I-D20021",
                "license": "政府資料開放授權條款－第 1 版",
                "distribution": [
                    {
                        "resourceFormat": "CSV",
                        "resourceCharacterEncoding": "UTF-8",
                        "resourceDownloadUrl": "https://info.nhi.gov.tw/data.csv",
                    }
                ],
            },
        },
        ensure_ascii=False,
    ).encode()
    opener = QueueOpener(
        FakeResponse(200, metadata, {"Content-Type": "application/json"}),
        FakeResponse(503, b"upstream unavailable", {"Content-Type": "text/plain"}),
    )

    report = run_nhi_upstream_sync(
        tmp_path,
        expected_publisher_oid="A21030000I",
        opener=opener,
        clock=lambda: datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "failed"
    assert report["stage"] == "fetch"
    assert report["discovery"]["identifier"] == "A21030000I-D20021"
    assert report["discovery"]["metadata_sha256"]
    assert "fetch" not in report
    assert not (tmp_path / "manifests" / "current" / "nhi_fee.json").exists()


def test_sync_attempt_ids_are_unique_for_same_second_retry(tmp_path):
    from taiwan_lab_mcp.sync import run_nhi_sync

    def clock():
        return datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc)

    first = run_nhi_sync(None, tmp_path, clock=clock)
    second = run_nhi_sync(None, tmp_path, clock=clock)

    assert first["attempt_id"] != second["attempt_id"]
    assert len(list((tmp_path / "staged" / "nhi_fee").iterdir())) == 2


def test_cli_upstream_requires_explicit_publisher_oid(tmp_path, monkeypatch, capsys):
    import taiwan_lab_mcp.data_cli as data_cli

    calls = []

    def fake_upstream(data_root, **kwargs):
        calls.append((data_root, kwargs))
        return {"status": "passed", "stage": "validate"}

    monkeypatch.setattr("taiwan_lab_mcp.sync.run_nhi_upstream_sync", fake_upstream)
    exit_code = data_cli.main(
        [
            "sync",
            "nhi_fee",
            "--publisher-oid",
            "A21030000I",
            "--metadata-url",
            "https://data.gov.tw/api/v2/rest/dataset/174450",
            "--data-dir",
            str(tmp_path),
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls == [
        (
            tmp_path,
            {
                "expected_publisher_oid": "A21030000I",
                "metadata_url": "https://data.gov.tw/api/v2/rest/dataset/174450",
            },
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"status": "passed", "stage": "validate"}
