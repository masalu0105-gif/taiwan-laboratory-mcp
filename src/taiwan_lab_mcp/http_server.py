"""Serve the same read-only registry over a URL instead of a local subprocess.

The local way in (`taiwan-lab-mcp`) runs on the asking person's own computer and never leaves it.
This one answers over HTTP so one installation can serve many people, which is what Claude's
custom connectors need: they reach the server from Anthropic's cloud, not from the reader's
machine. Everything below the transport is unchanged — the same `server.mcp`, the same closed
registry of operations, the same read-only snapshot.

Two rules are enforced before the server will listen beyond this computer, because getting either
one wrong is silent rather than noisy:

  * a Host allowlist must be given, so a name that merely resolves to this machine cannot drive it;
  * the data mode must be `official_snapshot`, so synthetic fixtures are never served to other
    people even though every one of them is labelled `sample_only`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost only matters at runtime
    from starlette.applications import Starlette

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_PATH = "/mcp"
# Binding to one of these serves only programs already running on this computer.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class HttpConfigurationError(Exception):
    """The settings would start a server that is unsafe or cannot work."""


@dataclass(frozen=True)
class HttpSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    path: str = DEFAULT_PATH
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    mode: str = "sample"

    @classmethod
    def from_env(cls) -> HttpSettings:
        raw_port = os.environ.get("TAIWAN_LAB_HTTP_PORT", str(DEFAULT_PORT)).strip()
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise HttpConfigurationError(
                f"TAIWAN_LAB_HTTP_PORT must be a whole number, not {raw_port!r}"
            ) from exc
        if not 1 <= port <= 65535:
            raise HttpConfigurationError(f"TAIWAN_LAB_HTTP_PORT must be 1-65535, not {port}")

        path = os.environ.get("TAIWAN_LAB_HTTP_PATH", DEFAULT_PATH).strip() or DEFAULT_PATH
        if not path.startswith("/"):
            raise HttpConfigurationError(f"TAIWAN_LAB_HTTP_PATH must start with '/', not {path!r}")

        listed = os.environ.get("TAIWAN_LAB_HTTP_ALLOWED_HOSTS", "")
        allowed = tuple(name.strip() for name in listed.split(",") if name.strip())
        return cls(
            host=os.environ.get("TAIWAN_LAB_HTTP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=port,
            path=path,
            allowed_hosts=allowed,
            mode=os.environ.get("TAIWAN_LAB_DATA_MODE", "sample").strip().lower() or "sample",
        )

    @property
    def serves_other_computers(self) -> bool:
        return self.host not in LOOPBACK_HOSTS

    def check(self) -> None:
        """Raise when the settings would put an unsafe server on the network."""

        if not self.serves_other_computers:
            return
        if not self.allowed_hosts:
            raise HttpConfigurationError(
                f"host {self.host} answers other computers, so TAIWAN_LAB_HTTP_ALLOWED_HOSTS must "
                "list the name people will use (for example lab.example.com). Without it any "
                "name that resolves to this machine can drive the server."
            )
        if self.mode != "official_snapshot":
            raise HttpConfigurationError(
                f"host {self.host} answers other computers, so TAIWAN_LAB_DATA_MODE must be "
                f"official_snapshot, not {self.mode!r}. The sample fixtures are synthetic and are "
                "for trying the tools out on your own machine."
            )


def _transport_security(settings: HttpSettings):
    from mcp.server.transport_security import TransportSecuritySettings

    if not settings.allowed_hosts:
        # Loopback only: nothing outside this computer can reach the socket in the first place.
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=[f"https://{name}" for name in settings.allowed_hosts],
    )


def build_http_app(settings: HttpSettings | None = None) -> Starlette:
    """The web application that serves the registry. Callers that listen must `check()` first."""

    from .server import mcp

    settings = settings or HttpSettings()
    return mcp.streamable_http_app(
        streamable_http_path=settings.path,
        # Every operation is a read against a snapshot, so nothing needs to be remembered between
        # requests. Being stateless also means a restart does not drop anyone's session.
        stateless_http=True,
        transport_security=_transport_security(settings),
        host=settings.host,
    )


def main() -> int:
    import uvicorn

    try:
        settings = HttpSettings.from_env()
        settings.check()
    except HttpConfigurationError as exc:
        print(f"taiwan-lab-mcp-http: {exc}", flush=True)
        return 2

    # Say both things separately: which socket is open, and which names are accepted. Behind a
    # tunnel the socket is loopback while the requests still arrive addressed to a public name.
    reach = "只聽這台電腦" if not settings.serves_other_computers else "直接聽對外位址"
    names = (
        "、".join(settings.allowed_hosts) if settings.allowed_hosts else "不限（沒有設定網域名稱）"
    )
    print(
        f"taiwan-lab-mcp-http: {settings.mode} 模式，{reach}，接受的網域名稱：{names}", flush=True
    )
    print(
        f"taiwan-lab-mcp-http: listening on http://{settings.host}:{settings.port}{settings.path}",
        flush=True,
    )
    uvicorn.run(build_http_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
