# SPDX-License-Identifier: AGPL-3.0-or-later
"""The `.tdr` taxonomy, and the three places in this repository that restate it.

`proto/braemons/v1/trial_outcome.proto` is the taxonomy — a protobuf enum, whose value
names protobuf's JSON mapping puts on the wire and whose numbers are the `.tdr`
codes. `tools/check_outcomes.py` does the reading; this runs it in the test
suite so a drift is a red test rather than something CI alone would notice.

It replaces a vendored `outcomes.json` and a vendored checker
(`contracts/INTERACTIONS.md` §6). Same protection, one fewer file format: the
enum says "numbers are never reused" by being an enum, rather than by saying so
in prose beside a JSON array.
"""

from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS))

import check_outcomes  # noqa: E402


def test_every_copy_of_the_taxonomy_agrees_with_the_enum():
    problems = check_outcomes.problems()
    assert not problems, "\n".join(problems)


def test_the_enum_is_the_tdr_codes():
    # Spelled out rather than derived: these numbers are in every .tdr the lab
    # has written, so a test that computed them from the same file it is
    # checking would agree with any renumbering.
    taxonomy = check_outcomes.taxonomy()
    assert taxonomy["UNDETERMINED"] == -1
    assert taxonomy["NOT_STARTED"] == 0
    assert taxonomy["HIT"] == 1
    assert taxonomy["UNEXPECTED_START_SIGNAL"] == 8
    assert taxonomy["NEVER_FINISHED"] == 11
