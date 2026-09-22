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
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from ipaddress import ip_address
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cost only matters at runtime
    from starlette.applications import Starlette

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
DEFAULT_PATH = "/mcp"
DEFAULT_RATE_LIMIT_PER_MINUTE = 240
DEFAULT_MAX_REQUEST_BYTES = 256 * 1024
MAX_TRACKED_CLIENTS = 10_000
# Binding to one of these serves only programs already running on this computer.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class HttpConfigurationError(Exception):
    """The settings would start a server that is unsafe or cannot work."""


@dataclass(frozen=True)
class HttpSettings:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    path: str = DEFAULT_PATH
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    mode: str = "sample"
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    bearer_token_sha256: str | None = field(default=None, repr=False)

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
        rate_limit = _positive_int_from_env(
            "TAIWAN_LAB_HTTP_RATE_LIMIT_PER_MINUTE", DEFAULT_RATE_LIMIT_PER_MINUTE
        )
        max_request_bytes = _positive_int_from_env(
            "TAIWAN_LAB_HTTP_MAX_REQUEST_BYTES", DEFAULT_MAX_REQUEST_BYTES
        )
        token_sha256 = os.environ.get("TAIWAN_LAB_HTTP_BEARER_TOKEN_SHA256", "").strip().lower()
        if token_sha256 and not _SHA256_RE.fullmatch(token_sha256):
            raise HttpConfigurationError(
                "TAIWAN_LAB_HTTP_BEARER_TOKEN_SHA256 must be 64 lowercase hexadecimal characters"
            )
        return cls(
            host=os.environ.get("TAIWAN_LAB_HTTP_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            port=port,
            path=path,
            allowed_hosts=allowed,
            mode=os.environ.get("TAIWAN_LAB_DATA_MODE", "sample").strip().lower() or "sample",
            rate_limit_per_minute=rate_limit,
            max_request_bytes=max_request_bytes,
            bearer_token_sha256=token_sha256 or None,
        )

    @property
    def serves_other_computers(self) -> bool:
        return self.host not in LOOPBACK_HOSTS

    def check(self) -> None:
        """Raise when the settings would put an unsafe server on the network."""

        if self.rate_limit_per_minute <= 0:
            raise HttpConfigurationError("rate_limit_per_minute must be positive")
        if self.max_request_bytes <= 0:
            raise HttpConfigurationError("max_request_bytes must be positive")
        if self.bearer_token_sha256 and not _SHA256_RE.fullmatch(self.bearer_token_sha256):
            raise HttpConfigurationError("bearer_token_sha256 must be a lowercase SHA-256 digest")
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


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise HttpConfigurationError(
            f"{name} must be a positive whole number, not {raw!r}"
        ) from exc
    if value <= 0:
        raise HttpConfigurationError(f"{name} must be a positive whole number, not {value}")
    return value


class PublicHttpGuard:
    """Bound anonymous HTTP traffic without retaining request bodies or query text."""

    def __init__(self, app, settings: HttpSettings, *, clock=time.monotonic):
        self.app = app
        self.settings = settings
        self.clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != self.settings.path:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", ())
        }
        client_key = self._client_key(scope, headers)
        now = self.clock()
        if client_key not in self._requests and len(self._requests) >= MAX_TRACKED_CLIENTS:
            # The proxy supplies the client address, but still cap bookkeeping so a flood of
            # one-off addresses cannot make this small public service retain memory forever.
            self._requests.pop(next(iter(self._requests)))
        recent = self._requests[client_key]
        while recent and recent[0] <= now - 60:
            recent.popleft()
        if len(recent) >= self.settings.rate_limit_per_minute:
            await self._reject(send, 429, "rate_limit_exceeded", retry_after="60")
            return
        recent.append(now)

        if self.settings.bearer_token_sha256 is not None:
            authorization = headers.get("authorization", "")
            supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
            supplied_sha256 = sha256(supplied.encode("utf-8")).hexdigest()
            if not supplied or not compare_digest(
                supplied_sha256, self.settings.bearer_token_sha256
            ):
                await self._reject(send, 401, "authentication_required")
                return

        content_length = headers.get("content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                await self._reject(send, 400, "invalid_content_length")
                return
            if declared_length < 0:
                await self._reject(send, 400, "invalid_content_length")
                return
            if declared_length > self.settings.max_request_bytes:
                await self._reject(send, 413, "request_too_large")
                return

        body_messages = []
        body_bytes = 0
        more_body = True
        while more_body:
            message = await receive()
            body_bytes += len(message.get("body", b""))
            if body_bytes > self.settings.max_request_bytes:
                await self._reject(send, 413, "request_too_large")
                return
            body_messages.append(message)
            more_body = bool(message.get("more_body", False))

        async def replay_receive():
            if body_messages:
                return body_messages.pop(0)
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                secured_names = {b"cache-control", b"referrer-policy", b"x-content-type-options"}
                response_headers = [
                    pair
                    for pair in message.get("headers", ())
                    if pair[0].lower() not in secured_names
                ]
                response_headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                message = {**message, "headers": response_headers}
            await send(message)

        await self.app(scope, replay_receive, secure_send)

    def _client_key(self, scope, headers: dict[str, str]) -> str:
        client = scope.get("client") or ("unknown", 0)
        direct_host = str(client[0])
        if direct_host in LOOPBACK_HOSTS:
            # A trusted loopback reverse proxy appends the real peer at the right-hand side.
            # Ignore invalid values instead of letting arbitrary header text create client keys.
            forwarded = headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip()
            if forwarded:
                try:
                    return ip_address(forwarded).compressed
                except ValueError:
                    pass
        return direct_host

    @staticmethod
    async def _reject(send, status: int, code: str, *, retry_after: str | None = None) -> None:
        body = ('{"error":"' + code + '"}').encode("ascii")
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
        ]
        if retry_after is not None:
            headers.append((b"retry-after", retry_after.encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


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
    app = mcp.streamable_http_app(
        streamable_http_path=settings.path,
        # Every operation is a read against a snapshot, so nothing needs to be remembered between
        # requests. Being stateless also means a restart does not drop anyone's session.
        stateless_http=True,
        transport_security=_transport_security(settings),
        host=settings.host,
    )
    app.add_middleware(PublicHttpGuard, settings=settings)
    return app


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
    uvicorn.run(
        build_http_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
