import json

import openai

from briefing.llm import _SYNTHESIS_PROMPT, SynthesisItem, ThemeData, _parse_themes

CONDENSE_MODEL = "deepseek-chat"
SYNTHESIS_MODEL = "deepseek-chat"


class DeepSeekBackend:
    def __init__(self, api_key: str) -> None:
        self._client = openai.OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    def condense(self, text: str) -> str:
        return self._chat(CONDENSE_MODEL, f"Condense into 2-3 plain sentences:\n\n{text}")

    def synthesise(self, items: list[SynthesisItem]) -> list[ThemeData]:
        return _parse_themes(
            self._chat(SYNTHESIS_MODEL, _SYNTHESIS_PROMPT.format(items=json.dumps(items)))
        )

    def _chat(self, model: str, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        content = resp.choices[0].message.content
        if content is None:
            raise ValueError("DeepSeek returned an empty message content")
        return content.strip()
