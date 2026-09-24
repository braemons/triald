# SPDX-License-Identifier: AGPL-3.0-or-later
"""The browser's way in: the panels, and gRPC-Web over them.

**A browser cannot speak gRPC.** It has no access to HTTP trailers and no
control over HTTP/2 framing, which is why gRPC-Web exists at all. Rust solves
this in-process with `tonic-web`, and statemachined and mousewheeld do; Python
has no maintained equivalent — `sonora` was last released in 2023 — so this is
written here, against the protocol specification, and it is small because
gRPC-Web is small:

* **Every call is an HTTP POST** whose body is one enveloped message — a flag
  byte, a big-endian length, the protobuf bytes.
* **The answer is the same envelope**, once for a unary call and once per frame
  for a stream, followed by a *trailer frame*: flag bit 7 set, and the trailers
  gRPC would have sent as HTTP/2 trailers written out as header lines. The
  status, the message and the typed refusal ride there, so an error is
  protobuf like everything else.

That is the whole protocol surface a browser needs, and it is why this file is
short enough to own.

**Protobuf only.** This edge used to speak the Connect protocol, which also
takes JSON, and the panels sent JSON because that is the Connect transport's
default. `contracts/DAEMON_LAYOUT.md` says every wire in the family carries
protobuf, and gRPC-Web has no JSON codec to fall back to — the same transport
the other daemons' panels use, so one browser client shape serves all three.

**Nothing here knows what a trial is.** It dispatches by descriptor into the
same servicers `grpc_server.py` registers, so the two transports cannot drift:
an rpc added to the proto and implemented once is reachable from both. The
daemon's own port speaks real gRPC, for clients, CLIs and grpcurl; this is the
edge, and a rig with no browser on it loses nothing by never starting it.
"""

from __future__ import annotations

import base64
import logging
import struct
from collections.abc import Callable
from pathlib import Path

import grpc
from google.protobuf.message import DecodeError, Message
from google.protobuf.message_factory import GetMessageClass

from triald._proto.triald.v1 import (
    service_pb2,
)
from triald.api.service import SessionService

log = logging.getLogger(__name__)

#: What a gRPC-Web client sends, and what this edge answers with. The bare
#: `application/grpc-web` means the same binary codec; `+text` (base64 bodies,
#: for browsers without binary fetch) is not served, because none that runs the
#: panels lacks it.
_REQUEST_CONTENT_TYPES = {"application/grpc-web", "application/grpc-web+proto"}
_CONTENT_TYPE = b"application/grpc-web+proto"

#: Bit 7 of the flag byte marks the trailer frame. Bit 0 would mean the message
#: is compressed, which this never does.
_TRAILER = 0x80


class Aborted(Exception):
    """What a servicer's `context.abort()` raises on this transport.

    The servicers were written against `grpc.aio.ServicerContext` and touch
    exactly one method of it. That is what lets the same code serve two
    protocols: this transport supplies a context whose `abort` raises, and
    everything else about a servicer is unaware there are two.
    """

    def __init__(self, code: grpc.StatusCode, detail: str, metadata) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.metadata = dict(metadata or ())


class EdgeContext:
    """The servicer context, as much of it as a servicer actually uses."""

    async def abort(self, code, details="", trailing_metadata=()):
        raise Aborted(code, details, trailing_metadata)


class Rpc:
    """One method: how to decode its request, call it, and encode its answer."""

    def __init__(self, handler: Callable, request_type, streaming: bool) -> None:
        self.handler = handler
        self.request_type = request_type
        self.streaming = streaming


def rpcs_of(servicers: dict[str, object]) -> dict[str, Rpc]:
    """Every rpc in the proto, by the path gRPC addresses it at.

    Built from the descriptor rather than written out: the path is
    `/triald.v1.Session/Arm`, the request type comes from the descriptor, and
    an rpc added to `service.proto` becomes reachable here as soon as something
    implements it. There is no list to forget to update.
    """
    table: dict[str, Rpc] = {}
    for name, descriptor in service_pb2.DESCRIPTOR.services_by_name.items():
        servicer = servicers[name]
        for method in descriptor.methods:
            handler = getattr(servicer, method.name)
            table[f"/{descriptor.full_name}/{method.name}"] = Rpc(
                handler,
                GetMessageClass(method.input_type),
                streaming=method.server_streaming,
            )
    return table


# -- the protocol ---------------------------------------------------------------


def _envelope(flags: int, payload: bytes) -> bytes:
    """One gRPC-Web frame: a flag byte, a big-endian length, the body."""
    return struct.pack(">BI", flags, len(payload)) + payload


def _percent_encoded(detail: str) -> str:
    """`grpc-message` as the gRPC spec writes it: printable ASCII but `%` as
    itself, every other byte of the UTF-8 as `%XX`."""
    return "".join(
        chr(byte) if 0x20 <= byte <= 0x7E and byte != 0x25 else f"%{byte:02X}"
        for byte in detail.encode()
    )


def _trailers(
    code: grpc.StatusCode = grpc.StatusCode.OK, detail: str = "", metadata=None
) -> bytes:
    """The trailer frame: what HTTP/2 trailers would have carried.

    The typed refusal goes in under the same `-bin` key the gRPC transport
    uses, so a browser and a Python client read the same `triald.v1.Error` from
    the same place and neither has to parse a sentence. A `-bin` value is
    base64 on this wire, unpadded as gRPC writes it.
    """
    lines = [f"grpc-status: {code.value[0]}"]
    if detail:
        lines.append(f"grpc-message: {_percent_encoded(detail)}")
    for key, value in (metadata or {}).items():
        if key.endswith("-bin"):
            value = base64.b64encode(value).decode().rstrip("=")
        lines.append(f"{key}: {value}")
    return _envelope(_TRAILER, "".join(f"{line}\r\n" for line in lines).encode())


def _decode(rpc: Rpc, body: bytes) -> Message:
    """The one message a gRPC-Web request carries, out of its envelope."""
    if len(body) < 5:
        raise DecodeError("the request is not an enveloped message")
    flags, length = struct.unpack(">BI", body[:5])
    if flags & 1:
        raise DecodeError("the request is compressed, which this edge does not accept")
    if len(body) - 5 != length:
        raise DecodeError(f"the envelope says {length} bytes and carries {len(body) - 5}")
    return rpc.request_type.FromString(body[5:])


async def _send(send, status: int, content_type: str, body: bytes) -> None:
    """A plain HTTP answer: the panels, a preflight, a request that is not gRPC-Web."""
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", content_type.encode()), *_CORS_HEADERS],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive) -> bytes:
    body = b""
    while True:
        event = await receive()
        body += event.get("body", b"")
        if not event.get("more_body", False):
            return body


async def _start(send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", _CONTENT_TYPE), *_CORS_HEADERS],
        }
    )


async def _frame(send, payload: bytes, *, more: bool = True) -> None:
    await send({"type": "http.response.body", "body": payload, "more_body": more})


async def _call(rpc: Rpc, body: bytes, send) -> None:
    """One call, unary or streaming: 200, the frames, the trailers.

    The status line goes out before anything is known about how the call will
    go, which is the protocol's own rule and the reason the trailers carry the
    outcome: by the time a stream fails, the status line is long gone. A unary
    call is the same shape with one frame, so there is one path for both.
    """
    await _start(send)
    try:
        request = _decode(rpc, body)
    except DecodeError as problem:
        return await _frame(
            send, _trailers(grpc.StatusCode.INVALID_ARGUMENT, str(problem)), more=False
        )
    try:
        if rpc.streaming:
            async for answer in rpc.handler(request, EdgeContext()):
                await _frame(send, _envelope(0, answer.SerializeToString()))
        else:
            answer = await rpc.handler(request, EdgeContext())
            await _frame(send, _envelope(0, answer.SerializeToString()))
    except Aborted as problem:
        return await _frame(
            send, _trailers(problem.code, problem.detail, problem.metadata), more=False
        )
    except (ConnectionResetError, BrokenPipeError):
        # The browser navigated away mid-stream. Not a failure of anything,
        # and nothing left to send it.
        return
    await _frame(send, _trailers(), more=False)


# -- the panels -----------------------------------------------------------------


def find_web_root() -> Path:
    """Where the panels are, installed or in a checkout.

    The panels are authored in `client/web/` — a sibling of `daemon/`, not a
    subdirectory of it, because talking to a rig should not mean installing one
    (`contracts/DAEMON_LAYOUT.md`). A wheel cannot ship a directory from
    outside its package, so the build copies it to `triald/web` and the
    installed daemon finds it there.

    An *editable* install applies no such copy, which is the case a developer
    is always in: there, the only copy is the authored one, four levels up.
    Trying the packaged location first means a real install never touches the
    filesystem outside itself.
    """
    packaged = Path(__file__).resolve().parent.parent / "web"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[4] / "client" / "web"


#: Enough to serve what this UI is made of, and no more. An unknown suffix is
#: refused rather than served as a guess.
_CONTENT_TYPE_BY_SUFFIX = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".png": "image/png",
}

#: **CORS is open, and `/elements/` is why.** A console served from somewhere
#: else imports these panels by URL and calls this daemon from its own origin;
#: that is the contract, not an accident.
_CORS_HEADERS = [
    (b"access-control-allow-origin", b"*"),
    (b"access-control-allow-headers", b"*"),
    (b"access-control-expose-headers", b"*"),
    (b"cache-control", b"no-cache, must-revalidate"),
]


def _read_asset(root: Path, relative: str) -> tuple[bytes, str] | None:
    """One file under `root`, or nothing.

    `resolve()` and then a containment check, because `..` in a URL is how a
    static file server becomes a way to read `/etc/shadow`.
    """
    path = (root / relative).resolve()
    if not path.is_file() or root.resolve() not in path.parents:
        return None
    content_type = _CONTENT_TYPE_BY_SUFFIX.get(path.suffix)
    if content_type is None:
        return None
    return path.read_bytes(), content_type


# -- the app --------------------------------------------------------------------


def build_edge(service: SessionService, servicers: dict[str, object]):
    """An ASGI app: the panels, and the rpcs a browser can reach.

    `servicers` is the same mapping `grpc_server.py` registers, so both
    transports call one implementation. Nothing is wired by name here.
    """
    table = rpcs_of(servicers)
    web_root = find_web_root()
    if not web_root.is_dir():  # pragma: no cover - only if built without the UI
        log.warning("no web UI at %s; serving the rpcs only", web_root)

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        path = scope["path"]
        method = scope["method"]

        if method == "OPTIONS":
            # The preflight a browser sends before a cross-origin POST.
            return await _send(send, 204, "text/plain", b"")

        if method == "POST":
            content_type = _header(scope, b"content-type").split(";")[0].strip()
            if content_type not in _REQUEST_CONTENT_TYPES:
                # Not a gRPC-Web client at all, so an HTTP status is the only
                # answer it can read.
                return await _send(
                    send,
                    415,
                    "text/plain",
                    f"{content_type or 'no content type'} is not one of "
                    f"{sorted(_REQUEST_CONTENT_TYPES)}".encode(),
                )
            rpc = table.get(path)
            body = await _read_body(receive)
            if rpc is None:
                await _start(send)
                return await _frame(
                    send,
                    _trailers(grpc.StatusCode.UNIMPLEMENTED, f"no rpc at {path}"),
                    more=False,
                )
            return await _call(rpc, body, send)

        if method == "GET":
            relative = "index.html" if path == "/" else path.lstrip("/")
            asset = _read_asset(web_root, relative)
            if asset is None:
                return await _send(send, 404, "text/plain", f"no {relative}".encode())
            content, content_type = asset
            return await _send(send, 200, content_type, content)

        await _send(send, 405, "text/plain", b"")

    return app


def _header(scope, name: bytes) -> str:
    for key, value in scope.get("headers", ()):
        if key.lower() == name:
            return value.decode()
    return ""
