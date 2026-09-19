from google.protobuf import struct_pb2 as _struct_pb2
from triald._proto.triald.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SwitchRule(_message.Message):
    __slots__ = ("enabled", "criterion", "count", "target")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    CRITERION_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    criterion: _common_pb2.TrialCountCriterion
    count: int
    target: str
    def __init__(self, enabled: _Optional[bool] = ..., criterion: _Optional[_Union[_common_pb2.TrialCountCriterion, str]] = ..., count: _Optional[int] = ..., target: _Optional[str] = ...) -> None: ...

class TrialType(_message.Message):
    __slots__ = ("name", "trials_per_round", "statemachine_graph", "reward_ms", "params")
    NAME_FIELD_NUMBER: _ClassVar[int]
    TRIALS_PER_ROUND_FIELD_NUMBER: _ClassVar[int]
    STATEMACHINE_GRAPH_FIELD_NUMBER: _ClassVar[int]
    REWARD_MS_FIELD_NUMBER: _ClassVar[int]
    PARAMS_FIELD_NUMBER: _ClassVar[int]
    name: str
    trials_per_round: int
    statemachine_graph: str
    reward_ms: int
    params: _struct_pb2.Struct
    def __init__(self, name: _Optional[str] = ..., trials_per_round: _Optional[int] = ..., statemachine_graph: _Optional[str] = ..., reward_ms: _Optional[int] = ..., params: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class TrialTypeSet(_message.Message):
    __slots__ = ("name", "trial_types", "switch_rule", "trials_per_round", "runnable", "set_number", "active")
    NAME_FIELD_NUMBER: _ClassVar[int]
    TRIAL_TYPES_FIELD_NUMBER: _ClassVar[int]
    SWITCH_RULE_FIELD_NUMBER: _ClassVar[int]
    TRIALS_PER_ROUND_FIELD_NUMBER: _ClassVar[int]
    RUNNABLE_FIELD_NUMBER: _ClassVar[int]
    SET_NUMBER_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    name: str
    trial_types: _containers.RepeatedCompositeFieldContainer[TrialType]
    switch_rule: SwitchRule
    trials_per_round: int
    runnable: bool
    set_number: int
    active: bool
    def __init__(self, name: _Optional[str] = ..., trial_types: _Optional[_Iterable[_Union[TrialType, _Mapping]]] = ..., switch_rule: _Optional[_Union[SwitchRule, _Mapping]] = ..., trials_per_round: _Optional[int] = ..., runnable: _Optional[bool] = ..., set_number: _Optional[int] = ..., active: _Optional[bool] = ...) -> None: ...

class Sets(_message.Message):
    __slots__ = ("sets", "active", "chain_problem")
    SETS_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    CHAIN_PROBLEM_FIELD_NUMBER: _ClassVar[int]
    sets: _containers.RepeatedCompositeFieldContainer[TrialTypeSet]
    active: str
    chain_problem: str
    def __init__(self, sets: _Optional[_Iterable[_Union[TrialTypeSet, _Mapping]]] = ..., active: _Optional[str] = ..., chain_problem: _Optional[str] = ...) -> None: ...

class SetName(_message.Message):
    __slots__ = ("name",)
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class WriteSetRequest(_message.Message):
    __slots__ = ("name", "set")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SET_FIELD_NUMBER: _ClassVar[int]
    name: str
    set: TrialTypeSet
    def __init__(self, name: _Optional[str] = ..., set: _Optional[_Union[TrialTypeSet, _Mapping]] = ...) -> None: ...
