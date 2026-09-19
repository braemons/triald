from triald._proto.triald.v1 import common_pb2 as _common_pb2
from triald._proto.triald.v1 import config_pb2 as _config_pb2
from triald._proto.triald.v1 import debug_pb2 as _debug_pb2
from triald._proto.triald.v1 import policy_pb2 as _policy_pb2
from triald._proto.triald.v1 import session_pb2 as _session_pb2
from triald._proto.triald.v1 import sets_pb2 as _sets_pb2
from triald._proto.triald.v1 import trial_pb2 as _trial_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class StopRequest(_message.Message):
    __slots__ = ("reason",)
    REASON_FIELD_NUMBER: _ClassVar[int]
    reason: str
    def __init__(self, reason: _Optional[str] = ...) -> None: ...

class ReadPolicyRequest(_message.Message):
    __slots__ = ("source",)
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    source: bool
    def __init__(self, source: _Optional[bool] = ...) -> None: ...

class ReadStateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class WatchStateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ArmRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StartRecordingRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PauseRecordingRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResumeRecordingRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StopRecordingRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class NextTrialRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadSetsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadConfigRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResetRoundsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ResetCountersRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ClearPolicyRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadSimRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadFreeRunRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
