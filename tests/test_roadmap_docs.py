import re

from factory import project_store

ROADMAP_PATH = project_store.REPO_ROOT / "docs" / "roadmap.md"
PHASE_REGISTRY_PATH = project_store.REPO_ROOT / "docs" / "phase-registry.md"
MESHY_GATE_PATH = project_store.REPO_ROOT / "docs" / "meshy-approval-gate.md"
EXAMPLES_LIBRARY_PATH = project_store.REPO_ROOT / "docs" / "examples-library.md"
CAD_BACKENDS_PATH = project_store.REPO_ROOT / "docs" / "cad-backends.md"
FUTURE_ORGANIC_README = project_store.REPO_ROOT / "examples" / "future-organic-models" / "README.md"
CONCEPT_README_PATHS = (
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "car-concept" / "README.md",
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "animal-concept" / "README.md",
    project_store.REPO_ROOT / "examples" / "future-organic-models" / "human-figure-study" / "README.md",
)


def _content(path) -> str:
    return path.read_text(encoding="utf-8").lower()


# ---- existence ----


def test_roadmap_doc_exists():
    assert ROADMAP_PATH.is_file()


def test_phase_registry_doc_exists():
    assert PHASE_REGISTRY_PATH.is_file()


# ---- numbering policy (Phase 20) ----


def test_roadmap_has_numbering_policy_section():
    content = _content(ROADMAP_PATH)
    assert "roadmap numbering policy" in content
    assert "not yet phase-numbered" in content


def test_roadmap_has_future_tracks_section():
    content = _content(ROADMAP_PATH)
    assert "future tracks, not yet phase-numbered" in content


def test_roadmap_future_tracks_are_clearly_labeled_and_not_numbered():
    content = ROADMAP_PATH.read_text(encoding="utf-8")
    marker = "## Future tracks, not yet phase-numbered"
    assert marker in content
    tracks_section = content.split(marker, 1)[1]

    for track in (
        "meshy approval/cost-gated implementation track",
        "blender local repair/render track",
        "3mf packaging experiments track",
        "advanced slicer review automation track",
        "rich organic examples track",
        "mac launcher/dashboard track",
    ):
        assert track in tracks_section.lower(), f"missing track: {track!r}"

    # None of the track subheadings may look like a numbered phase heading
    # (e.g. "### Phase 21 - ...") - tracks are named, not pre-numbered.
    assert not re.search(r"###\s*phase\s+\d+", tracks_section.lower())


def test_phase_registry_lists_future_tracks_separately_from_numbered_phases():
    content = _content(PHASE_REGISTRY_PATH)
    assert "future tracks (not phase-numbered)" in content
    assert "meshy approval/cost-gated implementation track" in content
    assert "blender local repair/render track" in content


def test_phase_registry_numbered_rows_are_sequential_with_no_gaps():
    content = PHASE_REGISTRY_PATH.read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r"^\|\s*(\d+)\s*\|", content, re.MULTILINE)]
    assert numbers, "expected at least one purely-numeric phase row"
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), (
        f"phase-registry.md numbered rows have a gap or duplicate: {numbers}"
    )


# ---- Meshy remains future-gated only, never claimed implemented ----


def test_meshy_approval_gate_doc_says_not_implemented():
    content = _content(MESHY_GATE_PATH)
    assert "does not implement" in content
    assert "no code in this repo calls meshy" in content


def test_meshy_still_described_as_disabled_gated_future():
    content = _content(MESHY_GATE_PATH)
    for phrase in ("disabled", "future-only", "gated"):
        assert phrase in content, f"missing {phrase!r} in meshy-approval-gate.md"


def test_no_doc_claims_meshy_is_implemented():
    forbidden_phrases = (
        "meshy is implemented",
        "meshy is now implemented",
        "meshy is enabled",
        "meshy integration is complete",
    )
    for path in (ROADMAP_PATH, MESHY_GATE_PATH, EXAMPLES_LIBRARY_PATH, CAD_BACKENDS_PATH, FUTURE_ORGANIC_README):
        content = _content(path)
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{path} appears to claim Meshy is implemented ({phrase!r})"


# ---- Blender remains future-only, no automation, never claimed implemented ----


def test_blender_still_described_as_future_track_no_automation():
    content = _content(ROADMAP_PATH)
    assert "blender local repair/render track" in content
    assert "no blender add-ons" in content


def test_no_doc_claims_blender_automation_is_implemented():
    forbidden_phrases = (
        "blender automation is implemented",
        "blender integration is complete",
        "blender is now automated",
    )
    for path in (ROADMAP_PATH, EXAMPLES_LIBRARY_PATH, CAD_BACKENDS_PATH, FUTURE_ORGANIC_README):
        content = _content(path)
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{path} appears to claim Blender automation is implemented ({phrase!r})"


# ---- future-organic-models concept examples: still concept-only, docs use track language ----


def test_concept_readmes_reference_future_tracks_not_stale_phase_numbers():
    for path in CONCEPT_README_PATHS:
        content = path.read_text(encoding="utf-8").lower()
        assert "blender local repair/render track" in content
        assert "not printable" in content
        # Phase 20 was briefly (and incorrectly) cited here for Blender before
        # this cleanup - must not reappear as a stale forward reference.
        assert "phase 20" not in content
