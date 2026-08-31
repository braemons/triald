"""Choosing the next trial type.

A round is a bag: each trial type contributes as many tokens as its
``trials_per_round`` weight, and trials are drawn without replacement until the
bag is empty, at which point it is refilled. The three orderings differ only in
how the draw is made and how big the bag is.

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

    def draw(self) -> int:
        """Draw the next trial type index. Refills first if the bag is empty.

        Does not consume: the bag empties only when a trial is *accepted*, via
        :meth:`consume`. A trial type can therefore be drawn several times in a
        row while the animal fails to produce an acceptable trial, which is the
        behaviour VStim has and the behaviour the weights imply.
        """
        if self.total_remaining == 0:
            self.refill()

        index = (
            self._draw_ascending()
            if self._ordering is Ordering.ASCENDING
            else self._draw_weighted()
        )
        self._last = index
        return index

    def consume(self, index: int) -> None:
        """Take one token of `index` out of the bag, for an accepted trial."""
        if self._remaining[index] > 0:
            self._remaining[index] -= 1

    def reset(self) -> None:
        """Refill the bag and forget what was drawn last."""
        self.refill()
        self._last = None

    # -- the draws --------------------------------------------------------------

    def _draw_ascending(self) -> int:
        for index, remaining in enumerate(self._remaining):
            if remaining > 0:
                return index
        return 0  # unreachable: refill() runs first, and the set is runnable

    def _draw_weighted(self) -> int:
        """Weighted draw over the remaining counts, optionally avoiding a repeat.

        With `avoid_repeat` the previous trial type is excluded from the draw -
        but only while something else is left. When the previous type is all that
        remains, it repeats rather than the round stalling.
        """
        candidates = list(enumerate(self._remaining))

        if self._avoid_repeat and self._last is not None:
            without_last = [(i, n) for i, n in candidates if i != self._last and n > 0]
            if without_last:
                candidates = without_last
            else:
                return self._last

        population = [i for i, n in candidates if n > 0]
        weights = [n for _, n in candidates if n > 0]
        if not population:
            self.refill()
            return self._draw_weighted()

        return self._rng.choices(population, weights=weights, k=1)[0]
