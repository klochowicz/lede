from unittest.mock import MagicMock, patch

import anthropic
import pytest

from briefing.llm import ClaudeAPIBackend, _parse_themes, get_backend


def _text_message(text):
    return MagicMock(content=[anthropic.types.TextBlock(type="text", text=text, citations=None)])


@patch("briefing.llm.anthropic.Anthropic")
def test_get_backend_reads_setting(mock_anthropic, settings):
    settings.BRIEFING_LLM_BACKEND = "claude-api"
    settings.ANTHROPIC_API_KEY = "sk-test"
    assert isinstance(get_backend(), ClaudeAPIBackend)


def test_parse_themes_rejects_malformed_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_themes("here you go: {not: valid}")


def test_parse_themes_rejects_missing_themes_key():
    with pytest.raises(ValueError, match="themes"):
        _parse_themes('{"error": "model refused"}')


def test_get_backend_unknown_raises(settings):
    settings.BRIEFING_LLM_BACKEND = "nope"
    with pytest.raises(ValueError, match="nope"):
        get_backend()


@patch("briefing.llm.anthropic.Anthropic")
def test_claude_api_condense_returns_text(mock_anthropic):
    client = mock_anthropic.return_value
    client.messages.create.return_value = _text_message("short summary")
    backend = ClaudeAPIBackend(api_key="sk-test")
    assert backend.condense("a long article body") == "short summary"


@patch("briefing.llm.anthropic.Anthropic")
def test_claude_api_synthesise_parses_themes(mock_anthropic):
    client = mock_anthropic.return_value
    payload = (
        '{"themes": [{"title": "AI", "narrative": "n", "importance": 5, '
        '"items": [{"item_id": 1, "rationale": "r"}]}]}'
    )
    client.messages.create.return_value = _text_message(payload)
    backend = ClaudeAPIBackend(api_key="sk-test")
    themes = backend.synthesise([{"item_id": 1, "title": "t", "summary": "s"}])
    assert themes[0]["title"] == "AI"
    assert themes[0]["items"][0]["item_id"] == 1
