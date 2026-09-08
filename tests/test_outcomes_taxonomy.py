# SPDX-License-Identifier: AGPL-3.0-or-later
"""triald's copies of the `.tdr` taxonomy against the canonical one.

There are five copies of this table across the family, because five languages
and contexts need it, and until now *nothing* held them together. §5.2 of the
contracts repo is what that costs: code 8 was spelled two ways, so one outcome
was unparseable at the far end and any graph written from the other vocabulary
was refused at compile — by a person with both spellings in front of them in two
web UIs.

**Outcomes cross the wire by name**, so a copy that drifts is not a cosmetic
problem. This checks triald's two against `tests/contracts/outcomes.json`, which
is vendored rather than imported: see that directory's README.
"""

from __future__ import annotations

import sys
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parent / "contracts"
sys.path.insert(0, str(CONTRACTS))

import check_outcomes as check  # noqa: E402

SOURCE = Path(__file__).resolve().parents[1] / "src" / "triald"


def taxonomy() -> dict:
    return check.load_taxonomy(CONTRACTS / "outcomes.json")


def test_the_enum_is_the_canonical_table():
    problems = check.problems(
        taxonomy(),
        {"src/triald/outcomes.py": check.python_enum((SOURCE / "outcomes.py").read_text())},
    )
    assert not problems, "\n".join(problems)


def test_the_counters_table_has_a_column_for_every_outcome_a_trial_can_carry():
    # Not UNDETERMINED: nobody assigns it, so the column would always read zero
    # and invite the question of what it meant.
    app = (SOURCE / "web" / "app.js").read_text()
    problems = check.countable_problems(
        taxonomy(), "web/app.js OUTCOME_COLUMNS", check.javascript_names(app, "OUTCOME_COLUMNS")
    )
    assert not problems, "\n".join(problems)


def test_there_is_an_accept_flag_for_every_outcome_and_no_others():
    """`AcceptancePolicy` decides per outcome, so a missing flag is a trial that
    can never be accepted and an extra one is a setting that does nothing."""
    from triald.outcomes import AcceptancePolicy, TrialOutcome

    expected = {name.lower() for name in check.canonical_values(taxonomy())}
    # UNDETERMINED is never reported, so it has no flag; every other one does.
    expected.discard("undetermined")
    flags = {
        field
        for field in AcceptancePolicy.__dataclass_fields__
        if field not in {"frame_loss", "imprecise_fixation", "_BY_OUTCOME"}
    }
    assert flags == expected

    # And the mapping from outcome to flag reaches all of them.
    mapped = {AcceptancePolicy._BY_OUTCOME.get(o) for o in TrialOutcome}
    assert mapped == expected | {None}  # None for UNDETERMINED


def test_the_defaults_are_the_ones_the_taxonomy_states():
    """Which outcomes count towards a round is a decision about the experiment,
    and it is recorded once, here."""
    from triald.outcomes import AcceptancePolicy, TrialOutcome

    policy = AcceptancePolicy()
    for name, accepted in check.accepted_by_default(taxonomy()).items():
        if name == "UNDETERMINED":
            continue
        assert policy.accepts_outcome(TrialOutcome[name]) is accepted, name


def test_the_checker_would_notice_a_drift():
    """The one failure mode of a regex-based checker: a pattern that stops
    matching finds nothing and passes vacuously. So a deliberate drift must be
    caught, and an unreadable file must be reported as unreadable."""
    assert check.problems(taxonomy(), {"nothing": {}})
    assert check.problems(
        taxonomy(), {"renamed": {**check.canonical_values(taxonomy()), "HIT": 99}}
    )
    assert check.python_enum("class Unrelated:\n    HIT = 1\n") == {}
