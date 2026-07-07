from factory.manufacturing import decision_engine, knowledge

ALL_OPTION_IDS = {
    "single_piece",
    "multipart_build_volume",
    "multipart_color",
    "multipart_detail",
    "multipart_paint",
    "multipart_strength",
    "replaceable_components",
}


def _h2d_capabilities():
    return knowledge.printer_capabilities(knowledge.get_printer("bambu_h2d"))


def _centauri_capabilities():
    return knowledge.printer_capabilities(knowledge.get_printer("elegoo_centauri_carbon"))


def test_all_options_are_always_explained_regardless_of_description():
    result = decision_engine.evaluate_manufacturing_options("", None)
    option_ids = {o["option_id"] for o in result["options"]}
    assert option_ids == ALL_OPTION_IDS
    for option in result["options"]:
        assert option["advantages"]
        assert option["disadvantages"]


def test_selected_manufacturing_option_is_always_none():
    result = decision_engine.evaluate_manufacturing_options("a two-color nameplate", _h2d_capabilities())
    assert result["selected_manufacturing_option"] is None
    assert result["requires_human_confirmation"] is True


def test_empty_description_recommends_single_piece():
    result = decision_engine.evaluate_manufacturing_options("", None)
    assert result["recommended_option"] == "single_piece"


def test_color_keywords_recommend_multipart_color_when_multicolor_available():
    result = decision_engine.evaluate_manufacturing_options(
        "a two-color raised-letter nameplate", _h2d_capabilities()
    )
    assert result["recommended_option"] == "multipart_color"


def test_multipart_color_unavailable_without_multicolor_printer():
    result = decision_engine.evaluate_manufacturing_options(
        "a two-color raised-letter nameplate", _centauri_capabilities()
    )
    color_option = next(o for o in result["options"] if o["option_id"] == "multipart_color")
    assert color_option["available"] is False
    assert color_option["availability_note"]
    # Recommendation must not be an unavailable option.
    assert result["recommended_option"] != "multipart_color"


def test_multipart_color_unavailable_with_no_printer_specified():
    result = decision_engine.evaluate_manufacturing_options("a two-color sign", None)
    color_option = next(o for o in result["options"] if o["option_id"] == "multipart_color")
    assert color_option["available"] is False


def test_paint_keywords_recommend_multipart_paint():
    result = decision_engine.evaluate_manufacturing_options(
        "a figure that needs hand-painting after printing", None
    )
    assert result["recommended_option"] == "multipart_paint"


def test_strength_keywords_recommend_multipart_strength():
    result = decision_engine.evaluate_manufacturing_options(
        "a load-bearing structural mounting bracket", None
    )
    assert result["recommended_option"] == "multipart_strength"


def test_replaceable_keywords_recommend_replaceable_components():
    result = decision_engine.evaluate_manufacturing_options(
        "a clip that wears out and should be a replaceable spare part", None
    )
    assert result["recommended_option"] == "replaceable_components"


def test_build_volume_keywords_recommend_multipart_build_volume():
    result = decision_engine.evaluate_manufacturing_options(
        "an oversized panel that exceeds build volume", None
    )
    assert result["recommended_option"] == "multipart_build_volume"


def test_detail_keywords_recommend_multipart_detail():
    result = decision_engine.evaluate_manufacturing_options(
        "an intricate design with fine detail engraving", None
    )
    assert result["recommended_option"] == "multipart_detail"


def test_recommendation_rationale_is_non_binding():
    result = decision_engine.evaluate_manufacturing_options("a two-color nameplate", _h2d_capabilities())
    assert "non-binding" in result["recommendation_rationale"]
