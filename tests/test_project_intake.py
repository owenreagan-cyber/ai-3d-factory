"""Phase 30 tests: `factory.project_intake` - the local, fully deterministic
Project Intake Engine. No AI, no LLM, no network, no search - closed
keyword tables and regexes only. See docs/project-intake.md,
docs/roadmap.md Phase 30.
"""

import inspect

import pytest

from factory import project_intake, project_store
from factory.project_intake import (
    CATEGORIES,
    CONFIDENCE_LEVELS,
    ENVIRONMENTS,
    MATERIALS,
    PRINTERS,
    QUALITY_TARGETS,
    SOURCES,
    analyze,
    analyze_project,
    analyze_text,
    analyze_text_file,
    extract_intake_fields,
)

_INTAKE_KEYS = {
    "project_name", "category", "purpose", "audience", "environment",
    "material_assumptions", "printer_assumptions", "quality_target",
    "manufacturing_style", "functional_goals", "visual_goals",
    "dimensional_constraints", "commercial_intent", "warnings",
}


def _assert_well_shaped(summary):
    assert _INTAKE_KEYS <= set(summary.keys())
    for key in _INTAKE_KEYS - {"warnings"}:
        field = summary[key]
        assert set(field.keys()) == {"value", "confidence"}
        assert field["confidence"] in CONFIDENCE_LEVELS
    assert isinstance(summary["warnings"], list)
    assert all(isinstance(w, str) for w in summary["warnings"])


# ---- vocabulary sanity ----


def test_categories_include_all_required_values():
    assert set(CATEGORIES) == {
        "sign", "organizer", "toy", "décor", "fixture", "mechanical",
        "educational", "storage", "replacement part", "accessory", "unknown",
    }


def test_environments_include_all_required_values():
    assert set(ENVIRONMENTS) == {"classroom", "office", "home", "garage", "outdoor", "unknown"}


def test_materials_include_all_required_values():
    assert set(MATERIALS) == {"PLA", "PETG", "ABS", "TPU", "unknown"}


def test_printers_include_all_required_values():
    assert set(PRINTERS) == {"Bambu", "Prusa", "Voron", "generic FDM", "unknown"}


def test_quality_targets_include_all_required_values():
    assert set(QUALITY_TARGETS) == {
        "prototype", "functional", "premium", "etsy-worthy", "presentation", "gift", "unknown",
    }


def test_confidence_levels_are_exactly_four_values():
    assert CONFIDENCE_LEVELS == ("high", "medium", "low", "unknown")


def test_sources_include_all_required_values():
    assert set(SOURCES) == {"brief_description", "text_file", "markdown_file", "none"}


# ---- empty / minimal / malformed-looking input ----


def test_empty_text_returns_clean_unknown_result():
    summary = extract_intake_fields("")
    _assert_well_shaped(summary)
    assert summary["category"]["value"] == "unknown"
    assert summary["category"]["confidence"] == "unknown"
    assert summary["material_assumptions"]["value"] == []
    assert summary["commercial_intent"]["value"] is False
    assert "No project description text found to analyze" in summary["warnings"][0]


def test_whitespace_only_text_treated_as_empty():
    summary = extract_intake_fields("   \n\t  ")
    assert summary["warnings"] == ["No project description text found to analyze - nothing could be inferred."]


def test_never_raises_on_arbitrary_garbage_text():
    garbage = "{[<>]}!!!\x00\x01 \\n \\t %%% ### @@@ 12345 ,,,, ;;;;"
    summary = extract_intake_fields(garbage)  # must not raise
    _assert_well_shaped(summary)


def test_minimal_single_sentence_input():
    summary = extract_intake_fields("I want a small box.")
    _assert_well_shaped(summary)
    assert summary["purpose"]["value"] == "I want a small box."
    assert summary["category"]["value"] == "unknown"
    assert "Human review recommended" in " ".join(summary["warnings"])


# ---- category ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("I want a nameplate for my desk.", "sign"),
        ("I need a small organizer for pens.", "organizer"),
        ("Design a toy figurine for my kid.", "toy"),
        ("A decorative centerpiece for the table.", "décor"),
        ("A wall mount bracket for my router.", "fixture"),
        ("A gear and hinge mechanism for the lid.", "mechanical"),
        ("A storage bin for the garage.", "storage"),
        ("A replacement part for my broken vacuum.", "replacement part"),
        ("A phone case accessory.", "accessory"),
    ],
)
def test_category_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["category"]["value"] == expected
    assert summary["category"]["confidence"] in ("high", "medium")


def test_category_unknown_when_no_keyword_present():
    summary = extract_intake_fields("Something indescribable and abstract.")
    assert summary["category"]["value"] == "unknown"
    assert summary["category"]["confidence"] == "unknown"


def test_category_confidence_high_for_single_unambiguous_match():
    summary = extract_intake_fields("A simple toy for the yard.")
    # "toy" matches category=toy; "yard" matches environment=outdoor - these
    # are different fields, so category itself should be unambiguous here.
    assert summary["category"]["value"] == "toy"
    assert summary["category"]["confidence"] == "high"


def test_category_confidence_medium_when_multiple_categories_match():
    summary = extract_intake_fields("A classroom sign for the teacher.")
    # "sign" -> sign; "classroom"/"teacher" -> educational: two distinct
    # category candidates present, resolved to the first (sign) but flagged
    # as ambiguous via "medium" confidence.
    assert summary["category"]["value"] == "sign"
    assert summary["category"]["confidence"] == "medium"


# ---- environment ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A sign for my classroom.", "classroom"),
        ("A tray for the office cubicle.", "office"),
        ("A decoration for my living room.", "home"),
        ("A tool holder for the garage workshop.", "garage"),
        ("A planter for the garden patio.", "outdoor"),
    ],
)
def test_environment_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["environment"]["value"] == expected


def test_environment_unknown_when_absent():
    summary = extract_intake_fields("A generic object with no context.")
    assert summary["environment"]["value"] == "unknown"
    assert summary["environment"]["confidence"] == "unknown"


# ---- material / printer assumptions ----


@pytest.mark.parametrize("text,expected", [
    ("Print it in PLA.", ["PLA"]),
    ("Use PETG for durability.", ["PETG"]),
    ("ABS is preferred for heat resistance.", ["ABS"]),
    ("A flexible TPU part.", ["TPU"]),
])
def test_material_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["material_assumptions"]["value"] == expected
    assert summary["material_assumptions"]["confidence"] == "high"


def test_material_multiple_values_all_captured():
    summary = extract_intake_fields("Either PLA or PETG would work.")
    assert set(summary["material_assumptions"]["value"]) == {"PLA", "PETG"}
    assert summary["material_assumptions"]["confidence"] == "high"


def test_material_unknown_when_absent():
    summary = extract_intake_fields("No material mentioned here.")
    assert summary["material_assumptions"]["value"] == []
    assert summary["material_assumptions"]["confidence"] == "unknown"
    assert "Material not specified." in summary["warnings"]


@pytest.mark.parametrize("text,expected", [
    ("Printed on a Bambu printer.", ["Bambu"]),
    ("I use a Prusa MK4.", ["Prusa"]),
    ("Built for a Voron 2.4.", ["Voron"]),
    ("Any generic FDM printer works.", ["generic FDM"]),
])
def test_printer_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["printer_assumptions"]["value"] == expected


def test_printer_unknown_when_absent():
    summary = extract_intake_fields("No printer mentioned here.")
    assert summary["printer_assumptions"]["value"] == []
    assert "Printer not specified." in summary["warnings"]


def test_ams_keyword_implies_bambu_printer():
    summary = extract_intake_fields("It needs to be AMS compatible.")
    assert summary["printer_assumptions"]["value"] == ["Bambu"]


# ---- quality target ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Just a quick prototype for testing.", "prototype"),
        ("A functional prototype that needs to work reliably.", "functional"),
        ("A premium finish is expected.", "premium"),
        ("This should be etsy-worthy quality.", "etsy-worthy"),
        ("A presentation-quality showpiece for display.", "presentation"),
        ("This is meant as a gift for my sister.", "gift"),
    ],
)
def test_quality_target_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["quality_target"]["value"] == expected


def test_quality_target_unknown_when_absent():
    summary = extract_intake_fields("A plain object with no quality mentioned.")
    assert summary["quality_target"]["value"] == "unknown"


def test_quality_target_priority_etsy_worthy_wins_over_premium_and_gift():
    summary = extract_intake_fields("A premium, etsy-worthy, gift-quality piece.")
    assert summary["quality_target"]["value"] == "etsy-worthy"
    assert summary["quality_target"]["confidence"] == "medium"  # multiple candidates present


def test_gift_quality_triggers_advisory():
    summary = extract_intake_fields("This is meant as a gift for my sister, made from PLA on a Bambu printer.")
    assert "Gift-quality target detected" in " ".join(summary["warnings"])


# ---- manufacturing style ----


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A multi-part assembly.", ["multi-part"]),
        ("A single-part, one-piece design.", ["single-part"]),
        ("Needs to be AMS compatible.", ["AMS"]),
        ("A multi-color, two-tone design.", ["multi-color"]),
        ("A single-color print.", ["single-color"]),
        ("Please avoid supports if possible.", ["support-free preferred"]),
    ],
)
def test_manufacturing_style_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["manufacturing_style"]["value"] == expected


def test_modular_keyword_maps_to_multi_part():
    summary = extract_intake_fields("A modular design that can be reprinted in pieces.")
    assert "multi-part" in summary["manufacturing_style"]["value"]


# ---- functional / visual goals ----


def test_functional_goals_detects_mechanical_keywords():
    summary = extract_intake_fields("It needs to hold small items and clip onto a shelf with a hinge.")
    assert "hold" in summary["functional_goals"]["value"]
    assert "clip" in summary["functional_goals"]["value"]
    assert "hinge" in summary["functional_goals"]["value"]
    assert summary["functional_goals"]["confidence"] == "high"
    assert "Mechanical testing recommended" in " ".join(summary["warnings"])


def test_functional_goals_empty_when_purely_decorative():
    summary = extract_intake_fields("A purely decorative display piece, not functional or mechanical in any way.")
    # "not functional" is a negation this heuristic can't understand (no NLP) -
    # it may still flag the word "functional" as a quality-target keyword,
    # but functional_goals itself only scans a *different*, disjoint keyword
    # set (hold/clip/hinge/etc.), so it stays empty here - this is the
    # documented "no negation understanding" limitation in practice.
    assert summary["functional_goals"]["value"] == []
    assert "Mechanical testing recommended" not in " ".join(summary["warnings"])


def test_visual_goals_detects_style_keywords():
    summary = extract_intake_fields("An anime-inspired design with raised lettering.")
    assert "anime" in summary["visual_goals"]["value"]
    assert "raised" in summary["visual_goals"]["value"]
    assert "lettering" in summary["visual_goals"]["value"]
    assert summary["visual_goals"]["confidence"] == "high"


def test_visual_goals_single_match_is_medium_confidence():
    summary = extract_intake_fields("A minimalist design.")
    assert summary["visual_goals"]["value"] == ["minimalist"]
    assert summary["visual_goals"]["confidence"] == "medium"


# ---- dimensional constraints ----


@pytest.mark.parametrize("text,expected_substr", [
    ("It should be 120mm wide.", "120mm"),
    ("About 48-inch across.", "48-inch"),
    ("Roughly 30 cm tall.", "30 cm"),
    ("A 6 inch diameter part.", "6 inch"),
])
def test_dimensional_constraint_detection(text, expected_substr):
    summary = extract_intake_fields(text)
    assert any(expected_substr.lower() in m.lower() for m in summary["dimensional_constraints"]["value"])
    assert summary["dimensional_constraints"]["confidence"] == "high"


def test_dimensional_constraints_empty_triggers_advisory():
    summary = extract_intake_fields("A box with no size mentioned.")
    assert summary["dimensional_constraints"]["value"] == []
    assert "Dimensions not specified." in summary["warnings"]


def test_dimensional_constraint_does_not_false_positive_on_bare_in_word():
    # "in a classroom" should not be mistaken for an "in" (inch) unit -
    # only digit-adjacent unit tokens should match.
    summary = extract_intake_fields("A sign to hang in a classroom.")
    assert summary["dimensional_constraints"]["value"] == []


# ---- commercial intent ----


@pytest.mark.parametrize("text", [
    "I plan to sell these to customers.",
    "This is for my Etsy shop.",
    "Taking commissions for clients.",
])
def test_commercial_intent_detected(text):
    summary = extract_intake_fields(text)
    assert summary["commercial_intent"]["value"] is True
    assert summary["commercial_intent"]["confidence"] == "high"
    assert "Commercial intent detected" in " ".join(summary["warnings"])


def test_commercial_intent_not_triggered_by_etsy_worthy_quality_phrase():
    # "etsy-worthy" (a quality bar, docs/design-quality-standard.md) must not
    # be confused with actual commercial/selling language.
    summary = extract_intake_fields("This should be etsy-worthy quality, just for my own home.")
    assert summary["commercial_intent"]["value"] is False


def test_commercial_intent_false_by_default():
    summary = extract_intake_fields("A simple personal project.")
    assert summary["commercial_intent"]["value"] is False
    assert summary["commercial_intent"]["confidence"] == "unknown"


# ---- audience ----


@pytest.mark.parametrize("text,expected", [
    ("A toy for my students.", "Students"),
    ("Made for my teacher.", "Teachers"),
    ("A gift for my friend.", "Gift recipient"),
    ("For my customers.", "Customers"),
])
def test_audience_detection(text, expected):
    summary = extract_intake_fields(text)
    assert summary["audience"]["value"] == expected


def test_audience_none_when_absent():
    summary = extract_intake_fields("A generic object.")
    assert summary["audience"]["value"] is None
    assert summary["audience"]["confidence"] == "unknown"


# ---- purpose / project_name ----


def test_purpose_is_first_sentence():
    summary = extract_intake_fields("I want a sign. It should be blue. It should be small.")
    assert summary["purpose"]["value"] == "I want a sign."


def test_project_name_from_markdown_heading():
    text = "# My Cool Project\n\nSome description text here."
    summary = extract_intake_fields(text)
    assert summary["project_name"]["value"] == "My Cool Project"
    assert summary["project_name"]["confidence"] == "high"


def test_project_name_falls_back_to_first_short_line():
    text = "A Cool Nameplate\n\nMore descriptive text follows here about the design."
    summary = extract_intake_fields(text)
    assert summary["project_name"]["value"] == "A Cool Nameplate"
    assert summary["project_name"]["confidence"] == "medium"


def test_project_name_unknown_when_first_line_too_long():
    long_line = "This is a very long first line that reads like a full descriptive paragraph rather than a short title, well past eighty characters in length."
    summary = extract_intake_fields(long_line)
    assert summary["project_name"]["value"] is None
    assert summary["project_name"]["confidence"] == "unknown"


# ---- Unicode input ----


def test_unicode_input_handled_cleanly():
    # Keyword tables are English-only by design (documented limitation, no
    # multi-language support) - this asserts the module never raises and
    # still returns a well-shaped result on non-English/emoji input, not
    # that it understands French.
    text = "Un porte-clés décoratif pour ma salle de classe. Café, café, café! 你好世界 🎨"
    summary = extract_intake_fields(text)  # must not raise
    _assert_well_shaped(summary)
    assert summary["environment"]["value"] == "unknown"


def test_unicode_decor_keyword_matches_accented_form():
    summary = extract_intake_fields("A décor piece for the home.")
    assert summary["category"]["value"] == "décor"


# ---- analyze_text / source tagging ----


def test_analyze_text_tags_source():
    summary = analyze_text("A sign.", source="text_file")
    assert summary["source"] == "text_file"


# ---- analyze_text_file ----


def test_analyze_text_file_reads_plain_text(tmp_path):
    path = tmp_path / "idea.txt"
    path.write_text("A premium nameplate made of PLA.", encoding="utf-8")
    summary = analyze_text_file(path)
    assert summary["source"] == "text_file"
    assert summary["category"]["value"] == "sign"


def test_analyze_text_file_reads_markdown(tmp_path):
    path = tmp_path / "idea.md"
    path.write_text("# A Sign\n\nA premium nameplate.", encoding="utf-8")
    summary = analyze_text_file(path)
    assert summary["source"] == "markdown_file"
    assert summary["project_name"]["value"] == "A Sign"


def test_analyze_text_file_missing_file_returns_clean_result(tmp_path):
    summary = analyze_text_file(tmp_path / "does-not-exist.md")
    assert summary["category"]["value"] == "unknown"
    assert summary["warnings"]


def test_analyze_text_file_empty_file_returns_clean_result(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    summary = analyze_text_file(path)
    assert summary["category"]["value"] == "unknown"
    assert "No project description text found to analyze" in summary["warnings"][0]


def test_analyze_text_file_handles_non_utf8_bytes_gracefully(tmp_path):
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe\x00\x01garbage\x80\x81")
    summary = analyze_text_file(path)  # must not raise
    _assert_well_shaped(summary)


def test_analyze_text_file_unicode_content(tmp_path):
    path = tmp_path / "idea.md"
    path.write_text("# Décor pour salon\n\nUn décor élégant. 你好", encoding="utf-8")
    summary = analyze_text_file(path)
    assert summary["project_name"]["value"] == "Décor pour salon"
    assert summary["category"]["value"] == "décor"


def test_analyze_text_file_writes_no_files(tmp_path):
    path = tmp_path / "idea.md"
    path.write_text("# X", encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    analyze_text_file(path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- analyze_project ----


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def test_analyze_project_reads_brief_description(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy classroom sign made of PLA on a Bambu printer."
    project_store.save_json(brief_path, brief)

    summary = analyze_project(project_root)
    assert summary["source"] == "brief_description"
    assert summary["category"]["value"] == "sign"
    assert summary["material_assumptions"]["value"] == ["PLA"]


def test_analyze_project_prefers_brief_project_name(project_root):
    summary = analyze_project(project_root)
    assert summary["project_name"]["value"] == "Demo Project"
    assert summary["project_name"]["confidence"] == "high"


def test_analyze_project_missing_brief_returns_clean_result(isolated_projects_dir):
    empty_dir = isolated_projects_dir / "no-brief-here"
    empty_dir.mkdir()
    summary = analyze_project(empty_dir)
    assert summary["source"] == "none"
    assert summary["category"]["value"] == "unknown"


def test_analyze_project_malformed_brief_returns_clean_result(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    summary = analyze_project(project_root)
    assert summary["source"] == "none"


def test_analyze_project_includes_constraints_text(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["constraints"] = ["Must be printed in ABS for heat resistance."]
    project_store.save_json(brief_path, brief)

    summary = analyze_project(project_root)
    assert "ABS" in summary["material_assumptions"]["value"]


def test_analyze_project_writes_no_files(project_root):
    before = sorted(p.name for p in project_root.rglob("*") if p.is_file())
    analyze_project(project_root)
    after = sorted(p.name for p in project_root.rglob("*") if p.is_file())
    assert before == after


# ---- analyze() dispatch ----


def test_analyze_dispatches_to_project_for_directory(project_root):
    summary = analyze(project_root)
    assert summary["source"] == "brief_description"


def test_analyze_dispatches_to_text_file_for_file(tmp_path):
    path = tmp_path / "idea.md"
    path.write_text("# A Sign", encoding="utf-8")
    summary = analyze(path)
    assert summary["source"] == "markdown_file"


def test_analyze_nonexistent_path_returns_clean_result(tmp_path):
    summary = analyze(tmp_path / "does-not-exist")
    assert summary["source"] == "none"
    assert summary["category"]["value"] == "unknown"


# ---- no forbidden network/AI/subprocess calls anywhere in this module ----


def test_project_intake_module_has_no_forbidden_calls():
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "openai", "anthropic", "import torch", "import tensorflow", "import sklearn",
        "write_text(", "write_bytes(", "save_json(",
    )
    source = inspect.getsource(project_intake)
    for forbidden_call in forbidden:
        assert forbidden_call not in source, f"found forbidden call {forbidden_call!r} in project_intake.py"


def test_project_intake_module_does_not_set_human_approved_or_print_ready():
    source = inspect.getsource(project_intake)
    assert '"human_approved": True' not in source
    assert '"print_ready": True' not in source
