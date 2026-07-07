import ast
import inspect

from factory.manufacturing import decision_engine, knowledge, manifest

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
    for module in (knowledge, decision_engine, manifest):
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
