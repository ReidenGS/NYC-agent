from app.nodes.understand import _extract_bedroom_from_text


def test_bedroom_extract_1b1b_compact():
    assert _extract_bedroom_from_text("我想看1b1b户型的房子") == "1br"


def test_bedroom_extract_chinese_alias():
    assert _extract_bedroom_from_text("预算有限，先看一室一厅") == "1br"


def test_bedroom_extract_english_alias():
    assert _extract_bedroom_from_text("Looking for a two bedroom apartment") == "2br"


def test_bedroom_extract_studio():
    assert _extract_bedroom_from_text("I only want studio units") == "studio"
