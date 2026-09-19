# SPDX-License-Identifier: AGPL-3.0-or-later
"""The types this client hands back, and the ones it takes.

**No protobuf type crosses this package's edge**, which is the rule
`contracts/DAEMON_LAYOUT.md` states for every client in this family: the
generated code is private, in `triald_client._proto`, and this module is the
vocabulary a person writes against. Somebody reading a reaction time out of a
trial should not have to learn a generated API to do it.

Everything here is a frozen dataclass, so a record you were handed cannot be
edited into something the daemon never said. `_wire_conversions.py` is the seam
in both directions and is the only module that imports the generated types.

**The names are the proto's**, field for field, because the family's rule is
that a name travels unchanged: `trial_number` is `trial_number` in the proto,
on the wire, in the `trials.jsonl` line on disk, in the browser and here.

The enums are the one deliberate departure. `triald.v1.Ordering` spells its
values `ORDERING_RANDOM_IN_ROUND`, because protobuf requires a value name to be
unique across every enum in its package; nobody writing Python should have to
say `Ordering.ORDERING_RANDOM_IN_ROUND`. The prefix is dropped here and put
back on the wire, in one place, by the conversions.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Any

# -- the enums ------------------------------------------------------------------


class TrialOutcome(enum.IntEnum):
    """How a trial ended, as the `.tdr` code it has always been.

    An `IntEnum` because **these numbers are the contract**. They are in every
    `.tdr` the lab has written and in every analysis script that reads one, and
    they are never renumbered — so `TrialOutcome.HIT == 1` is a fact worth
    being able to rely on, and `int(outcome)` is what goes into a table.

    `NEVER_FINISHED` is the only one triald assigns to itself: nothing reports
    it, and it means the trial's deadline passed with no verdict.
    """

    UNDETERMINED = -1
    NOT_STARTED = 0
    HIT = 1
    WRONG_RESPONSE = 2
    EARLY_HIT = 3
    EARLY_WRONG_RESPONSE = 4
    EARLY = 5
    LATE = 6
    EYE_ERROR = 7
    UNEXPECTED_START_SIGNAL = 8
    WRONG_START_SIGNAL = 9
    CANCELLED = 10
    NEVER_FINISHED = 11


class Manipulandum(enum.IntEnum):
    """Which input device produced an outcome. Recorded, never interpreted."""

    NONE = 0
    LEVER = 1
    TOUCH_BAR = 2
    BUTTON = 3
    JOYSTICK = 4
    GAMEPAD = 5
    SERIAL = 6
    SIMULATED = 7


class Ordering(enum.StrEnum):
    """How the next trial type is drawn from the bag.

    A `StrEnum`, so a config file or a CLI argument can carry the name and
    compare equal to it. `docs/reference/api.md` in the daemon's repository has
    what each one does to a round.
    """

    RANDOM_IN_ROUND = "random_in_round"
    RANDOM_IN_EXPERIMENT = "random_in_experiment"
    ASCENDING = "ascending"
    DESCENDING = "descending"
    RANDOM_WITH_REPLACEMENT = "random_with_replacement"


class TrialCountCriterion(enum.StrEnum):
    """Which trials a stop rule or a switch rule counts.

    One enum for both, deliberately: it is the same question in both places,
    and two would drift.
    """

    ACCEPTED_TRIALS = "accepted_trials"
    HITS = "hits"
    ALL_TRIALS = "all_trials"


class PolicyOrigin(enum.StrEnum):
    """Where the loaded policy came from."""

    DEFAULT = "default"
    FILE = "file"
    UPLOADED = "uploaded"


# -- what a trial is ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrameLoss:
    """A video frame the display did not deliver, and where.

    Comes from vstimd, through whoever ran the trial. Its presence can veto
    acceptance on its own, whatever the outcome was.
    """

    interval: int
    frame: int


@dataclass(frozen=True, slots=True)
class OutcomeReport:
    """What you send when a trial ends.

    The one inbound message that matters, and it has to carry every modifier
    that takes part in the accept decision — the daemon has no other way to
    learn them. `precise_fixation` comes from the eye monitor and `frame_loss`
    from the display; either can refuse an otherwise-accepted trial.

    `trial_id` is not here: it addresses the message rather than describing the
    outcome, and `TrialdClient.report_outcome` takes it as its own argument.
    """

    outcome: TrialOutcome
    manipulandum: Manipulandum = Manipulandum.NONE
    reaction_time_ms: float | None = None
    terminating_interval: int | None = None
    precise_fixation: bool = True
    frame_loss: FrameLoss | None = None
    reward_ms: int = 0
    hit_condition: bool = False
    simulated: bool = False
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    """A trial's outcome as the daemon recorded it.

    `code` and `name` are the same thing twice — the number an analysis script
    wants and the word a person reads — and they come from the daemon rather
    than being derived here, so a client that is older than the taxonomy still
    shows what happened.
    """

    code: TrialOutcome
    name: str
    manipulandum: str
    reaction_time_ms: float | None
    terminating_interval: int | None
    precise_fixation: bool
    frame_loss: FrameLoss | None
    reward_ms: int
    hit_condition: bool
    simulated: bool
    note: str | None


@dataclass(frozen=True, slots=True)
class TrialSpec:
    """The trial that was selected, latched at the moment of selection.

    Everything here is stable for the whole trial — including `recording`, so a
    trial that began recording finishes recording even if somebody pauses in
    the middle of it.

    `deadline` is when the daemon gives up and records `NEVER_FINISHED`. It is
    published so that whoever runs the trial can use the same number as its own
    wall-clock cap rather than inventing one.
    """

    trial_number: int
    trial_type_index: int
    trial_type_number: int
    trial_type_name: str
    set_name: str
    statemachine_graph: str
    reward_ms: int
    recording: bool
    paused: bool
    started_at: dt.datetime | None = None
    deadline: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class TrialRecord:
    """One finished trial: what was selected, what happened, and whether it counted.

    **`accepted` is the field to read first.** Every reported outcome is
    *counted*; only an accepted one consumes from the bag, advances the round
    and moves a set towards its switch rule. Three things can veto it — the
    outcome's own accept flag, frame loss, imprecise fixation — and
    `refusal_reason` says which one did, because an experimenter watching a
    session stall at 40 accepted trials needs to know.
    """

    trial: TrialSpec | None
    outcome: Outcome | None
    accepted: bool
    refusal_reason: str | None
    ended_at: dt.datetime | None
    policy_state: dict[str, Any] | None


# -- the settings ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Acceptance:
    """Which outcomes consume a slot in the round, plus the two vetoes.

    The last two cut across every outcome: a trial that lost a frame, or whose
    fixation was imprecise, can be refused whatever it otherwise was.
    """

    not_started: bool = False
    hit: bool = True
    wrong_response: bool = True
    early_hit: bool = True
    early_wrong_response: bool = True
    early: bool = True
    late: bool = True
    eye_error: bool = True
    unexpected_start_signal: bool = False
    wrong_start_signal: bool = False
    cancelled: bool = False
    never_finished: bool = False
    frame_loss: bool = True
    imprecise_fixation: bool = True


@dataclass(frozen=True, slots=True)
class SessionConfig:
    """One experiment's declarative settings — everything editable without Python."""

    initial_set: str
    ordering: Ordering
    rounds: int
    avoid_repeat: bool
    acceptance: Acceptance
    trial_cap_ms: int
    stop_when_rounds_done: bool
    stop_after_trials: int | None
    stop_criterion: TrialCountCriterion
    extend_trial_type_number: bool
    seed: int | None


@dataclass(frozen=True, slots=True)
class ConfigPatch:
    """A change to the config: only the fields you are setting.

    `None` means "leave it alone" everywhere except `stop_after_trials`, where
    "no limit" is itself a value — clear that one by sending `0`.

    The settings split three ways and the split is worth knowing before a
    session runs: the accept flags and stop rules take effect on the next
    trial; `ordering`, `rounds` and `avoid_repeat` rebuild the bag and restart
    the round; and `initial_set`, `extend_trial_type_number` and `seed` are
    **refused while a session runs**, because each decides something that has
    already happened.
    """

    ordering: Ordering | None = None
    rounds: int | None = None
    avoid_repeat: bool | None = None
    acceptance: Acceptance | None = None
    trial_cap_ms: int | None = None
    stop_when_rounds_done: bool | None = None
    stop_after_trials: int | None = None
    stop_criterion: TrialCountCriterion | None = None
    initial_set: str | None = None
    extend_trial_type_number: bool | None = None
    seed: int | None = None


@dataclass(frozen=True, slots=True)
class ConfigUpdateResult:
    """What a config change actually cost."""

    changed: tuple[str, ...]
    bag_rebuilt: bool
    config: SessionConfig | None


# -- sets -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SwitchRule:
    """When to leave this set, and for which one.

    `target` is a set **name**, not an index: an index-based rule points
    somewhere else the moment sets are reordered.
    """

    enabled: bool
    criterion: TrialCountCriterion
    count: int
    target: str | None


@dataclass(frozen=True, slots=True)
class TrialType:
    """One condition, and how much of a round it is worth.

    `params` is paradigm data — a contrast, a coherence, a target position —
    and **triald never interprets it**. It is recorded verbatim with every
    trial, which is where an adaptive procedure's intensity lives.

    `statemachine_graph` is a name, not an index, and empty means "leave
    whatever the executor has loaded". triald holds no graphs.
    """

    name: str
    trials_per_round: int
    statemachine_graph: str = ""
    reward_ms: int = 0
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrialTypeSet:
    """A named list of trial types, with its own switch rule.

    The rule travels with the set — through the store, through "save as", and
    onto another rig — which is why it is here rather than in the config.

    The last four fields are the daemon's view of the set and are ignored on
    the way in: `trials_per_round` is the sum of the weights, `runnable` says
    whether a round would be non-empty, and `set_number` is what extends a
    trial type number when that is on.
    """

    name: str
    trial_types: tuple[TrialType, ...]
    switch_rule: SwitchRule | None = None
    trials_per_round: int = 0
    runnable: bool = True
    set_number: int = 0
    active: bool = False


@dataclass(frozen=True, slots=True)
class Sets:
    """Every set the daemon holds, and whether the chain hangs together.

    `chain_problem` is the check `Arm` refuses on, run continuously — so a set
    three hops away that nobody filled in shows up before anybody starts a
    session rather than at two in the morning.
    """

    sets: tuple[TrialTypeSet, ...]
    active: str | None
    chain_problem: str | None


# -- what is happening ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResultCount:
    """Tallies. `total` is every outcome reported; `accepted` is the ones that counted."""

    total: int
    accepted: int
    remaining: int
    frame_loss: int
    by_outcome: dict[str, int]
    hits: int
    hit_rate: float | None


@dataclass(frozen=True, slots=True)
class CounterRow:
    """One trial type of the active set, with its definition joined onto its tallies.

    The columns VStim's Trial Type Manager showed, already matched up, so a
    client does not have to do the join itself.

    `p_next` is advisory: it describes the declarative ordering, and a policy
    whose `select_trial` returns a type decides for itself.
    """

    index: int
    trial_type_number: int
    name: str
    trials_per_round: int
    statemachine_graph: str
    reward_ms: int
    p_next: float
    total: int
    accepted: int
    remaining: int
    frame_loss: int
    by_outcome: dict[str, int]
    hits: int
    hit_rate: float | None


@dataclass(frozen=True, slots=True)
class SetProgress:
    """How far the loaded set has got towards its switch rule, since it was loaded."""

    set_name: str
    accepted_trials: int
    hits: int
    all_trials: int
    criterion: TrialCountCriterion | None
    target: int | None
    switch_to: str | None
    reached: int
    fraction: float | None


@dataclass(frozen=True, slots=True)
class PolicyError:
    """A policy hook that raised. Recorded against the trial, never fatal.

    A policy exception does not end a session: every hook is wrapped, the
    traceback is kept, and the declarative behaviour stands.
    """

    hook: str
    trial_number: int
    error: str
    traceback: str
    at: dt.datetime | None


@dataclass(frozen=True, slots=True)
class PolicyInfo:
    """The loaded policy, and what it last said about itself.

    `sha256` is what the session record carries, so "which version of the
    staircase ran on Tuesday" is answerable from the session directory alone.
    `source` is present only when it was asked for.
    """

    name: str
    class_name: str
    sha256: str | None
    origin: PolicyOrigin
    source: str | None
    state: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class SessionState:
    """Everything true right now, in one object.

    The answer to `read_state`, the payload of every `watch_state` frame, and
    what every mutating call gives back — so there is one description of what
    is happening rather than several that drift.
    """

    running: bool
    armed: bool
    recording: bool
    paused: bool
    stop_reason: str | None
    current: TrialSpec | None
    last: TrialRecord | None
    set_name: str
    set_progress: SetProgress | None
    rounds_completed: int
    rounds_configured: int
    trials_per_round: int
    trials_remaining: int
    totals: ResultCount | None
    counters: tuple[CounterRow, ...]
    trials_started: int
    seed: int
    config: SessionConfig | None
    policy: PolicyInfo | None
    policy_errors: tuple[PolicyError, ...]
    recent: tuple[TrialRecord, ...]


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """One frame of `watch_state`.

    `sequence` is monotonic and **a gap is not loss**: frames are coalesced
    under load, and each one is a whole state, so the newest is always the
    truth. A client that missed three has missed nothing it could have used.
    """

    sequence: int
    at: dt.datetime | None
    state: SessionState | None


# -- policies, and the simulated subject ----------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyDiagnostic:
    """One problem found in a policy, with a line number an editor can mark."""

    line: int | None
    column: int | None
    message: str


@dataclass(frozen=True, slots=True)
class PolicyCheckResult:
    """What checking a policy found.

    The check imports it and smoke-runs it over a throwaway copy of the
    experiment, so it never touches counters somebody is watching.
    """

    ok: bool
    class_name: str | None
    sha256: str
    diagnostics: tuple[PolicyDiagnostic, ...]
    trials_run: int


@dataclass(frozen=True, slots=True)
class SimSettings:
    """The synthetic subject's dials, for driving the real loop with no rig attached."""

    hit_rate: float = 0.75
    not_started_rate: float = 0.05
    eye_error_rate: float = 0.08
    early_rate: float = 0.05
    frame_loss_rate: float = 0.0
    imprecise_fixation_rate: float = 0.0
    hit_rate_by_type: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepResult:
    """What a debug step produced: how many trials ran, and whether the session ended."""

    trials: int
    stopped: bool
    stop_reason: str | None
    state: SessionState | None


@dataclass(frozen=True, slots=True)
class FreeRunStatus:
    """Whether the simulated subject is free-running, and how fast."""

    running: bool
    interval_ms: int
