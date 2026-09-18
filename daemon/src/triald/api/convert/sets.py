# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trial types, in named sets, and the rule for leaving one."""

from __future__ import annotations

from google.protobuf.struct_pb2 import Struct

from triald.counters import TrialCountCriterion
from triald.trialtypes import SwitchRule, TrialType, TrialTypeSet
from triald.v1 import sets_pb2

from .config import _CRITERIA_TO_WIRE, criterion_from_wire


def switch_rule_to_wire(rule: SwitchRule) -> sets_pb2.SwitchRule:
    message = sets_pb2.SwitchRule(
        enabled=rule.enabled,
        criterion=_CRITERIA_TO_WIRE[rule.criterion],
        count=rule.count,
    )
    if rule.target is not None:
        message.target = rule.target
    return message


def switch_rule_from_wire(message: sets_pb2.SwitchRule) -> SwitchRule:
    return SwitchRule(
        enabled=message.enabled,
        # A switch rule counts hits when it does not say — which is not what a
        # stop rule does, and is why the enum cannot carry one default.
        criterion=criterion_from_wire(message.criterion, when_omitted=TrialCountCriterion.HITS),
        count=message.count,
        target=message.target if message.HasField("target") else None,
    )


def trial_type_to_wire(trial_type: TrialType) -> sets_pb2.TrialType:
    message = sets_pb2.TrialType(
        name=trial_type.name,
        trials_per_round=trial_type.trials_per_round,
        statemachine_graph=trial_type.statemachine_graph,
        reward_ms=trial_type.reward_ms,
    )
    # Paradigm values, stored and returned verbatim. `Struct` is what "this
    # daemon has no opinion about the contents" looks like in a schema.
    params = Struct()
    params.update(trial_type.params)
    message.params.CopyFrom(params)
    return message


def trial_type_from_wire(message: sets_pb2.TrialType) -> TrialType:
    return TrialType(
        name=message.name,
        trials_per_round=message.trials_per_round,
        statemachine_graph=message.statemachine_graph,
        reward_ms=message.reward_ms,
        params=dict(message.params),
    )


def trial_type_set_to_wire(
    trial_type_set: TrialTypeSet, *, set_number: int = 0, active: bool = False
) -> sets_pb2.TrialTypeSet:
    """The set, plus four facts computed on the way out.

    `trials_per_round`, `runnable`, `set_number` and `active` are the daemon's
    answers about the set rather than part of it, and are ignored on the way
    back in — see `trial_type_set_from_wire`.
    """
    return sets_pb2.TrialTypeSet(
        name=trial_type_set.name,
        trial_types=[trial_type_to_wire(t) for t in trial_type_set],
        switch_rule=switch_rule_to_wire(trial_type_set.switch_rule),
        trials_per_round=trial_type_set.trials_per_round,
        runnable=trial_type_set.is_runnable(),
        set_number=set_number,
        active=active,
    )


def trial_type_set_from_wire(message: sets_pb2.TrialTypeSet) -> TrialTypeSet:
    return TrialTypeSet(
        name=message.name,
        trial_types=[trial_type_from_wire(t) for t in message.trial_types],
        switch_rule=switch_rule_from_wire(message.switch_rule),
    )


def sets_to_wire(
    sets: list[TrialTypeSet], *, active: str | None, chain_problem: str | None
) -> sets_pb2.Sets:
    message = sets_pb2.Sets(
        sets=[
            trial_type_set_to_wire(one, set_number=number, active=one.name == active)
            for number, one in enumerate(sets, start=1)
        ]
    )
    if active is not None:
        message.active = active
    if chain_problem is not None:
        message.chain_problem = chain_problem
    return message
