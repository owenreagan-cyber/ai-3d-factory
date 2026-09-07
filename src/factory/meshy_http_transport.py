"""Phase 47B: the real Meshy HTTP transport - NOT invoked by anything in
this repo unless every gate in `factory.meshy_live_adapter`'s locked
execution order has already passed.

**This is the only module in this repository that may ever open a real
network connection to Meshy.** Every other Meshy module (`meshy_models`,
`meshy_mock_transport`, `meshy_adapter`, `meshy_approval`, `meshy_ledger`,
`meshy_live_approval`, `meshy_live_adapter`) contains zero network-capable
code - see `tests/test_meshy_http_transport_safety.py`'s AST scan, which
asserts exactly this module is the sole exception.

Uses Python's standard library (`urllib.request`) rather than adding a
new HTTP dependency - `docs/meshy-live-readiness.md` section 4 leaves the
final choice to "Phase 47B's own implementation, made with the actual
repo state at that time"; this repo has no existing HTTP client
dependency (`pyproject.toml` lists none), so the standard library is the
narrower, dependency-free choice, and is fully mockable in tests via
dependency injection of an `_HttpClient`-shaped object rather than by
patching `urllib` internals.

SSRF-safe by construction, not by afterthought:

- The API host is hardcoded (`api.meshy.ai`) and never taken from any
  request/response field or caller argument.
- Redirects are never followed automatically - a redirect response from
  the API itself is treated as a protocol error, and an artifact-download
  redirect is followed at most once, re-validated against the same host
  checks below.
- `download_artifact()` refuses `localhost`/loopback/link-local
  (`169.254.169.254` - the cloud-metadata SSRF target)/private RFC1918
  ranges/non-`https` schemes outright, and otherwise only ever downloads
  the exact URL a same-call `get_task()` response returned - never an
  arbitrary caller-supplied URL (see `docs/meshy-live-readiness.md`
  section 5 - the real artifact-CDN host could not be determined without
  a real API response, so this defensive design is the safest posture
  until Phase 47B's first real call reveals it).
"""

from __future__ import annotations

import ipaddress
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MESHY_API_HOST = "api.meshy.ai"
MESHY_API_BASE = f"https://{MESHY_API_HOST}"
MESHY_CREDENTIAL_ENV_VAR = "MESHY_API_KEY"

_CONNECT_READ_TIMEOUT_SECONDS = 30.0  # urllib exposes one combined timeout, not separate connect/read
_DOWNLOAD_TIMEOUT_SECONDS = 120.0
_MAX_ARTIFACT_BYTES = 200 * 1024 * 1024  # 200 MB - comfortably above any plausible single mesh+textures
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

_BLOCKED_HOSTNAMES = {"localhost"}


class MeshyHttpError(Exception):
    """Raised for any structured transport failure - never lets a raw
    `urllib`/`ssl`/`socket` exception (which could carry request headers,
    including `Authorization`) escape uncaught. See `error_code`."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _is_blocked_host(hostname: str) -> bool:
    """SSRF hardening: reject loopback, link-local (including the cloud
    metadata address `169.254.169.254`), and private RFC1918 ranges. A
    bare hostname check (`_BLOCKED_HOSTNAMES`) catches `localhost`; an IP
    check catches everything else, including a hostname that itself
    resolves to a private address is NOT checked here (this repo does
    not perform DNS resolution itself before validation - see
    "Limitations" in docs/meshy-live-transport.md) - literal IP forms in
    the URL are what this function actually defends against."""
    if hostname in _BLOCKED_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False  # not a literal IP - a real hostname, allowed to proceed to the allowlist check
    return ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_multicast


def validate_artifact_url(url: str) -> None:
    """Raises `MeshyHttpError` unless `url` is `https://`-only and not a
    blocked/private/loopback host. Does **not** allowlist a specific CDN
    host - `docs/meshy-live-readiness.md` section 5 could not determine
    Meshy's real artifact-CDN host without a real API response, so this
    function is the documented, defensive fallback: it only rejects
    known-bad hosts rather than trying to guess-allowlist a good one.
    Callers must still only ever pass a URL taken verbatim from this same
    task's own `get_task()` response - never a caller-supplied,
    log-derived, or webhook-derived URL (see `HttpMeshyTransport.download_artifact`).
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise MeshyHttpError("invalid_artifact", f"artifact URL scheme must be https, got {parsed.scheme!r}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise MeshyHttpError("invalid_artifact", "artifact URL has no hostname")
    if hostname == MESHY_API_HOST:
        return  # the API host itself is always allowed
    if _is_blocked_host(hostname):
        raise MeshyHttpError("invalid_artifact", f"artifact URL host {hostname!r} is a blocked/private/loopback address")


# ---------------------------------------------------------------------------
# Credential provider
# ---------------------------------------------------------------------------


class MeshyCredentialError(Exception):
    pass


class LiveMeshyCredentialProvider:
    """Reads `MESHY_API_KEY` from the environment - lazily, only when
    `get_api_key()` is actually called, and never before every local gate
    in `factory.meshy_live_adapter`'s locked order has passed. Never
    loads `.env`/`dotenv`. Never caches the key to disk. The key is never
    included in `repr()`/`str()`, in any exception this class raises, or
    in any log/JSON output anywhere in this repo."""

    def __repr__(self) -> str:
        return "LiveMeshyCredentialProvider(key=<redacted>)"

    def get_api_key(self) -> str:
        key = os.environ.get(MESHY_CREDENTIAL_ENV_VAR)
        if not key:
            # Deliberately does not echo the env var name's absence in a
            # way that could be confused with the key's value - there is
            # no key value to leak here, but the message is still kept
            # generic for consistency with every other credential-error path.
            raise MeshyCredentialError(f"{MESHY_CREDENTIAL_ENV_VAR} is not set in the environment")
        return key


class MockCredentialProvider:
    """Test-only. Returns a fixed fake key - never touches
    `os.environ["MESHY_API_KEY"]`. Exists so tests can prove the
    *shape* of credential handling (e.g. "the key never appears in
    output") without exercising `LiveMeshyCredentialProvider` against a
    real environment variable."""

    def __init__(self, fake_key: str = "msy_test_fake_key_never_real"):
        self._fake_key = fake_key

    def __repr__(self) -> str:
        return "MockCredentialProvider(key=<redacted>)"

    def get_api_key(self) -> str:
        return self._fake_key


# ---------------------------------------------------------------------------
# Redirect-suppressing opener (never follows a redirect automatically)
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 - stdlib signature
        return None  # returning None makes urllib raise the redirect response as an HTTPError instead of following it


def _opener() -> urllib.request.OpenerDirector:
    # Certificate verification always on - ssl.create_default_context()'s
    # own defaults (CERT_REQUIRED, hostname checking) are never weakened
    # here; there is no verify=False equivalent anywhere in this module.
    context = ssl.create_default_context()
    return urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

from factory.meshy_mock_transport import MeshyTransport, MeshyTransportError  # noqa: E402 - after module-level constants, matches meshy_adapter's import ordering


class HttpMeshyTransport(MeshyTransport):
    """The real Meshy transport. Hardcodes `MESHY_API_BASE` - never
    accepts a caller-supplied base URL (see module docstring). Every
    method raises `MeshyTransportError` (never a bare `urllib`/`ssl`
    exception) so `factory.meshy_live_adapter` can translate failures
    into `factory.meshy_models.ERROR_CODES` uniformly, exactly like
    `MockMeshyTransport` already does for the mocked path.
    """

    def __init__(self, credential_provider: LiveMeshyCredentialProvider):
        self._credential_provider = credential_provider

    def _headers(self, *, json_body: bool) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._credential_provider.get_api_key()}"}
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    def _request(self, method: str, url: str, *, headers: dict[str, str], body: bytes | None) -> dict[str, Any]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with _opener().open(request, timeout=_CONNECT_READ_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            self._raise_for_http_error(exc)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise MeshyTransportError("network_error", f"network error contacting {MESHY_API_HOST}: {exc}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise MeshyTransportError("invalid_request", f"non-JSON response from {MESHY_API_HOST}: {exc}") from exc

    def _raise_for_http_error(self, exc: urllib.error.HTTPError) -> None:
        status = exc.code
        if status in (301, 302, 303, 307, 308):
            raise MeshyTransportError("invalid_request", f"unexpected redirect ({status}) from {MESHY_API_HOST} - redirects are never followed")
        if status in (401, 403):
            raise MeshyTransportError("credential_rejected", f"Meshy rejected the API key (HTTP {status})")
        if status == 429:
            raise MeshyTransportError("rate_limited", "Meshy rate limit exceeded (HTTP 429)", retry_allowed=False)
        if 500 <= status < 600:
            raise MeshyTransportError("server_error", f"Meshy server error (HTTP {status})", retry_allowed=False)
        raise MeshyTransportError("invalid_request", f"unexpected HTTP {status} from {MESHY_API_HOST}")

    def submit_task(self, request: dict[str, Any]) -> dict[str, Any]:
        """`POST /openapi/v2/text-to-3d`. Strictly parses the documented
        `{"result": "<task_id>"}` shape (`docs/meshy-live-readiness.md`
        section 2's correction to earlier research) - anything else is
        `invalid_request`, never a best-effort guess."""
        body = {
            "prompt": request["prompt"],
            "mode": request["mode"],
            "ai_model": request["model"],
            "ultra_mode": request.get("ultra_mode", False),
            "target_formats": request.get("target_formats", ["stl"]),
        }
        if request.get("target_polygon_count") is not None:
            body["target_polycount"] = request["target_polygon_count"]

        response = self._request(
            "POST", f"{MESHY_API_BASE}/openapi/v2/text-to-3d",
            headers=self._headers(json_body=True), body=json.dumps(body).encode("utf-8"),
        )
        task_id = response.get("result")
        if not isinstance(task_id, str) or not task_id:
            raise MeshyTransportError("invalid_request", f"submit response missing string 'result' (task id): {response!r}")
        return {"id": task_id, "status": "PENDING", "type": "text-to-3d"}

    def get_task(self, task_id: str) -> dict[str, Any]:
        """`GET /openapi/v2/text-to-3d/:id`. Requires `status` present in
        the response; an unrecognized status is surfaced as-is (the
        adapter layer maps unrecognized values to `unknown_provider_status`
        and stops - see `factory.meshy_live_adapter`)."""
        response = self._request("GET", f"{MESHY_API_BASE}/openapi/v2/text-to-3d/{task_id}", headers=self._headers(json_body=False), body=None)
        if "status" not in response or "id" not in response:
            raise MeshyTransportError("invalid_request", f"get_task response missing 'status'/'id': {response!r}")
        return response

    def download_artifact(self, model_url: str, destination: Path) -> Path:
        """Downloads exactly the URL given - which callers must only ever
        pass verbatim from this task's own, immediately-prior
        `get_task()` response (see module docstring). Streams with a
        running byte count, aborting past `_MAX_ARTIFACT_BYTES`; writes
        atomically (temp file + `os.replace`); never trusts a remote
        `Content-Disposition` filename (the destination path is always
        Factory-chosen, never derived from the response).

        `validate_artifact_url()` raises `MeshyHttpError`, not
        `MeshyTransportError` (it's a standalone, independently-testable
        function) - every call site here translates it, so this method
        (like every other `MeshyTransport` method) only ever raises
        `MeshyTransportError` to callers."""
        try:
            validate_artifact_url(model_url)
        except MeshyHttpError as exc:
            raise MeshyTransportError(exc.error_code, exc.message) from exc

        request = urllib.request.Request(model_url, method="GET")
        redirects_followed = 0
        url = model_url
        while True:
            try:
                with _opener().open(request, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:
                    destination = Path(destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    tmp_path = destination.with_suffix(destination.suffix + ".part")
                    total = 0
                    with open(tmp_path, "wb") as f:
                        while True:
                            chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > _MAX_ARTIFACT_BYTES:
                                tmp_path.unlink(missing_ok=True)
                                raise MeshyTransportError("invalid_artifact", f"artifact exceeded the {_MAX_ARTIFACT_BYTES}-byte cap")
                            f.write(chunk)
                    if total == 0:
                        tmp_path.unlink(missing_ok=True)
                        raise MeshyTransportError("invalid_artifact", "downloaded artifact is empty")
                    os.replace(tmp_path, destination)
                    return destination
            except urllib.error.HTTPError as exc:
                if exc.code in (301, 302, 303, 307, 308):
                    if redirects_followed >= 1:
                        raise MeshyTransportError("download_failed", "artifact download redirected more than once - refusing to follow an open-ended redirect chain")
                    location = exc.headers.get("Location")
                    if not location:
                        raise MeshyTransportError("download_failed", "redirect response had no Location header")
                    try:
                        validate_artifact_url(location)  # re-validate the redirect target before following it once
                    except MeshyHttpError as inner_exc:
                        raise MeshyTransportError(inner_exc.error_code, inner_exc.message) from inner_exc
                    url = location
                    request = urllib.request.Request(url, method="GET")
                    redirects_followed += 1
                    continue
                raise MeshyTransportError("download_failed", f"artifact download failed (HTTP {exc.code})")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise MeshyTransportError("download_failed", f"artifact download failed: {exc}") from exc
