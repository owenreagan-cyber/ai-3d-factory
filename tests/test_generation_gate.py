"""Phase 34 tests: `factory.generation_gate` - the local, deterministic
Readiness-Gated CAD Generation Router. An adapter/gate around this repo's
*existing* local CAD generation backends (OpenSCAD, CadQuery), never a
second CAD backend. No AI, no LLM, no network, no Blender, no Meshy. See
docs/generation-gate.md, docs/roadmap.md Phase 34.
"""

import inspect

import pytest

from factory import generation_gate, project_store
from factory.design_orchestrator import evaluate_readiness_for_path
from factory.generation_gate import (
    DECISIONS,
    GENERATED_DIRNAME,
    MINIMUM_READINESS_SCORE,
    RECEIPT_FILENAME,
    SUPPORTED_ENGINES,
    build_artifact_tracking,
    build_execution_receipt,
    evaluate_generation_gate,
    evaluate_generation_gate_for_path,
    plan_generation,
    read_last_execution_receipt,
    run_generation,
    summarize_generation_execution,
    summarize_generation_gate,
    write_generation_receipt,
)
from factory.project_intake import analyze as analyze_intake

STORAGE_BIN_LID_PATH = project_store.REPO_ROOT / "examples" / "storage-bin-lid"

RICH_DESCRIPTION = (
    "A premium etsy-worthy classroom nameplate sign made of PLA on a Bambu H2D printer, "
    "120mm wide by 40mm tall by 5mm thick, single color."
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def _ready_project(project_root):
    """Push a freshly-scaffolded project's readiness above
    MINIMUM_READINESS_SCORE with no critical advisories missing, so
    evaluate_generation_gate() can reach "Needs Confirmation"/"Allowed".
    """
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = RICH_DESCRIPTION
    brief["intended_printer"] = "Bambu H2D"
    brief["constraints"] = ["120mm wide, 40mm tall, 5mm thick", "PLA filament only"]
    brief["design_intent"] = {
        "quality_standard": "premium",
        "use_case": "classroom nameplate sign",
        "style_direction": ["clean", "modern"],
        "reference_inputs": ["Classroom sign example"],
        "manufacturability_constraints": {"max_size_mm": [120, 40, 5]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_root / "reference_board.json",
        {
            "references": [
                {
                    "title": "Classroom sign example",
                    "source_type": "image",
                    "license": "public_domain",
                    "usage_intent": "design_reference_only",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/sign",
                }
            ]
        },
    )
    return project_root


# ---- vocabulary sanity ----


def test_decisions_are_the_five_required_values():
    assert set(DECISIONS) == {"Allowed", "Needs Confirmation", "Blocked", "Unsupported Engine", "Dry Run Only"}


def test_supported_engines_are_only_openscad_and_cadquery():
    assert set(SUPPORTED_ENGINES) == {"OpenSCAD", "CadQuery"}


def test_minimum_readiness_score_matches_design_orchestrator_ready_threshold():
    assert MINIMUM_READINESS_SCORE == 60


# ---- plan_generation() ----


def test_plan_generation_openscad():
    plan = plan_generation({}, {"recommended_engine": "OpenSCAD"})
    assert plan["engine"] == "OpenSCAD"
    assert plan["template"] == "sign"


def test_plan_generation_cadquery():
    plan = plan_generation({}, {"recommended_engine": "CadQuery"})
    assert plan["engine"] == "CadQuery"
    assert plan["template"] == "mechanical-plate"


def test_plan_generation_unsupported_engine_returns_none():
    assert plan_generation({}, {"recommended_engine": "Blender"}) is None
    assert plan_generation({}, {"recommended_engine": "Meshy (Concept Only)"}) is None
    assert plan_generation({}, {"recommended_engine": "Unknown"}) is None


def test_plan_generation_never_raises_on_none_inputs():
    plan_generation(None, None)


# ---- evaluate_generation_gate(): decision priority ----


def test_blocked_readiness_state_always_blocks():
    result = evaluate_generation_gate({}, {"readiness_state": "Blocked", "recommended_engine": "OpenSCAD", "score": {"overall": 95}, "advisories": []})
    assert result["decision"] == "Blocked"


def test_blocked_overrides_confirm_generate():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Blocked", "recommended_engine": "OpenSCAD", "score": {"overall": 95}, "advisories": []}, confirm_generate=True
    )
    assert result["decision"] == "Blocked"


def test_unsupported_engine_blender():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Ready For Organic Modeling", "recommended_engine": "Blender", "score": {"overall": 95}, "advisories": []}
    )
    assert result["decision"] == "Unsupported Engine"


def test_unsupported_engine_meshy():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Ready For Organic Modeling", "recommended_engine": "Meshy (Concept Only)", "score": {"overall": 95}, "advisories": []}
    )
    assert result["decision"] == "Unsupported Engine"


def test_unsupported_engine_unknown():
    result = evaluate_generation_gate({}, {"readiness_state": "Not Ready", "recommended_engine": "Unknown", "score": {"overall": 0}, "advisories": []})
    assert result["decision"] == "Unsupported Engine"


def test_low_readiness_score_is_dry_run_only():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Needs Information", "recommended_engine": "OpenSCAD", "score": {"overall": 36}, "advisories": []}
    )
    assert result["decision"] == "Dry Run Only"
    assert any("36" in item and "60" in item for item in result["required_before_generation"])


def test_missing_dimensions_advisory_forces_dry_run_only_even_with_high_score():
    result = evaluate_generation_gate(
        {},
        {
            "readiness_state": "Ready For Mechanical CAD",
            "recommended_engine": "OpenSCAD",
            "score": {"overall": 95},
            "advisories": ["Dimensions missing"],
        },
    )
    assert result["decision"] == "Dry Run Only"
    assert "dimensions missing" in result["required_before_generation"]


def test_material_unspecified_advisory_forces_dry_run_only():
    result = evaluate_generation_gate(
        {},
        {
            "readiness_state": "Ready For Mechanical CAD",
            "recommended_engine": "OpenSCAD",
            "score": {"overall": 95},
            "advisories": ["Material unspecified"],
        },
    )
    assert result["decision"] == "Dry Run Only"


def test_readiness_state_not_ready_for_forces_dry_run_only_even_above_score_threshold():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Needs Information", "recommended_engine": "OpenSCAD", "score": {"overall": 65}, "advisories": []}
    )
    assert result["decision"] == "Dry Run Only"


def test_needs_confirmation_when_gate_passes_but_not_confirmed():
    result = evaluate_generation_gate(
        {}, {"readiness_state": "Ready For Mechanical CAD", "recommended_engine": "OpenSCAD", "score": {"overall": 90}, "advisories": []}
    )
    assert result["decision"] == "Needs Confirmation"
    assert "human confirmation required (--confirm-generate)" in result["required_before_generation"]


def test_allowed_when_gate_passes_and_confirmed():
    result = evaluate_generation_gate(
        {},
        {"readiness_state": "Ready For Mechanical CAD", "recommended_engine": "OpenSCAD", "score": {"overall": 90}, "advisories": []},
        confirm_generate=True,
    )
    assert result["decision"] == "Allowed"
    assert result["required_before_generation"] == []


def test_evaluate_generation_gate_shape():
    result = evaluate_generation_gate({}, {"readiness_state": "Not Ready", "recommended_engine": "Unknown", "score": {"overall": 0}, "advisories": []})
    assert set(result.keys()) == {
        "decision", "recommended_engine", "readiness_state", "readiness_score", "plan",
        "required_before_generation", "confirm_generate",
    }
    assert result["decision"] in DECISIONS


def test_evaluate_generation_gate_never_raises_on_none_inputs():
    result = evaluate_generation_gate(None, None)
    assert result["decision"] in DECISIONS


def test_evaluate_generation_gate_is_deterministic():
    orchestrator = {"readiness_state": "Ready For Mechanical CAD", "recommended_engine": "OpenSCAD", "score": {"overall": 90}, "advisories": []}
    a = evaluate_generation_gate({}, orchestrator)
    b = evaluate_generation_gate({}, orchestrator)
    assert a == b


# ---- worked example from the Phase 34 spec: storage-bin-lid ----


def test_storage_bin_lid_worked_example():
    result = evaluate_generation_gate_for_path(STORAGE_BIN_LID_PATH)
    assert result["recommended_engine"] == "OpenSCAD"
    assert result["decision"] == "Dry Run Only"
    assert result["readiness_score"] < MINIMUM_READINESS_SCORE


def test_evaluate_generation_gate_for_path_never_writes_files(tmp_path):
    before = sorted(p.name for p in STORAGE_BIN_LID_PATH.iterdir())
    evaluate_generation_gate_for_path(STORAGE_BIN_LID_PATH)
    after = sorted(p.name for p in STORAGE_BIN_LID_PATH.iterdir())
    assert before == after


# ---- summarize_generation_gate() ----


def test_summarize_generation_gate_shape():
    summary = summarize_generation_gate({}, {"readiness_state": "Not Ready", "recommended_engine": "Unknown", "score": {"overall": 0}, "advisories": []})
    assert set(summary.keys()) == {"decision", "recommended_engine", "ready", "reason"}


def test_summarize_generation_gate_always_dry_run_even_if_gate_would_allow():
    orchestrator = {"readiness_state": "Ready For Mechanical CAD", "recommended_engine": "OpenSCAD", "score": {"overall": 90}, "advisories": []}
    summary = summarize_generation_gate({}, orchestrator)
    assert summary["decision"] == "Needs Confirmation"
    assert summary["ready"] is True


def test_summarize_generation_gate_not_ready_when_dry_run_only():
    orchestrator = {"readiness_state": "Needs Information", "recommended_engine": "OpenSCAD", "score": {"overall": 36}, "advisories": []}
    summary = summarize_generation_gate({}, orchestrator)
    assert summary["decision"] == "Dry Run Only"
    assert summary["ready"] is False
    assert summary["reason"] is not None


def test_summarize_generation_gate_not_ready_when_blocked():
    orchestrator = {"readiness_state": "Blocked", "recommended_engine": "OpenSCAD", "score": {"overall": 90}, "advisories": []}
    summary = summarize_generation_gate({}, orchestrator)
    assert summary["ready"] is False


# ---- run_generation(): real, end-to-end local generation ----


def test_run_generation_openscad_writes_expected_file(isolated_projects_dir):
    project_root = _ready_project(project_store.init_project("Classroom Sign"))
    gate = evaluate_generation_gate_for_path(project_root, confirm_generate=True)
    assert gate["decision"] == "Allowed", gate

    result = run_generation(project_root, gate)
    assert result["written_files"]
    written_paths = [p for p in result["written_files"]]
    assert any(p.endswith("sign.scad") for p in written_paths)
    assert (project_root / "cad" / "sign.scad").is_file()


def test_run_generation_raises_when_decision_not_allowed():
    gate = {"decision": "Dry Run Only", "plan": None}
    with pytest.raises(ValueError):
        run_generation("does-not-matter", gate)


def test_run_generation_raises_on_needs_confirmation():
    gate = {"decision": "Needs Confirmation", "plan": {"engine": "OpenSCAD", "template": "sign", "params": {"text": "x"}}}
    with pytest.raises(ValueError):
        run_generation("does-not-matter", gate)


def test_dry_run_default_never_calls_run_generation_writes_nothing(isolated_projects_dir):
    project_root = _ready_project(project_store.init_project("Classroom Sign"))
    before = sorted(p.name for p in (project_root / "cad").iterdir())
    gate = evaluate_generation_gate_for_path(project_root)  # confirm_generate defaults to False
    assert gate["decision"] == "Needs Confirmation"
    after = sorted(p.name for p in (project_root / "cad").iterdir())
    assert before == after


def test_confirmed_generation_requires_confirm_generate_flag(isolated_projects_dir):
    # Even a fully-ready project does NOT reach "Allowed" without explicitly
    # passing confirm_generate=True - human-in-the-loop is not optional.
    project_root = _ready_project(project_store.init_project("Classroom Sign"))
    gate = evaluate_generation_gate_for_path(project_root)
    assert gate["decision"] != "Allowed"


# ---- module hygiene: reuses design_orchestrator/openscad/cadquery, never duplicates ----


def test_module_reuses_evaluate_readiness_for_path_not_a_second_scorer():
    source = inspect.getsource(generation_gate)
    assert "from factory.design_orchestrator import evaluate_readiness_for_path" in source
    assert "CATEGORY_WEIGHTS" not in source
    assert "_score_intake" not in source
    assert "_score_manufacturing" not in source


def test_module_calls_existing_generate_openscad_and_generate_cadquery_not_reimplemented():
    source = inspect.getsource(generation_gate)
    assert "generate_openscad(" in source
    assert "cadquery_backend.generate_cadquery(" in source


def test_module_never_imports_project_inspection():
    # generation_gate.py must be a "leaf" module - project_inspection.py
    # imports from it, never the other way around.
    source = inspect.getsource(generation_gate)
    assert "import factory.project_inspection" not in source
    assert "from factory.project_inspection" not in source
    assert "from factory import project_inspection" not in source


def test_module_has_no_forbidden_network_or_blender_or_meshy_execution_calls():
    # "Meshy (Concept Only)"/"Blender" as plain words are expected (they're
    # entries this module reads from recommended_engine and rejects as
    # "Unsupported Engine") - only an actual import/invocation is forbidden.
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "openai", "anthropic", "import bpy", "openscad_exec", "meshy_api", "meshy.generate",
    )
    source = inspect.getsource(generation_gate)
    for forbidden_call in forbidden:
        assert forbidden_call.lower() not in source.lower(), f"found forbidden call {forbidden_call!r}"


def test_module_never_installs_anything():
    source = inspect.getsource(generation_gate)
    for forbidden in ("pip install", "pip.main(", "subprocess", "brew install"):
        assert forbidden not in source


# ---- execution receipts: write_generation_receipt() / build_execution_receipt() ----


@pytest.fixture()
def allowed_generation(isolated_projects_dir):
    """A real, confirmed, successful OpenSCAD generation - the only
    precondition write_generation_receipt()/build_execution_receipt() are
    ever meant to run against.
    """
    project_root = _ready_project(project_store.init_project("Classroom Sign"))
    gate = evaluate_generation_gate_for_path(project_root, confirm_generate=True)
    assert gate["decision"] == "Allowed", gate
    generation_result = run_generation(project_root, gate)
    return project_root, gate, generation_result


def test_write_generation_receipt_writes_expected_path(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    receipt_path = write_generation_receipt(project_root, gate, generation_result)
    assert receipt_path == project_root / GENERATED_DIRNAME / RECEIPT_FILENAME
    assert receipt_path.is_file()


def test_build_execution_receipt_shape(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    receipt = build_execution_receipt(project_root, gate, generation_result)
    assert set(receipt.keys()) == {
        "project", "engine", "backend", "template", "readiness_score", "readiness_state",
        "execution_decision", "files_generated", "artifact_sizes", "artifact_tracking",
        "validation_status", "warnings", "errors", "success", "timestamp",
    }


def test_build_execution_receipt_field_values(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    receipt = build_execution_receipt(project_root, gate, generation_result)
    assert receipt["project"] == str(project_root)
    assert receipt["engine"] == "OpenSCAD"
    assert receipt["backend"] == "openscad"
    assert receipt["template"] == "sign"
    assert receipt["execution_decision"] == "Allowed"
    assert receipt["files_generated"] == ["cad/sign.scad"]
    assert receipt["artifact_sizes"]["cad/sign.scad"] > 0
    assert receipt["warnings"] == []
    assert receipt["errors"] == []
    assert receipt["success"] is True
    assert isinstance(receipt["timestamp"], str) and receipt["timestamp"]
    assert receipt["validation_status"] == "not_yet_validated"


def test_build_execution_receipt_never_raises_on_missing_plan(isolated_projects_dir):
    project_root = project_store.init_project("No Plan Project")
    gate = {"decision": "Allowed", "recommended_engine": "OpenSCAD", "readiness_state": "x", "readiness_score": 1, "plan": None}
    receipt = build_execution_receipt(project_root, gate, {"written_files": [], "warnings": []})
    assert receipt["engine"] == "OpenSCAD"
    assert receipt["template"] is None
    assert receipt["files_generated"] == []


def test_write_generation_receipt_overwrites_previous_receipt(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    first_path = write_generation_receipt(project_root, gate, generation_result)
    first = project_store.load_json(first_path)
    second_path = write_generation_receipt(project_root, gate, generation_result)
    second = project_store.load_json(second_path)
    assert first_path == second_path
    assert first["engine"] == second["engine"]


# ---- dry runs never produce receipts ----


def test_dry_run_never_creates_generated_directory(isolated_projects_dir):
    project_root = _ready_project(project_store.init_project("Classroom Sign"))
    evaluate_generation_gate_for_path(project_root)  # confirm_generate defaults to False
    assert not (project_root / GENERATED_DIRNAME).exists()


def test_evaluate_generation_gate_for_path_never_creates_generated_directory():
    evaluate_generation_gate_for_path(STORAGE_BIN_LID_PATH)
    assert not (STORAGE_BIN_LID_PATH / GENERATED_DIRNAME).exists()


# ---- build_artifact_tracking() ----


def test_build_artifact_tracking_categorizes_openscad_source(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    tracking = build_artifact_tracking(project_root, generation_result["written_files"])
    assert tracking["cad_source"] == [{"path": generation_result["written_files"][0], "category": "OpenSCAD"}]


def test_build_artifact_tracking_categorizes_cadquery_source():
    assert generation_gate._cad_source_category("cad/mechanical_plate.py") == "CadQuery"
    assert generation_gate._cad_source_category("cad/sign.scad") == "OpenSCAD"
    assert generation_gate._cad_source_category("cad/whatever.stl") == "Other"


def test_build_artifact_tracking_only_includes_matched_manifest_parts(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    # Add an unrelated manifest entry (as if from a different, earlier generation) -
    # it must never leak into this generation's artifact tracking.
    manifest_path = project_root / "part_manifest.json"
    manifest = project_store.load_json(manifest_path)
    manifest["parts"].append({"part_name": "unrelated", "file_path": "stl/unrelated.stl", "cad_source": "cad/unrelated.scad"})
    project_store.save_json(manifest_path, manifest)

    tracking = build_artifact_tracking(project_root, generation_result["written_files"])
    part_names = [p["part_name"] for p in tracking["manifest"]["parts"]]
    assert "unrelated" not in part_names
    assert "sign" in part_names


def test_build_artifact_tracking_stl_not_yet_exported(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    tracking = build_artifact_tracking(project_root, generation_result["written_files"])
    assert tracking["stl"] == [{"part_name": "sign", "expected_path": "stl/sign.stl", "exists": False, "size_bytes": None}]
    assert tracking["validation"] == [{"part_name": "sign", "status": "not_yet_validated", "report_path": None}]
    assert tracking["preview"] == [{"part_name": "sign", "status": "not_yet_rendered", "render_path": None}]
    assert "factory review-gate" in tracking["review"]


def test_build_artifact_tracking_reuses_an_existing_validation_report_never_revalidates(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    stl_path = project_root / "stl" / "sign.stl"
    stl_path.write_bytes(b"not a real mesh, just proving file-existence tracking")
    validation_report = {"overall_status": "PASS", "checks": []}
    project_store.save_json(project_root / "validation" / "sign_validation.json", validation_report)

    tracking = build_artifact_tracking(project_root, generation_result["written_files"])
    assert tracking["stl"][0]["exists"] is True
    assert tracking["stl"][0]["size_bytes"] > 0
    assert tracking["validation"][0]["status"] == "PASS"
    assert tracking["validation"][0]["report_path"] == "validation/sign_validation.json"

    receipt = build_execution_receipt(project_root, gate, generation_result)
    assert receipt["validation_status"] == "PASS"


def test_build_artifact_tracking_never_writes_anything(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    before = sorted(str(p) for p in project_root.rglob("*"))
    build_artifact_tracking(project_root, generation_result["written_files"])
    after = sorted(str(p) for p in project_root.rglob("*"))
    assert before == after


def test_build_artifact_tracking_empty_written_files_returns_empty_sections():
    tracking = build_artifact_tracking(project_store.REPO_ROOT / "examples" / "storage-bin-lid", [])
    assert tracking["cad_source"] == []
    assert tracking["manifest"]["parts"] == []
    assert tracking["stl"] == []


# ---- read_last_execution_receipt() / summarize_generation_execution() ----


def test_read_last_execution_receipt_none_when_missing(isolated_projects_dir):
    project_root = project_store.init_project("No Receipt Yet")
    assert read_last_execution_receipt(project_root) is None


def test_read_last_execution_receipt_returns_written_receipt(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    write_generation_receipt(project_root, gate, generation_result)
    receipt = read_last_execution_receipt(project_root)
    assert receipt is not None
    assert receipt["engine"] == "OpenSCAD"


def test_read_last_execution_receipt_tolerates_corrupt_json(isolated_projects_dir):
    project_root = project_store.init_project("Corrupt Receipt")
    receipt_path = project_root / GENERATED_DIRNAME / RECEIPT_FILENAME
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{not valid json", encoding="utf-8")
    assert read_last_execution_receipt(project_root) is None


def test_summarize_generation_execution_shape_with_no_receipt(isolated_projects_dir):
    project_root = project_store.init_project("No Receipt Project")
    summary = summarize_generation_execution(project_root)
    assert set(summary.keys()) == {"receipt_available", "last_execution", "last_execution_engine"}
    assert summary == {"receipt_available": False, "last_execution": None, "last_execution_engine": None}


def test_summarize_generation_execution_reflects_a_written_receipt(allowed_generation):
    project_root, gate, generation_result = allowed_generation
    write_generation_receipt(project_root, gate, generation_result)
    summary = summarize_generation_execution(project_root)
    assert summary["receipt_available"] is True
    assert summary["last_execution_engine"] == "OpenSCAD"
    assert isinstance(summary["last_execution"], str) and summary["last_execution"]


def test_summarize_generation_execution_never_writes_anything(isolated_projects_dir):
    project_root = project_store.init_project("Read Only Check")
    before = sorted(str(p) for p in project_root.rglob("*"))
    summarize_generation_execution(project_root)
    after = sorted(str(p) for p in project_root.rglob("*"))
    assert before == after
    assert not (project_root / GENERATED_DIRNAME).exists()


# ---- summarize_generation_gate() shape is unchanged by execution-receipt additions ----


def test_summarize_generation_gate_shape_unaffected_by_execution_receipts():
    # summarize_generation_gate()'s own shape must stay exactly as every
    # existing Generation Gate test already pins it - "last_execution"/
    # "receipt_available" live on the separate summarize_generation_execution()
    # function/field instead. See docs/generation-gate.md.
    summary = summarize_generation_gate({}, {"readiness_state": "Not Ready", "recommended_engine": "Unknown", "score": {"overall": 0}, "advisories": []})
    assert set(summary.keys()) == {"decision", "recommended_engine", "ready", "reason"}
