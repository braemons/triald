import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class PolicyOrigin(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    POLICY_ORIGIN_UNSPECIFIED: _ClassVar[PolicyOrigin]
    POLICY_ORIGIN_DEFAULT: _ClassVar[PolicyOrigin]
    POLICY_ORIGIN_FILE: _ClassVar[PolicyOrigin]
    POLICY_ORIGIN_UPLOADED: _ClassVar[PolicyOrigin]
POLICY_ORIGIN_UNSPECIFIED: PolicyOrigin
POLICY_ORIGIN_DEFAULT: PolicyOrigin
POLICY_ORIGIN_FILE: PolicyOrigin
POLICY_ORIGIN_UPLOADED: PolicyOrigin

class PolicyInfo(_message.Message):
    __slots__ = ("name", "class_name", "sha256", "origin", "source", "state")
    NAME_FIELD_NUMBER: _ClassVar[int]
    CLASS_NAME_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    ORIGIN_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    name: str
    class_name: str
    sha256: str
    origin: PolicyOrigin
    source: str
    state: _struct_pb2.Struct
    def __init__(self, name: _Optional[str] = ..., class_name: _Optional[str] = ..., sha256: _Optional[str] = ..., origin: _Optional[_Union[PolicyOrigin, str]] = ..., source: _Optional[str] = ..., state: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class PolicySource(_message.Message):
    __slots__ = ("name", "source")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    name: str
    source: str
    def __init__(self, name: _Optional[str] = ..., source: _Optional[str] = ...) -> None: ...

class PolicyDiagnostic(_message.Message):
    __slots__ = ("line", "column", "message")
    LINE_FIELD_NUMBER: _ClassVar[int]
    COLUMN_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    line: int
    column: int
    message: str
    def __init__(self, line: _Optional[int] = ..., column: _Optional[int] = ..., message: _Optional[str] = ...) -> None: ...

class PolicyCheckResult(_message.Message):
    __slots__ = ("ok", "class_name", "sha256", "diagnostics", "trials_run")
    OK_FIELD_NUMBER: _ClassVar[int]
    CLASS_NAME_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    DIAGNOSTICS_FIELD_NUMBER: _ClassVar[int]
    TRIALS_RUN_FIELD_NUMBER: _ClassVar[int]
    ok: bool
    class_name: str
    sha256: str
    diagnostics: _containers.RepeatedCompositeFieldContainer[PolicyDiagnostic]
    trials_run: int
    def __init__(self, ok: _Optional[bool] = ..., class_name: _Optional[str] = ..., sha256: _Optional[str] = ..., diagnostics: _Optional[_Iterable[_Union[PolicyDiagnostic, _Mapping]]] = ..., trials_run: _Optional[int] = ...) -> None: ...

class PolicyError(_message.Message):
    __slots__ = ("hook", "trial_number", "error", "traceback", "at")
    HOOK_FIELD_NUMBER: _ClassVar[int]
    TRIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    TRACEBACK_FIELD_NUMBER: _ClassVar[int]
    AT_FIELD_NUMBER: _ClassVar[int]
    hook: str
    trial_number: int
    error: str
    traceback: str
    at: _timestamp_pb2.Timestamp
    def __init__(self, hook: _Optional[str] = ..., trial_number: _Optional[int] = ..., error: _Optional[str] = ..., traceback: _Optional[str] = ..., at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...
