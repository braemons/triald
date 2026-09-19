from triald.v1 import session_pb2 as _session_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SimSettings(_message.Message):
    __slots__ = ("hit_rate", "not_started_rate", "eye_error_rate", "early_rate", "frame_loss_rate", "imprecise_fixation_rate", "hit_rate_by_type")
    class HitRateByTypeEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    HIT_RATE_FIELD_NUMBER: _ClassVar[int]
    NOT_STARTED_RATE_FIELD_NUMBER: _ClassVar[int]
    EYE_ERROR_RATE_FIELD_NUMBER: _ClassVar[int]
    EARLY_RATE_FIELD_NUMBER: _ClassVar[int]
    FRAME_LOSS_RATE_FIELD_NUMBER: _ClassVar[int]
    IMPRECISE_FIXATION_RATE_FIELD_NUMBER: _ClassVar[int]
    HIT_RATE_BY_TYPE_FIELD_NUMBER: _ClassVar[int]
    hit_rate: float
    not_started_rate: float
    eye_error_rate: float
    early_rate: float
    frame_loss_rate: float
    imprecise_fixation_rate: float
    hit_rate_by_type: _containers.ScalarMap[str, float]
    def __init__(self, hit_rate: _Optional[float] = ..., not_started_rate: _Optional[float] = ..., eye_error_rate: _Optional[float] = ..., early_rate: _Optional[float] = ..., frame_loss_rate: _Optional[float] = ..., imprecise_fixation_rate: _Optional[float] = ..., hit_rate_by_type: _Optional[_Mapping[str, float]] = ...) -> None: ...

class StepRequest(_message.Message):
    __slots__ = ("trials",)
    TRIALS_FIELD_NUMBER: _ClassVar[int]
    trials: int
    def __init__(self, trials: _Optional[int] = ...) -> None: ...

class StepResult(_message.Message):
    __slots__ = ("trials", "stopped", "stop_reason", "state")
    TRIALS_FIELD_NUMBER: _ClassVar[int]
    STOPPED_FIELD_NUMBER: _ClassVar[int]
    STOP_REASON_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    trials: int
    stopped: bool
    stop_reason: str
    state: _session_pb2.SessionState
    def __init__(self, trials: _Optional[int] = ..., stopped: _Optional[bool] = ..., stop_reason: _Optional[str] = ..., state: _Optional[_Union[_session_pb2.SessionState, _Mapping]] = ...) -> None: ...

class FreeRun(_message.Message):
    __slots__ = ("running", "interval_ms")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_MS_FIELD_NUMBER: _ClassVar[int]
    running: bool
    interval_ms: int
    def __init__(self, running: _Optional[bool] = ..., interval_ms: _Optional[int] = ...) -> None: ...

class FreeRunStatus(_message.Message):
    __slots__ = ("running", "interval_ms")
    RUNNING_FIELD_NUMBER: _ClassVar[int]
    INTERVAL_MS_FIELD_NUMBER: _ClassVar[int]
    running: bool
    interval_ms: int
    def __init__(self, running: _Optional[bool] = ..., interval_ms: _Optional[int] = ...) -> None: ...
