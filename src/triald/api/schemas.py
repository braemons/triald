"""The wire schema: every shape that crosses the API, in one place.

**These models are the contract.** The web UI, the Python client, the MATLAB
client and the Bonsai client are written against them and against the OpenAPI
document FastAPI generates from them - never against :class:`triald.Session`,
whose signatures are free to change.

Two rules keep them honest:

* **The record shape and the wire shape are the same shape.** A
  :class:`TrialRecordModel` serialises to exactly what
  :meth:`triald.state.TrialRecord.as_dict` writes into ``trials.jsonl``, and a
  test asserts it. Anything that reads a session directory can therefore also
  read the WebSocket stream, and a divergence is a failing test rather than a
  discovery six months later.
* **Add fields, never repurpose a name.** There are no field numbers to protect
  us here, so evolution is by convention: a client that does not know a field
  ignores it, and a name that once meant one thing never means another.

Directions are marked in each model's docstring: *in* is what a caller sends,
*out* is what the daemon returns, *both* is a round-trippable settings block.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

from triald.counters import ResultCount, TrialCountCriterion
from triald.outcomes import (
    AcceptancePolicy,
    FrameLoss,
    Manipulandum,
    OutcomeReport,
    TrialOutcome,
)
from triald.selection import Ordering
from triald.session import SessionConfig
from triald.state import SessionState, SetProgress, TrialRecord, TrialSpec
from triald.trialtypes import SwitchRule, TrialType, TrialTypeSet


def _isoformat(value: dt.datetime) -> str:
    return value.isoformat()


#: A wall-clock time, written the way the session record writes it.
#:
#: Pydantic would otherwise spell UTC as a trailing ``Z`` where
#: ``datetime.isoformat()`` spells it ``+00:00``. The same instant either way,
#: but not the same bytes - and the claim these models make is that a trial on
#: the wire and a trial in ``trials.jsonl`` are byte-for-byte the same object.
#: The record has years of files behind it, so the record wins.
Timestamp = Annotated[
    dt.datetime, PlainSerializer(_isoformat, return_type=str, when_used="json")
]


class Model(BaseModel):
    """Base for every wire model: unknown fields are refused, not ignored.

    A typo in a config a scientist edits by hand should be a message naming the
    field, not a setting that silently did nothing.
    """

    model_config = ConfigDict(extra="forbid")


# -- trial types, sets and the switch rule --------------------------------------


class SwitchRuleModel(Model):
    """When to leave a set, and for which one. *both*"""

    enabled: bool = False
    criterion: TrialCountCriterion = TrialCountCriterion.HITS
    count: int = Field(0, ge=0, description="Trials of `criterion` before leaving.")
    target: str | None = Field(None, description="Name of the set to go to.")

    @classmethod
    def of(cls, rule: SwitchRule) -> SwitchRuleModel:
        return cls(
            enabled=rule.enabled,
            criterion=rule.criterion,
            count=rule.count,
            target=rule.target,
        )

    def build(self) -> SwitchRule:
        return SwitchRule(
            enabled=self.enabled,
            criterion=self.criterion,
            count=self.count,
            target=self.target,
        )


class TrialTypeModel(Model):
    """One condition. *both*"""

    name: str = ""
    trials_per_round: int = Field(0, ge=0, description="Weight; zero means unused.")
    graph: str = Field(
        "",
        description=(
            "Name of the state graph this type runs; empty means whatever the "
            "executor already has loaded. A name, never an index."
        ),
    )
    reward_ms: int = Field(0, ge=0)
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Paradigm values, stored and returned verbatim; never interpreted.",
    )

    @classmethod
    def of(cls, trial_type: TrialType) -> TrialTypeModel:
        return cls(
            name=trial_type.name,
            trials_per_round=trial_type.trials_per_round,
            graph=trial_type.graph,
            reward_ms=trial_type.reward_ms,
            params=dict(trial_type.params),
        )

    def build(self) -> TrialType:
        return TrialType(
            name=self.name,
            trials_per_round=self.trials_per_round,
            graph=self.graph,
            reward_ms=self.reward_ms,
            params=dict(self.params),
        )


class TrialTypeSetModel(Model):
    """A named collection of trial types plus its switch rule. *both*

    ``trials_per_round``, ``runnable``, ``set_number`` and ``active`` are
    computed on the way out and ignored on the way in.
    """

    name: str = Field(min_length=1)
    trial_types: list[TrialTypeModel] = Field(default_factory=list)
    switch_rule: SwitchRuleModel = Field(default_factory=SwitchRuleModel)

    trials_per_round: int = 0
    runnable: bool = False
    set_number: int = Field(0, description="1-based position in the store; 0 if absent.")
    active: bool = False

    @classmethod
    def of(
        cls,
        trial_type_set: TrialTypeSet,
        *,
        set_number: int = 0,
        active: bool = False,
    ) -> TrialTypeSetModel:
        return cls(
            name=trial_type_set.name,
            trial_types=[TrialTypeModel.of(t) for t in trial_type_set],
            switch_rule=SwitchRuleModel.of(trial_type_set.switch_rule),
            trials_per_round=trial_type_set.trials_per_round,
            runnable=trial_type_set.is_runnable(),
            set_number=set_number,
            active=active,
        )

    def build(self) -> TrialTypeSet:
        return TrialTypeSet(
            name=self.name,
            trial_types=[t.build() for t in self.trial_types],
            switch_rule=self.switch_rule.build(),
        )


class SetsModel(Model):
    """Every set in the store, and whether the switch chain hangs together. *out*"""

    sets: list[TrialTypeSetModel]
    active: str | None
    chain_problem: str | None = Field(
        None,
        description=(
            "Why the switch rules reachable from the active set cannot be "
            "followed, or null when they can. The same check arm() refuses on, "
            "run continuously so the UI can show it before anybody starts."
        ),
    )


# -- config ---------------------------------------------------------------------


class AcceptanceModel(Model):
    """Which outcomes consume a slot in the round. *both*

    The eleven per-outcome flags plus the two that cut across every outcome. Any
    of the three checks can veto on its own - see
    :meth:`triald.outcomes.AcceptancePolicy.accepts`.
    """

    not_started: bool = False
    hit: bool = True
    wrong_response: bool = True
    early_hit: bool = True
    early_wrong_response: bool = True
    early: bool = True
    late: bool = True
    eye_error: bool = True
    inexpected_start_signal: bool = False
    wrong_start_signal: bool = False
    cancelled: bool = False

    frame_loss: bool = True
    imprecise_fixation: bool = True

    @classmethod
    def of(cls, policy: AcceptancePolicy) -> AcceptanceModel:
        return cls(**{name: getattr(policy, name) for name in cls.model_fields})

    def build(self) -> AcceptancePolicy:
        return AcceptancePolicy(**self.model_dump())


class SessionConfigModel(Model):
    """One experiment's declarative settings. *both*

    Everything the web UI can edit without anybody writing Python. Which of these
    may change while a session runs is decided by
    :meth:`triald.session.Session.reconfigure` and reported in
    :class:`ConfigUpdateResult`.
    """

    initial_set: str
    ordering: Ordering = Ordering.RANDOM_IN_ROUND
    rounds: int = Field(10, ge=1)
    avoid_repeat: bool = True
    acceptance: AcceptanceModel = Field(default_factory=AcceptanceModel)

    stop_when_rounds_done: bool = False
    stop_after_trials: int | None = Field(None, ge=0)
    stop_criterion: TrialCountCriterion = TrialCountCriterion.ACCEPTED_TRIALS

    extend_trial_type_number: bool = False
    seed: int | None = None

    @classmethod
    def of(cls, config: SessionConfig) -> SessionConfigModel:
        return cls(
            initial_set=config.initial_set,
            ordering=config.ordering,
            rounds=config.rounds,
            avoid_repeat=config.avoid_repeat,
            acceptance=AcceptanceModel.of(config.acceptance),
            stop_when_rounds_done=config.stop_when_rounds_done,
            stop_after_trials=config.stop_after_trials,
            stop_criterion=config.stop_criterion,
            extend_trial_type_number=config.extend_trial_type_number,
            seed=config.seed,
        )

    def build(self) -> SessionConfig:
        return SessionConfig(
            initial_set=self.initial_set,
            ordering=self.ordering,
            rounds=self.rounds,
            avoid_repeat=self.avoid_repeat,
            acceptance=self.acceptance.build(),
            stop_when_rounds_done=self.stop_when_rounds_done,
            stop_after_trials=self.stop_after_trials,
            stop_criterion=self.stop_criterion,
            extend_trial_type_number=self.extend_trial_type_number,
            seed=self.seed,
        )


class ConfigPatch(Model):
    """A partial config update: send only the fields you are changing. *in*

    Every field is optional and ``null`` means "leave it alone" - except
    ``stop_after_trials``, where null is itself a value meaning "no limit", so it
    is cleared by sending ``0``.
    """

    ordering: Ordering | None = None
    rounds: int | None = Field(None, ge=1)
    avoid_repeat: bool | None = None
    acceptance: AcceptanceModel | None = None
    stop_when_rounds_done: bool | None = None
    stop_after_trials: int | None = Field(None, ge=0)
    stop_criterion: TrialCountCriterion | None = None

    initial_set: str | None = None
    extend_trial_type_number: bool | None = None
    seed: int | None = None

    def changes(self) -> dict[str, Any]:
        """The fields actually present, ready for ``Session.reconfigure``."""
        given = self.model_dump(exclude_none=True)
        if "acceptance" in given:
            given["acceptance"] = AcceptancePolicy(**given["acceptance"])
        if given.get("stop_after_trials") == 0:
            given["stop_after_trials"] = None
        return given


class ConfigUpdateResult(Model):
    """What a config change actually did. *out*"""

    changed: list[str] = Field(description="Fields whose value is now different.")
    bag_rebuilt: bool = Field(
        description="Whether the round restarted because the bag had to be rebuilt."
    )
    config: SessionConfigModel


# -- outcomes -------------------------------------------------------------------


class FrameLossModel(Model):
    """Where the first lost frame of a trial was seen. *both*"""

    interval: int
    frame: int


class OutcomeReportModel(Model):
    """One trial's result. *in* - **the daemon's primary inbound message.**

    ``outcome`` accepts the numeric ``.tdr`` code or the name (``1`` or
    ``"HIT"``) and is always returned as the code. Every modifier that
    participates in the accept decision has to be here, because the daemon has no
    other way to learn it: ``frame_loss`` comes from vstimd and
    ``precise_fixation`` from the eye monitor.
    """

    outcome: TrialOutcome
    manipulandum: Manipulandum = Manipulandum.NONE
    reaction_time_ms: float | None = None
    terminating_interval: int | None = None
    precise_fixation: bool = True
    frame_loss: FrameLossModel | None = None
    reward_ms: int = Field(0, ge=0)
    hit_condition: bool = False
    simulated: bool = False
    note: str | None = None

    @field_validator("outcome", mode="before")
    @classmethod
    def _outcome_by_name_or_code(cls, value: Any) -> Any:
        return _by_name(TrialOutcome, value)

    @field_validator("manipulandum", mode="before")
    @classmethod
    def _manipulandum_by_name_or_code(cls, value: Any) -> Any:
        return _by_name(Manipulandum, value)

    def build(self) -> OutcomeReport:
        return OutcomeReport(
            outcome=self.outcome,
            manipulandum=self.manipulandum,
            reaction_time_ms=self.reaction_time_ms,
            terminating_interval=self.terminating_interval,
            precise_fixation=self.precise_fixation,
            frame_loss=(
                None
                if self.frame_loss is None
                else FrameLoss(interval=self.frame_loss.interval, frame=self.frame_loss.frame)
            ),
            reward_ms=self.reward_ms,
            hit_condition=self.hit_condition,
            simulated=self.simulated,
            note=self.note,
        )


def _by_name(enum_type: Any, value: Any) -> Any:
    """Let a caller send ``"HIT"`` where the schema says ``1``.

    The numeric codes are the ``.tdr`` contract and what analysis reads, but a
    person writing a request by hand - or a MATLAB client without an enum type -
    should not have to look one up.
    """
    if isinstance(value, str) and not value.lstrip("-").isdigit():
        try:
            return enum_type[value.upper()]
        except KeyError:
            known = ", ".join(m.name for m in enum_type)
            raise ValueError(f"{value!r} is not one of: {known}") from None
    return value


class OutcomeModel(Model):
    """The outcome block of a trial record. *out*

    Carries both ``code`` and ``name``: the code is the ``.tdr`` wire contract
    that analysis decodes, the name is what a person reads in a log.
    """

    code: int
    name: str
    manipulandum: str
    reaction_time_ms: float | None
    terminating_interval: int | None
    precise_fixation: bool
    frame_loss: FrameLossModel | None
    reward_ms: int
    hit_condition: bool
    simulated: bool
    note: str | None

    @classmethod
    def of(cls, report: OutcomeReport) -> OutcomeModel:
        return cls(
            code=int(report.outcome),
            name=report.outcome.name,
            manipulandum=report.manipulandum.name,
            reaction_time_ms=report.reaction_time_ms,
            terminating_interval=report.terminating_interval,
            precise_fixation=report.precise_fixation,
            frame_loss=(
                None
                if report.frame_loss is None
                else FrameLossModel(
                    interval=report.frame_loss.interval, frame=report.frame_loss.frame
                )
            ),
            reward_ms=report.reward_ms,
            hit_condition=report.hit_condition,
            simulated=report.simulated,
            note=report.note,
        )


# -- the trial ------------------------------------------------------------------


class TrialSpecModel(Model):
    """The selection for one trial, published the moment it is made. *out*

    Everything here is latched at selection and stable for the whole trial -
    including ``recording``, so a trial that began recording finishes recording
    even if somebody pauses in the middle of it.
    """

    trial_number: int
    trial_type_index: int
    trial_type_number: int
    trial_type_name: str
    set_name: str
    graph: str
    reward_ms: int
    recording: bool
    paused: bool
    started_at: Timestamp

    @classmethod
    def of(cls, spec: TrialSpec) -> TrialSpecModel:
        return cls.model_validate(spec.as_dict())


class TrialRecordModel(Model):
    """One finished trial. *out*

    Serialises to exactly the line ``trials.jsonl`` holds - see this module's
    docstring. ``accepted`` and ``refusal_reason`` are the two fields worth
    reading first: a counted trial is not an accepted one, and the reason says
    which of the three acceptance checks turned it away.
    """

    trial: TrialSpecModel
    outcome: OutcomeModel
    accepted: bool
    refusal_reason: str | None
    ended_at: Timestamp
    policy_state: dict[str, Any] | None = None

    @classmethod
    def of(cls, record: TrialRecord) -> TrialRecordModel:
        return cls(
            trial=TrialSpecModel.of(record.spec),
            outcome=OutcomeModel.of(record.report),
            accepted=record.accepted,
            refusal_reason=record.refusal_reason,
            ended_at=record.ended_at,
            policy_state=record.policy_state,
        )


# -- counters -------------------------------------------------------------------


class ResultCountModel(Model):
    """Tallies for one trial type, or for the whole session. *out*

    ``total`` counts every reported outcome; ``accepted`` counts the ones that
    consumed a slot in the round. The gap between the two is the number an
    experimenter watching a stalled session actually wants.
    """

    total: int
    accepted: int
    remaining: int
    frame_loss: int
    by_outcome: dict[str, int] = Field(description="Keyed by outcome name.")
    hits: int
    hit_rate: float | None

    @classmethod
    def of(cls, count: ResultCount) -> ResultCountModel:
        return cls(
            total=count.total,
            accepted=count.accepted,
            remaining=count.remaining,
            frame_loss=count.frame_loss,
            by_outcome={o.name: n for o, n in sorted(count.by_outcome.items())},
            hits=count.hits,
            hit_rate=count.hit_rate,
        )


class CounterRowModel(ResultCountModel):
    """One row of the counters table: a trial type and its tallies. *out*

    The columns VStim's Trial Type Manager shows, joined here so the UI does not
    have to match the trial type definitions against the counters itself.
    """

    index: int = Field(description="Position in the active set.")
    trial_type_number: int = Field(description="Extended by the set number when that is on.")
    name: str
    trials_per_round: int
    graph: str
    reward_ms: int
    p_next: float = Field(
        description=(
            "Chance this type is drawn next by the declarative ordering. "
            "Advisory: a policy that selects for itself is not consulted here."
        )
    )


class SetProgressModel(Model):
    """How far the active set has got towards its switch rule. *out*"""

    set_name: str
    accepted_trials: int
    hits: int
    all_trials: int
    criterion: TrialCountCriterion | None
    target: int | None
    switch_to: str | None
    reached: int
    fraction: float | None

    @classmethod
    def of(cls, progress: SetProgress) -> SetProgressModel:
        return cls.model_validate(progress.as_dict())


# -- policy ---------------------------------------------------------------------


class PolicyInfoModel(Model):
    """The policy the session is running. *out*

    ``sha256`` is taken over the source text and is what the session manifest
    records: "which version of the staircase ran on Tuesday" has to be
    answerable from the session directory alone, and a filename cannot answer it
    because the file changes.
    """

    name: str
    class_name: str
    sha256: str | None
    origin: Literal["default", "file", "uploaded"]
    source: str | None = None
    state: dict[str, Any] | None = Field(
        None, description="Whatever the policy's snapshot() last returned."
    )


class PolicySourceModel(Model):
    """Source text to check or load. *in* - never a path; see dev/PLAN.md."""

    name: str = Field("policy", min_length=1, max_length=128)
    source: str = Field(max_length=1_000_000)


class PolicyDiagnostic(Model):
    """One problem found in a policy. *out*"""

    line: int | None = None
    column: int | None = None
    message: str


class PolicyCheckResult(Model):
    """What ``CheckPolicy`` found. *out*

    Diagnostics carry line numbers so an editor can mark the offending line
    rather than printing a traceback underneath it.
    """

    ok: bool
    class_name: str | None
    sha256: str
    diagnostics: list[PolicyDiagnostic] = Field(default_factory=list)
    trials_run: int = Field(0, description="Trials of the smoke run that completed.")


class PolicyErrorModel(Model):
    """A policy hook that raised. *out*

    Recorded rather than fatal: there is an animal in the rig, and a stopped
    experiment is worse than a fallback trial.
    """

    hook: str
    trial_number: int
    error: str
    traceback: str
    at: str


# -- the session snapshot -------------------------------------------------------


class SessionStateModel(Model):
    """Everything the UI, a client or a policy can see. *out*

    The payload of ``GET /api/state`` and of every message on the WebSocket
    stream, so there is one description of what is happening rather than two that
    drift.
    """

    running: bool
    armed: bool = Field(description="A session object exists; it may since have stopped.")
    recording: bool
    paused: bool
    stop_reason: str | None

    current: TrialSpecModel | None = Field(description="The trial in flight, or null.")
    last: TrialRecordModel | None

    set_name: str
    set_progress: SetProgressModel
    rounds_completed: int
    rounds_configured: int
    trials_per_round: int
    trials_remaining: int

    totals: ResultCountModel
    counters: list[CounterRowModel]

    trials_started: int
    seed: int
    config: SessionConfigModel
    policy: PolicyInfoModel
    policy_errors: list[PolicyErrorModel] = Field(default_factory=list)
    recent: list[TrialRecordModel] = Field(
        default_factory=list, description="The last few finished trials, oldest first."
    )

    @classmethod
    def of(
        cls,
        state: SessionState,
        *,
        armed: bool,
        trial_type_set: TrialTypeSet,
        config: SessionConfigModel,
        policy: PolicyInfoModel,
        policy_errors: list[dict[str, Any]],
        number_offset: int = 0,
        recent: int = 25,
    ) -> SessionStateModel:
        return cls(
            running=state.running,
            armed=armed,
            recording=state.recording,
            paused=state.paused,
            stop_reason=state.stop_reason,
            current=None if state.current is None else TrialSpecModel.of(state.current),
            last=None if state.last is None else TrialRecordModel.of(state.last),
            set_name=state.set_name,
            set_progress=SetProgressModel.of(state.set_progress),
            rounds_completed=state.rounds_completed,
            rounds_configured=state.rounds_configured,
            trials_per_round=state.trials_per_round,
            trials_remaining=state.trials_remaining,
            totals=ResultCountModel.of(state.totals),
            counters=counter_rows(state, trial_type_set, number_offset),
            trials_started=len(state.history),
            seed=state.seed,
            config=config,
            policy=policy,
            policy_errors=[PolicyErrorModel(**e) for e in policy_errors[-20:]],
            recent=[TrialRecordModel.of(r) for r in state.recent(recent)],
        )


def counter_rows(
    state: SessionState, trial_type_set: TrialTypeSet, number_offset: int = 0
) -> list[CounterRowModel]:
    """Join the active set's definitions onto its counters, row by row.

    The two are parallel by construction - the counter bank is grown to the
    length of the set as it is loaded - but only in one direction: a set that has
    just been shortened has counter rows the definitions no longer reach, and
    those are dropped rather than shown against a name that is gone.

    Args:
        number_offset: what the set contributes to the trial type number, which
            is ``set_number * 256`` under extended numbering and zero otherwise.
            The table has to show the number the *record* will carry, or the
            column is no use for looking a trial up afterwards.
    """
    rows: list[CounterRowModel] = []
    for index, count in enumerate(state.per_trial_type):
        if index >= len(trial_type_set):
            break
        trial_type = trial_type_set[index]
        rows.append(
            CounterRowModel(
                **ResultCountModel.of(count).model_dump(),
                index=index,
                trial_type_number=number_offset + index,
                name=trial_type.name,
                trials_per_round=trial_type.trials_per_round,
                graph=trial_type.graph,
                reward_ms=trial_type.reward_ms,
                p_next=state.p_next[index] if index < len(state.p_next) else 0.0,
            )
        )
    return rows


# -- debug and simulation -------------------------------------------------------


class SimSettingsModel(Model):
    """The synthetic subject behind the debug controls. *both*

    Not a model of behaviour and not meant to be. It exists so a policy can be
    run over 500 trials in a second and its logic checked before anything is
    connected to a rig - and so this UI can be driven with no hardware at all.
    """

    hit_rate: float = Field(0.75, ge=0.0, le=1.0)
    not_started_rate: float = Field(0.05, ge=0.0, le=1.0)
    eye_error_rate: float = Field(0.08, ge=0.0, le=1.0)
    early_rate: float = Field(0.05, ge=0.0, le=1.0)
    frame_loss_rate: float = Field(0.0, ge=0.0, le=1.0)
    imprecise_fixation_rate: float = Field(0.0, ge=0.0, le=1.0)
    hit_rate_by_type: dict[str, float] = Field(default_factory=dict)


class StepRequest(Model):
    """Run whole simulated trials. *in* - **debug only.**"""

    trials: int = Field(1, ge=1, le=10_000)


class StepResult(Model):
    """What a debug step produced. *out*"""

    trials: int
    stopped: bool
    stop_reason: str | None
    state: SessionStateModel


class FreeRunModel(Model):
    """Start or stop the free-running simulator. *in* - **debug only.**"""

    running: bool
    interval_ms: int = Field(250, ge=10, le=60_000)


class FreeRunStatus(Model):
    """Whether the simulator is free-running, and how fast. *out*"""

    running: bool
    interval_ms: int


class CancelTrialModel(Model):
    """Why the trial in flight is being abandoned. *in*"""

    reason: str = Field("cancelled by the experimenter", min_length=1, max_length=1024)


class NoteModel(Model):
    """An experimenter's note, appended to the event stream. *in*"""

    text: str = Field(min_length=1, max_length=4096)


class OkModel(Model):
    """Nothing to say beyond that it worked. *out*"""

    ok: Literal[True] = True


class ErrorModel(Model):
    """Why a call was refused. *out*, with a 4xx status.

    ``detail`` is meant to be shown to a person: it says what was wrong and,
    where there is one, what to do instead.
    """

    error: str = Field(description="A short machine-readable kind, e.g. 'session'.")
    detail: str


class StreamMessage(Model):
    """One frame on the WebSocket stream. *out*

    ``kind`` is always ``"state"`` today. It exists so that a later message type
    - a log line, a chart point - can be added without every client having to
    learn a second envelope.
    """

    kind: Literal["state"] = "state"
    sequence: int = Field(description="Monotonic; a gap means frames were coalesced.")
    at: Timestamp
    state: SessionStateModel
