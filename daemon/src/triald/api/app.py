# SPDX-License-Identifier: AGPL-3.0-or-later
"""The routes, and the app that serves them.

Thin on purpose. A route parses its body into a wire type, calls one method on
:class:`~triald.api.service.SessionService`, and converts, and answers; everything
about *when* something may be done lives in the service, and everything about
*what shape* it has lives in ``proto/triald/v1/``. If a route grows a
decision in it, the decision is in the wrong place.

Two conventions run through all of it:

* **Every mutating call answers with the new state.** The WebSocket stream
  pushes it too, but a client that has just changed something should not have to
  wait for a frame to find out what it did - and a MATLAB script with no
  WebSocket at all should still be able to work purely from the replies.
* **A refusal is a ``triald.v1.Error`` with a 4xx.** The
  ``detail`` is written to be shown to a person, because it usually is.

The ``/api/debug`` group drives the *simulated* subject and exists so the whole
loop can be exercised with no rig attached. It is the same loop: a debug step
goes through :func:`triald.runner.run_trial`, exactly as a real session does.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from google.protobuf import json_format

from triald.api import convert, wire
from triald.api.service import ServiceError, SessionService, SimSettings
from triald.session import SessionConfig
from triald.trialtypes import TrialTypeStore
from triald.v1 import (
    common_pb2,
    config_pb2,
    debug_pb2,
    policy_pb2,
    session_pb2,
    sets_pb2,
    trial_pb2,
)

log = logging.getLogger(__name__)


def _find_web_root() -> Path:
    """Where the panels are, installed or in a checkout.

    The panels are authored in ``client/web/`` -- a sibling of ``daemon/``, not
    a subdirectory of it, because talking to a rig should not mean installing
    one (``contracts/DAEMON_LAYOUT.md``). A wheel cannot ship a directory from
    outside its package, so the build copies it to ``triald/web`` and the
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


WEB_ROOT = _find_web_root()

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

#: **Nothing here is cached.** This daemon serves both the elements and the
#: API they call, which is what keeps them the same version; a browser
#: holding yesterday's `/elements/triald.js` against today's API -- or simply
#: against yesterday's own set of panels -- would give that guarantee away
#: for a few kilobytes. Matches statemachined's web_user_interface_routes.py,
#: which the `/elements/` contract is specified against.
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}


def _read_asset(relative_path: str, root: Path) -> FileResponse:
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise HTTPException(404, f"no such file in the web UI: {relative_path!r}")
    content_type = _CONTENT_TYPE_BY_SUFFIX.get(candidate.suffix)
    if content_type is None:
        raise HTTPException(404, f"{candidate.suffix!r} is not a type this daemon serves")
    return FileResponse(candidate, media_type=content_type, headers=_NO_CACHE_HEADERS)


DESCRIPTION = """
The trial control daemon's HTTP and WebSocket API.

`GET /api/state` and the `/api/stream` WebSocket carry the same
`SessionStateModel`; everything else is a small call that changes something and
returns the new state. Outcome codes are the `.tdr` wire contract and are never
renumbered.

The `/api/debug` group drives a simulated subject through the real trial loop,
so the whole daemon can be exercised with no rig attached.
"""


def create_app(
    service: SessionService | None = None,
    *,
    store: TrialTypeStore | None = None,
    config: SessionConfig | None = None,
) -> FastAPI:
    """Build the application around `service`, or around a demo experiment.

    Args:
        service: the session to serve. Built from `store` and `config` when not
            given, and from the built-in training sequence when those are not
            given either - which is what makes ``triald serve`` useful with no
            configuration at all.
    """
    if service is None:
        if store is None or config is None:
            store, config = demo_experiment()
        service = SessionService(store, config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Nobody is responsible for delivering an outcome, so triald notices for
        # itself when one stops arriving. See SessionService.start_watchdog.
        await app.state.service.start_watchdog()
        yield
        await app.state.service.shutdown()

    app = FastAPI(
        title="triald",
        summary="Scriptable trial control daemon for brain research",
        description=DESCRIPTION,
        version="0",
        lifespan=lifespan,
    )
    app.state.service = service

    # `/elements/` is meant to be embedded in a console served from somewhere
    # else (statemachined's dev/DAEMON.md §5, which this daemon follows), so
    # nothing here may assume same-origin. The price is paid once, here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> Response:
        """Every refusal in the same shape, through the same seam as an answer.

        `detail` is meant to be shown to a person: it says what was wrong and,
        where there is one, what to do instead.
        """
        return Response(
            status_code=exc.status,
            content=wire.to_json(common_pb2.Error(error=exc.kind, detail=exc.detail)),
            media_type="application/json",
        )

    app.include_router(_api(service))

    if WEB_ROOT.is_dir():
        # Explicit routes rather than `StaticFiles`, so every response carries
        # `_NO_CACHE_HEADERS` -- `StaticFiles` sends only an `ETag`, which lets a
        # browser skip revalidation for a while under heuristic freshness, and
        # a stale `/elements/triald.js` is exactly the panel list going stale
        # in somebody's tab. The catch-all is last, or it would shadow `/api`
        # and `/elements/` above it.
        @app.get("/", include_in_schema=False)
        def read_index() -> HTMLResponse:
            return HTMLResponse(
                (WEB_ROOT / "index.html").read_text(), headers=_NO_CACHE_HEADERS
            )

        @app.get("/elements/{relative_path:path}", include_in_schema=False)
        def read_element_module(relative_path: str) -> FileResponse:
            """The public contract: a console in another repo loads these by URL."""
            return _read_asset(relative_path, WEB_ROOT / "elements")

        @app.get("/{relative_path:path}", include_in_schema=False)
        def read_shell_asset(relative_path: str) -> FileResponse:
            """This daemon's own shell -- not a contract; rearrange at will."""
            return _read_asset(relative_path, WEB_ROOT)
    else:  # pragma: no cover - only if the package was built without the UI
        log.warning("no web UI at %s; serving the API only", WEB_ROOT)

    return app


def _api(service: SessionService) -> APIRouter:
    """The routes, every one of them declared in `proto/triald/v1/service.proto`.

    **Nothing here has a `response_model`.** The interface is the proto, the
    types are generated from it, and `triald.api.wire` turns one into the bytes
    a client reads. FastAPI's own schema generation described the pydantic
    models instead, which were a second description of the same interface —
    exactly what `contracts/DAEMON_LAYOUT.md` exists to stop.

    The cost is that request bodies are read and parsed here rather than
    injected. It is a small cost and it buys the refusal: `wire.from_json`
    rejects an unknown field by name, which is §11's rule for a request.
    """
    router = APIRouter(prefix="/api")

    def answer(message) -> Response:
        return Response(content=wire.to_json(message), media_type="application/json")

    async def body(request: Request, message_type):
        """The request, parsed, or this API's own refusal.

        A malformed body is the caller's mistake and says so with the field
        named, rather than a 422 full of pydantic's internal paths.
        """
        try:
            return wire.from_json(await request.body(), message_type)
        except json_format.ParseError as exc:
            # 422 rather than 400, which is what pydantic answered here before
            # the types were generated: the JSON parsed, and what was wrong was
            # its meaning. Kept because nothing forces a change and a client
            # written against the old status should not have to learn a new one.
            raise ServiceError(str(exc), kind="request", status=422) from exc

    def state_message() -> session_pb2.SessionState:
        return convert.session_state_to_wire_from_snapshot(service.snapshot())

    # -- state ------------------------------------------------------------------

    @router.get("/state", tags=["state"])
    async def get_state() -> Response:
        """The whole snapshot: counters, the active set, the config, the policy."""
        return answer(state_message())

    @router.websocket("/stream")
    async def stream(websocket: WebSocket) -> None:
        """Push a frame on every change, plus one on connect.

        Frames are coalesced rather than queued for a slow client: every frame
        is a whole state, so the newest is the only one worth having and a gap
        in `sequence` is not loss.
        """
        await websocket.accept()
        with service.subscribe() as queue:
            opening = session_pb2.StreamFrame(sequence=0)
            opening.at.FromDatetime(_now())
            opening.state.CopyFrom(state_message())
            await websocket.send_text(wire.to_json(opening))
            try:
                while True:
                    frame = await queue.get()
                    await websocket.send_text(wire.to_json(convert.stream_frame_to_wire(frame)))
            except WebSocketDisconnect:
                return

    # -- session lifecycle ------------------------------------------------------

    @router.post("/session/arm", tags=["session"])
    async def arm() -> Response:
        """Validate everything and start a new session. Counters start at zero."""
        async with service.publishing():
            service.arm()
        return answer(state_message())

    @router.post("/session/stop", tags=["session"])
    async def stop(reason: str = "stopped by the operator") -> Response:
        async with service.publishing():
            await service.set_free_run(False, 250)
            service.stop(reason)
        return answer(state_message())

    @router.post("/session/recording/start", tags=["session"])
    async def start_recording() -> Response:
        """Record from the next trial on. Opens a session directory if configured."""
        async with service.publishing():
            service.start_recording()
        return answer(state_message())

    @router.post("/session/recording/pause", tags=["session"])
    async def pause_recording() -> Response:
        """Keep running, stop recording. A pausing trial runs but scores nothing."""
        async with service.publishing():
            service.pause_recording()
        return answer(state_message())

    @router.post("/session/recording/resume", tags=["session"])
    async def resume_recording() -> Response:
        async with service.publishing():
            service.resume_recording()
        return answer(state_message())

    @router.post("/session/recording/stop", tags=["session"])
    async def stop_recording() -> Response:
        """Close the record. The session keeps running."""
        async with service.publishing():
            service.stop_recording()
        return answer(state_message())

    # -- the trial loop ---------------------------------------------------------

    @router.post("/trial/next", tags=["trial"])
    async def next_trial() -> Response:
        """Select the next trial type and publish it.

        Everything about the trial is latched here, ``recording`` included.
        Refused while a trial is already in flight - report or cancel it first,
        which is what stops one result being attributed to another trial.
        """
        async with service.publishing():
            return answer(convert.trial_spec_to_wire(service.next_trial()))

    @router.post("/trial/outcome", tags=["trial"])
    async def report_outcome(request: Request) -> Response:
        """Report how the trial in flight ended. The primary inbound message.

        The reply says whether it was *accepted* as well as counted, and why
        not when it was not.
        """
        message = await body(request, trial_pb2.OutcomeReport)
        if not message.HasField("trial_id"):
            raise ServiceError(
                "trial_id says which trial this is the outcome of, and is required: "
                "a report that arrives late or twice must be refusable rather than "
                "attributed to the trial after the one it belongs to",
                kind="request",
                status=422,
            )
        async with service.publishing():
            record = service.report_outcome(
                convert.outcome_report_from_wire(message), trial_id=message.trial_id
            )
        return answer(convert.trial_record_to_wire(record))

    @router.post("/trial/cancel", tags=["trial"])
    async def cancel_trial(request: Request) -> Response:
        """End the trial in flight as CANCELLED.

        Recorded rather than dropped, so a gap in the trial numbering never has
        to be explained afterwards.
        """
        message = await body(request, trial_pb2.CancelTrial)
        async with service.publishing():
            return answer(convert.trial_record_to_wire(service.cancel_trial(message.reason)))

    # -- sets -------------------------------------------------------------------

    def sets_answer() -> Response:
        snapshot = service.sets()
        return answer(
            convert.sets_to_wire(
                snapshot.sets, active=snapshot.active, chain_problem=snapshot.chain_problem
            )
        )

    @router.get("/sets", tags=["sets"])
    async def get_sets() -> Response:
        """Every set, plus whether the switch chain from the active one holds up."""
        return sets_answer()

    @router.put("/sets/{name}", tags=["sets"])
    async def put_set(name: str, request: Request) -> Response:
        """Add or replace a set, with its trial types and its switch rule."""
        message = await body(request, sets_pb2.TrialTypeSet)
        if message.name != name:
            raise ServiceError(
                f"the path says {name!r} and the body says {message.name!r}; "
                f"renaming a set is a delete and a put",
                kind="sets",
                status=400,
            )
        async with service.publishing():
            service.put_set(convert.trial_type_set_from_wire(message))
        return sets_answer()

    @router.delete("/sets/{name}", tags=["sets"])
    async def delete_set(name: str) -> Response:
        async with service.publishing():
            service.delete_set(name)
        return sets_answer()

    @router.post("/sets/{name}/load", tags=["sets"])
    async def load_set(name: str) -> Response:
        """Make `name` active. Its block starts from nothing; counters are banked."""
        async with service.publishing():
            service.load_set(name)
        return answer(state_message())

    # -- config -----------------------------------------------------------------

    @router.get("/config", tags=["config"])
    async def get_config() -> Response:
        return answer(convert.session_config_to_wire(service.config))

    @router.patch("/config", tags=["config"])
    async def patch_config(request: Request) -> Response:
        """Change part of the config, and hear what the change cost.

        The accept flags and the stop rules take effect on the next trial. The
        ordering, the round count and avoid-repeat rebuild the bag, which
        restarts the round. The rest is refused while a session runs.
        """
        message = await body(request, config_pb2.ConfigPatch)
        try:
            changes = convert.config_patch_from_wire(message)
        except convert.config.Refused as exc:
            raise ServiceError(str(exc), kind="config", status=400) from exc
        async with service.publishing():
            return answer(convert.config_update_to_wire(service.update_config(changes)))

    @router.post("/config/reset-rounds", tags=["config"])
    async def reset_rounds() -> Response:
        """Refill the bag and clear the round and set-progress counters."""
        async with service.publishing():
            service.reset_rounds()
        return answer(state_message())

    @router.post("/config/reset-counters", tags=["config"])
    async def reset_counters() -> Response:
        """Clear every outcome tally, in every set. The bag and round are left alone."""
        async with service.publishing():
            service.reset_counters()
        return answer(state_message())

    # -- policy -----------------------------------------------------------------

    @router.get("/policy", tags=["policy"])
    async def get_policy(source: bool = False) -> Response:
        """The running policy, its content hash, and its last snapshot()."""
        return answer(convert.policy_info_to_wire(service.policy_info(with_source=source)))

    @router.post("/policy/check", tags=["policy"])
    async def check_policy(request: Request) -> Response:
        """Import and smoke-run source text without touching the session.

        Diagnostics carry line numbers so an editor can mark the offending line.
        """
        message = await body(request, policy_pb2.PolicySource)
        return answer(
            convert.policy_check_to_wire(service.check_policy(message.name, message.source))
        )

    @router.put("/policy", tags=["policy"])
    async def load_policy(request: Request) -> Response:
        """Store source text and run it from the next arm onwards.

        Checked first, always: a syntax error must never reach a session.
        """
        message = await body(request, policy_pb2.PolicySource)
        async with service.publishing():
            info = service.load_policy_source(message.name, message.source)
        return answer(convert.policy_info_to_wire(info))

    @router.delete("/policy", tags=["policy"])
    async def clear_policy() -> Response:
        """Go back to the declarative behaviour."""
        async with service.publishing():
            return answer(convert.policy_info_to_wire(service.clear_policy()))

    # -- events -----------------------------------------------------------------

    @router.post("/events/note", tags=["events"])
    async def note(request: Request) -> Response:
        """Append an experimenter's note to the session's event stream."""
        message = await body(request, session_pb2.NoteRequest)
        service.note(message.text)
        return answer(common_pb2.Ok(ok=True))

    # -- debug ------------------------------------------------------------------

    @router.get("/debug/sim", tags=["debug"])
    async def get_sim() -> Response:
        return answer(convert.sim_settings_to_wire(service.sim))

    @router.put("/debug/sim", tags=["debug"])
    async def put_sim(request: Request) -> Response:
        """Retune the simulated subject. The RNG keeps its place."""
        message = await body(request, debug_pb2.SimSettings)
        async with service.publishing():
            service.set_sim(convert.sim_settings_from_wire(message, SimSettings))
        return answer(convert.sim_settings_to_wire(service.sim))

    @router.post("/debug/step", tags=["debug"])
    async def step(request: Request) -> Response:
        """Run whole simulated trials through the real loop, and return the state."""
        message = await body(request, debug_pb2.StepRequest)
        async with service.publishing():
            ran = service.step(message.trials)
        result = debug_pb2.StepResult(
            trials=ran,
            stopped=not service.session.running,
            state=state_message(),
        )
        if service.session.stop_reason is not None:
            result.stop_reason = service.session.stop_reason
        return answer(result)

    @router.get("/debug/free-run", tags=["debug"])
    async def get_free_run() -> Response:
        return answer(convert.free_run_to_wire(service.free_run_status()))

    @router.put("/debug/free-run", tags=["debug"])
    async def put_free_run(request: Request) -> Response:
        """Step the simulator on a timer until it is stopped or the session ends."""
        message = await body(request, debug_pb2.FreeRun)
        status = await service.set_free_run(message.running, message.interval_ms)
        await service.publish()
        return answer(convert.free_run_to_wire(status))

    return router


def demo_experiment() -> tuple[TrialTypeStore, SessionConfig]:
    """The three-set training sequence ``triald sim`` runs.

    Shared with the CLI rather than written out twice, so the web UI and the
    simulator demonstrate the same experiment.
    """
    from triald.cli import demo_experiment as build

    return build()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
