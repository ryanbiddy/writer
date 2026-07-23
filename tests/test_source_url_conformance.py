"""Cross-product source URLs must match Zing's landed hostile corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from writer.schemas import is_valid_source_url


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "suite_integration_v1"
FIXTURE_PATH = FIXTURE_DIR / "source-url.json"
PROVENANCE_PATH = FIXTURE_DIR / "source-url.provenance.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
PROVENANCE = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))


def test_source_url_fixture_is_the_pinned_zing_blob() -> None:
    digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest().upper()
    assert FIXTURE["fixture"] == "ryan.suite.source-url-conformance"
    assert FIXTURE["version"] == 1
    assert len(FIXTURE["cases"]) == 16
    assert PROVENANCE == {
        "repository": "ryanbiddy/zing",
        "commit": "0bddbc8a7ba9e13a84f025fc6c33f260ca25d4fb",
        "fixture": "tools/eval/fixtures/suite_v1/source-url.json",
        "git_blob_sha": "1592c5dc4f2b3bd7e113abf2912180fbe1a951e0",
        "fixture_sha256": (
            "3C3628558AE830A2D41631FF1D7F48E54C4E588C7BBF6B533DD9F5835E834063"
        ),
        "copy_note": (
            "The local copy is byte-for-byte identical to the pinned Zing blob."
        ),
    }
    assert digest == PROVENANCE["fixture_sha256"]


@pytest.mark.parametrize(
    "case", FIXTURE["cases"], ids=lambda case: case["id"]
)
def test_source_urls_match_the_shared_conformance_fixture(case) -> None:
    assert is_valid_source_url(case["value"]) is case["expected_valid"]
