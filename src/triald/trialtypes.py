"""Trial types, the sets they live in, and the rule for leaving a set.

A **trial type** is one condition: a name, how often it should run in a round, the
time sequence it uses, and how much reward it is worth. A **set** is a named
collection of them plus the rule for when to move on to another set.

The switch rule belongs to the set rather than to the session because it travels
with the set: through the store, through "save as", and through being loaded on
another rig. Training runs in blocks - fixation, then one line, then 1.5 cycles -
and the rule is what lets a session walk through those blocks on its own instead
of somebody sitting at the machine loading the next set by hand.

Ported from ``VStim::TrialType::TrialTypeConfig`` / ``TrialTypeSet`` /
``TrialTypeSetSwitchRule`` (VStim issue #239).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

from triald.counters import TrialCountCriterion

#: How many trial types a set can hold.
#:
#: VStim fixes this at 256 (``BaseMaximumNumberOfTrialTypes``) because the
#: extended trial type number is ``set * 256 + type`` and the ``.tdr`` format has
#: fixed-width fields for it. Nothing here needs a ceiling, but the encoding does,
#: so it stays until the ``.tdr`` question is settled - see dev/PLAN.md.
TRIAL_TYPES_PER_SET = 256


@dataclasses.dataclass(slots=True)
class SwitchRule:
    """When to leave this set, and for which one.

    ``target`` is a set *name*. VStim uses a 1-based index into a fixed store,
    which means a rule silently points somewhere else the moment sets are
    reordered. Names are stable under reordering and readable in a diff.
    """

    enabled: bool = False
    criterion: TrialCountCriterion = TrialCountCriterion.HITS
    count: int = 0
    """Trials of the chosen kind to complete in this set before leaving it."""

    target: str | None = None
    """Name of the set to go to. None means no target."""

    def is_armed(self) -> bool:
        """Whether this rule could ever fire, ignoring the target's validity."""
        return self.enabled and self.count > 0 and bool(self.target)


@dataclasses.dataclass(slots=True)
class TrialType:
    """One condition."""

    name: str = ""
    """What the experimenter calls this condition."""

    trials_per_round: int = 0
    """Weight: how many of this type make up one round. Zero means unused."""

    time_sequence: int = 0
    """Index of the time sequence this type runs with."""

    reward_ms: int = 0
    """Reward the type is worth. What is actually delivered is reported back."""

    params: dict[str, object] = dataclasses.field(default_factory=dict)
    """Paradigm parameters, passed through to vstimd and the behaviour source.

    triald does not interpret these - a contrast, a spatial frequency, a target
    position mean nothing to it. They exist because adaptive procedures work in a
    continuous *intensity* while trial types are discrete *conditions*, and the
    intensity has to live somewhere.

    A discrete staircase can ignore this and name its types ``contrast_1`` ..
    ``contrast_n``. A continuous one - QUEST, Psi - sets ``params["contrast"]``
    on a single type and lets the value carry the level. Recorded verbatim with
    every trial, so the level that actually ran is never in doubt.
    """


@dataclasses.dataclass(slots=True)
class TrialTypeSet:
    """A named collection of trial types, plus the rule for leaving it."""

    name: str
    trial_types: list[TrialType] = dataclasses.field(default_factory=list)
    switch_rule: SwitchRule = dataclasses.field(default_factory=SwitchRule)

    def __post_init__(self) -> None:
        if len(self.trial_types) > TRIAL_TYPES_PER_SET:
            raise ValueError(
                f"set {self.name!r} has {len(self.trial_types)} trial types, "
                f"more than the {TRIAL_TYPES_PER_SET} the .tdr encoding allows"
            )

    @property
    def trials_per_round(self) -> int:
        """How many trials make up one round of this set.

        Zero means the set cannot run: VStim divides by this in ``UpdateRounds()``,
        which is why an empty set is refused at every point it could be loaded.
        """
        return sum(t.trials_per_round for t in self.trial_types)

    def is_runnable(self) -> bool:
        return self.trials_per_round > 0

    def index_of(self, name: str) -> int:
        """Index of the trial type called `name`.

        Raises:
            KeyError: if no trial type in this set has that name.
        """
        for i, t in enumerate(self.trial_types):
            if t.name == name:
                return i
        raise KeyError(f"set {self.name!r} has no trial type named {name!r}")

    def __len__(self) -> int:
        return len(self.trial_types)

    def __getitem__(self, index: int) -> TrialType:
        return self.trial_types[index]

    def __iter__(self) -> Iterator[TrialType]:
        return iter(self.trial_types)


class TrialTypeStore:
    """The sets available to a session, addressed by name."""

    def __init__(self, sets: list[TrialTypeSet] | None = None) -> None:
        self._sets: dict[str, TrialTypeSet] = {}
        for s in sets or []:
            self.add(s)

    def add(self, trial_type_set: TrialTypeSet) -> None:
        if trial_type_set.name in self._sets:
            raise ValueError(f"a set named {trial_type_set.name!r} is already in the store")
        self._sets[trial_type_set.name] = trial_type_set

    def put(self, trial_type_set: TrialTypeSet) -> None:
        """Add `trial_type_set`, or replace the one that has its name.

        Replacing keeps the set's position, which matters under extended trial
        type numbering: the number is derived from where the set sits in the
        store, so editing a set must not silently renumber every trial after it.
        """
        self._sets[trial_type_set.name] = trial_type_set

    def remove(self, name: str) -> TrialTypeSet:
        """Take the set called `name` out of the store and return it.

        Raises:
            KeyError: if there is no such set.
        """
        try:
            return self._sets.pop(name)
        except KeyError:
            raise KeyError(f"no trial type set named {name!r}") from None

    def sets(self) -> list[TrialTypeSet]:
        """Every set, in store order."""
        return list(self._sets.values())

    def index_of(self, name: str) -> int:
        """Where `name` sits in the store, or -1. The set number, less one."""
        names = list(self._sets)
        return names.index(name) if name in self._sets else -1

    def get(self, name: str) -> TrialTypeSet:
        try:
            return self._sets[name]
        except KeyError:
            raise KeyError(f"no trial type set named {name!r}") from None

    def names(self) -> list[str]:
        return list(self._sets)

    def __contains__(self, name: object) -> bool:
        return name in self._sets

    def __len__(self) -> int:
        return len(self._sets)

    def validate_switch_chain(self, start: str) -> str | None:
        """Say why the switch rules reachable from `start` cannot be followed.

        Walks the whole chain, so a set three hops away that nobody filled in is
        caught before a session is left alone with it overnight. An A -> B -> A
        loop is fine and ends the walk.

        This runs when the session is armed, never when a rule fires: the switch
        happens between trials with nobody watching, where there is nothing
        sensible to do about a bad target. VStim learned this the hard way - an
        empty target set makes ``trials_per_round`` zero and the round arithmetic
        divides by it.

        Returns:
            A description of the first problem found, or None if the chain is
            sound.
        """
        if start not in self._sets:
            return f"no trial type set named {start!r}"

        seen: set[str] = set()
        name = start
        while name not in seen:
            seen.add(name)
            rule = self._sets[name].switch_rule
            if not rule.is_armed():
                return None

            assert rule.target is not None  # is_armed() checked it
            target = rule.target

            if target == name:
                return (
                    f"set {name!r} switches to itself, which would restart its block for ever"
                )
            if target not in self._sets:
                return f"set {name!r} switches to {target!r}, which is not in the store"
            if not self._sets[target].is_runnable():
                return (
                    f"set {name!r} switches to {target!r}, which has no trials in "
                    f"it and could never run"
                )
            name = target

        return None


def reconcile_names(sets: list[TrialTypeSet]) -> None:
    """Fill in trial type names that sets are missing from each other.

    Only empty names are written, using the first non-empty one found at that
    index in any set, so nothing anybody typed is ever replaced. This is what
    makes a name entered in one set show up in the others, and why a set stored
    before the name existed does not show a blank column (VStim issue #538).

    Only meaningful while the trial type number is *not* extended by the set
    number. With the extension the sets hold genuinely different trial types and
    the names are properly their own.

    Names that disagree are left disagreeing - deciding between them is what
    :func:`copy_names_to_all` is for.
    """
    width = max((len(s.trial_types) for s in sets), default=0)
    for index in range(width):
        canonical = next(
            (
                s.trial_types[index].name
                for s in sets
                if index < len(s.trial_types) and s.trial_types[index].name
            ),
            "",
        )
        if not canonical:
            continue
        for s in sets:
            if index < len(s.trial_types) and not s.trial_types[index].name:
                s.trial_types[index].name = canonical


def copy_names_to_all(
    source: TrialTypeSet, sets: list[TrialTypeSet], index: int | None = None
) -> None:
    """Copy trial type names from `source` into every set in `sets`.

    Unlike :func:`reconcile_names` this overwrites. Without "extend trial type
    number by set number" a trial type number addresses the same condition in
    every set, so its name belongs to the number rather than to whichever set it
    happened to be typed in (VStim issue #538).

    Args:
        index: the single trial type to copy, or None for all of them.
    """
    indices = range(len(source.trial_types)) if index is None else [index]
    for i in indices:
        if i >= len(source.trial_types):
            continue
        name = source.trial_types[i].name
        for s in sets:
            if s is not source and i < len(s.trial_types):
                s.trial_types[i].name = name
