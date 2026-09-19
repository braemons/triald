# SPDX-License-Identifier: AGPL-3.0-or-later
"""One trial: its selection, its outcome, and the record it became."""

from __future__ import annotations

import datetime as dt

from google.protobuf.struct_pb2 import (
    Struct,  # ty: ignore[unresolved-import]  (built at runtime by protobuf's builder)
)

from triald._proto.triald.v1 import (
    trial_pb2,
)
from triald.outcomes import FrameLoss, Manipulandum, OutcomeReport, TrialOutcome
from triald.state import TrialRecord, TrialSpec


def trial_spec_to_wire(spec: TrialSpec) -> trial_pb2.TrialSpec:
    message = trial_pb2.TrialSpec(
        trial_number=spec.trial_number,
        trial_type_index=spec.trial_type_index,
        trial_type_number=spec.trial_type_number,
        trial_type_name=spec.trial_type_name,
        set_name=spec.set_name,
        statemachine_graph=spec.statemachine_graph,
        reward_ms=spec.reward_ms,
        recording=spec.recording,
        paused=spec.paused,
    )
    message.started_at.FromDatetime(spec.started_at)
    if spec.deadline is not None:
        message.deadline.FromDatetime(spec.deadline)
    return message


def outcome_to_wire(report: OutcomeReport) -> trial_pb2.Outcome:
    """The outcome block of a record — the code *and* the name.

    Both, because they answer different questions: the code is what analysis
    decodes and the name is what a person reads. They cannot disagree, since
    one is derived from the other here.
    """
    message = trial_pb2.Outcome(
        code=int(report.outcome),
        name=report.outcome.name,
        manipulandum=report.manipulandum.name,
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


def trial_record_to_wire(record: TrialRecord) -> trial_pb2.TrialRecord:
    message = trial_pb2.TrialRecord(
        trial=trial_spec_to_wire(record.spec),
        outcome=outcome_to_wire(record.report),
        accepted=record.accepted,
    )
    message.ended_at.FromDatetime(record.ended_at)
    if record.refusal_reason is not None:
        message.refusal_reason = record.refusal_reason
    if record.policy_state is not None:
        # A policy's snapshot is whatever somebody's Python returned; the daemon
        # records it and never reads inside it, which is what `Struct` says.
        state = Struct()
        state.update(record.policy_state)
        message.policy_state.CopyFrom(state)
    return message


def outcome_report_from_wire(message: trial_pb2.OutcomeReport) -> OutcomeReport:
    """The daemon's primary inbound message.

    `precise_fixation` is the one field where absent is not false: fixation held
    unless somebody says otherwise, because the eye monitor is optional and a
    rig without one must not refuse every trial.
    """
    return OutcomeReport(
        outcome=TrialOutcome(message.outcome),
        manipulandum=Manipulandum(message.manipulandum),
        reaction_time_ms=(
            message.reaction_time_ms if message.HasField("reaction_time_ms") else None
        ),
        terminating_interval=(
            message.terminating_interval if message.HasField("terminating_interval") else None
        ),
        precise_fixation=(
            message.precise_fixation if message.HasField("precise_fixation") else True
        ),
        frame_loss=(
            FrameLoss(interval=message.frame_loss.interval, frame=message.frame_loss.frame)
            if message.HasField("frame_loss")
            else None
        ),
        reward_ms=message.reward_ms,
        hit_condition=message.hit_condition,
        simulated=message.simulated,
        note=message.note if message.HasField("note") else None,
    )


def to_datetime(timestamp) -> dt.datetime:
    """A wire instant as an aware UTC datetime, which is what the daemon uses."""
    return timestamp.ToDatetime(tzinfo=dt.UTC)
