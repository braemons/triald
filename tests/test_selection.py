"""The bag: orderings, drawing without replacement, avoid-repeat, refilling."""

from __future__ import annotations

import itertools
import random
from collections import Counter

import pytest

from triald.selection import Ordering, TrialBag
from triald.trialtypes import TrialType, TrialTypeSet


def make_set(*weights: int, name: str = "s") -> TrialTypeSet:
    return TrialTypeSet(
        name=name,
        trial_types=[
            TrialType(name=f"t{i}", trials_per_round=w) for i, w in enumerate(weights)
        ],
    )


def drain(bag: TrialBag, n: int) -> list[int]:
    """Draw and consume `n` trials, as an accepted-every-trial session would."""
    drawn = []
    for _ in range(n):
        index = bag.draw()
        bag.consume(index)
        drawn.append(index)
    return drawn


def test_a_set_with_no_trials_is_refused():
    with pytest.raises(ValueError, match="no trials in it"):
        TrialBag(make_set(0, 0))


def test_round_is_the_sum_of_the_weights():
    bag = TrialBag(make_set(3, 2, 1), rounds=4)
    assert bag.trials_per_round == 6
    assert bag.trials_per_experiment == 24


def test_a_round_contains_exactly_the_weights():
    bag = TrialBag(make_set(3, 2, 1), rng=random.Random(0))
    counts = Counter(drain(bag, 6))
    assert counts == {0: 3, 1: 2, 2: 1}


def test_the_bag_refills_after_a_round():
    bag = TrialBag(make_set(2, 1), rng=random.Random(0))
    counts = Counter(drain(bag, 6))
    assert counts == {0: 4, 1: 2}  # two identical rounds


def test_random_in_experiment_holds_every_round_at_once():
    bag = TrialBag(make_set(2, 1), ordering=Ordering.RANDOM_IN_EXPERIMENT, rounds=3)
    assert bag.total_remaining == 9
    assert bag.remaining == [6, 3]


def test_ascending_takes_the_lowest_remaining_index():
    bag = TrialBag(make_set(2, 2), ordering=Ordering.ASCENDING)
    assert drain(bag, 4) == [0, 0, 1, 1]


def test_avoid_repeat_never_repeats_while_anything_else_is_left():
    bag = TrialBag(make_set(5, 5), avoid_repeat=True, rng=random.Random(1))
    drawn = drain(bag, 10)
    assert all(a != b for a, b in itertools.pairwise(drawn))


def test_avoid_repeat_gives_up_rather_than_stalling():
    # One type has a single trial left and it is the one just drawn: repeating is
    # the only option, and the round must not deadlock.
    bag = TrialBag(make_set(1, 0), avoid_repeat=True)
    first = bag.draw()
    bag.consume(first)
    assert bag.draw() == 0


def test_without_avoid_repeat_repeats_are_allowed():
    bag = TrialBag(make_set(20, 1), avoid_repeat=False, rng=random.Random(2))
    drawn = drain(bag, 20)
    assert any(a == b for a, b in itertools.pairwise(drawn))


def test_draw_does_not_consume():
    # Only accepted trials consume. A refused trial leaves the bag untouched, so
    # the round still contains the configured weights.
    bag = TrialBag(make_set(2, 2))
    before = bag.total_remaining
    bag.draw()
    assert bag.total_remaining == before


def test_the_same_seed_reproduces_the_same_sequence():
    # This is what VStim's rand() % n cannot do, and what makes replay possible.
    a = drain(TrialBag(make_set(4, 3, 2), rng=random.Random(1234)), 9)
    b = drain(TrialBag(make_set(4, 3, 2), rng=random.Random(1234)), 9)
    assert a == b


def test_weights_are_respected_over_many_rounds():
    bag = TrialBag(make_set(6, 3, 1), avoid_repeat=False, rng=random.Random(7))
    counts = Counter(drain(bag, 1000))
    assert counts[0] == 600
    assert counts[1] == 300
    assert counts[2] == 100


def test_zero_weight_types_are_never_drawn():
    bag = TrialBag(make_set(3, 0, 2), rng=random.Random(0))
    assert 1 not in set(drain(bag, 50))
