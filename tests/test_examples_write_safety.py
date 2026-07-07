"""Regression guard: no test may invoke a write-capable `factory` CLI
command directly against a committed `examples/` path.

`examples/` (see `docs/examples-library.md`) holds committed reference
fixtures, not scratch space - a write-capable command (one that writes
files given a path argument, e.g. `preview-project`) pointed at a real
`examples/...` path via `CliRunner.invoke()` would mutate a committed
file. Phase 17 fixed exactly this: `test_preview_project_cli_reports_
multipart_state` ran `factory preview-project` against
`examples/multipart-classroom-sign` directly, regenerating that example's
`preview_package/{index.json,preview_report.md}` `generated_at`/
`Generated:` timestamp on every `pytest` run and leaving the working tree
dirty. The fix was to copy the example into `tmp_path` first (see
`_copy_example_to()` in `tests/test_examples_library.py`) and invoke the
command against that copy instead.

This module is a simple source-text scan across every test file, not a
full AST interpreter - deliberately, per the "avoid brittle
over-engineering" guidance this phase was scoped to. It looks for the
literal call shape `runner.invoke(app, ["<write-command>", "examples/...`
(and the f-string equivalent). It does not understand variables, so
`runner.invoke(app, ["preview-project", str(project_dir)])` is correctly
treated as safe even without knowing what `project_dir` resolves to - that
is an accepted gap for a lightweight guard, not a full-precision analysis.
Read-only commands (`list-examples`, `show-example`, `review-gate`,
`preview-index`, `check-future-tools`, ...) are always safe against
`examples/` and are never flagged.
"""

from __future__ import annotations

import re

from factory import project_store

TESTS_DIR = project_store.REPO_ROOT / "tests"

# Commands that write file(s) given a path argument. A test invoking one of
# these against a literal "examples/..." path (instead of a tmp_path copy)
# would mutate a committed fixture. Read-only commands are never listed
# here and are implicitly allowed against examples/ - see cli.py's
# AVAILABLE_COMMANDS and each command's own docstring for the read/write
# classification this list is derived from.
WRITE_CAPABLE_COMMANDS = (
    "plan",
    "choose-option",
    "generate-openscad",
    "generate-cadquery",
    "validate",
    "render",
    "preview-project",
    "preview-board",
)

# Documented for clarity only (not read by the scan itself - anything not
# in WRITE_CAPABLE_COMMANDS is implicitly allowed against examples/).
READ_ONLY_COMMANDS_ALLOWED_AGAINST_EXAMPLES = (
    "status",
    "list-options",
    "route-cad",
    "list-printers",
    "show-printer",
    "list-accessories",
    "show-accessory",
    "list-materials",
    "show-material",
    "fleet-summary",
    "check-manufacturing",
    "render-coverage",
    "plan-renders",
    "preview-index",
    "review-gate",
    "inspect-slicer",
    "report",
    "list-examples",
    "show-example",
    "check-future-tools",
)


def _build_unsafe_pattern() -> re.Pattern[str]:
    """`runner.invoke(app, ["<write-command>", <literal "examples..." string>`.

    Matches a literal string (optionally an f-string) that starts with
    "examples" immediately after a write-capable command name - whether
    the path is `"examples/foo"` (a specific example) or just `"examples"`
    (e.g. `preview-board` pointed at the whole library, which would write
    `examples/preview_board/`). `\\s` matches newlines too, so a
    multi-line `runner.invoke(app, [\\n    "preview-project",\\n
    "examples/...` call is still caught.
    """
    commands = "|".join(re.escape(cmd) for cmd in WRITE_CAPABLE_COMMANDS)
    return re.compile(r'\[\s*["\'](?:' + commands + r')["\']\s*,\s*f?["\']examples(?:/|["\'])')


UNSAFE_PATTERN = _build_unsafe_pattern()


def _scan_source(source: str, label: str) -> list[str]:
    violations = []
    for match in UNSAFE_PATTERN.finditer(source):
        line_no = source[: match.start()].count("\n") + 1
        violations.append(f"{label}:{line_no}: {match.group(0)!r}")
    return violations


# ---- the guard itself ----


def test_no_test_file_invokes_write_capable_cli_commands_against_committed_examples():
    # Exclude this file itself: its self-tests below deliberately contain
    # known-bad sample strings (as plain fixture data, never passed to
    # CliRunner) to prove the detector works - those aren't real
    # invocations and would otherwise be flagged as false positives.
    this_file = TESTS_DIR / "test_examples_write_safety.py"

    violations: list[str] = []
    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        if test_file == this_file:
            continue
        source = test_file.read_text(encoding="utf-8")
        violations.extend(_scan_source(source, str(test_file.relative_to(project_store.REPO_ROOT))))

    assert not violations, (
        "Found test(s) invoking a write-capable CLI command directly against a "
        "committed examples/ path - copy the example into tmp_path first "
        "(see _copy_example_to() in tests/test_examples_library.py) and invoke "
        "against the copy instead:\n" + "\n".join(violations)
    )


# ---- self-tests: prove the detector itself works, on sample source text ----


def test_guard_detects_the_known_phase17_bug_pattern():
    bad_source = 'result = runner.invoke(app, ["preview-project", "examples/multipart-classroom-sign"])'
    assert _scan_source(bad_source, "sample")


def test_guard_detects_fstring_variant_of_the_bug_pattern():
    bad_source = 'result = runner.invoke(app, ["preview-project", f"examples/{MULTIPART_EXAMPLE}"])'
    assert _scan_source(bad_source, "sample")


def test_guard_detects_other_write_capable_commands():
    samples = [
        'runner.invoke(app, ["generate-openscad", "examples/foo", "--template", "test-cube"])',
        'runner.invoke(app, ["generate-cadquery", "examples/foo", "--template", "mechanical-plate"])',
        'runner.invoke(app, ["choose-option", "examples/foo", "single_piece"])',
        'runner.invoke(app, ["plan", "examples/foo/brief.json"])',
        'runner.invoke(app, ["validate", "examples/foo/stl/part.stl"])',
        'runner.invoke(app, ["render", "examples/foo/stl/part.stl"])',
        'runner.invoke(app, ["preview-board", "examples"])',
    ]
    for sample in samples:
        assert _scan_source(sample, "sample"), f"guard should have flagged: {sample!r}"


def test_guard_detects_bad_pattern_split_across_multiple_lines():
    bad_source = (
        "result = runner.invoke(\n"
        "    app,\n"
        '    ["preview-project", "examples/simple-nameplate"],\n'
        ")\n"
    )
    assert _scan_source(bad_source, "sample")


def test_guard_allows_tmp_path_copy_usage():
    good_sources = [
        'result = runner.invoke(app, ["preview-project", str(example_copy)])',
        'result = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "test-cube"])',
        'result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])',
    ]
    for sample in good_sources:
        assert not _scan_source(sample, "sample"), f"guard should not have flagged: {sample!r}"


def test_guard_allows_read_only_commands_against_examples():
    good_sources = [
        'result = runner.invoke(app, ["review-gate", f"examples/{MULTIPART_EXAMPLE}"])',
        'result = runner.invoke(app, ["preview-index", "examples/simple-nameplate"])',
        'result = runner.invoke(app, ["list-examples"])',
        'result = runner.invoke(app, ["show-example", "multipart-classroom-sign"])',
        'result = runner.invoke(app, ["check-future-tools"])',
    ]
    for sample in good_sources:
        assert not _scan_source(sample, "sample"), f"guard should not have flagged: {sample!r}"


def test_write_capable_and_read_only_command_lists_do_not_overlap():
    assert set(WRITE_CAPABLE_COMMANDS).isdisjoint(READ_ONLY_COMMANDS_ALLOWED_AGAINST_EXAMPLES)
