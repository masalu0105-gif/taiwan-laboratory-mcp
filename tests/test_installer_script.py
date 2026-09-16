"""The Windows installer script must stay readable to Windows PowerShell and match the CLI."""

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "Install-TaiwanLabMcp.ps1"
# The four names install-snapshot accepts; see data_cli.bundle_sources.
BUNDLE_SOURCES = {"nhi_fee", "tfda_devices", "cdc_authorized_labs", "cdc_specimen_manual"}


def test_the_script_keeps_its_byte_order_mark() -> None:
    """Windows PowerShell 5.1 reads a .ps1 as the system code page unless it starts with a BOM.

    On a Traditional Chinese machine that means cp950, which turns every Chinese message in the
    script into a parse error before a single line runs. Saving it with LF and no BOM, the way
    everything else here is saved, silently breaks it.
    """

    assert SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_script_offers_exactly_the_datasets_the_cli_installs() -> None:
    from taiwan_lab_mcp import data_cli

    source = Path(data_cli.__file__).read_text(encoding="utf-8")
    listed = re.search(r"bundle_sources = \[(.*?)\]", source, re.DOTALL)
    assert listed is not None
    assert set(re.findall(r'"([a-z_]+)"', listed.group(1))) == BUNDLE_SOURCES

    script = SCRIPT.read_text(encoding="utf-8-sig")
    names = re.search(r"\$DatasetNames = @\{(.*?)\n\}", script, re.DOTALL)
    assert names is not None
    assert set(re.findall(r"'([a-z_]+)' *=", names.group(1))) == BUNDLE_SOURCES
