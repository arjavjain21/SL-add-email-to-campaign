import src.ui_components as components


def test_api_key_mask_shows_first_four_characters_only():
    api_key = "abcd1234efgh"
    masked = components.ApiKeyInput.mask(api_key)
    assert masked == "abcd****"


def test_api_key_input_renders_masked_value(monkeypatch):
    captured = {}

    def fake_text_input(label, value="", **kwargs):
        captured["label"] = label
        captured["value"] = value
        captured["kwargs"] = kwargs
        return value

    monkeypatch.setattr(components.st, "text_input", fake_text_input)

    api_key = "abcd1234efgh"
    result = components.ApiKeyInput.render(api_key)

    assert result == api_key
    assert captured["value"] == "abcd****"
    assert "type" not in captured["kwargs"]


def test_api_key_input_updates_when_value_changes(monkeypatch):
    new_value = "newkeyvalue"

    def fake_text_input(label, value="", **kwargs):
        return new_value

    monkeypatch.setattr(components.st, "text_input", fake_text_input)

    result = components.ApiKeyInput.render("oldkey")
    assert result == new_value
