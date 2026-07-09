"""Phase 28 tests: `factory.reference_board` - the local, read-only Reference
Board planning model. See docs/reference-board.md, docs/roadmap.md Phase 28.

This is planning/data-model scaffolding only - these tests exist to prove
no network/download/scrape/search behavior exists anywhere in this module,
not just that the summary shape is correct.
"""

import inspect

import pytest

from factory import project_store, reference_board
from factory.reference_board import (
    ATTACHED_TO_VALUES,
    LICENSES,
    SOURCE_TYPES,
    USAGE_INTENTS,
    read_reference_board,
    summarize_reference_board,
)


# ---- read_reference_board() ----


def test_read_reference_board_empty_when_file_missing(tmp_path):
    assert read_reference_board(tmp_path) == {"references": []}


def test_read_reference_board_empty_when_invalid_json(tmp_path):
    (tmp_path / "reference_board.json").write_text("{not valid json", encoding="utf-8")
    assert read_reference_board(tmp_path) == {"references": []}


def test_read_reference_board_empty_when_not_a_dict(tmp_path):
    (tmp_path / "reference_board.json").write_text('["a", "list"]', encoding="utf-8")
    assert read_reference_board(tmp_path) == {"references": []}


def test_read_reference_board_empty_when_references_not_a_list(tmp_path):
    (tmp_path / "reference_board.json").write_text('{"references": "not a list"}', encoding="utf-8")
    assert read_reference_board(tmp_path) == {"references": []}


def test_read_reference_board_returns_entries_as_read(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [{"title": "x"}]})
    assert read_reference_board(tmp_path) == {"references": [{"title": "x"}]}


def test_read_reference_board_writes_no_files(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": []})
    before = sorted(p.name for p in tmp_path.iterdir())
    read_reference_board(tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- summarize_reference_board(): clean empty result ----


def test_summarize_reference_board_clean_empty_result_when_missing(tmp_path):
    summary = summarize_reference_board(tmp_path)
    assert summary == {
        "reference_count": 0,
        "by_license": {},
        "by_source_type": {},
        "by_usage_intent": {},
        "attached_to_design_intent_count": 0,
        "warnings": [],
    }


def test_summarize_reference_board_clean_empty_result_when_explicitly_empty(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": []})
    summary = summarize_reference_board(tmp_path)
    assert summary["reference_count"] == 0
    assert summary["warnings"] == []


def test_summarize_reference_board_empty_when_malformed_json(tmp_path):
    (tmp_path / "reference_board.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_reference_board(tmp_path)
    assert summary["reference_count"] == 0


# ---- summarize_reference_board(): fully populated ----


FULL_REFERENCE = {
    "title": "Classroom storage inspiration",
    "source_url": "https://example.com/classroom-storage-reference",
    "source_type": "inspiration",
    "license": "cc_by",
    "usage_intent": "design_reference_only",
    "attached_to": "design_intent.reference_inputs",
    "notes": "Used only as a style and organization reference.",
}


def test_summarize_reference_board_fully_populated(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [FULL_REFERENCE]})
    summary = summarize_reference_board(tmp_path)

    assert summary["reference_count"] == 1
    assert summary["by_license"] == {"cc_by": 1}
    assert summary["by_source_type"] == {"inspiration": 1}
    assert summary["by_usage_intent"] == {"design_reference_only": 1}
    assert summary["attached_to_design_intent_count"] == 1
    assert summary["warnings"] == []  # cc_by is a known-good license, url present, attached


def test_summarize_reference_board_multiple_references_aggregate_correctly(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {
            "references": [
                {**FULL_REFERENCE, "title": "A", "license": "cc_by"},
                {**FULL_REFERENCE, "title": "B", "license": "cc_by"},
                {**FULL_REFERENCE, "title": "C", "license": "public_domain"},
            ]
        },
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["reference_count"] == 3
    assert summary["by_license"] == {"cc_by": 2, "public_domain": 1}


# ---- summarize_reference_board(): partial / malformed entries -> fallback + advisories ----


def test_summarize_reference_board_missing_license_defaults_to_unknown_with_warning(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "No license", "source_type": "image", "source_url": "https://x"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["by_license"] == {"unknown": 1}
    assert any("commercial use unclear" in w for w in summary["warnings"])


def test_summarize_reference_board_explicit_unknown_license_warns(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "X", "license": "unknown", "source_url": "https://x"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert any("commercial use unclear" in w for w in summary["warnings"])


def test_summarize_reference_board_missing_source_url_warns(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "No URL", "license": "cc_by"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert any("no source_url recorded" in w for w in summary["warnings"])


@pytest.mark.parametrize("license_value", ["unknown", "proprietary"])
def test_summarize_reference_board_remix_candidate_with_unsafe_license_warns(tmp_path, license_value):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {
            "references": [
                {
                    "title": "Risky remix",
                    "license": license_value,
                    "usage_intent": "remix_candidate",
                    "source_url": "https://x",
                }
            ]
        },
    )
    summary = summarize_reference_board(tmp_path)
    assert any("remix candidate" in w and "do not remix" in w for w in summary["warnings"])


def test_summarize_reference_board_remix_candidate_with_safe_license_no_remix_warning(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {
            "references": [
                {
                    "title": "Safe remix",
                    "license": "public_domain",
                    "usage_intent": "remix_candidate",
                    "source_url": "https://x",
                }
            ]
        },
    )
    summary = summarize_reference_board(tmp_path)
    assert not any("do not remix" in w for w in summary["warnings"])


def test_summarize_reference_board_unsupported_source_type_warns_and_falls_back(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "X", "source_type": "not_a_real_type", "license": "cc_by", "source_url": "https://x"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["by_source_type"] == {"unknown": 1}
    assert any("source_type" in w and "not a supported value" in w for w in summary["warnings"])


def test_summarize_reference_board_unrecognized_license_warns_and_falls_back(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "X", "license": "not_a_real_license", "source_url": "https://x"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["by_license"] == {"unknown": 1}
    assert any("license" in w and "not a supported value" in w for w in summary["warnings"])


def test_summarize_reference_board_unrecognized_usage_intent_warns(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "X", "usage_intent": "not_a_real_intent", "license": "cc_by", "source_url": "https://x"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["by_usage_intent"] == {}
    assert any("usage_intent" in w and "not a supported value" in w for w in summary["warnings"])


def test_summarize_reference_board_malformed_entry_not_a_dict_skipped_with_warning(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": ["not a dict", 123, None, FULL_REFERENCE]},
    )
    summary = summarize_reference_board(tmp_path)
    # 4 declared entries total, but only 1 valid one contributes to breakdowns.
    assert summary["reference_count"] == 4
    assert summary["by_license"] == {"cc_by": 1}
    malformed_warnings = [w for w in summary["warnings"] if "is not a valid object and was skipped" in w]
    assert len(malformed_warnings) == 3


def test_summarize_reference_board_untitled_entry_gets_a_positional_fallback_title(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [{"license": "unknown"}]})
    summary = summarize_reference_board(tmp_path)
    assert any(w.startswith("Reference #1:") for w in summary["warnings"])


def test_summarize_reference_board_no_references_attached_to_design_intent_warns(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": "X", "license": "cc_by", "source_url": "https://x", "attached_to": "project"}]},
    )
    summary = summarize_reference_board(tmp_path)
    assert summary["attached_to_design_intent_count"] == 0
    assert "No references are attached to design_intent.reference_inputs yet." in summary["warnings"]


def test_summarize_reference_board_attached_reference_does_not_trigger_unattached_warning(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [FULL_REFERENCE]})
    summary = summarize_reference_board(tmp_path)
    assert "No references are attached to design_intent.reference_inputs yet." not in summary["warnings"]


def test_summarize_reference_board_is_deterministic(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [FULL_REFERENCE]})
    assert summarize_reference_board(tmp_path) == summarize_reference_board(tmp_path)


def test_summarize_reference_board_writes_no_files(tmp_path):
    project_store.save_json(tmp_path / "reference_board.json", {"references": [FULL_REFERENCE]})
    before = sorted(p.name for p in tmp_path.iterdir())
    summarize_reference_board(tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- never a hard failure - advisory only ----


def test_summarize_reference_board_never_raises_on_wildly_malformed_input(tmp_path):
    project_store.save_json(
        tmp_path / "reference_board.json",
        {"references": [{"title": 123, "license": [], "source_type": {}, "usage_intent": 1.5, "attached_to": True}]},
    )
    summary = summarize_reference_board(tmp_path)  # must not raise
    assert summary["reference_count"] == 1


# ---- vocabulary sanity ----


def test_source_types_include_all_required_values():
    assert set(SOURCE_TYPES) == {
        "inspiration", "reference", "remixable", "user_uploaded", "sketch",
        "image", "stl", "step", "vector", "unknown",
    }


def test_licenses_include_all_required_values():
    assert set(LICENSES) == {
        "unknown", "personal_use", "commercial_allowed", "cc_by", "cc_by_sa",
        "cc_by_nc", "public_domain", "proprietary", "custom",
    }


def test_usage_intents_include_all_required_values():
    assert set(USAGE_INTENTS) == {
        "design_reference_only", "remix_candidate", "dimensional_reference",
        "style_reference", "functional_reference", "manufacturing_reference",
    }


def test_attached_to_values_include_all_required_values():
    assert set(ATTACHED_TO_VALUES) == {
        "design_intent.reference_inputs", "project", "part", "unknown",
    }


# ---- no network/subprocess/scrape/download behavior anywhere in this module ----


def test_reference_board_module_has_no_forbidden_calls():
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "write_text(", "write_bytes(", "save_json(",
    )
    source = inspect.getsource(reference_board)
    for forbidden_call in forbidden:
        assert forbidden_call not in source, f"found forbidden call {forbidden_call!r} in reference_board.py"


def test_reference_board_module_does_not_set_human_approved_or_print_ready():
    source = inspect.getsource(reference_board)
    assert '"human_approved": True' not in source
    assert '"print_ready": True' not in source
    assert "human_approved = True" not in source
    assert "print_ready = True" not in source


def test_reference_board_module_never_touches_source_url_beyond_reading_the_field():
    # The only two mentions of source_url in this module should be reading it
    # (entry.get) and echoing it back into the normalized dict/warning text -
    # never opening, fetching, or otherwise acting on it.
    source = inspect.getsource(reference_board)
    forbidden_url_actions = ("urlopen(source_url", "requests.get(source_url", "fetch(source_url", "download(")
    for action in forbidden_url_actions:
        assert action not in source
