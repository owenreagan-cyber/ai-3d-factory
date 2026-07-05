from factory import project_store

REQUIRED_BLOCKED_ACTIONS = {
    "cloud_api_calls",
    "paid_api_calls",
    "printer_control",
    "auto_print",
    "bambu_cloud_upload",
    "lan_print",
    "meshy_without_explicit_approval",
    "mcp_setup",
    "blender_addon_install",
    "secret_creation",
    "copyrighted_franchise_assets",
}


def test_agent_policy_contains_required_blocked_actions():
    policy = project_store.load_json(project_store.CONFIG_DIR / "agent_policy.json")
    blocked = set(policy["blocked_actions"])
    missing = REQUIRED_BLOCKED_ACTIONS - blocked
    assert not missing, f"agent_policy.json is missing blocked actions: {missing}"


def test_agent_policy_caps_automatic_status():
    policy = project_store.load_json(project_store.CONFIG_DIR / "agent_policy.json")
    assert policy["status_gates"]["max_automatic_status"] == "slicer_review_ready"
    assert policy["status_gates"]["print_ready_requires"] == "explicit_human_approval"


def test_tolerances_do_not_use_a_single_universal_value():
    tolerances = project_store.load_json(project_store.CONFIG_DIR / "tolerances.json")
    keys = tolerances["tolerances_mm"].keys()
    expected = {
        "seam_gap_mm",
        "letter_pocket_clearance_mm",
        "connector_clearance_mm",
        "decorative_inlay_clearance_mm",
        "sliding_fit_clearance_mm",
    }
    assert expected.issubset(keys)


def test_printer_config_flags_unverified_build_volume():
    printers = project_store.load_json(project_store.CONFIG_DIR / "printers.json")
    primary = printers["printers"][printers["primary_printer"]]
    assert "verified" in primary
    assert "verification_note" in primary


def test_no_real_env_file_committed():
    env_path = project_store.REPO_ROOT / ".env"
    assert not env_path.is_file(), ".env must not exist in this repo - only .env.example is allowed"


def test_env_example_has_no_uncommented_secret_values():
    content = (project_store.REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            _, _, value = stripped.partition("=")
            assert value.strip() == "", f"unexpected non-empty value in .env.example: {line!r}"
