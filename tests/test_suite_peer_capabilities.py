"""Writer accepts a newer Uoink that advertises extra capabilities."""
from __future__ import annotations

import pytest

from writer import suite_peer

REQUIRED = list(suite_peer.UOINK_CAPABILITIES)


def test_exact_version_1_capabilities_pass():
    assert suite_peer._capabilities(list(REQUIRED), code="x") == REQUIRED


def test_extra_capability_is_accepted():
    value = sorted(REQUIRED + ["uoink.capture/1"])
    assert suite_peer._capabilities(value, code="x") == value


@pytest.mark.parametrize("value", [
    REQUIRED[:2],                                   # a required one is missing
    sorted(REQUIRED + ["uoink.capture/1"])[::-1],   # not sorted
    REQUIRED + [REQUIRED[0]],                       # duplicate
    REQUIRED + [""],                                # empty entry
    REQUIRED + [7],                                 # not a string
    "uoink.corpus.read/1",                          # not a list
])
def test_bad_capabilities_are_refused(value):
    with pytest.raises(suite_peer.PeerError, match="do not match version 1"):
        suite_peer._capabilities(value, code="x")
