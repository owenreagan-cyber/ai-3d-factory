from factory.validators.dimension_check import check_build_volume_fit


def _printer(build_volume=None, verified=False, display_name="Test Printer"):
    printer = {"display_name": display_name, "verified": verified}
    if build_volume is not None:
        printer["build_volume_mm"] = build_volume
    return printer


def test_no_bounding_box_warns():
    result = check_build_volume_fit(None, _printer(build_volume={"x": 100, "y": 100, "z": 100}))
    assert result["status"] == "WARN"
    assert result["name"] == "build_volume_fit"


def test_no_printer_warns():
    result = check_build_volume_fit({"x": 10, "y": 10, "z": 10}, None)
    assert result["status"] == "WARN"


def test_printer_without_build_volume_field_warns():
    result = check_build_volume_fit({"x": 10, "y": 10, "z": 10}, {"display_name": "No Volume Printer"})
    assert result["status"] == "WARN"


def test_fits_and_verified_passes():
    result = check_build_volume_fit(
        {"x": 10, "y": 10, "z": 10}, _printer(build_volume={"x": 100, "y": 100, "z": 100}, verified=True)
    )
    assert result["status"] == "PASS"


def test_fits_but_unverified_warns():
    result = check_build_volume_fit(
        {"x": 10, "y": 10, "z": 10}, _printer(build_volume={"x": 100, "y": 100, "z": 100}, verified=False)
    )
    assert result["status"] == "WARN"
    assert "UNVERIFIED" in result["detail"]


def test_does_not_fit_in_any_orientation_warns_not_fails():
    result = check_build_volume_fit(
        {"x": 500, "y": 500, "z": 500}, _printer(build_volume={"x": 100, "y": 100, "z": 100}, verified=True)
    )
    assert result["status"] == "WARN"
    assert "does not fit" in result["detail"]


def test_fits_via_axis_permutation():
    # 10x100x10 doesn't fit as-is against a 100x10x100 volume, but does after
    # reordering axes - the check must try all orientations before failing.
    result = check_build_volume_fit(
        {"x": 10, "y": 100, "z": 10}, _printer(build_volume={"x": 100, "y": 10, "z": 100}, verified=True)
    )
    assert result["status"] == "PASS"
