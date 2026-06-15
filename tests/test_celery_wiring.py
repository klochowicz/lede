from briefing.tasks import ping


def test_ping_runs_eagerly_and_returns_pong():
    result = ping.delay()
    assert result.get(timeout=1) == "pong"
