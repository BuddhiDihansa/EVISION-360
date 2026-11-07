import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from run_pipeline import STEPS  # noqa: E402


def test_every_pipeline_step_points_to_an_existing_script():
    for title, script, _ in STEPS:
        assert (ROOT / script).is_file(), f"{title}: {script} not found"


def test_database_step_is_last():
    assert STEPS[-1][2] is True and not any(s[2] for s in STEPS[:-1])