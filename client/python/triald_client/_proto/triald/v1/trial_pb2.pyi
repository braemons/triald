import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from triald_client._proto.triald.v1 import common_pb2 as _common_pb2
from triald_client._proto.braemons.v1 import trial_outcome_pb2 as _trial_outcome_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FrameLoss(_message.Message):
    __slots__ = ("interval", "frame")
    INTERVAL_FIELD_NUMBER: _ClassVar[int]
    FRAME_FIELD_NUMBER: _ClassVar[int]
    interval: int
    frame: int
    def __init__(self, interval: _Optional[int] = ..., frame: _Optional[int] = ...) -> None: ...

class OutcomeReport(_message.Message):
    __slots__ = ("trial_id", "outcome", "manipulandum", "reaction_time_ms", "terminating_interval", "precise_fixation", "frame_loss", "reward_ms", "hit_condition", "simulated", "note")
    TRIAL_ID_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    MANIPULANDUM_FIELD_NUMBER: _ClassVar[int]
    REACTION_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TERMINATING_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    PRECISE_FIXATION_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_FIELD_NUMBER: _ClassVar[int]
    REWARD_MS_FIELD_NUMBER: _ClassVar[int]
    HIT_CONDITION_FIELD_NUMBER: _ClassVar[int]
    SIMULATED_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    trial_id: int
    outcome: _trial_outcome_pb2.TrialOutcome
    manipulandum: _common_pb2.Manipulandum
    reaction_time_ms: float
    terminating_interval: int
    precise_fixation: bool
    frame_loss: FrameLoss
    reward_ms: int
    hit_condition: bool
    simulated: bool
    note: str
    def __init__(self, trial_id: _Optional[int] = ..., outcome: _Optional[_Union[_trial_outcome_pb2.TrialOutcome, str]] = ..., manipulandum: _Optional[_Union[_common_pb2.Manipulandum, str]] = ..., reaction_time_ms: _Optional[float] = ..., terminating_interval: _Optional[int] = ..., precise_fixation: _Optional[bool] = ..., frame_loss: _Optional[_Union[FrameLoss, _Mapping]] = ..., reward_ms: _Optional[int] = ..., hit_condition: _Optional[bool] = ..., simulated: _Optional[bool] = ..., note: _Optional[str] = ...) -> None: ...

class Outcome(_message.Message):
    __slots__ = ("code", "name", "manipulandum", "reaction_time_ms", "terminating_interval", "precise_fixation", "frame_loss", "reward_ms", "hit_condition", "simulated", "note")
    CODE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    MANIPULANDUM_FIELD_NUMBER: _ClassVar[int]
    REACTION_TIME_MS_FIELD_NUMBER: _ClassVar[int]
    TERMINATING_INTERVAL_FIELD_NUMBER: _ClassVar[int]
    PRECISE_FIXATION_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_FIELD_NUMBER: _ClassVar[int]
    REWARD_MS_FIELD_NUMBER: _ClassVar[int]
    HIT_CONDITION_FIELD_NUMBER: _ClassVar[int]
    SIMULATED_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    code: int
    name: str
    manipulandum: str
    reaction_time_ms: float
    terminating_interval: int
    precise_fixation: bool
    frame_loss: FrameLoss
    reward_ms: int
    hit_condition: bool
    simulated: bool
    note: str
    def __init__(self, code: _Optional[int] = ..., name: _Optional[str] = ..., manipulandum: _Optional[str] = ..., reaction_time_ms: _Optional[float] = ..., terminating_interval: _Optional[int] = ..., precise_fixation: _Optional[bool] = ..., frame_loss: _Optional[_Union[FrameLoss, _Mapping]] = ..., reward_ms: _Optional[int] = ..., hit_condition: _Optional[bool] = ..., simulated: _Optional[bool] = ..., note: _Optional[str] = ...) -> None: ...

class TrialSpec(_message.Message):
    __slots__ = ("trial_number", "trial_type_index", "trial_type_number", "trial_type_name", "set_name", "statemachine_graph", "reward_ms", "recording", "paused", "started_at", "deadline")
    TRIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    TRIAL_TYPE_INDEX_FIELD_NUMBER: _ClassVar[int]
    TRIAL_TYPE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    TRIAL_TYPE_NAME_FIELD_NUMBER: _ClassVar[int]
    SET_NAME_FIELD_NUMBER: _ClassVar[int]
    STATEMACHINE_GRAPH_FIELD_NUMBER: _ClassVar[int]
    REWARD_MS_FIELD_NUMBER: _ClassVar[int]
    RECORDING_FIELD_NUMBER: _ClassVar[int]
    PAUSED_FIELD_NUMBER: _ClassVar[int]
    STARTED_AT_FIELD_NUMBER: _ClassVar[int]
    DEADLINE_FIELD_NUMBER: _ClassVar[int]
    trial_number: int
    trial_type_index: int
    trial_type_number: int
    trial_type_name: str
    set_name: str
    statemachine_graph: str
    reward_ms: int
    recording: bool
    paused: bool
    started_at: _timestamp_pb2.Timestamp
    deadline: _timestamp_pb2.Timestamp
    def __init__(self, trial_number: _Optional[int] = ..., trial_type_index: _Optional[int] = ..., trial_type_number: _Optional[int] = ..., trial_type_name: _Optional[str] = ..., set_name: _Optional[str] = ..., statemachine_graph: _Optional[str] = ..., reward_ms: _Optional[int] = ..., recording: _Optional[bool] = ..., paused: _Optional[bool] = ..., started_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., deadline: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TrialRecord(_message.Message):
    __slots__ = ("trial", "outcome", "accepted", "refusal_reason", "ended_at", "policy_state")
    TRIAL_FIELD_NUMBER: _ClassVar[int]
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    REFUSAL_REASON_FIELD_NUMBER: _ClassVar[int]
    ENDED_AT_FIELD_NUMBER: _ClassVar[int]
    POLICY_STATE_FIELD_NUMBER: _ClassVar[int]
    trial: TrialSpec
    outcome: Outcome
    accepted: bool
    refusal_reason: str
    ended_at: _timestamp_pb2.Timestamp
    policy_state: _struct_pb2.Struct
    def __init__(self, trial: _Optional[_Union[TrialSpec, _Mapping]] = ..., outcome: _Optional[_Union[Outcome, _Mapping]] = ..., accepted: _Optional[bool] = ..., refusal_reason: _Optional[str] = ..., ended_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., policy_state: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class CancelTrial(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...
