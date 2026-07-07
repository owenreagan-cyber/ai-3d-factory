import re

import pytest

from factory import project_store

DESIGN_QUALITY_STANDARD_PATH = project_store.REPO_ROOT / "docs" / "design-quality-standard.md"
ROADMAP_PATH = project_store.REPO_ROOT / "docs" / "roadmap.md"
EXAMPLES_LIBRARY_PATH = project_store.REPO_ROOT / "docs" / "examples-library.md"
MESHY_GATE_PATH = project_store.REPO_ROOT / "docs" / "meshy-approval-gate.md"
BLENDER_TRACK_PATH = project_store.REPO_ROOT / "docs" / "blender-local-track.md"

NEW_CONCEPT_DIRS = (
    "future-organic-models/piggy-bank-design-study",
    "future-functional-designs/chip-bag-clip-study",
)

FUTURE_ORGANIC_README_PATHS = (
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "README.md",
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "car-concept" / "README.md",
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "animal-concept" / "README.md",
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "human-figure-study" / "README.md",
)

FORBIDDEN_JSON_KEYS = ("human_approved", "print_ready")


def _content(path) -> str:
    return path.read_text(encoding="utf-8").lower()


def _normalized(path) -> str:
    # Markdown source line-wraps prose, so normalize whitespace before
    # searching for a multi-word phrase that may span a line break.
    return " ".join(_content(path).split())


# ---- existence and required content ----


def test_design_quality_standard_doc_exists():
    assert DESIGN_QUALITY_STANDARD_PATH.is_file()


def test_mentions_etsy_worthy():
    assert "etsy-worthy" in _normalized(DESIGN_QUALITY_STANDARD_PATH)


def test_mentions_piggy_bank():
    assert "piggy bank" in _content(DESIGN_QUALITY_STANDARD_PATH)


def test_mentions_chip_bag_clip_and_tension_flex():
    content = _content(DESIGN_QUALITY_STANDARD_PATH)
    assert "chip bag clip" in content or "chip clip" in content
    assert "tension" in content
    assert "flex" in content


def test_says_not_blobby_blocky_generic():
    content = _content(DESIGN_QUALITY_STANDARD_PATH)
    for word in ("blobby", "blocky", "generic"):
        assert word in content, f"missing {word!r}"


def test_mentions_print_ready_and_human_approved_only_as_requirements_not_claims():
    content = _normalized(DESIGN_QUALITY_STANDARD_PATH)
    assert "print_ready" in content
    assert "human_approved" in content
    # The doc must state plainly that it changes no behavior/gate - a claim
    # that would be false if it also silently granted either status.
    assert "does not implement any generation pipeline" in content
    assert "does not relax any safety gate" in content


def test_core_principle_present():
    content = _normalized(DESIGN_QUALITY_STANDARD_PATH)
    assert "can it generate a printable mesh" in content
    assert "polished, useful, and visually intentional" in content


def test_both_design_tracks_present():
    content = _content(DESIGN_QUALITY_STANDARD_PATH)
    assert "artistic / organic custom design track" in content or "artistic/organic" in content
    assert "functional / mechanical custom design track" in content or "functional/mechanical" in content


def test_functional_track_says_prototype_until_tested():
    content = _normalized(DESIGN_QUALITY_STANDARD_PATH)
    assert "must be treated as prototypes until" in content
    assert "without a human actually testing" in content or "without human testing" in content


# ---- roadmap / examples-library cross-references ----


def test_roadmap_has_custom_design_quality_pipeline_track():
    assert "custom design quality pipeline" in _content(ROADMAP_PATH)


def test_roadmap_custom_design_quality_pipeline_is_unnumbered():
    content = ROADMAP_PATH.read_text(encoding="utf-8")
    marker = "## Future tracks, not yet phase-numbered"
    assert marker in content
    tracks_section = content.split(marker, 1)[1]
    assert "Custom Design Quality Pipeline" in tracks_section
    assert not re.search(r"###\s*phase\s+\d+", tracks_section.lower())


def test_examples_library_mentions_design_quality_standard():
    assert "design-quality-standard.md" in _content(EXAMPLES_LIBRARY_PATH)


@pytest.mark.parametrize("path", FUTURE_ORGANIC_README_PATHS)
def test_future_organic_readme_references_design_quality_standard(path):
    assert "design-quality-standard.md" in path.read_text(encoding="utf-8")


# ---- new concept study dirs remain concept-only ----


def test_future_functional_designs_readme_exists():
    path = project_store.REPO_ROOT / "examples" / "future-functional-designs" / "README.md"
    assert path.is_file()


@pytest.mark.parametrize("relative", NEW_CONCEPT_DIRS)
def test_new_concept_study_has_no_brief_json_or_generated_assets(relative):
    root = project_store.REPO_ROOT / "examples" / relative
    assert not (root / "brief.json").is_file()
    assert not any(root.rglob("*.stl"))
    assert not any(root.rglob("*.png"))
    assert not (root / "cad").exists()


@pytest.mark.parametrize("relative", NEW_CONCEPT_DIRS)
def test_new_concept_study_is_marked_concept_only(relative):
    concept_brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / relative / "concept_brief.json"
    )
    assert concept_brief["status"] == "concept_only"
    assert concept_brief["not_printable"] is True
    assert concept_brief["not_generated"] is True


def _assert_no_forbidden_keys(data, path):
    if isinstance(data, dict):
        for key in FORBIDDEN_JSON_KEYS:
            assert key not in data, f"{path} must not set {key!r}"
        for value in data.values():
            _assert_no_forbidden_keys(value, path)
    elif isinstance(data, list):
        for item in data:
            _assert_no_forbidden_keys(item, path)


@pytest.mark.parametrize("relative", NEW_CONCEPT_DIRS)
def test_new_concept_study_sets_no_human_approved_or_print_ready(relative):
    concept_brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / relative / "concept_brief.json"
    )
    _assert_no_forbidden_keys(concept_brief, relative)


# ---- no STL/PNG/binary assets anywhere under examples/ ----


def test_examples_dir_still_has_no_stl_or_png_files():
    examples_dir = project_store.REPO_ROOT / "examples"
    assert not any(examples_dir.rglob("*.stl"))
    assert not any(examples_dir.rglob("*.png"))


# ---- no real secrets/.env files ----


def test_no_real_env_file_exists():
    assert not (project_store.REPO_ROOT / ".env").is_file()


def test_new_docs_contain_no_secret_like_markers():
    suspicious_markers = (
        "sk-ant-", "sk-proj-", "sk-live-", "AIzaSy",
        "MESHY_API_KEY=", "OPENAI_API_KEY=", "GEMINI_API_KEY=", "ANTHROPIC_API_KEY=",
    )
    paths = (
        DESIGN_QUALITY_STANDARD_PATH,
        project_store.REPO_ROOT / "examples" / "future-organic-models" / "piggy-bank-design-study" / "concept_brief.json",
        project_store.REPO_ROOT / "examples" / "future-functional-designs" / "chip-bag-clip-study" / "concept_brief.json",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for marker in suspicious_markers:
            assert marker not in text, f"{path} contains a suspicious secret-like marker: {marker!r}"


# ---- Phase 22: future gate docs connected to the design-quality standard ----


def test_meshy_gate_doc_references_design_quality_standard():
    content = _content(MESHY_GATE_PATH)
    assert "design-quality-standard.md" in content
    assert "etsy-worthy" in content


def test_meshy_gate_doc_says_generated_mesh_is_not_enough():
    content = _normalized(MESHY_GATE_PATH)
    assert "must not be accepted merely because it generated a mesh" in content


def test_meshy_gate_doc_mentions_piggy_bank_and_avoids_pig_shaped_blob():
    content = _normalized(MESHY_GATE_PATH)
    assert "piggy bank" in content
    assert "pig-shaped blob" in content or "pig shaped blob" in content


def test_meshy_gate_doc_has_design_quality_gate_section():
    content = MESHY_GATE_PATH.read_text(encoding="utf-8")
    assert "## Design-quality gate" in content


def test_meshy_still_disabled_and_future_gated_after_phase22():
    content = _content(MESHY_GATE_PATH)
    assert "does not implement" in content
    assert "no code in this repo calls meshy" in content
    assert "future_gate_required" in content or "future-gated" in content or "future_gated" in content


def test_blender_track_doc_references_design_quality_preservation():
    content = _content(BLENDER_TRACK_PATH)
    assert "design-quality-standard.md" in content
    assert "design-quality review for blender outputs" in content


def test_blender_track_doc_says_preserve_or_improve_design_quality():
    content = _normalized(BLENDER_TRACK_PATH)
    assert "preserve or improve" in content


def test_blender_still_future_only_and_not_automated_after_phase22():
    content = _content(BLENDER_TRACK_PATH)
    assert "does not implement blender automation" in _normalized(BLENDER_TRACK_PATH)
    assert "no code in this repo launches blender" in content


def test_roadmap_meshy_and_blender_tracks_reference_design_quality():
    raw = ROADMAP_PATH.read_text(encoding="utf-8")
    marker = "## Future tracks, not yet phase-numbered"
    assert marker in raw
    # Normalize whitespace - markdown line-wraps prose, so a quoted
    # multi-word section title can span a line break in the raw source.
    tracks_section = " ".join(raw.split(marker, 1)[1].lower().split())
    assert "design-quality gate" in tracks_section
    assert "design-quality review for blender outputs" in tracks_section


def test_roadmap_still_mentions_custom_design_quality_pipeline_unnumbered():
    content = ROADMAP_PATH.read_text(encoding="utf-8")
    marker = "## Future tracks, not yet phase-numbered"
    tracks_section = content.split(marker, 1)[1]
    assert "Custom Design Quality Pipeline" in tracks_section
    assert not re.search(r"###\s*phase\s+\d+", tracks_section.lower())


@pytest.mark.parametrize(
    "path",
    (
        project_store.REPO_ROOT / "examples" / "future-organic-models" / "piggy-bank-design-study" / "README.md",
        project_store.REPO_ROOT / "examples" / "future-functional-designs" / "chip-bag-clip-study" / "README.md",
    ),
)
def test_concept_study_readme_links_to_future_gate_docs(path):
    text = path.read_text(encoding="utf-8")
    assert "meshy-approval-gate.md" in text or "blender-local-track.md" in text


def test_gate_modules_still_have_no_execution_code_after_phase22():
    # Phase 22 is docs/planning only - the source modules backing the
    # existing gate CLI commands should be untouched. Re-runs the same
    # no-subprocess check test_meshy_gate.py/test_blender_gate.py already
    # apply, as a cheap cross-check specific to this phase's doc-only claim.
    import inspect

    from factory import future_cloud_tools, future_local_tools

    for module in (future_cloud_tools, future_local_tools):
        source = inspect.getsource(module)
        for forbidden in ("subprocess.run(", "subprocess.call(", "subprocess.Popen("):
            assert forbidden not in source, f"{module.__name__} must stay execution-free; found {forbidden!r}"


def test_examples_dir_still_has_no_stl_or_png_files_after_phase22():
    examples_dir = project_store.REPO_ROOT / "examples"
    assert not any(examples_dir.rglob("*.stl"))
    assert not any(examples_dir.rglob("*.png"))
