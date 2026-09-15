import os
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

REQUIRED_FILES = {
    "taiwan_lab_mcp/contracts/acceptance-contract-v1.json",
    "taiwan_lab_mcp/contracts/public-contract-v1.json",
    "taiwan_lab_mcp/fetch.py",
    "taiwan_lab_mcp/nhi_source.py",
    "taiwan_lab_mcp/publish.py",
    "taiwan_lab_mcp/sync.py",
    "taiwan_lab_mcp/importers/nhi.py",
    "taiwan_lab_mcp/qualifier_specs/pdfium-layout-v1.json",
    "taiwan_lab_mcp/review_protocols/nhi-r1-owner-review/1.json",
    "taiwan_lab_mcp/review_protocols/nhi-r1-owner-review/2.json",
    "taiwan_lab_mcp/review_protocols/cdc-labs-r1-ai-review/1.json",
    "taiwan_lab_mcp/review_protocols/cdc-labs-r1-auto-review/1.json",
    "taiwan_lab_mcp/review_protocols/cdc-manual-r1-ai-review/1.json",
    "taiwan_lab_mcp/review_protocols/nhi-r1-auto-review/1.json",
    "taiwan_lab_mcp/review_protocols/nhi-r1-auto-review/2.json",
    "taiwan_lab_mcp/review_protocols/tfda-r1-ai-review/1.json",
    "taiwan_lab_mcp/review_protocols/tfda-r1-ai-review/2.json",
    "taiwan_lab_mcp/review_protocols/tfda-r1-auto-review/1.json",
    "taiwan_lab_mcp/review_protocols/tfda-r1-auto-review/2.json",
    "taiwan_lab_mcp/rules/nhi_lab_scope/v1.json",
    "taiwan_lab_mcp/rules/nhi_lab_scope/v2.json",
    "taiwan_lab_mcp/rules/tfda_ivd/v1.json",
    "taiwan_lab_mcp/schemas/nhi_fee/nhi-7-v1.json",
}


def _archive_files(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    with tarfile.open(path, "r:gz") as archive:
        names = [member.name for member in archive.getmembers() if member.isfile()]
    normalized = []
    for name in names:
        relative = name.split("/", 1)[1] if "/" in name else name
        normalized.append(relative[4:] if relative.startswith("src/") else relative)
    return normalized


def _denied(path: str) -> bool:
    lowered = path.lower()
    name = PurePosixPath(lowered).name
    return (
        any(fragment in lowered for fragment in ("data/raw/", "data/staged/", "data/quarantine/"))
        or "manifests/current/" in lowered
        or lowered.endswith((".sqlite3", ".sqlite", ".db", ".key", ".pem"))
        or name in {".env", ".env.local"}
        or any(token in name for token in ("secret", "token", "credential"))
        or "__pycache__/" in lowered
        or lowered.endswith(".pyc")
        or path.startswith(("/", "\\"))
        or (len(path) >= 2 and path[1] == ":")
    )


@pytest.mark.parametrize("suffix", [".whl", ".tar.gz"])
def test_built_archive_contains_only_release_safe_files(tmp_path, suffix):
    artifact_dir = Path(os.environ.get("TAIWAN_LAB_ARTIFACT_DIR", "dist"))
    matches = sorted(artifact_dir.glob(f"*{suffix}"))
    if not matches:
        pytest.skip(f"no {suffix} artifact in {artifact_dir}")
    assert len(matches) == 1
    files = _archive_files(matches[0])
    assert REQUIRED_FILES <= set(files)
    assert not [path for path in files if _denied(path)]
    assert not any(path.lower().endswith("uv.lock") for path in files)
