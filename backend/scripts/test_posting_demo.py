import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import posting_demo  # noqa: E402


def test_demo_runs_every_scenario_offline(capsys):
    assert posting_demo.main() == 0
    out = capsys.readouterr().out
    assert out.count("after: Completed") == 3  # scenarios 1-3 posted
    assert "posting it again: status=posted already_posted=True" in out
    for reason in ("UpstreamUnavailable", "TimeLimitExceeded", "NO_PREPARED_FEEDBACK", "PROJECT_NOT_ALLOWED",
                   "POSTING_DISABLED"):
        assert f"reason={reason}" in out
    assert str(posting_demo.TMP) in out  # everything in the temp folder, never data/
