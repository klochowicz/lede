from unittest.mock import MagicMock, patch

from briefing.llm_deepseek import DeepSeekBackend


@patch("briefing.llm_deepseek.openai.OpenAI")
def test_deepseek_uses_openai_sdk_with_base_url(mock_openai):
    client = mock_openai.return_value
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="short summary"))]
    )
    backend = DeepSeekBackend(api_key="dk-test")
    assert backend.condense("body") == "short summary"
    assert mock_openai.call_args.kwargs["base_url"] == "https://api.deepseek.com"
