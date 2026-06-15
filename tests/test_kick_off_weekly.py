from unittest.mock import patch

from briefing.tasks import kick_off_weekly


def test_kick_off_weekly_spans_seven_days(db):
    with patch("briefing.tasks.kick_off_digest") as kick:
        kick_off_weekly()
    kind, start_iso, end_iso = kick.call_args.args
    assert kind == "weekly"
    from datetime import datetime

    span = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
    assert span.days == 7
