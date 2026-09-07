"""Phase 49 safety tests: static/AST inspection proving
`factory.blender_adaptation` and the second Factory-owned Blender script
(`blender_fixtures/factory_organic_cleanup_workflow.py`) stay inside their
safety contract. Mirrors `tests/test_blender_adapter_safety.py`'s (Phase
45) and `tests/test_hybrid_workflow_safety.py`'s (Phase 48) conventions
exactly. See docs/blender-adaptation.md.
"""

from __future__ import annotations

import ast
import importlib
import socket
import subprocess

import pytest

from factory import blender_adaptation, blender_gate, project_store

_MINIMAL_STL = (
    "solid t\n"
    "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
    "endsolid t\n"
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def meshy_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    artifact_dir = root / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(_MINIMAL_STL)
    return root, artifact_path


# ---------------------------------------------------------------------------
# factory.blender_adaptation itself never imports subprocess/network, and
# never imports the module that would let it launch Blender's GUI.
# ---------------------------------------------------------------------------


def test_module_imports_no_subprocess_or_network_library():
    tree = ast.parse(open(importlib.import_module("factory.blender_adaptation").__file__).read())
    forbidden = {"subprocess", "socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"blender_adaptation.py imports forbidden module(s): {imported & forbidden}"


def test_module_never_imports_cad_execution_module():
    """This module may execute Blender (via factory.blender_adapter,
    which is the sole subprocess-invoking module) but must never import
    factory.cad.backend (CAD execution) - organic_cleanup_workflow is
    Blender-only."""
    tree = ast.parse(open(importlib.import_module("factory.blender_adaptation").__file__).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "factory.cad.backend" not in imported


def test_no_desktop_automation_patterns():
    text = importlib_source("factory.blender_adaptation")
    for pattern in ('os.system(', 'os.popen(', 'subprocess.Popen(', '"osascript"', "'osascript'", '"pkill"', "'pkill'", '["open"', "['open'"):
        assert pattern not in text


def importlib_source(module_name: str) -> str:
    return open(importlib.import_module(module_name).__file__, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# Behavioral proof: planning survives poisoned network/subprocess
# ---------------------------------------------------------------------------


def test_build_plan_survives_poisoned_network_and_subprocess(meshy_project, monkeypatch):
    _, artifact_path = meshy_project

    def _boom(*a, **k):
        raise AssertionError("planning must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    assert plan["automatic_execution_allowed"] is False


def test_blocked_execution_survives_poisoned_network_and_subprocess(tmp_path, monkeypatch):
    """Without --confirm, execution must never reach Blender - and must
    never touch network/subprocess either, even with a real-looking
    (but poisoned) environment."""
    artifact = tmp_path / "loose.stl"
    artifact.write_text(_MINIMAL_STL)

    def _boom(*a, **k):
        raise AssertionError("a blocked (unconfirmed) execution must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = blender_adaptation.run_organic_cleanup_workflow(artifact, target_max_dimension_mm=150.0, confirm=False)
    assert result["organic_cleanup_status"] == "blocked"


# ---------------------------------------------------------------------------
# Path containment / no-overwrite
# ---------------------------------------------------------------------------


def test_output_artifact_path_is_always_under_generated_blender_adapted(meshy_project):
    project_dir, artifact_path = meshy_project
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    output = plan["output_artifact"]
    assert output is not None
    assert output.startswith(str(project_dir / "generated" / "blender" / "adapted"))


def test_plan_never_modifies_the_input_artifact(meshy_project):
    _, artifact_path = meshy_project
    before = artifact_path.read_bytes()
    blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    after = artifact_path.read_bytes()
    assert before == after


# ---------------------------------------------------------------------------
# The second Factory-owned Blender script: statically parsed (AST, not
# just a substring scan), mirroring tests/test_blender_adapter_safety.py's
# fixture-script tests exactly.
# ---------------------------------------------------------------------------

_FORBIDDEN_SCRIPT_IMPORT_MODULES = {"subprocess", "socket", "requests", "urllib", "os"}


def test_organic_cleanup_script_path_is_a_fixed_module_constant():
    assert blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.is_file()
    assert blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.name == "factory_organic_cleanup_workflow.py"
    assert blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.parent.name == "blender_fixtures"


def test_organic_cleanup_script_imports_only_bpy_and_sys():
    tree = ast.parse(blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert imported_modules == {"bpy", "sys"}, f"unexpected imports: {imported_modules}"
    assert imported_modules.isdisjoint(_FORBIDDEN_SCRIPT_IMPORT_MODULES)


def test_organic_cleanup_script_never_calls_os_system_or_shell_commands():
    text = blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("os.system(", "subprocess.", "socket.", "urlopen(", "shell=True"):
        assert forbidden not in text


def test_organic_cleanup_script_has_exactly_one_output_write_call():
    text = blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.count("bpy.ops.wm.stl_export(") == 1
    assert text.count("bpy.ops.wm.stl_import(") == 1
    assert "output_path" in text


def test_organic_cleanup_script_never_reads_any_hardcoded_external_path():
    tree = ast.parse(blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.read_text(encoding="utf-8"))
    string_constants = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    suspicious_paths = [s for s in string_constants if s.startswith("/") or s.startswith("~")]
    assert suspicious_paths == [], f"organic cleanup script contains a hardcoded absolute/home path: {suspicious_paths}"


def test_organic_cleanup_script_never_performs_topology_operations():
    """Scope guard: this script's only allowed `bpy.ops.*` calls are
    import/select/scale/transform-apply/export - never repair, remesh,
    decimate, smooth, or sculpt. Checked via AST against the actual
    `bpy.ops.<module>.<op>(...)` call sites, never a raw substring scan of
    the file (which would also flag this scope note in the module's own
    docstring, explaining what is *not* done)."""
    tree = ast.parse(blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH.read_text(encoding="utf-8"))
    forbidden_fragments = ("remesh", "decimate", "smooth", "sculpt", "retopo", "boolean", "fill_holes", "modifier", "geometry_nodes")
    ops_calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr_chain = []
            cur = node.func
            while isinstance(cur, ast.Attribute):
                attr_chain.append(cur.attr)
                cur = cur.value
            # attr_chain is reverse-order (deepest attr first); after the
            # loop `cur` is whatever sits at the base of the chain (a Name
            # for `bpy.ops.wm.stl_export`) and attr_chain[-1] is "ops".
            if isinstance(cur, ast.Name) and cur.id == "bpy" and attr_chain and attr_chain[-1] == "ops":
                ops_calls.append(".".join(reversed(attr_chain[:-1])))
    assert ops_calls, "expected at least one bpy.ops.* call"
    for call in ops_calls:
        lowered = call.lower()
        for forbidden in forbidden_fragments:
            assert forbidden not in lowered, f"unexpected bpy.ops call {call!r} contains forbidden fragment {forbidden!r}"


def test_no_arbitrary_script_path_accepted_anywhere():
    """No CLI option or function parameter anywhere accepts an arbitrary
    Blender script path - mirrors test_blender_adapter_safety.py's
    identical guarantee for the Phase 45 fixture script."""
    for module_name in ("factory.blender_adaptation", "factory.blender_adapter", "factory.blender_gate"):
        source = importlib_source(module_name)
        assert "script_path" not in source
        assert "user_script" not in source


def test_only_the_factory_owned_organic_cleanup_script_is_ever_passed_to_python_flag():
    adapter_source = importlib_source("factory.blender_adapter")
    assert "blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH" in adapter_source
