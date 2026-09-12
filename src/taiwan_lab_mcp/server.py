from __future__ import annotations

from typing import Any

from mcp.server import MCPServer

from .adapters.base import SAMPLE_WARNING, data_mode
from .adapters.cdc import CDCAdapter
from .adapters.eqa import eqa_status as _eqa_status
from .adapters.nhi import NHIAdapter
from .adapters.standards import standards_status as _standards_status
from .adapters.tfda import TFDAAdapter
from .models import ToolResult
from .sources import OFFICIAL_SOURCES

mcp = MCPServer("Taiwan Laboratory MCP")
cdc = CDCAdapter()
tfda = TFDAAdapter()
nhi = NHIAdapter()


@mcp.tool()
def search_disease(query: str) -> ToolResult:
    """Search Taiwan CDC laboratory-oriented disease/sample records."""
    return cdc.search_disease(query)


@mcp.tool()
def get_specimen_requirement(disease: str) -> ToolResult:
    """Get specimen, collection, container, transport and submission guidance provenance for a disease."""
    return cdc.get_specimen_requirement(disease)


@mcp.tool()
def get_collection_method(disease: str) -> ToolResult:
    """Get collection-method information for a disease from the CDC specimen source."""
    return cdc.get_specimen_requirement(disease)


@mcp.tool()
def get_container(disease: str) -> ToolResult:
    """Get specimen-container information for a disease."""
    return cdc.get_specimen_requirement(disease)


@mcp.tool()
def get_transport_requirement(disease: str) -> ToolResult:
    """Get specimen storage and transport information for a disease."""
    return cdc.get_specimen_requirement(disease)


@mcp.tool()
def get_submission_rule(disease: str) -> ToolResult:
    """Get Taiwan CDC submission-rule information for a disease."""
    return cdc.get_specimen_requirement(disease)


@mcp.tool()
def find_authorized_lab(query: str, city: str | None = None) -> ToolResult:
    """Find Taiwan CDC recognized infectious-disease laboratories by disease/scope/name and optional city."""
    return cdc.find_authorized_lab(query, city)


@mcp.tool()
def get_lab_scope(query: str) -> ToolResult:
    """Look up recognized laboratory scopes."""
    return cdc.find_authorized_lab(query)


@mcp.tool()
def search_ivd(query: str, manufacturer: str | None = None) -> ToolResult:
    """Search Taiwan TFDA medical-device/IVD licence data."""
    return tfda.search_ivd(query, manufacturer)


@mcp.tool()
def get_license(license_no: str) -> ToolResult:
    """Get a TFDA medical-device licence record by licence number."""
    return tfda.get_license(license_no)


@mcp.tool()
def find_manufacturer(name: str) -> ToolResult:
    """Find TFDA device records for a manufacturer."""
    return tfda.find_manufacturer(name)


@mcp.tool()
def compare_products(query: str, limit: int = 10) -> ToolResult:
    """Return comparable TFDA device records matching a laboratory product/analyte query."""
    return tfda.compare_products(query, limit)


@mcp.tool()
def search_lab_code(query: str) -> ToolResult:
    """Search Taiwan NHI medical-service payment codes; use laboratory keywords or a code."""
    return nhi.search_lab_code(query)


@mcp.tool()
def get_points(code: str) -> ToolResult:
    """Get NHI payment points for a code."""
    return nhi.get_points(code)


@mcp.tool()
def get_payment_rule(query: str) -> ToolResult:
    """Search NHI payment records and notes relevant to a test/code."""
    return nhi.get_payment_rule(query)


@mcp.tool()
def standards_status() -> dict[str, Any]:
    """Show reserved LOINC/FHIR/SNOMED adapter status without implementing Taiwan mappings."""
    return _standards_status()


@mcp.tool()
def eqa_status() -> dict[str, Any]:
    """Report the unconfigured EQA/CAP adapter; does not retrieve any catalog."""
    return _eqa_status()


@mcp.tool()
def get_data_status() -> dict[str, Any]:
    """Call first: bundled records are synthetic samples; official sync is unavailable."""
    return {
        "data_mode": data_mode(),
        "sample_only": True,
        "official_data_loaded": False,
        "official_sources": OFFICIAL_SOURCES,
        "note": SAMPLE_WARNING,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
