from triald._proto.triald.v1 import common_pb2 as _common_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Acceptance(_message.Message):
    __slots__ = ("not_started", "hit", "wrong_response", "early_hit", "early_wrong_response", "early", "late", "eye_error", "unexpected_start_signal", "wrong_start_signal", "cancelled", "never_finished", "frame_loss", "imprecise_fixation")
    NOT_STARTED_FIELD_NUMBER: _ClassVar[int]
    HIT_FIELD_NUMBER: _ClassVar[int]
    WRONG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    EARLY_HIT_FIELD_NUMBER: _ClassVar[int]
    EARLY_WRONG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    EARLY_FIELD_NUMBER: _ClassVar[int]
    LATE_FIELD_NUMBER: _ClassVar[int]
    EYE_ERROR_FIELD_NUMBER: _ClassVar[int]
    UNEXPECTED_START_SIGNAL_FIELD_NUMBER: _ClassVar[int]
    WRONG_START_SIGNAL_FIELD_NUMBER: _ClassVar[int]
    CANCELLED_FIELD_NUMBER: _ClassVar[int]
    NEVER_FINISHED_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_FIELD_NUMBER: _ClassVar[int]
    IMPRECISE_FIXATION_FIELD_NUMBER: _ClassVar[int]
    not_started: bool
    hit: bool
    wrong_response: bool
    early_hit: bool
    early_wrong_response: bool
    early: bool
    late: bool
    eye_error: bool
    unexpected_start_signal: bool
    wrong_start_signal: bool
    cancelled: bool
    never_finished: bool
    frame_loss: bool
    imprecise_fixation: bool
    def __init__(self, not_started: _Optional[bool] = ..., hit: _Optional[bool] = ..., wrong_response: _Optional[bool] = ..., early_hit: _Optional[bool] = ..., early_wrong_response: _Optional[bool] = ..., early: _Optional[bool] = ..., late: _Optional[bool] = ..., eye_error: _Optional[bool] = ..., unexpected_start_signal: _Optional[bool] = ..., wrong_start_signal: _Optional[bool] = ..., cancelled: _Optional[bool] = ..., never_finished: _Optional[bool] = ..., frame_loss: _Optional[bool] = ..., imprecise_fixation: _Optional[bool] = ...) -> None: ...

class SessionConfig(_message.Message):
    __slots__ = ("initial_set", "ordering", "rounds", "avoid_repeat", "acceptance", "trial_cap_ms", "stop_when_rounds_done", "stop_after_trials", "stop_criterion", "extend_trial_type_number", "seed")
    INITIAL_SET_FIELD_NUMBER: _ClassVar[int]
    ORDERING_FIELD_NUMBER: _ClassVar[int]
    ROUNDS_FIELD_NUMBER: _ClassVar[int]
    AVOID_REPEAT_FIELD_NUMBER: _ClassVar[int]
    ACCEPTANCE_FIELD_NUMBER: _ClassVar[int]
    TRIAL_CAP_MS_FIELD_NUMBER: _ClassVar[int]
    STOP_WHEN_ROUNDS_DONE_FIELD_NUMBER: _ClassVar[int]
    STOP_AFTER_TRIALS_FIELD_NUMBER: _ClassVar[int]
    STOP_CRITERION_FIELD_NUMBER: _ClassVar[int]
    EXTEND_TRIAL_TYPE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    initial_set: str
    ordering: _common_pb2.Ordering
    rounds: int
    avoid_repeat: bool
    acceptance: Acceptance
    trial_cap_ms: int
    stop_when_rounds_done: bool
    stop_after_trials: int
    stop_criterion: _common_pb2.TrialCountCriterion
    extend_trial_type_number: bool
    seed: int
    def __init__(self, initial_set: _Optional[str] = ..., ordering: _Optional[_Union[_common_pb2.Ordering, str]] = ..., rounds: _Optional[int] = ..., avoid_repeat: _Optional[bool] = ..., acceptance: _Optional[_Union[Acceptance, _Mapping]] = ..., trial_cap_ms: _Optional[int] = ..., stop_when_rounds_done: _Optional[bool] = ..., stop_after_trials: _Optional[int] = ..., stop_criterion: _Optional[_Union[_common_pb2.TrialCountCriterion, str]] = ..., extend_trial_type_number: _Optional[bool] = ..., seed: _Optional[int] = ...) -> None: ...

class ConfigPatch(_message.Message):
    __slots__ = ("ordering", "rounds", "avoid_repeat", "acceptance", "trial_cap_ms", "stop_when_rounds_done", "stop_after_trials", "stop_criterion", "initial_set", "extend_trial_type_number", "seed")
    ORDERING_FIELD_NUMBER: _ClassVar[int]
    ROUNDS_FIELD_NUMBER: _ClassVar[int]
    AVOID_REPEAT_FIELD_NUMBER: _ClassVar[int]
    ACCEPTANCE_FIELD_NUMBER: _ClassVar[int]
    TRIAL_CAP_MS_FIELD_NUMBER: _ClassVar[int]
    STOP_WHEN_ROUNDS_DONE_FIELD_NUMBER: _ClassVar[int]
    STOP_AFTER_TRIALS_FIELD_NUMBER: _ClassVar[int]
    STOP_CRITERION_FIELD_NUMBER: _ClassVar[int]
    INITIAL_SET_FIELD_NUMBER: _ClassVar[int]
    EXTEND_TRIAL_TYPE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    SEED_FIELD_NUMBER: _ClassVar[int]
    ordering: _common_pb2.Ordering
    rounds: int
    avoid_repeat: bool
    acceptance: Acceptance
    trial_cap_ms: int
    stop_when_rounds_done: bool
    stop_after_trials: int
    stop_criterion: _common_pb2.TrialCountCriterion
    initial_set: str
    extend_trial_type_number: bool
    seed: int
    def __init__(self, ordering: _Optional[_Union[_common_pb2.Ordering, str]] = ..., rounds: _Optional[int] = ..., avoid_repeat: _Optional[bool] = ..., acceptance: _Optional[_Union[Acceptance, _Mapping]] = ..., trial_cap_ms: _Optional[int] = ..., stop_when_rounds_done: _Optional[bool] = ..., stop_after_trials: _Optional[int] = ..., stop_criterion: _Optional[_Union[_common_pb2.TrialCountCriterion, str]] = ..., initial_set: _Optional[str] = ..., extend_trial_type_number: _Optional[bool] = ..., seed: _Optional[int] = ...) -> None: ...

class ConfigUpdateResult(_message.Message):
    __slots__ = ("changed", "bag_rebuilt", "config")
    CHANGED_FIELD_NUMBER: _ClassVar[int]
    BAG_REBUILT_FIELD_NUMBER: _ClassVar[int]
    CONFIG_FIELD_NUMBER: _ClassVar[int]
    changed: _containers.RepeatedScalarFieldContainer[str]
    bag_rebuilt: bool
    config: SessionConfig
    def __init__(self, changed: _Optional[_Iterable[str]] = ..., bag_rebuilt: _Optional[bool] = ..., config: _Optional[_Union[SessionConfig, _Mapping]] = ...) -> None: ...
