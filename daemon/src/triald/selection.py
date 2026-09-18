# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choosing the next trial type.

A round is a bag: each trial type contributes as many tokens as its
``trials_per_round`` weight, and trials are drawn without replacement until the
bag is empty, at which point it is refilled. The three orderings differ only in
how the draw is made and how big the bag is - except
:attr:`Ordering.RANDOM_WITH_REPLACEMENT`, which puts the token back.

Ported from ``TrialTypeManager::GetNextTrialType`` / ``InitNewRound``, with one
deliberate change: the random number generator. VStim uses ``rand() % n``, which
is both biased towards low indices and unseedable in practice, so a VStim session
cannot be reproduced. Here the generator is an explicit
:class:`random.Random` whose seed is recorded with the session, which makes
``ReplaySession`` possible.
"""

from __future__ import annotations

import enum
import random
from collections.abc import Iterable, Sequence

from triald.trialtypes import TrialTypeSet


class Ordering(enum.StrEnum):
    """How the next trial type is drawn from the bag."""

    RANDOM_IN_ROUND = "random_in_round"
    """Random within a round: the bag holds one round and refills each round.

    Every round therefore contains exactly the configured weights, which is what
    you want when a block has to be balanced.
    """

    RANDOM_IN_EXPERIMENT = "random_in_experiment"
    """Random across the whole experiment: the bag holds every round at once.

    Rounds stop being balanced individually - the whole experiment is - so a run
    of one condition is possible and expected.
    """

    ASCENDING = "ascending"
    """Strictly by trial type index, lowest remaining first."""

    DESCENDING = "descending"
    """Strictly by trial type index, highest remaining first.

    The mirror of :attr:`ASCENDING`, and the reason it exists: a ladder of
    difficulties runs from easy to hard under one and hard to easy under the
    other, without anybody having to renumber the trial types.
    """

    RANDOM_WITH_REPLACEMENT = "random_with_replacement"
    """Random on the configured weights, ignoring what has already run.

    The other four draw *without* replacement: a token comes out of the bag and
    the round is balanced by construction. This one puts the token back, so each
    trial is an independent draw on the weights and a round is balanced only in
    expectation. Runs of one condition are longer than people expect, which is
    the point when a subject can learn that a condition is "used up".

    The round is still ``trials_per_round`` accepted trials long - it has to be,
    or rounds and the stop rules would mean nothing - but which types fill it is
    left to chance. The per-type ``remaining`` therefore reads as the quota still
    owed, and can sit at zero while the round runs on.
    """


class TrialBag:
    """The remaining-count bag that trial types are drawn from.

    Holds one entry per trial type in the set, counting down as trials are
    accepted. Only *accepted* trials consume from the bag: a trial the acceptance
    policy turns away leaves the bag untouched and will be made up later in the
    round.
    """

    def __init__(
        self,
        trial_type_set: TrialTypeSet,
        *,
        ordering: Ordering = Ordering.RANDOM_IN_ROUND,
        rounds: int = 10,
        avoid_repeat: bool = True,
        rng: random.Random | None = None,
    ) -> None:
        if not trial_type_set.is_runnable():
            raise ValueError(
                f"set {trial_type_set.name!r} has no trials in it; the round "
                f"arithmetic would divide by zero"
            )
        if rounds < 1:
            raise ValueError(f"rounds must be at least 1, got {rounds}")

        self._set = trial_type_set
        self._ordering = ordering
        self._rounds = rounds
        self._avoid_repeat = avoid_repeat
        self._rng = rng if rng is not None else random.Random()

        self._remaining: list[int] = []
        self._last: int | None = None

        # Trials left in the round under RANDOM_WITH_REPLACEMENT, where the
        # per-type counts are a quota rather than a stock and cannot be summed
        # to get it. Maintained in every ordering so total_remaining has one
        # answer, but only consulted in that one.
        self._round_remaining = 0
        self.refill()

    # -- shape of the experiment ------------------------------------------------

    @property
    def trials_per_round(self) -> int:
        return self._set.trials_per_round

    @property
    def trials_per_experiment(self) -> int:
        return self.trials_per_round * self._rounds

    @property
    def remaining(self) -> list[int]:
        """Remaining count per trial type index. A copy; mutate via the bag."""
        return list(self._remaining)

    @property
    def total_remaining(self) -> int:
        """Trials left before the bag refills.

        Under :attr:`Ordering.RANDOM_WITH_REPLACEMENT` this is the round length
        counting down, not the sum of the per-type counts: a type can be drawn
        after its quota is spent, so the two part company.
        """
        if self._ordering is Ordering.RANDOM_WITH_REPLACEMENT:
            return self._round_remaining
        return sum(self._remaining)

    @property
    def last_drawn(self) -> int | None:
        return self._last

    # -- filling and emptying ---------------------------------------------------

    def refill(self) -> None:
        """Fill the bag for a fresh round or experiment.

        Under :attr:`Ordering.RANDOM_IN_EXPERIMENT` the bag holds every round at
        once, which is what makes rounds irregular under that ordering.
        """
        scale = self._rounds if self._ordering is Ordering.RANDOM_IN_EXPERIMENT else 1
        self._remaining = [t.trials_per_round * scale for t in self._set]
        self._round_remaining = sum(self._remaining)

    def draw(self) -> int:
        """Draw the next trial type index. Refills first if the bag is empty.

        Does not consume: the bag empties only when a trial is *accepted*, via
        :meth:`consume`. A trial type can therefore be drawn several times in a
        row while the animal fails to produce an acceptable trial, which is the
        behaviour VStim has and the behaviour the weights imply.
        """
        if self.total_remaining == 0:
            self.refill()

        if self._ordering is Ordering.ASCENDING:
            index = self._draw_in_order(range(len(self._remaining)))
        elif self._ordering is Ordering.DESCENDING:
            index = self._draw_in_order(reversed(range(len(self._remaining))))
        elif self._ordering is Ordering.RANDOM_WITH_REPLACEMENT:
            index = self._draw_with_replacement()
        else:
            index = self._draw_weighted()
        self._last = index
        return index

    def consume(self, index: int) -> None:
        """Take one token of `index` out of the bag, for an accepted trial.

        The per-type count floors at zero, which only happens with replacement:
        every other ordering draws from the counts and so cannot overdraw one.
        """
        if self._remaining[index] > 0:
            self._remaining[index] -= 1
        if self._round_remaining > 0:
            self._round_remaining -= 1

    def reset(self) -> None:
        """Refill the bag and forget what was drawn last."""
        self.refill()
        self._last = None

    # -- the draws --------------------------------------------------------------

    def _draw_in_order(self, indices: Iterable[int]) -> int:
        """The first index in `indices` that still has something left."""
        for index in indices:
            if self._remaining[index] > 0:
                return index
        return 0  # unreachable: refill() runs first, and the set is runnable

    def _draw_with_replacement(self) -> int:
        """An independent draw on the configured weights.

        The remaining counts play no part: a type whose quota is spent can still
        come up, which is what "with replacement" means. Avoid-repeat still
        applies, and still gives way when there is nothing else to draw.
        """
        population, weights = self._eligible(self._weights())
        if not population:
            return self._last if self._last is not None else 0
        return self._rng.choices(population, weights=weights, k=1)[0]

    def _draw_weighted(self) -> int:
        """Weighted draw over the remaining counts, optionally avoiding a repeat."""
        population, weights = self._eligible(self._remaining)
        if not population:
            self.refill()
            population, weights = self._eligible(self._remaining)
            if not population:
                return 0  # unreachable: the set is runnable, so a refill fills it
        return self._rng.choices(population, weights=weights, k=1)[0]

    def _eligible(self, weights: Sequence[int]) -> tuple[list[int], list[int]]:
        """The indices `weights` allows to be drawn, and their weights.

        With `avoid_repeat` the previous trial type is excluded - but only while
        something else is left. When it is all that remains it repeats, rather
        than the round stalling.
        """
        population = [i for i, w in enumerate(weights) if w > 0]
        if self._avoid_repeat and self._last is not None and len(population) > 1:
            population = [i for i in population if i != self._last]
        return population, [weights[i] for i in population]

    def _weights(self) -> list[int]:
        """The configured per-round weights, whatever the bag has left."""
        return [t.trials_per_round for t in self._set]

    # -- what the next draw will probably be ------------------------------------

    def probabilities(self) -> list[float]:
        """Chance of each trial type coming up next, one entry per type.

        VStim's ``GetProbabilityOfNextTrialType``, and the ``P(next)`` column of
        the counters table. The deterministic orderings answer 1 and 0, which is
        the honest answer rather than a missing one.

        **Advisory.** It describes what the bag would do. A policy whose
        ``select_trial`` returns a type decides for itself and the bag is never
        asked, so the column is a description of the declarative fallback.
        """
        width = len(self._remaining)
        if width == 0:
            return []

        # draw() refills an empty bag before drawing, so report the refilled one
        # rather than a row of zeros at every round boundary.
        remaining = self._remaining
        if self.total_remaining == 0 or not any(remaining):
            scale = self._rounds if self._ordering is Ordering.RANDOM_IN_EXPERIMENT else 1
            remaining = [t.trials_per_round * scale for t in self._set]

        p = [0.0] * width

        if self._ordering in (Ordering.ASCENDING, Ordering.DESCENDING):
            order: Iterable[int] = (
                range(width) if self._ordering is Ordering.ASCENDING else reversed(range(width))
            )
            for index in order:
                if remaining[index] > 0:
                    p[index] = 1.0
                    break
            return p

        weights = (
            self._weights() if self._ordering is Ordering.RANDOM_WITH_REPLACEMENT else remaining
        )
        population, eligible = self._eligible(weights)
        total = sum(eligible)
        if total <= 0:
            return p
        for index, weight in zip(population, eligible, strict=True):
            p[index] = weight / total
        return p
