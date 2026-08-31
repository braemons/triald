"""Sets, the store, switch-chain validation, and name reconciliation (#538)."""

from __future__ import annotations

import pytest

from triald.counters import TrialCountCriterion
from triald.trialtypes import (
    SwitchRule,
    TrialType,
    TrialTypeSet,
    TrialTypeStore,
    copy_names_to_all,
    reconcile_names,
)


def make_set(name: str, *weights: int, rule: SwitchRule | None = None) -> TrialTypeSet:
    return TrialTypeSet(
        name=name,
        trial_types=[
            TrialType(name=f"t{i}", trials_per_round=w) for i, w in enumerate(weights)
        ],
        switch_rule=rule or SwitchRule(),
    )


def test_trials_per_round_is_the_sum_of_the_weights():
    assert make_set("a", 3, 2, 1).trials_per_round == 6


def test_a_set_with_only_zero_weights_is_not_runnable():
    assert not make_set("a", 0, 0).is_runnable()


def test_a_set_cannot_exceed_the_tdr_ceiling():
    with pytest.raises(ValueError, match="more than the 256"):
        TrialTypeSet(name="huge", trial_types=[TrialType() for _ in range(257)])


def test_index_of_finds_a_named_trial_type():
    assert make_set("a", 1, 1, 1).index_of("t1") == 1


def test_index_of_reports_a_missing_name():
    with pytest.raises(KeyError, match="t9"):
        make_set("a", 1).index_of("t9")


# -- the store -----------------------------------------------------------------


def test_the_store_refuses_duplicate_names():
    store = TrialTypeStore([make_set("a", 1)])
    with pytest.raises(ValueError, match="already in the store"):
        store.add(make_set("a", 1))


def test_the_store_reports_a_missing_set():
    with pytest.raises(KeyError, match="nowhere"):
        TrialTypeStore().get("nowhere")


# -- switch rules --------------------------------------------------------------


def test_a_rule_is_armed_only_when_it_could_fire():
    assert not SwitchRule().is_armed()
    assert not SwitchRule(enabled=True, count=0, target="b").is_armed()
    assert not SwitchRule(enabled=True, count=5, target=None).is_armed()
    assert SwitchRule(enabled=True, count=5, target="b").is_armed()


def test_a_sound_chain_validates():
    store = TrialTypeStore(
        [
            make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            make_set("b", 2, rule=SwitchRule(enabled=True, count=1, target="c")),
            make_set("c", 2),
        ]
    )
    assert store.validate_switch_chain("a") is None


def test_a_missing_target_is_caught():
    store = TrialTypeStore(
        [make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="ghost"))]
    )
    assert "not in the store" in (store.validate_switch_chain("a") or "")


def test_an_empty_target_is_caught():
    # This is the one that divides by zero in VStim's round arithmetic.
    store = TrialTypeStore(
        [
            make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            make_set("b", 0, 0),
        ]
    )
    assert "no trials in it" in (store.validate_switch_chain("a") or "")


def test_a_self_switch_is_caught():
    store = TrialTypeStore(
        [make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="a"))]
    )
    assert "switches to itself" in (store.validate_switch_chain("a") or "")


def test_a_problem_three_hops_away_is_caught():
    store = TrialTypeStore(
        [
            make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            make_set("b", 2, rule=SwitchRule(enabled=True, count=1, target="c")),
            make_set("c", 2, rule=SwitchRule(enabled=True, count=1, target="ghost")),
        ]
    )
    assert "ghost" in (store.validate_switch_chain("a") or "")


def test_a_loop_terminates_the_walk():
    store = TrialTypeStore(
        [
            make_set("a", 2, rule=SwitchRule(enabled=True, count=1, target="b")),
            make_set("b", 2, rule=SwitchRule(enabled=True, count=1, target="a")),
        ]
    )
    assert store.validate_switch_chain("a") is None


def test_the_criterion_travels_with_the_set():
    s = make_set(
        "a",
        2,
        rule=SwitchRule(enabled=True, criterion=TrialCountCriterion.HITS, count=9, target="b"),
    )
    assert s.switch_rule.criterion is TrialCountCriterion.HITS
    assert s.switch_rule.count == 9


# -- names across sets (#538) ---------------------------------------------------


def test_reconcile_fills_in_blanks_without_overwriting():
    a = TrialTypeSet(name="a", trial_types=[TrialType(name="left"), TrialType(name="")])
    b = TrialTypeSet(name="b", trial_types=[TrialType(name=""), TrialType(name="right")])

    reconcile_names([a, b])

    assert [t.name for t in a] == ["left", "right"]
    assert [t.name for t in b] == ["left", "right"]


def test_reconcile_leaves_genuine_disagreements_alone():
    a = TrialTypeSet(name="a", trial_types=[TrialType(name="left")])
    b = TrialTypeSet(name="b", trial_types=[TrialType(name="port")])

    reconcile_names([a, b])

    assert a[0].name == "left"
    assert b[0].name == "port"


def test_copy_names_to_all_overwrites():
    a = TrialTypeSet(name="a", trial_types=[TrialType(name="left"), TrialType(name="right")])
    b = TrialTypeSet(
        name="b", trial_types=[TrialType(name="port"), TrialType(name="starboard")]
    )

    copy_names_to_all(a, [a, b])

    assert [t.name for t in b] == ["left", "right"]


def test_copy_names_can_target_one_trial_type():
    a = TrialTypeSet(name="a", trial_types=[TrialType(name="left"), TrialType(name="right")])
    b = TrialTypeSet(
        name="b", trial_types=[TrialType(name="port"), TrialType(name="starboard")]
    )

    copy_names_to_all(a, [a, b], index=0)

    assert [t.name for t in b] == ["left", "starboard"]
