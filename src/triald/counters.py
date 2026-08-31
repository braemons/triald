"""Outcome tallies, per trial type and in total.

Every reported outcome lands here. Whether it was *accepted* - whether it
consumed a slot in the round - is recorded alongside it but decided elsewhere, by
:class:`~triald.outcomes.AcceptancePolicy`. Keeping the two apart is the point:
an experimenter watching a session needs to see both how many trials the animal
did and how many of them counted.
"""

from __future__ import annotations

import dataclasses
import enum
from collections import Counter

from triald.outcomes import OutcomeReport, TrialOutcome


class TrialCountCriterion(enum.StrEnum):
    """A way of counting trials, shared by the switch rule and the stop rule.

    One enum rather than two because the question is the same one - *how many
    trials of what kind* - and VStim asks it in both places with the same three
    answers (``TrialCountCriterion``). Two enums would drift.
    """

    ACCEPTED_TRIALS = "accepted_trials"
    """Trials the accept flags let through - the ones that fill a round."""

    HITS = "hits"
    """Trials that ended in :attr:`~triald.outcomes.TrialOutcome.HIT`.

    Early hits do not count - see :data:`~triald.outcomes.HIT_OUTCOMES`.
    """

    ALL_TRIALS = "all_trials"
    """Every completed trial, whatever it ended in."""


@dataclasses.dataclass(slots=True)
class ResultCount:
    """Tallies for one trial type, or for a whole session.

    Mirrors VStim's ``ResultCount``, with the eleven separate ``n*Err`` fields
    collapsed into :attr:`by_outcome` - they were only ever one counter per
    outcome code, and spelling them out made every new outcome a change in five
    places.
    """

    total: int = 0
    """Every outcome reported. VStim's ``nAll``."""

    accepted: int = 0
    """Outcomes that consumed a slot in the round. VStim's ``nDone``."""

    remaining: int = 0
    """Trials of this kind still to run in the current round or experiment."""

    frame_loss: int = 0
    """Trials that lost at least one frame, whatever else happened in them."""

    by_outcome: Counter[TrialOutcome] = dataclasses.field(default_factory=Counter)
    """One tally per outcome code."""

    def record(self, report: OutcomeReport, *, accepted: bool) -> None:
        """Tally `report`. Does not touch :attr:`remaining` - the bag owns that."""
        self.total += 1
        self.by_outcome[report.outcome] += 1
        if report.had_frame_loss:
            self.frame_loss += 1
        if accepted:
            self.accepted += 1

    def count_of(self, outcome: TrialOutcome) -> int:
        return self.by_outcome[outcome]

    @property
    def hits(self) -> int:
        return self.by_outcome[TrialOutcome.HIT]

    def counted(self, criterion: TrialCountCriterion) -> int:
        """The tally `criterion` names. VStim's ``TrialsCountedInSession``."""
        if criterion is TrialCountCriterion.HITS:
            return self.hits
        if criterion is TrialCountCriterion.ALL_TRIALS:
            return self.total
        return self.accepted

    @property
    def hit_rate(self) -> float | None:
        """Hits as a fraction of all reported trials, or None if there are none."""
        return self.hits / self.total if self.total else None

    def reset(self) -> None:
        """Clear every tally. :attr:`remaining` is the bag's, and is left alone."""
        self.total = 0
        self.accepted = 0
        self.frame_loss = 0
        self.by_outcome.clear()

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "accepted": self.accepted,
            "remaining": self.remaining,
            "frame_loss": self.frame_loss,
            "by_outcome": {o.name: n for o, n in sorted(self.by_outcome.items())},
        }
