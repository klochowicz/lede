import json
from unittest.mock import patch

from briefing.llm_subscription import ClaudeSubscriptionBackend


@patch("briefing.llm_subscription.subprocess.run")
def test_subscription_condense_shells_out_to_claude(mock_run):
    mock_run.return_value.stdout = json.dumps({"result": "a short summary"})
    mock_run.return_value.returncode = 0
    backend = ClaudeSubscriptionBackend()
    assert backend.condense("body text") == "a short summary"
    args = mock_run.call_args.args[0]
    assert args[0] == "claude"
    assert "--output-format" in args and "json" in args
