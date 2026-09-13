from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Collection
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .canonical import sha256_bytes

FetchClock = Callable[[], datetime]


class FetchError(ValueError):
    def __init__(
        self,
        code: str,
        stage: str | None = None,
        *,
        discovery: dict | None = None,
        metadata: FetchedArtifact | None = None,
    ) -> None:
        self.code = code
        self.stage = stage
        self.discovery = discovery
        self.metadata = metadata
        super().__init__(code)


@dataclass(frozen=True)
class FetchedArtifact:
    requested_url: str
    final_url: str
    status_code: int
    payload: bytes
    sha256: str
    fetched_at: str
    headers: dict[str, str]
    redirect_trace: tuple[str, ...]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _validate_https_url(url: str, allowed_hosts: Collection[str]) -> str:
    if not isinstance(url, str) or not url:
        raise FetchError("FETCH_INVALID_URL")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise FetchError("FETCH_INVALID_URL") from exc
    if parsed.scheme.lower() != "https":
        raise FetchError("FETCH_HTTPS_DOWNGRADE")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise FetchError("FETCH_INVALID_URL")
    if port not in (None, 443):
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    host = parsed.hostname.rstrip(".").lower()
    allowed = {str(value).rstrip(".").lower() for value in allowed_hosts}
    if host not in allowed:
        raise FetchError("FETCH_HOST_NOT_ALLOWED")
    return url


def _safe_headers(headers) -> dict[str, str]:
    selected = {
        "content-type",
        "content-length",
        "content-disposition",
        "date",
        "etag",
        "last-modified",
    }
    result: dict[str, str] = {}
    for key, value in headers.items():
        normalized = str(key).lower()
        if normalized in selected:
            result[normalized] = str(value)
    return result


def _header(headers, name: str) -> str | None:
    target = name.lower()
    for key, value in headers.items():
        if str(key).lower() == target:
            return str(value)
    return None


def _fetched_at(clock: FetchClock | None) -> str:
    value = clock() if clock else datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise FetchError("FETCH_CLOCK_INVALID")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fetch_https_bytes(
    url: str,
    *,
    allowed_hosts: Collection[str],
    max_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 30.0,
    max_redirects: int = 3,
    allowed_content_types: Collection[str] | None = None,
    opener=None,
    clock: FetchClock | None = None,
) -> FetchedArtifact:
    """Fetch one bounded HTTPS artifact without following an unvalidated redirect."""

    if type(max_bytes) is not int or max_bytes <= 0:
        raise FetchError("FETCH_SIZE_LIMIT")
    if type(max_redirects) is not int or max_redirects < 0:
        raise FetchError("FETCH_REDIRECT_LIMIT")
    if timeout_seconds <= 0:
        raise FetchError("FETCH_TIMEOUT_INVALID")
    current_url = _validate_https_url(url, allowed_hosts)
    requested_url = current_url
    redirect_trace = [current_url]
    transport = opener or build_opener(_NoRedirectHandler())
    accepted_types = {
        str(value).split(";", 1)[0].strip().lower() for value in (allowed_content_types or ())
    }

    for redirect_count in range(max_redirects + 1):
        request = Request(
            current_url,
            headers={"Accept": "*/*", "User-Agent": "taiwan-laboratory-mcp/0.1"},
        )
        try:
            try:
                response = transport.open(request, timeout=timeout_seconds)
            except HTTPError as exc:
                response = exc
        except (OSError, URLError, TimeoutError) as exc:
            raise FetchError("FETCH_NETWORK_ERROR") from exc

        try:
            try:
                status_code = int(response.getcode())
            except (TypeError, ValueError, AttributeError, OSError) as exc:
                raise FetchError("FETCH_NETWORK_ERROR") from exc
            response_headers = response.headers
            if 300 <= status_code < 400:
                location = _header(response_headers, "location")
                if not location:
                    raise FetchError("FETCH_REDIRECT_INVALID")
                if redirect_count >= max_redirects:
                    raise FetchError("FETCH_REDIRECT_LIMIT")
                current_url = _validate_https_url(urljoin(current_url, location), allowed_hosts)
                redirect_trace.append(current_url)
                continue
            if status_code != 200:
                raise FetchError("FETCH_HTTP_STATUS")

            headers = _safe_headers(response_headers)
            content_type = headers.get("content-type")
            if accepted_types:
                normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
                if normalized_type not in accepted_types:
                    raise FetchError("FETCH_CONTENT_TYPE")
            content_length = headers.get("content-length")
            if content_length is not None:
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise FetchError("FETCH_CONTENT_LENGTH_INVALID") from exc
                if declared_size < 0:
                    raise FetchError("FETCH_CONTENT_LENGTH_INVALID")
                if declared_size > max_bytes:
                    raise FetchError("FETCH_SIZE_LIMIT")

            chunks: list[bytes] = []
            total = 0
            while True:
                try:
                    chunk = response.read(min(64 * 1024, max_bytes - total + 1))
                except (OSError, TimeoutError) as exc:
                    raise FetchError("FETCH_NETWORK_ERROR") from exc
                if not isinstance(chunk, bytes):
                    raise FetchError("FETCH_BODY_NOT_BYTES")
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError("FETCH_SIZE_LIMIT")
                chunks.append(chunk)
            payload = b"".join(chunks)
            if not payload:
                raise FetchError("FETCH_EMPTY_RESPONSE")
            return FetchedArtifact(
                requested_url=requested_url,
                final_url=current_url,
                status_code=status_code,
                payload=payload,
                sha256=sha256_bytes(payload),
                fetched_at=_fetched_at(clock),
                headers=headers,
                redirect_trace=tuple(redirect_trace),
            )
        finally:
            try:
                response.close()
            except OSError:
                pass

    raise FetchError("FETCH_REDIRECT_LIMIT")
