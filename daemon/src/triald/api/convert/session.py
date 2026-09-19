# SPDX-License-Identifier: AGPL-3.0-or-later
"""Everything the UI, a client or a policy can see, in one message."""

from __future__ import annotations

from typing import Any

from triald._proto.triald.v1 import (
    session_pb2,
)
from triald.counters import ResultCount
from triald.state import SessionState, SetProgress
from triald.trialtypes import TrialTypeSet

from .config import _CRITERIA_TO_WIRE, session_config_to_wire
from .policy import policy_error_to_wire, policy_info_to_wire
from .trial import trial_record_to_wire, trial_spec_to_wire

#: The tallies a counters row repeats. `CounterRow` is flat rather than nesting
#: a `ResultCount` because a table row is what it is; this is the one list that
#: keeps the two from drifting.
TALLIES = ("total", "accepted", "remaining", "frame_loss", "hits")


def set_progress_to_wire(progress: SetProgress) -> session_pb2.SetProgress:
    message = session_pb2.SetProgress(
        set_name=progress.set_name,
        accepted_trials=progress.accepted_trials,
        hits=progress.hits,
        all_trials=progress.all_trials,
        # Properties, not fields: computed from the criterion, and sent so a UI
        # does not have to know which of the three counts the rule is watching.
        reached=progress.reached,
    )
    if progress.criterion is not None:
        message.criterion = _CRITERIA_TO_WIRE[progress.criterion]
    if progress.target is not None:
        message.target = progress.target
    if progress.switch_to is not None:
        message.switch_to = progress.switch_to
    if progress.fraction is not None:
        message.fraction = progress.fraction
    return message


def result_count_to_wire(count: ResultCount) -> session_pb2.ResultCount:
    message = session_pb2.ResultCount(
        **{name: getattr(count, name) for name in TALLIES},
        # Keyed by outcome name, which is the same spelling the enum puts on
        # the wire. Sorted so two answers to the same question are byte-equal.
        by_outcome={outcome.name: n for outcome, n in sorted(count.by_outcome.items())},
    )
    if count.hit_rate is not None:
        message.hit_rate = count.hit_rate
    return message


def counter_rows_to_wire(
    state: SessionState, trial_type_set: TrialTypeSet, number_offset: int
) -> list[session_pb2.CounterRow]:
    """Join the active set's definitions onto its counters, row by row.

    The two are parallel by construction — the counter bank grows to the length
    of the set as it is loaded — but only in one direction: a set that has just
    been shortened has counter rows the definitions no longer reach, and those
    are dropped rather than shown against a name that is gone.
    """
    rows: list[session_pb2.CounterRow] = []
    for index, count in enumerate(state.per_trial_type):
        if index >= len(trial_type_set):
            break
        trial_type = trial_type_set[index]
        row = session_pb2.CounterRow(
            **{name: getattr(count, name) for name in TALLIES},
            by_outcome={outcome.name: n for outcome, n in sorted(count.by_outcome.items())},
            index=index,
            # The number the *record* will carry, or the column is no use for
            # looking a trial up afterwards.
            trial_type_number=number_offset + index,
            name=trial_type.name,
            trials_per_round=trial_type.trials_per_round,
            statemachine_graph=trial_type.statemachine_graph,
            reward_ms=trial_type.reward_ms,
            p_next=state.p_next[index] if index < len(state.p_next) else 0.0,
        )
        if count.hit_rate is not None:
            row.hit_rate = count.hit_rate
        rows.append(row)
    return rows


def session_state_to_wire(
    state: SessionState,
    *,
    armed: bool,
    trial_type_set: TrialTypeSet,
    config: Any,
    policy: dict[str, Any],
    policy_errors: list[dict[str, Any]],
    number_offset: int = 0,
    recent: int = 25,
) -> session_pb2.SessionState:
    message = session_pb2.SessionState(
        running=state.running,
        armed=armed,
        recording=state.recording,
        paused=state.paused,
        set_name=state.set_name,
        set_progress=set_progress_to_wire(state.set_progress),
        rounds_completed=state.rounds_completed,
        rounds_configured=state.rounds_configured,
        trials_per_round=state.trials_per_round,
        trials_remaining=state.trials_remaining,
        totals=result_count_to_wire(state.totals),
        counters=counter_rows_to_wire(state, trial_type_set, number_offset),
        trials_started=len(state.history),
        seed=state.seed,
        config=session_config_to_wire(config),
        policy=policy_info_to_wire(policy),
        # Bounded: a session that has been failing a hook every trial should
        # not answer with a megabyte of tracebacks.
        policy_errors=[policy_error_to_wire(e) for e in policy_errors[-20:]],
        recent=[trial_record_to_wire(r) for r in state.recent(recent)],
    )
    if state.stop_reason is not None:
        message.stop_reason = state.stop_reason
    if state.current is not None:
        message.current.CopyFrom(trial_spec_to_wire(state.current))
    if state.last is not None:
        message.last.CopyFrom(trial_record_to_wire(state.last))
    return message


def stream_frame_to_wire(frame) -> session_pb2.StreamFrame:
    """One frame of the state stream.

    Every frame is a whole state, which is why a gap in `sequence` is not loss:
    frames are coalesced under load and the newest is always the truth.
    """
    message = session_pb2.StreamFrame(sequence=frame.sequence)
    message.at.FromDatetime(frame.at)
    message.state.CopyFrom(session_state_to_wire_from_snapshot(frame.snapshot))
    return message


def session_state_to_wire_from_snapshot(snapshot) -> session_pb2.SessionState:
    """The snapshot the service assembles, as one message."""
    return session_state_to_wire(
        snapshot.state,
        armed=snapshot.armed,
        trial_type_set=snapshot.trial_type_set,
        config=snapshot.config,
        policy=snapshot.policy,
        policy_errors=snapshot.policy_errors,
        number_offset=snapshot.number_offset,
    )
