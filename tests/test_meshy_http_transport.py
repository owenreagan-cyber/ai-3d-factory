"""Phase 47B tests: `factory.meshy_http_transport`. Every test replaces
`meshy_http_transport._opener()` with a fake opener - **no test in this
file ever opens a real socket or contacts a real host**. See
docs/meshy-live-transport.md.
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from factory import meshy_http_transport as t
from factory.meshy_mock_transport import MeshyTransportError


# ---------------------------------------------------------------------------
# Fake opener - simulates urllib's OpenerDirector without any real I/O
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, body: bytes, *, chunked: bool = False):
        self._buf = io.BytesIO(body)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n) if n != -1 else self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeOpener:
    """Replaces `urllib.request.OpenerDirector`. `responses` maps a URL to
    either a `(status, body_bytes)` tuple (200 = success, else raises
    `urllib.error.HTTPError`) or an `Exception` instance to raise
    directly (simulating a connection failure/timeout)."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.requested_urls: list[str] = []

    def open(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        self.requested_urls.append(url)
        outcome = self.responses.get(url)
        if outcome is None:
            raise AssertionError(f"no fake response configured for {url}")
        if isinstance(outcome, Exception):
            raise outcome
        status, body = outcome
        if status == 200:
            return _FakeResponse(body)
        raise urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(body))


@pytest.fixture
def fake_opener(monkeypatch):
    holder: dict[str, _FakeOpener] = {}

    def _install(responses: dict[str, object]) -> _FakeOpener:
        opener = _FakeOpener(responses)
        monkeypatch.setattr(t, "_opener", lambda: opener)
        holder["opener"] = opener
        return opener

    return _install


# ---------------------------------------------------------------------------
# Credential provider
# ---------------------------------------------------------------------------


def test_live_credential_provider_reads_env_lazily(monkeypatch):
    monkeypatch.delenv(t.MESHY_CREDENTIAL_ENV_VAR, raising=False)
    provider = t.LiveMeshyCredentialProvider()
    with pytest.raises(t.MeshyCredentialError):
        provider.get_api_key()

    monkeypatch.setenv(t.MESHY_CREDENTIAL_ENV_VAR, "msy_fake_secret_value")
    assert provider.get_api_key() == "msy_fake_secret_value"


def test_live_credential_provider_repr_redacted(monkeypatch):
    monkeypatch.setenv(t.MESHY_CREDENTIAL_ENV_VAR, "msy_fake_secret_value")
    provider = t.LiveMeshyCredentialProvider()
    assert "msy_fake_secret_value" not in repr(provider)
    assert "redacted" in repr(provider)


def test_live_credential_provider_error_never_contains_key(monkeypatch):
    monkeypatch.setenv(t.MESHY_CREDENTIAL_ENV_VAR, "msy_should_never_appear")
    monkeypatch.delenv(t.MESHY_CREDENTIAL_ENV_VAR, raising=False)
    provider = t.LiveMeshyCredentialProvider()
    try:
        provider.get_api_key()
    except t.MeshyCredentialError as exc:
        assert "msy_should_never_appear" not in str(exc)


def test_mock_credential_provider_never_touches_env(monkeypatch):
    monkeypatch.delenv(t.MESHY_CREDENTIAL_ENV_VAR, raising=False)
    provider = t.MockCredentialProvider()
    assert provider.get_api_key() == "msy_test_fake_key_never_real"
    assert "msy_test_fake_key_never_real" not in repr(provider)


# ---------------------------------------------------------------------------
# Host allowlist / SSRF hardening
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "https://localhost/model.stl",
    "https://127.0.0.1/model.stl",
    "https://169.254.169.254/model.stl",
    "https://10.0.0.5/model.stl",
    "https://192.168.1.1/model.stl",
    "https://172.16.0.1/model.stl",
])
def test_blocked_hosts_rejected(url):
    with pytest.raises(t.MeshyHttpError):
        t.validate_artifact_url(url)


@pytest.mark.parametrize("url", ["http://cdn.example.com/model.stl", "file:///etc/passwd", "ftp://cdn.example.com/model.stl"])
def test_non_https_scheme_rejected(url):
    with pytest.raises(t.MeshyHttpError):
        t.validate_artifact_url(url)


def test_api_host_itself_allowed():
    t.validate_artifact_url(f"{t.MESHY_API_BASE}/some/artifact.stl")  # must not raise


def test_generic_https_cdn_host_allowed_by_default():
    """Not blocked - the real artifact CDN host is unknown until a real
    response is inspected (docs/meshy-live-readiness.md section 5); this
    function only rejects known-bad hosts, it doesn't allowlist a
    specific good one yet."""
    t.validate_artifact_url("https://assets.example-cdn.com/model.stl")  # must not raise


# ---------------------------------------------------------------------------
# submit_task / get_task - strict response parsing
# ---------------------------------------------------------------------------


def _transport():
    return t.HttpMeshyTransport(t.MockCredentialProvider())


def test_submit_success_parses_result_field(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (200, json.dumps({"result": "real-task-123"}).encode())})
    result = _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert result["id"] == "real-task-123"
    assert result["status"] == "PENDING"


def test_submit_malformed_response_missing_result(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (200, json.dumps({"task": "no-result-key"}).encode())})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "invalid_request"


def test_submit_non_json_response(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (200, b"not json at all")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "invalid_request"


@pytest.mark.parametrize("status,expected_code", [(401, "credential_rejected"), (403, "credential_rejected")])
def test_auth_failure_codes(fake_opener, status, expected_code):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (status, b"{}")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == expected_code


def test_rate_limit_429(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (429, b"{}")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "rate_limited"
    assert exc_info.value.retry_allowed is False


def test_server_error_5xx(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (500, b"{}")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "server_error"


def test_connection_failure(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: urllib.error.URLError("simulated connection refused")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "network_error"


def test_timeout(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: TimeoutError("simulated timeout")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "network_error"


def test_get_task_success(fake_opener):
    task_url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d/task-1"
    fake_opener({task_url: (200, json.dumps({"id": "task-1", "status": "SUCCEEDED"}).encode())})
    result = _transport().get_task("task-1")
    assert result["status"] == "SUCCEEDED"


def test_get_task_missing_required_fields(fake_opener):
    task_url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d/task-1"
    fake_opener({task_url: (200, json.dumps({"foo": "bar"}).encode())})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().get_task("task-1")
    assert exc_info.value.error_code == "invalid_request"


def test_unrecognized_5xx_variant_still_maps_to_server_error(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (503, b"{}")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "server_error"


# ---------------------------------------------------------------------------
# Redirect handling (submit/get - never followed)
# ---------------------------------------------------------------------------


def test_submit_redirect_treated_as_error(fake_opener):
    url = f"{t.MESHY_API_BASE}/openapi/v2/text-to-3d"
    fake_opener({url: (302, b"{}")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().submit_task({"prompt": "x", "mode": "preview", "model": "meshy-7"})
    assert exc_info.value.error_code == "invalid_request"


# ---------------------------------------------------------------------------
# Artifact download security
# ---------------------------------------------------------------------------


def test_download_success(fake_opener, tmp_path):
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"solid x\nendsolid x\n")})
    dest = tmp_path / "out.stl"
    result = _transport().download_artifact(url, dest)
    assert result == dest
    assert dest.read_bytes() == b"solid x\nendsolid x\n"


def test_download_atomic_no_partial_file_left_on_success(fake_opener, tmp_path):
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"solid x\nendsolid x\n")})
    dest = tmp_path / "out.stl"
    _transport().download_artifact(url, dest)
    leftovers = list(tmp_path.glob("*.part"))
    assert leftovers == []


def test_download_empty_artifact_rejected(fake_opener, tmp_path):
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact(url, tmp_path / "out.stl")
    assert exc_info.value.error_code == "invalid_artifact"
    assert not (tmp_path / "out.stl.part").exists()


def test_download_oversized_artifact_rejected(fake_opener, tmp_path, monkeypatch):
    monkeypatch.setattr(t, "_MAX_ARTIFACT_BYTES", 10)
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"x" * 1000)})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact(url, tmp_path / "out.stl")
    assert exc_info.value.error_code == "invalid_artifact"


def test_download_blocked_host_rejected_before_any_open(fake_opener, tmp_path):
    """download_artifact() only ever raises MeshyTransportError to
    callers (matching every other MeshyTransport method) - never the
    standalone validate_artifact_url()'s own MeshyHttpError."""
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact("https://169.254.169.254/model.stl", tmp_path / "out.stl")
    assert exc_info.value.error_code == "invalid_artifact"


def test_download_invalid_extension_is_callers_responsibility(fake_opener, tmp_path):
    """The transport writes exactly the Factory-chosen destination path -
    it never derives a filename/extension from the remote response, so
    there is no remote-controlled extension to validate here; this test
    documents that the destination is always caller-controlled."""
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"solid x\nendsolid x\n")})
    dest = tmp_path / "definitely_not_remote_named.stl"
    result = _transport().download_artifact(url, dest)
    assert result.name == "definitely_not_remote_named.stl"


def test_download_path_traversal_destination_stays_caller_chosen(fake_opener, tmp_path):
    """The transport never trusts a remote filename (no Content-Disposition
    parsing at all) - the destination is always the exact Path the caller
    passed in, so a malicious remote filename has no path-traversal surface."""
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: (200, b"solid x\nendsolid x\n")})
    safe_dest = tmp_path / "safe" / "out.stl"
    result = _transport().download_artifact(url, safe_dest)
    assert result == safe_dest
    assert result.is_relative_to(tmp_path)


def test_download_timeout(fake_opener, tmp_path):
    url = "https://cdn.example.com/model.stl"
    fake_opener({url: TimeoutError("simulated download timeout")})
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact(url, tmp_path / "out.stl")
    assert exc_info.value.error_code == "download_failed"


def test_download_single_redirect_followed_and_revalidated(fake_opener, tmp_path):
    original_url = "https://cdn.example.com/model.stl"
    redirected_url = "https://cdn2.example.com/model.stl"
    opener = fake_opener({
        original_url: urllib.error.HTTPError(original_url, 302, "redirect", {"Location": redirected_url}, io.BytesIO(b"")),
        redirected_url: (200, b"solid x\nendsolid x\n"),
    })
    dest = tmp_path / "out.stl"
    result = _transport().download_artifact(original_url, dest)
    assert result == dest
    assert dest.read_bytes() == b"solid x\nendsolid x\n"


def test_download_redirect_to_blocked_host_rejected(fake_opener, tmp_path):
    original_url = "https://cdn.example.com/model.stl"
    redirected_url = "https://169.254.169.254/model.stl"
    fake_opener({
        original_url: urllib.error.HTTPError(original_url, 302, "redirect", {"Location": redirected_url}, io.BytesIO(b"")),
    })
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact(original_url, tmp_path / "out.stl")
    assert exc_info.value.error_code in ("invalid_artifact", "download_failed")


def test_download_second_redirect_refused_open_ended_chain(fake_opener, tmp_path):
    url_1 = "https://cdn.example.com/a.stl"
    url_2 = "https://cdn.example.com/b.stl"
    url_3 = "https://cdn.example.com/c.stl"
    fake_opener({
        url_1: urllib.error.HTTPError(url_1, 302, "redirect", {"Location": url_2}, io.BytesIO(b"")),
        url_2: urllib.error.HTTPError(url_2, 302, "redirect", {"Location": url_3}, io.BytesIO(b"")),
    })
    with pytest.raises(MeshyTransportError) as exc_info:
        _transport().download_artifact(url_1, tmp_path / "out.stl")
    assert exc_info.value.error_code == "download_failed"
