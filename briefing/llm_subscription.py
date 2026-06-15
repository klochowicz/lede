import json
import subprocess

from briefing.llm import _SYNTHESIS_PROMPT, SynthesisItem, ThemeData, _parse_themes


class ClaudeSubscriptionBackend:
    """Shells out to the logged-in `claude` CLI. Local-dev default; free-at-margin."""

    def condense(self, text: str) -> str:
        return self._run(f"Condense the following into 2-3 plain sentences. Text:\n\n{text}")

    def synthesise(self, items: list[SynthesisItem]) -> list[ThemeData]:
        return _parse_themes(self._run(_SYNTHESIS_PROMPT.format(items=json.dumps(items))))

    def _run(self, prompt: str) -> str:
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return json.loads(proc.stdout)["result"].strip()
