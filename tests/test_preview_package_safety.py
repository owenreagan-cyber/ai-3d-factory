import ast
import inspect

from factory import preview_package

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


def test_preview_package_module_has_no_network_process_or_openscad_calls():
    tree = _strip_docstrings(ast.parse(inspect.getsource(preview_package)))
    code_only_source = ast.unparse(tree)
    for forbidden_term in FORBIDDEN:
        assert forbidden_term not in code_only_source, (
            f"factory.preview_package must stay local-only and never invoke OpenSCAD; found {forbidden_term!r}"
        )


def _function_source(tree: ast.Module, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.unparse(node)
    raise AssertionError(f"function {name!r} not found in factory.preview_package")


def test_gather_preview_data_and_markdown_report_never_write_files():
    tree = ast.parse(inspect.getsource(preview_package))
    for func_name in ("gather_preview_data", "build_markdown_report"):
        func_source = _function_source(tree, func_name)
        for write_call in ("write_text(", "write_bytes(", "save_json(", ".mkdir("):
            assert write_call not in func_source, f"{func_name} must not write files; found {write_call!r}"


def test_only_write_preview_package_writes_files():
    tree = ast.parse(inspect.getsource(preview_package))
    func_source = _function_source(tree, "write_preview_package")
    assert "save_json(" in func_source
    assert "write_text(" in func_source
