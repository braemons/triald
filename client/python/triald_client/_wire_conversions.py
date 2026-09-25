# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seam: generated types on one side, `api_types` on the other.

The only module in this package that imports the generated code, which is what
makes "no protobuf type crosses the edge" a fact about the imports rather than
a promise in a docstring.

Named `X_from_wire` and `X_to_wire`, in that direction and nothing else, so the
direction of a call is readable rather than looked up — the same rule the
daemon's own `api/convert/` keeps.

**The enum tables are exhaustive and are written out.** Deriving them by
stripping a prefix would be shorter and would silently mis-translate the first
value that does not follow the pattern; a table refuses a value it does not
know, loudly, at the seam, which is where a mistranslation is still cheap.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

# protobuf ships no stubs for its own well-known types that a checker can
# follow, so `Struct` and `Timestamp` come back as unknown. They are exercised
# by the seam tests, which is the check that runs the code.
from google.protobuf import json_format, struct_pb2
from google.protobuf.timestamp_pb2 import Timestamp  # ty: ignore[unresolved-import]

from ._proto.triald.v1 import (
    common_pb2,
    config_pb2,
    debug_pb2,
    policy_pb2,
    session_pb2,
    sets_pb2,
    trial_pb2,
)
from .api_types import (
    Acceptance,
    ConfigPatch,
    ConfigUpdateResult,
    CounterRow,
    FrameLoss,
    FreeRunStatus,
    Ordering,
    Outcome,
    OutcomeReport,
    PolicyCheckResult,
    PolicyDiagnostic,
    PolicyError,
    PolicyInfo,
    PolicyOrigin,
    ResultCount,
    SessionConfig,
    SessionState,
    SetProgress,
    Sets,
    SimSettings,
    StepResult,
    StreamFrame,
    SwitchRule,
    TrialCountCriterion,
    TrialOutcome,
    TrialRecord,
    TrialSpec,
    TrialType,
    TrialTypeSet,
)

# -- enums ----------------------------------------------------------------------
#
# The wire spells a value `ORDERING_RANDOM_IN_ROUND`, because protobuf requires
# value names to be unique across a package's enums. Nobody writing Python
# should have to say that, so the prefix lives here and nowhere else.

_ORDERING_TO_WIRE = {
    Ordering.RANDOM_IN_ROUND: common_pb2.ORDERING_RANDOM_IN_ROUND,
    Ordering.RANDOM_IN_EXPERIMENT: common_pb2.ORDERING_RANDOM_IN_EXPERIMENT,
    Ordering.ASCENDING: common_pb2.ORDERING_ASCENDING,
    Ordering.DESCENDING: common_pb2.ORDERING_DESCENDING,
    Ordering.RANDOM_WITH_REPLACEMENT: common_pb2.ORDERING_RANDOM_WITH_REPLACEMENT,
}
_ORDERING_FROM_WIRE = {value: key for key, value in _ORDERING_TO_WIRE.items()}

_CRITERION_TO_WIRE = {
    TrialCountCriterion.ACCEPTED_TRIALS: common_pb2.TRIAL_COUNT_CRITERION_ACCEPTED_TRIALS,
    TrialCountCriterion.HITS: common_pb2.TRIAL_COUNT_CRITERION_HITS,
    TrialCountCriterion.ALL_TRIALS: common_pb2.TRIAL_COUNT_CRITERION_ALL_TRIALS,
}
_CRITERION_FROM_WIRE = {value: key for key, value in _CRITERION_TO_WIRE.items()}

_ORIGIN_FROM_WIRE = {
    policy_pb2.POLICY_ORIGIN_DEFAULT: PolicyOrigin.DEFAULT,
    policy_pb2.POLICY_ORIGIN_FILE: PolicyOrigin.FILE,
    policy_pb2.POLICY_ORIGIN_UPLOADED: PolicyOrigin.UPLOADED,
}


def ordering_from_wire(value: int) -> Ordering:
    """An `Ordering`. Unspecified means the default, which is random in round."""
    return _ORDERING_FROM_WIRE.get(value, Ordering.RANDOM_IN_ROUND)


def ordering_to_wire(value: Ordering) -> int:
    return _ORDERING_TO_WIRE[Ordering(value)]


def criterion_from_wire(value: int) -> TrialCountCriterion | None:
    """A criterion, or `None` where the daemon said nothing.

    Unspecified is genuinely absent rather than a default: a set with no switch
    rule has no criterion, and answering `ACCEPTED_TRIALS` would invent one.
    """
    return _CRITERION_FROM_WIRE.get(value)


def criterion_to_wire(value: TrialCountCriterion | None) -> int:
    if value is None:
        return common_pb2.TRIAL_COUNT_CRITERION_UNSPECIFIED
    return _CRITERION_TO_WIRE[TrialCountCriterion(value)]


def policy_origin_from_wire(value: int) -> PolicyOrigin:
    return _ORIGIN_FROM_WIRE.get(value, PolicyOrigin.DEFAULT)


def outcome_code_from_wire(value: int) -> TrialOutcome:
    """The `.tdr` code, as itself.

    A code this client has never seen is a *newer daemon*, not a broken one —
    the taxonomy grows by addition — so it is kept as the integer it is rather
    than refused. `TrialOutcome` is an `IntEnum`, so the comparison a caller
    writes still works either way.
    """
    try:
        return TrialOutcome(value)
    except ValueError:
        return value  # ty: ignore[invalid-return-type]  (an unknown code stays a code)


# -- the small pieces -----------------------------------------------------------


def _time_from_wire(stamp: Timestamp | None, present: bool) -> dt.datetime | None:
    """A timestamp, as an aware UTC datetime, or `None`.

    `present` rather than a truthiness test on the message: protobuf's zero
    timestamp is 1970-01-01, which is a real moment and not the same as "the
    daemon did not say".
    """
    if not present or stamp is None:
        return None
    return stamp.ToDatetime(tzinfo=dt.UTC)


def _struct_from_wire(
    value: struct_pb2.Struct | None,  # ty: ignore[unresolved-attribute]
    present: bool,
) -> dict[str, Any] | None:
    """A `google.protobuf.Struct` as plain Python.

    `MessageToDict` rather than `dict(value)`: the latter leaves a nested list
    as a `ListValue`, which is a protobuf type escaping through the seam this
    module exists to close.

    **A `Struct` holds every number as a double**, so an integer put into
    `params` comes back as a float. That is protobuf's `Struct`, not a choice
    made here, and it is why triald never interprets `params` — it carries it.
    """
    if not present or value is None:
        return None
    return json_format.MessageToDict(value)


def _struct_to_wire(value: dict[str, Any]):  # -> struct_pb2.Struct
    struct = struct_pb2.Struct()  # ty: ignore[unresolved-attribute]
    struct.update(value)
    return struct


def frame_loss_from_wire(message: trial_pb2.FrameLoss) -> FrameLoss:
    return FrameLoss(interval=message.interval, frame=message.frame)


# -- a trial --------------------------------------------------------------------


def outcome_report_to_wire(report: OutcomeReport, *, trial_id: int) -> trial_pb2.OutcomeReport:
    """The one message this client sends that carries a decision.

    `trial_id` is passed separately because it addresses the message rather
    than describing the outcome — see `OutcomeReport`'s own docstring.
    """
    message = trial_pb2.OutcomeReport(
        trial_id=trial_id,
        outcome=int(report.outcome),  # ty: ignore[invalid-argument-type]
        manipulandum=int(report.manipulandum),  # ty: ignore[invalid-argument-type]
        precise_fixation=report.precise_fixation,
        reward_ms=report.reward_ms,
        hit_condition=report.hit_condition,
        simulated=report.simulated,
    )
    if report.reaction_time_ms is not None:
        message.reaction_time_ms = report.reaction_time_ms
    if report.terminating_interval is not None:
        message.terminating_interval = report.terminating_interval
    if report.note is not None:
        message.note = report.note
    if report.frame_loss is not None:
        message.frame_loss.interval = report.frame_loss.interval
        message.frame_loss.frame = report.frame_loss.frame
    return message


def outcome_from_wire(message: trial_pb2.Outcome) -> Outcome:
    return Outcome(
        code=outcome_code_from_wire(message.code),
        name=message.name,
        manipulandum=message.manipulandum,
        reaction_time_ms=(
            message.reaction_time_ms if message.HasField("reaction_time_ms") else None
        ),
        terminating_interval=(
            message.terminating_interval if message.HasField("terminating_interval") else None
        ),
        precise_fixation=message.precise_fixation,
        frame_loss=(
            frame_loss_from_wire(message.frame_loss) if message.HasField("frame_loss") else None
        ),
        reward_ms=message.reward_ms,
        hit_condition=message.hit_condition,
        simulated=message.simulated,
        note=message.note if message.HasField("note") else None,
    )


def trial_spec_from_wire(message: trial_pb2.TrialSpec) -> TrialSpec:
    return TrialSpec(
        trial_number=message.trial_number,
        trial_type_index=message.trial_type_index,
        trial_type_number=message.trial_type_number,
        trial_type_name=message.trial_type_name,
        set_name=message.set_name,
        statemachine_graph=message.statemachine_graph,
        mousewheel_zone_set=message.mousewheel_zone_set,
        reward_ms=message.reward_ms,
        recording=message.recording,
        paused=message.paused,
        started_at=_time_from_wire(message.started_at, message.HasField("started_at")),
        deadline=_time_from_wire(message.deadline, message.HasField("deadline")),
    )


def trial_record_from_wire(message: trial_pb2.TrialRecord) -> TrialRecord:
    return TrialRecord(
        trial=trial_spec_from_wire(message.trial) if message.HasField("trial") else None,
        outcome=outcome_from_wire(message.outcome) if message.HasField("outcome") else None,
        accepted=message.accepted,
        refusal_reason=message.refusal_reason if message.HasField("refusal_reason") else None,
        ended_at=_time_from_wire(message.ended_at, message.HasField("ended_at")),
        policy_state=_struct_from_wire(message.policy_state, message.HasField("policy_state")),
    )


# -- the settings ---------------------------------------------------------------

#: Every field of `Acceptance`, in the proto's order. Written once and used by
#: both directions, because a flag added to one and not the other is a flag
#: that silently stops travelling.
_ACCEPTANCE_FIELDS = (
    "not_started",
    "hit",
    "wrong_response",
    "early_hit",
    "early_wrong_response",
    "early",
    "late",
    "eye_error",
    "unexpected_start_signal",
    "wrong_start_signal",
    "cancelled",
    "never_finished",
    "frame_loss",
    "imprecise_fixation",
)


def acceptance_from_wire(message: config_pb2.Acceptance) -> Acceptance:
    """The accept flags.

    Every field is `optional` on the wire, and an absent one means the daemon's
    default rather than `False` — so the dataclass's own defaults stand in.
    """
    present = {
        name: getattr(message, name) for name in _ACCEPTANCE_FIELDS if message.HasField(name)
    }
    return Acceptance(**present)


def acceptance_to_wire(value: Acceptance) -> config_pb2.Acceptance:
    return config_pb2.Acceptance(**{name: getattr(value, name) for name in _ACCEPTANCE_FIELDS})


def session_config_from_wire(message: config_pb2.SessionConfig) -> SessionConfig:
    return SessionConfig(
        initial_set=message.initial_set,
        ordering=ordering_from_wire(message.ordering),
        rounds=message.rounds,
        avoid_repeat=message.avoid_repeat,
        acceptance=(
            acceptance_from_wire(message.acceptance)
            if message.HasField("acceptance")
            else Acceptance()
        ),
        trial_cap_ms=message.trial_cap_ms,
        stop_when_rounds_done=message.stop_when_rounds_done,
        stop_after_trials=(
            message.stop_after_trials if message.HasField("stop_after_trials") else None
        ),
        stop_criterion=(
            criterion_from_wire(message.stop_criterion) or TrialCountCriterion.ACCEPTED_TRIALS
        ),
        extend_trial_type_number=message.extend_trial_type_number,
        seed=message.seed if message.HasField("seed") else None,
    )


def config_patch_to_wire(patch: ConfigPatch) -> config_pb2.ConfigPatch:
    """Only the fields that were set.

    Absent means "leave it alone", which is a question protobuf can only answer
    for a field that tracks presence — which is why every field of
    `ConfigPatch` is `optional` in the proto.
    """
    message = config_pb2.ConfigPatch()
    if patch.ordering is not None:
        message.ordering = ordering_to_wire(patch.ordering)  # ty: ignore[invalid-assignment]
    if patch.rounds is not None:
        message.rounds = patch.rounds
    if patch.avoid_repeat is not None:
        message.avoid_repeat = patch.avoid_repeat
    if patch.acceptance is not None:
        message.acceptance.CopyFrom(acceptance_to_wire(patch.acceptance))
    if patch.trial_cap_ms is not None:
        message.trial_cap_ms = patch.trial_cap_ms
    if patch.stop_when_rounds_done is not None:
        message.stop_when_rounds_done = patch.stop_when_rounds_done
    if patch.stop_after_trials is not None:
        message.stop_after_trials = patch.stop_after_trials
    if patch.stop_criterion is not None:
        message.stop_criterion = criterion_to_wire(patch.stop_criterion)  # ty: ignore[invalid-assignment]
    if patch.initial_set is not None:
        message.initial_set = patch.initial_set
    if patch.extend_trial_type_number is not None:
        message.extend_trial_type_number = patch.extend_trial_type_number
    if patch.seed is not None:
        message.seed = patch.seed
    return message


def config_update_from_wire(message: config_pb2.ConfigUpdateResult) -> ConfigUpdateResult:
    return ConfigUpdateResult(
        changed=tuple(message.changed),
        bag_rebuilt=message.bag_rebuilt,
        config=(
            session_config_from_wire(message.config) if message.HasField("config") else None
        ),
    )


# -- sets -----------------------------------------------------------------------


def switch_rule_from_wire(message: sets_pb2.SwitchRule) -> SwitchRule:
    return SwitchRule(
        enabled=message.enabled,
        criterion=(
            criterion_from_wire(message.criterion) or TrialCountCriterion.ACCEPTED_TRIALS
        ),
        count=message.count,
        target=message.target if message.HasField("target") else None,
    )


def switch_rule_to_wire(rule: SwitchRule) -> sets_pb2.SwitchRule:
    message = sets_pb2.SwitchRule(
        enabled=rule.enabled,
        criterion=criterion_to_wire(rule.criterion),  # ty: ignore[invalid-argument-type]
        count=rule.count,
    )
    if rule.target is not None:
        message.target = rule.target
    return message


def trial_type_from_wire(message: sets_pb2.TrialType) -> TrialType:
    return TrialType(
        name=message.name,
        trials_per_round=message.trials_per_round,
        statemachine_graph=message.statemachine_graph,
        mousewheel_zone_set=message.mousewheel_zone_set,
        reward_ms=message.reward_ms,
        params=_struct_from_wire(message.params, message.HasField("params")) or {},
    )


def trial_type_to_wire(trial_type: TrialType) -> sets_pb2.TrialType:
    message = sets_pb2.TrialType(
        name=trial_type.name,
        trials_per_round=trial_type.trials_per_round,
        statemachine_graph=trial_type.statemachine_graph,
        mousewheel_zone_set=trial_type.mousewheel_zone_set,
        reward_ms=trial_type.reward_ms,
    )
    if trial_type.params:
        message.params.CopyFrom(_struct_to_wire(trial_type.params))
    return message


def trial_type_set_from_wire(message: sets_pb2.TrialTypeSet) -> TrialTypeSet:
    return TrialTypeSet(
        name=message.name,
        trial_types=tuple(trial_type_from_wire(each) for each in message.trial_types),
        switch_rule=(
            switch_rule_from_wire(message.switch_rule)
            if message.HasField("switch_rule")
            else None
        ),
        trials_per_round=message.trials_per_round,
        runnable=message.runnable,
        set_number=message.set_number,
        active=message.active,
    )


def trial_type_set_to_wire(value: TrialTypeSet) -> sets_pb2.TrialTypeSet:
    """A set, on its way in.

    The daemon's own view of it — `trials_per_round`, `runnable`, `set_number`,
    `active` — is not sent: those are answers, and a client that tried to set
    them would be telling the daemon what it already knows better.
    """
    message = sets_pb2.TrialTypeSet(
        name=value.name,
        trial_types=[trial_type_to_wire(each) for each in value.trial_types],
    )
    if value.switch_rule is not None:
        message.switch_rule.CopyFrom(switch_rule_to_wire(value.switch_rule))
    return message


def sets_from_wire(message: sets_pb2.Sets) -> Sets:
    return Sets(
        sets=tuple(trial_type_set_from_wire(each) for each in message.sets),
        active=message.active if message.HasField("active") else None,
        chain_problem=message.chain_problem if message.HasField("chain_problem") else None,
    )


# -- what is happening ----------------------------------------------------------


def result_count_from_wire(message: session_pb2.ResultCount) -> ResultCount:
    return ResultCount(
        total=message.total,
        accepted=message.accepted,
        remaining=message.remaining,
        frame_loss=message.frame_loss,
        by_outcome=dict(message.by_outcome),
        hits=message.hits,
        hit_rate=message.hit_rate if message.HasField("hit_rate") else None,
    )


def counter_row_from_wire(message: session_pb2.CounterRow) -> CounterRow:
    return CounterRow(
        index=message.index,
        trial_type_number=message.trial_type_number,
        name=message.name,
        trials_per_round=message.trials_per_round,
        statemachine_graph=message.statemachine_graph,
        mousewheel_zone_set=message.mousewheel_zone_set,
        reward_ms=message.reward_ms,
        p_next=message.p_next,
        total=message.total,
        accepted=message.accepted,
        remaining=message.remaining,
        frame_loss=message.frame_loss,
        by_outcome=dict(message.by_outcome),
        hits=message.hits,
        hit_rate=message.hit_rate if message.HasField("hit_rate") else None,
    )


def set_progress_from_wire(message: session_pb2.SetProgress) -> SetProgress:
    return SetProgress(
        set_name=message.set_name,
        accepted_trials=message.accepted_trials,
        hits=message.hits,
        all_trials=message.all_trials,
        criterion=(
            criterion_from_wire(message.criterion) if message.HasField("criterion") else None
        ),
        target=message.target if message.HasField("target") else None,
        switch_to=message.switch_to if message.HasField("switch_to") else None,
        reached=message.reached,
        fraction=message.fraction if message.HasField("fraction") else None,
    )


def policy_error_from_wire(message: policy_pb2.PolicyError) -> PolicyError:
    return PolicyError(
        hook=message.hook,
        trial_number=message.trial_number,
        error=message.error,
        traceback=message.traceback,
        at=_time_from_wire(message.at, message.HasField("at")),
    )


def policy_info_from_wire(message: policy_pb2.PolicyInfo) -> PolicyInfo:
    return PolicyInfo(
        name=message.name,
        class_name=message.class_name,
        sha256=message.sha256 if message.HasField("sha256") else None,
        origin=policy_origin_from_wire(message.origin),
        source=message.source if message.HasField("source") else None,
        state=_struct_from_wire(message.state, message.HasField("state")),
    )


def session_state_from_wire(message: session_pb2.SessionState) -> SessionState:
    return SessionState(
        running=message.running,
        armed=message.armed,
        recording=message.recording,
        paused=message.paused,
        stop_reason=message.stop_reason if message.HasField("stop_reason") else None,
        current=trial_spec_from_wire(message.current) if message.HasField("current") else None,
        last=trial_record_from_wire(message.last) if message.HasField("last") else None,
        set_name=message.set_name,
        set_progress=(
            set_progress_from_wire(message.set_progress)
            if message.HasField("set_progress")
            else None
        ),
        rounds_completed=message.rounds_completed,
        rounds_configured=message.rounds_configured,
        trials_per_round=message.trials_per_round,
        trials_remaining=message.trials_remaining,
        totals=result_count_from_wire(message.totals) if message.HasField("totals") else None,
        counters=tuple(counter_row_from_wire(each) for each in message.counters),
        trials_started=message.trials_started,
        seed=message.seed,
        config=session_config_from_wire(message.config) if message.HasField("config") else None,
        policy=policy_info_from_wire(message.policy) if message.HasField("policy") else None,
        policy_errors=tuple(policy_error_from_wire(each) for each in message.policy_errors),
        recent=tuple(trial_record_from_wire(each) for each in message.recent),
    )


def stream_frame_from_wire(message: session_pb2.StreamFrame) -> StreamFrame:
    return StreamFrame(
        sequence=message.sequence,
        at=_time_from_wire(message.at, message.HasField("at")),
        state=session_state_from_wire(message.state) if message.HasField("state") else None,
    )


# -- policies, and the simulated subject ----------------------------------------


def policy_diagnostic_from_wire(message: policy_pb2.PolicyDiagnostic) -> PolicyDiagnostic:
    return PolicyDiagnostic(
        line=message.line if message.HasField("line") else None,
        column=message.column if message.HasField("column") else None,
        message=message.message,
    )


def policy_check_from_wire(message: policy_pb2.PolicyCheckResult) -> PolicyCheckResult:
    return PolicyCheckResult(
        ok=message.ok,
        class_name=message.class_name if message.HasField("class_name") else None,
        sha256=message.sha256,
        diagnostics=tuple(policy_diagnostic_from_wire(each) for each in message.diagnostics),
        trials_run=message.trials_run,
    )


def sim_settings_from_wire(message: debug_pb2.SimSettings) -> SimSettings:
    return SimSettings(
        hit_rate=message.hit_rate,
        not_started_rate=message.not_started_rate,
        eye_error_rate=message.eye_error_rate,
        early_rate=message.early_rate,
        frame_loss_rate=message.frame_loss_rate,
        imprecise_fixation_rate=message.imprecise_fixation_rate,
        hit_rate_by_type=dict(message.hit_rate_by_type),
    )


def sim_settings_to_wire(value: SimSettings) -> debug_pb2.SimSettings:
    return debug_pb2.SimSettings(
        hit_rate=value.hit_rate,
        not_started_rate=value.not_started_rate,
        eye_error_rate=value.eye_error_rate,
        early_rate=value.early_rate,
        frame_loss_rate=value.frame_loss_rate,
        imprecise_fixation_rate=value.imprecise_fixation_rate,
        hit_rate_by_type=value.hit_rate_by_type,
    )


def step_result_from_wire(message: debug_pb2.StepResult) -> StepResult:
    return StepResult(
        trials=message.trials,
        stopped=message.stopped,
        stop_reason=message.stop_reason if message.HasField("stop_reason") else None,
        state=session_state_from_wire(message.state) if message.HasField("state") else None,
    )


def free_run_from_wire(message: debug_pb2.FreeRunStatus) -> FreeRunStatus:
    return FreeRunStatus(running=message.running, interval_ms=message.interval_ms)
