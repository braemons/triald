"""Adaptive procedures, built in so the common cases need no dependencies.

A transformed up/down staircase is thirty lines and has no business pulling a
GUI toolkit onto a rig box, so the up/down family lives here. Anything more -
QUEST, Psi, multiple interleaved staircases - is better taken from a library
that specialises in it:

* ``questplus`` (pure Python + numpy) for QUEST+.
* PsychoPy's ``psychopy.data`` for ``QuestHandler``, ``PsiHandler`` and
  ``MultiStairHandler``, which is worth the weight when a triald staircase has to
  match an existing PsychoPy experiment exactly.

Neither is a dependency of triald. On a rig, install them into the daemon's own
interpreter with ``trialctl env install questplus`` and import them from your
policy; numpy and scipy are already there. See dev/PLAN.md, "The runtime
environment".

These classes are deliberately *not* policies. They are the arithmetic; a
:class:`~triald.policy.Policy` decides how a level maps onto a trial type, which
is the part that differs per paradigm.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(slots=True)
class Staircase:
    """Transformed up/down staircase over a discrete ladder of levels.

    ``n_down`` correct responses in a row make the task harder by one step; a
    single incorrect response makes it easier. The classic 2-down-1-up converges
    on about 70.7% correct, 3-down-1-up on about 79.4%.

    Levels are indices into a ladder you define, not physical values, because the
    mapping from an index to a contrast or a coherence belongs to the paradigm.
    Index 0 is the *easiest* end by convention; :attr:`level` moves up towards
    harder.
    """

    n_levels: int
    level: int = 0
    n_down: int = 2
    """Correct responses needed in a row before stepping harder."""

    n_up: int = 1
    """Incorrect responses needed in a row before stepping easier."""

    step_up: int = 1
    """Levels to move when the task gets harder."""

    step_down: int = 1
    """Levels to move when the task gets easier."""

    _correct_run: int = dataclasses.field(default=0, init=False)
    _incorrect_run: int = dataclasses.field(default=0, init=False)
    _last_direction: int = dataclasses.field(default=0, init=False)
    reversals: int = dataclasses.field(default=0, init=False)
    history: list[int] = dataclasses.field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.n_levels < 1:
            raise ValueError(f"n_levels must be at least 1, got {self.n_levels}")
        self.level = max(0, min(self.level, self.n_levels - 1))

    def update(self, correct: bool) -> int:
        """Feed one response and return the new level.

        Only accepted trials should reach this. A staircase stepped on refused
        trials drifts in ways that are very hard to see afterwards.
        """
        self.history.append(self.level)

        if correct:
            self._correct_run += 1
            self._incorrect_run = 0
            if self._correct_run >= self.n_down:
                self._correct_run = 0
                self._step(+self.step_up)
        else:
            self._incorrect_run += 1
            self._correct_run = 0
            if self._incorrect_run >= self.n_up:
                self._incorrect_run = 0
                self._step(-self.step_down)

        return self.level

    def _step(self, delta: int) -> None:
        direction = 1 if delta > 0 else -1
        if self._last_direction != 0 and direction != self._last_direction:
            self.reversals += 1
        self._last_direction = direction
        self.level = max(0, min(self.level + delta, self.n_levels - 1))

    def threshold(self, last_n_reversals: int = 6) -> float | None:
        """Mean level over the last reversals, or None before there are enough.

        The usual estimator for an up/down staircase. It uses the levels the
        staircase *visited*, so it is only meaningful once it has settled.
        """
        if self.reversals < last_n_reversals or not self.history:
            return None
        tail = self.history[-(last_n_reversals * 2) :]
        return sum(tail) / len(tail)

    def snapshot(self) -> dict[str, object]:
        """State worth putting in the trial record."""
        return {
            "level": self.level,
            "reversals": self.reversals,
            "correct_run": self._correct_run,
            "incorrect_run": self._incorrect_run,
        }


@dataclasses.dataclass(slots=True)
class WeightedUpDown(Staircase):
    """Kaernbach's weighted up/down: asymmetric step sizes, one response each.

    Converges on ``step_down / (step_up + step_down)`` correct, which lets you
    target a threshold that the integer n-down/1-up ratios cannot reach. Set
    ``step_up=1, step_down=3`` for 75%.
    """

    def __post_init__(self) -> None:
        # Explicit rather than a zero-argument super(): @dataclass(slots=True)
        # builds a replacement class, so the closure super() captures points at
        # the original and raises "obj must be an instance or subtype of type".
        Staircase.__post_init__(self)
        self.n_down = 1
        self.n_up = 1
