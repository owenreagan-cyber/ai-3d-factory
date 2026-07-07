from factory import project_store

PRODUCT_VISION_PATH = project_store.REPO_ROOT / "docs" / "product-vision.md"


def test_product_vision_doc_exists():
    assert PRODUCT_VISION_PATH.is_file()


def _content() -> str:
    return PRODUCT_VISION_PATH.read_text(encoding="utf-8").lower()


def test_product_vision_mentions_local_app_and_launcher():
    content = _content()
    for phrase in ("local-first", "launcher", "dock icon", "dashboard"):
        assert phrase in content, f"missing {phrase!r}"


def test_product_vision_mentions_all_five_visual_requirements():
    content = _content()
    for phrase in (
        "mesh preview",
        "cad source preview",
        "manufacturing option preview",
        "exploded",
        "planning board",
    ):
        assert phrase in content, f"missing {phrase!r}"


def test_product_vision_mentions_reserved_future_commands():
    content = _content()
    for command in ("factory serve", "factory open", "factory preview-project", "factory launcher-info"):
        assert command in content, f"missing {command!r}"


def test_product_vision_reaffirms_safety_boundaries():
    content = _content()
    for phrase in ("no auto-print", "human_approved", "print_ready", "slicer_review_ready"):
        assert phrase in content, f"missing {phrase!r}"


def test_product_vision_does_not_claim_ui_is_implemented():
    content = _content()
    assert "not implemented" in content or "not yet built" in content or "nothing in this document is implemented" in content


def test_reserved_commands_do_not_exist_in_cli():
    import typer

    from factory.cli import app

    registered = set(typer.main.get_command(app).commands.keys())
    # `factory preview-project` was reserved in Phase 4 but is now implemented
    # (Phase 6) - see docs/product-vision.md's note on that command.
    for reserved in ("serve", "open", "launcher-info"):
        assert reserved not in registered, f"{reserved!r} should not be implemented yet"


def test_readme_references_product_vision():
    readme = (project_store.REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "product-vision.md" in readme


def test_roadmap_references_product_vision():
    roadmap = (project_store.REPO_ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert "product-vision.md" in roadmap
