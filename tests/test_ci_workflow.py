from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
NODE24_ACTION_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
}


def test_ci_uses_node24_action_runtimes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    seen: set[str] = set()
    for action, major_text in re.findall(
        r"uses:\s+(actions/(?:checkout|setup-python|upload-artifact))@v(\d+)",
        text,
    ):
        seen.add(action)
        assert int(major_text) >= NODE24_ACTION_MAJORS[action], (
            f"CI uses Node 20 action {action}@v{major_text}"
        )

    assert seen == set(NODE24_ACTION_MAJORS)
