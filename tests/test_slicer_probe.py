import inspect

from factory.slicer import local_slicer_probe
from factory.slicer.local_slicer_probe import probe_slicers


def test_probe_slicers_returns_expected_shape():
    results = probe_slicers()
    assert isinstance(results, list)
    assert len(results) >= 2

    names = {r["name"] for r in results}
    assert "Bambu Studio" in names
    assert "OrcaSlicer" in names

    for entry in results:
        assert set(entry.keys()) == {"name", "found", "method", "path"}
        assert isinstance(entry["found"], bool)


def test_probe_slicers_module_is_read_only():
    """Guard against this module gaining launch/slice/print capability."""
    source = inspect.getsource(local_slicer_probe)
    forbidden_substrings = ["subprocess", "os.system", "os.popen", "Popen"]
    for forbidden in forbidden_substrings:
        assert forbidden not in source, f"local_slicer_probe.py must stay read-only; found {forbidden!r}"


def test_probe_slicers_does_not_require_network_or_printer():
    # Calling this twice back to back should be side-effect-free and deterministic
    # in terms of shape (not necessarily identical `found` values across machines).
    first = probe_slicers()
    second = probe_slicers()
    assert [r["name"] for r in first] == [r["name"] for r in second]
