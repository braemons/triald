# SPDX-License-Identifier: AGPL-3.0-or-later
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


# -- descending -----------------------------------------------------------------


def test_descending_takes_the_highest_index_first():
    bag = TrialBag(make_set(2, 1, 3), ordering=Ordering.DESCENDING)
    assert drain(bag, 6) == [2, 2, 2, 1, 0, 0]


def test_descending_is_the_mirror_of_ascending():
    # Reverse the weights as well as the direction, and the two orderings walk
    # the same ladder from opposite ends.
    weights = (3, 1, 2)
    up = drain(TrialBag(make_set(*weights), ordering=Ordering.ASCENDING), 6)
    down = drain(TrialBag(make_set(*reversed(weights)), ordering=Ordering.DESCENDING), 6)
    assert down == [len(weights) - 1 - i for i in up]


def test_descending_ignores_avoid_repeat():
    # A deterministic ordering has nothing to avoid a repeat with: honouring the
    # flag would mean not running the weights, which is what the ordering is for.
    bag = TrialBag(make_set(3, 1), ordering=Ordering.DESCENDING, avoid_repeat=True)
    assert drain(bag, 4) == [1, 0, 0, 0]


# -- random with replacement ----------------------------------------------------


def test_with_replacement_can_overdraw_a_type():
    # The point of the ordering: a type whose quota is spent still comes up.
    bag = TrialBag(
        make_set(1, 1),
        ordering=Ordering.RANDOM_WITH_REPLACEMENT,
        avoid_repeat=False,
        rng=random.Random(3),
    )
    counts = Counter(drain(bag, 200))
    assert set(counts) == {0, 1}
    # A bag without replacement would give exactly 100 each over 100 rounds.
    assert counts[0] != 100


def test_with_replacement_still_has_rounds_of_the_right_length():
    # Rounds have to keep meaning something, or the stop rules do not either.
    bag = TrialBag(
        make_set(2, 1), ordering=Ordering.RANDOM_WITH_REPLACEMENT, rng=random.Random(0)
    )
    assert bag.trials_per_round == 3
    assert bag.total_remaining == 3
    for expected in (2, 1, 0):
        bag.consume(bag.draw())
        assert bag.total_remaining == expected
    bag.draw()  # refills first
    assert bag.total_remaining == 3


def test_with_replacement_follows_the_configured_weights():
    bag = TrialBag(
        make_set(3, 1),
        ordering=Ordering.RANDOM_WITH_REPLACEMENT,
        avoid_repeat=False,
        rng=random.Random(11),
    )
    counts = Counter(drain(bag, 4000))
    assert 0.70 < counts[0] / 4000 < 0.80  # 3 in 4


def test_with_replacement_honours_avoid_repeat():
    bag = TrialBag(
        make_set(5, 5),
        ordering=Ordering.RANDOM_WITH_REPLACEMENT,
        avoid_repeat=True,
        rng=random.Random(5),
    )
    drawn = drain(bag, 40)
    assert not any(a == b for a, b in itertools.pairwise(drawn))


# -- P(next) --------------------------------------------------------------------


def test_probabilities_follow_the_remaining_counts():
    bag = TrialBag(make_set(3, 1), avoid_repeat=False)
    assert bag.probabilities() == [0.75, 0.25]


def test_probabilities_are_certain_under_a_deterministic_ordering():
    assert TrialBag(make_set(1, 1), ordering=Ordering.ASCENDING).probabilities() == [1.0, 0.0]
    assert TrialBag(make_set(1, 1), ordering=Ordering.DESCENDING).probabilities() == [0.0, 1.0]


def test_probabilities_exclude_the_last_drawn_under_avoid_repeat():
    bag = TrialBag(make_set(3, 1), avoid_repeat=True, rng=random.Random(0))
    bag.consume(0)
    bag._last = 0  # as though type 0 had just been drawn
    assert bag.probabilities() == [0.0, 1.0]


def test_probabilities_describe_the_refilled_bag_when_it_is_empty():
    # draw() refills before drawing, so an empty bag must not read as all zeros
    # at every round boundary.
    bag = TrialBag(make_set(2, 2), avoid_repeat=False)
    drain(bag, 4)
    assert bag.total_remaining == 0
    assert bag.probabilities() == [0.5, 0.5]


def test_probabilities_under_replacement_ignore_what_has_run():
    bag = TrialBag(
        make_set(3, 1), ordering=Ordering.RANDOM_WITH_REPLACEMENT, avoid_repeat=False
    )
    bag.consume(0)
    bag.consume(0)
    bag.consume(0)
    assert bag.remaining[0] == 0
    assert bag.probabilities() == [0.75, 0.25]


def test_probabilities_sum_to_one():
    for ordering in Ordering:
        bag = TrialBag(make_set(4, 2, 1), ordering=ordering, avoid_repeat=False)
        assert sum(bag.probabilities()) == pytest.approx(1.0), ordering
