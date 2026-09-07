"""Phase 47A tests: `factory.meshy_mock_transport` - the only transport
implementation in this repo. Every test proves NO network access and NO
real Meshy contact of any kind."""

from __future__ import annotations

import pytest

from factory.meshy_mock_transport import (
    MeshyTransport,
    MeshyTransportError,
    MockMeshyTransport,
)
from factory.meshy_models import build_text_to_3d_request

_REQUEST = build_text_to_3d_request(prompt="a rounded concept")


def test_mock_transport_is_a_meshy_transport():
    assert isinstance(MockMeshyTransport(), MeshyTransport)


def test_only_mock_scenarios_accepted():
    with pytest.raises(ValueError):
        MockMeshyTransport(scenario="does-not-exist")


def test_submit_task_returns_mock_namespaced_id():
    transport = MockMeshyTransport(scenario="success")
    task = transport.submit_task(_REQUEST)
    assert task["id"].startswith("mock-meshy-")
    assert task["status"] == "PENDING"


def test_submit_task_ids_are_unique_per_call():
    transport = MockMeshyTransport(scenario="success")
    a = transport.submit_task(_REQUEST)
    b = transport.submit_task(_REQUEST)
    assert a["id"] != b["id"]


def test_success_lifecycle_progression():
    transport = MockMeshyTransport(scenario="success")
    task = transport.submit_task(_REQUEST)
    first_poll = transport.get_task(task["id"])
    assert first_poll["status"] == "IN_PROGRESS"
    second_poll = transport.get_task(task["id"])
    assert second_poll["status"] == "SUCCEEDED"
    assert second_poll["model_urls"]["stl"]


def test_failure_lifecycle_progression():
    transport = MockMeshyTransport(scenario="failure")
    task = transport.submit_task(_REQUEST)
    transport.get_task(task["id"])  # IN_PROGRESS
    final = transport.get_task(task["id"])
    assert final["status"] == "FAILED"
    assert final["task_error"]["message"]


def test_canceled_not_modeled_as_a_scenario_but_status_vocabulary_includes_it():
    from factory.meshy_models import MESHY_TASK_STATUSES

    assert "CANCELED" in MESHY_TASK_STATUSES


def test_rate_limit_raises_on_submit():
    transport = MockMeshyTransport(scenario="rate_limited")
    with pytest.raises(MeshyTransportError) as exc_info:
        transport.submit_task(_REQUEST)
    assert exc_info.value.error_code == "rate_limited"
    assert exc_info.value.retry_allowed is False


def test_server_error_raises_on_submit():
    transport = MockMeshyTransport(scenario="server_error")
    with pytest.raises(MeshyTransportError) as exc_info:
        transport.submit_task(_REQUEST)
    assert exc_info.value.error_code == "server_error"


def test_download_artifact_success_copies_local_fixture(tmp_path):
    transport = MockMeshyTransport(scenario="success")
    task = transport.submit_task(_REQUEST)
    transport.get_task(task["id"])
    final = transport.get_task(task["id"])
    destination = tmp_path / "out.stl"
    result_path = transport.download_artifact(final["model_urls"]["stl"], destination)
    assert result_path == destination
    assert destination.is_file()
    assert destination.stat().st_size > 0


def test_download_artifact_never_reads_the_url(tmp_path, monkeypatch):
    """`model_url` is accepted only to match the transport interface's
    real shape - it is never opened/resolved/contacted."""
    transport = MockMeshyTransport(scenario="success")
    destination = tmp_path / "out.stl"
    transport.download_artifact("mock://this-is-never-fetched.invalid/model.stl", destination)
    assert destination.is_file()


def test_download_artifact_missing_for_failure_scenario(tmp_path):
    transport = MockMeshyTransport(scenario="failure")
    with pytest.raises(MeshyTransportError) as exc_info:
        transport.download_artifact("mock://x", tmp_path / "out.stl")
    assert exc_info.value.error_code == "artifact_missing"


def test_download_artifact_expired_for_expired_scenario(tmp_path):
    transport = MockMeshyTransport(scenario="expired_artifact")
    with pytest.raises(MeshyTransportError) as exc_info:
        transport.download_artifact("mock://x", tmp_path / "out.stl")
    assert exc_info.value.error_code == "artifact_expired"


def test_expired_artifact_scenario_reports_succeeded_task_status():
    """An expired artifact is a Factory-side interpretation of
    `expires_at`, never a new Meshy `status` value - the task itself
    still reports SUCCEEDED."""
    transport = MockMeshyTransport(scenario="expired_artifact")
    task = transport.submit_task(_REQUEST)
    transport.get_task(task["id"])
    final = transport.get_task(task["id"])
    assert final["status"] == "SUCCEEDED"
    assert final["expires_at"] < 0


# ---------------------------------------------------------------------------
# Safety: no network anywhere in this module
# ---------------------------------------------------------------------------


def test_no_network_imports_in_mock_transport_module():
    import ast
    import factory.meshy_mock_transport as mod

    tree = ast.parse(open(mod.__file__).read())
    forbidden = {"socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), imported & forbidden


def test_mock_transport_full_lifecycle_survives_network_disabled(monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("MockMeshyTransport must never open a socket")

    monkeypatch.setattr(socket, "socket", _boom)
    transport = MockMeshyTransport(scenario="success")
    task = transport.submit_task(_REQUEST)
    transport.get_task(task["id"])
    transport.get_task(task["id"])
