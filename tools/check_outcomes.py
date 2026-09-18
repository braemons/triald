#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every copy of the `.tdr` taxonomy in this repository, against the enum.

`proto/triald/v1/outcomes.proto` **is** the taxonomy. This holds the three
places that restate it to what it says:

  * `triald.outcomes.TrialOutcome` — the Python enum the daemon works in;
  * the `Acceptance` message in `config.proto` — one flag per outcome a trial
    can carry, deciding whether it consumes a slot in the round;
  * `OUTCOME_COLUMNS` in the counters panel — one column per outcome a finished
    trial can carry.

**Outcomes cross the wire by name**, because protobuf's JSON mapping puts an
enum value's name on it, so a copy that drifts is not cosmetic.
`contracts/INTERACTIONS.md` §5.2 is what it costs: code 8 was spelled two ways,
so one outcome was unparseable at the far end and any graph written from the
other vocabulary was refused at compile — by a person with both spellings in
front of them in two web UIs.

This replaces `check_outcomes.py` + `outcomes.json`, vendored from the contracts
repository. The taxonomy is now a protobuf enum, which is the thing that JSON
file was imitating: numbers that are never reused, names that are a wire
contract, and a format two languages can generate from rather than parse with
regexes. What is still read with regexes is the *panel*, because JavaScript has
no other reader here.

Everything is text-matched rather than imported, so this runs with nothing
installed but `python3` — including in CI before any environment exists.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
PROTO = HERE / "proto" / "triald" / "v1" / "outcomes.proto"
CONFIG_PROTO = HERE / "proto" / "triald" / "v1" / "config.proto"
PYTHON_ENUM = HERE / "daemon" / "src" / "triald" / "outcomes.py"
PANEL = HERE / "client" / "web" / "elements" / "counters_panel_element.js"

#: Nobody assigns it: it is what a trial holds *while* it runs. A counters
#: column would always read zero, and an acceptance flag would decide the fate
#: of a trial that has not finished.
NEVER_ASSIGNED = {"UNDETERMINED"}


def taxonomy() -> dict[str, int]:
    """The enum, by name."""
    body = between(PROTO.read_text(), r"enum TrialOutcome\s*\{", r"^\}")
    return {
        name: int(value)
        for name, value in re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+)\s*;", body, re.M)
    }


def python_enum() -> dict[str, int]:
    body = between(PYTHON_ENUM.read_text(), r"class TrialOutcome\(.*?\):", r"^class |\Z")
    return {
        name: int(value)
        for name, value in re.findall(r"^\s{4}([A-Z][A-Z0-9_]*)\s*=\s*(-?\d+)", body, re.M)
    }


def acceptance_flags() -> set[str]:
    """The per-outcome flags of the `Acceptance` message, upper-cased.

    The message also carries two flags that are not outcomes at all —
    `frame_loss` and `imprecise_fixation` cut across every outcome — so the
    comparison is one-way: every outcome needs a flag, not every flag an
    outcome.
    """
    body = between(CONFIG_PROTO.read_text(), r"message Acceptance\s*\{", r"^\}")
    return {name.upper() for name in re.findall(r"optional bool (\w+)\s*=", body)}


def panel_columns() -> list[str]:
    body = between(PANEL.read_text(), r"const OUTCOME_COLUMNS\s*=\s*\[", r"^\];")
    return re.findall(r'"([A-Z][A-Z0-9_]*)"', body)


def between(source: str, start: str, end: str) -> str:
    match = re.search(start, source, re.M | re.S)
    if match is None:
        raise SystemExit(f"could not find {start!r} — this checker needs updating")
    rest = source[match.end() :]
    stop = re.search(end, rest, re.M)
    return rest[: stop.start()] if stop else rest


def problems() -> list[str]:
    canonical = taxonomy()
    if not canonical:
        return ["proto/triald/v1/outcomes.proto has no enum values this reader can see"]

    found: list[str] = []
    countable = {name for name in canonical if name not in NEVER_ASSIGNED}

    for name, value in sorted(python_enum().items()):
        if name not in canonical:
            found.append(f"triald.outcomes.TrialOutcome has {name}, which the enum does not")
        elif canonical[name] != value:
            found.append(
                f"triald.outcomes.TrialOutcome spells {name} = {value}; "
                f"the enum says {canonical[name]}"
            )
    for name in sorted(set(canonical) - set(python_enum())):
        found.append(f"triald.outcomes.TrialOutcome is missing {name}")

    flags = acceptance_flags()
    for name in sorted(countable - flags):
        found.append(f"the Acceptance message has no flag for {name}")
    #: An acceptance flag for something nobody assigns would decide the fate of
    #: a trial that has not finished.
    for name in sorted(flags & NEVER_ASSIGNED):
        found.append(f"the Acceptance message has a flag for {name}, which nobody assigns")

    columns = panel_columns()
    for name in sorted(countable - set(columns)):
        found.append(f"the counters panel has no column for {name}")
    for name in sorted(set(columns) - countable):
        reason = " (nobody assigns it)" if name in NEVER_ASSIGNED else ""
        found.append(f"the counters panel has a column for {name}{reason}, which is not countable")

    return found


def main() -> int:
    found = problems()
    if found:
        print("the taxonomy and its copies disagree:")
        for problem in found:
            print(f"  {problem}")
        print()
        print("proto/triald/v1/outcomes.proto is the taxonomy. Change it there first,")
        print("then follow it in the Python enum, the Acceptance message and the panel.")
        return 1
    print(f"the taxonomy and its three copies agree ({len(taxonomy())} outcomes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
