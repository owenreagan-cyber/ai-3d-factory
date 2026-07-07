import ast
import inspect

from factory.manufacturing import check, decision_engine, inspect as manufacturing_inspect, knowledge, manifest, selection

FORBIDDEN = [
    "import subprocess",
    "subprocess.",
    "os.system(",
    "os.popen(",
    "Popen(",
    "socket.",
    "import urllib",
    "import requests",
    "http.client",
]


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
    return tree


def test_manufacturing_modules_have_no_network_or_process_calls():
    for module in (knowledge, decision_engine, manifest, selection, manufacturing_inspect, check):
        tree = _strip_docstrings(ast.parse(inspect.getsource(module)))
        code_only_source = ast.unparse(tree)
        for forbidden_term in FORBIDDEN:
            assert forbidden_term not in code_only_source, (
                f"{module.__name__} must stay local-only; found {forbidden_term!r}"
            )


def test_accessory_catalog_never_grants_print_or_control_capabilities():
    accessories = knowledge.load_accessories()
    forbidden_capabilities = {"print", "auto_print", "printer_control", "cloud_upload"}
    for accessory in accessories.values():
        capabilities = set(accessory.get("adds_capabilities", []))
        assert not (forbidden_capabilities & capabilities)


def test_fleet_state_example_is_not_referenced_by_any_manufacturing_module():
    # fleet_state.example.json is documentation/scaffolding only (Phase 5) -
    # no code path may read it yet, since it isn't live hardware data.
    for module in (knowledge, decision_engine, manifest, selection, manufacturing_inspect, check):
        source = inspect.getsource(module)
        assert "fleet_state" not in source, f"{module.__name__} must not read fleet_state yet"
