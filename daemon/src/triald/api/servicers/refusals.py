# SPDX-License-Identifier: AGPL-3.0-or-later
"""One refusal shape, for every rpc.

`ServiceError` stays the daemon's own vocabulary — raised in `service.py`,
`convert/` and the domain modules, and carrying a sentence meant to be read by
a person. This is the single place it becomes a gRPC status.

**The codes are chosen for what they mean**, not by transcribing the HTTP
status this API used to answer with:

* `failed_precondition` — the daemon is not in a state where this means
  anything: no session armed, a trial already in flight, a late outcome report.
* `invalid_argument` — understood and refused: a config change that is not
  allowed while a session runs, a set whose name does not match.
* `not_found` — no such set, no such policy.
* `internal` — the daemon broke, not the caller.

**The whole refusal also travels as itself.** A status code is a category and a
message is a sentence; `error` — `session`, `sets`, `policy` — is the part a
client switches on. So `triald.v1.Error` is encoded into the trailing metadata
entry `triald-error-bin`, which is what makes `proto/triald/v1/common.proto`
the one description of a refusal rather than a shape nothing sends. The message
keeps the sentence for everything that has not been told about the metadata:
grpcurl, a log line, a failed test.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import grpc

from triald.api.service import ServiceError
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    common_pb2,
)

#: Where the typed refusal rides. `-bin` is gRPC's own spelling for a metadata
#: value that is bytes rather than ASCII, which is what lets `detail` hold a
#: set name with a non-ASCII character in it.
REFUSAL_METADATA_KEY = "triald-error-bin"

#: The daemon's own statuses, as the gRPC codes that mean the same thing.
_CODE_FOR_STATUS = {
    400: grpc.StatusCode.INVALID_ARGUMENT,
    404: grpc.StatusCode.NOT_FOUND,
    409: grpc.StatusCode.FAILED_PRECONDITION,
    422: grpc.StatusCode.INVALID_ARGUMENT,
    500: grpc.StatusCode.INTERNAL,
}


async def refuse(context: grpc.aio.ServicerContext, refusal: ServiceError):
    """Abort the call with the refusal, in full.

    `abort` never returns — it raises — but it is awaited and typed as though
    it might, so callers `raise` the result to make the control flow visible.
    """
    await context.abort(
        _CODE_FOR_STATUS.get(refusal.status, grpc.StatusCode.UNKNOWN),
        refusal.detail,
        trailing_metadata=(
            (
                REFUSAL_METADATA_KEY,
                common_pb2.Error(error=refusal.kind, detail=refusal.detail).SerializeToString(),
            ),
        ),
    )


async def answering[T](
    context: grpc.aio.ServicerContext, work: Callable[[], Awaitable[T]]
) -> T:
    """Run one rpc's body, turning this daemon's refusal into a status.

    Every servicer method goes through here, so a `ServiceError` raised six
    frames down in the session logic reaches the caller as the refusal it is
    rather than as an `INTERNAL` with a traceback in the log.
    """
    try:
        return await work()
    except ServiceError as refusal:
        await refuse(context, refusal)
        raise  # unreachable: abort() raises. Here so the type is honest.


# **Unknown fields in a request are not refused on the binary wire, and cannot
# be.** §11 of `contracts/INTERACTIONS.md` asks for it — a request refuses what
# it does not understand, a response ignores it — and this code tried to
# provide it with `message.UnknownFields()`. That accessor raises
# `NotImplementedError` under protobuf's upb runtime, which is the default one
# everywhere, so the check was a crash rather than a refusal.
#
# What is true instead:
#
# * **The JSON codec does refuse them**, by name, in `json_format.Parse`. That
#   is the path a hand-written request arrives on — a panel, a script, a person
#   with a terminal — and it is where the mistake §11 is about actually gets
#   made.
# * **The binary codec ignores them**, because protobuf ignores them. A client
#   newer than this daemon sends a field this build has never heard of and the
#   daemon proceeds without it. That is protobuf's design and no daemon in this
#   family can opt out of it, which is worth knowing rather than papering over.
