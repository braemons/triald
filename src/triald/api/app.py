# SPDX-License-Identifier: AGPL-3.0-or-later
"""The routes, and the app that serves them.

Thin on purpose. A route parses its body into a model, calls one method on
:class:`~triald.api.service.SessionService`, and returns a model; everything
about *when* something may be done lives in the service, and everything about
*what shape* it has lives in :mod:`triald.api.schemas`. If a route grows a
decision in it, the decision is in the wrong place.

Two conventions run through all of it:

* **Every mutating call answers with the new state.** The WebSocket stream
  pushes it too, but a client that has just changed something should not have to
  wait for a frame to find out what it did - and a MATLAB script with no
  WebSocket at all should still be able to work purely from the replies.
* **A refusal is an :class:`~triald.api.schemas.ErrorModel` with a 4xx.** The
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

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from triald.api import schemas as sc
from triald.api.service import ServiceError, SessionService
from triald.session import SessionConfig
from triald.trialtypes import TrialTypeStore

log = logging.getLogger(__name__)

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"

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

    @app.exception_handler(ServiceError)
    async def _service_error(request: Request, exc: ServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content=sc.ErrorModel(error=exc.kind, detail=exc.detail).model_dump(),
        )

    app.include_router(_api(service))

    if WEB_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
    else:  # pragma: no cover - only if the package was built without the UI
        log.warning("no web UI at %s; serving the API only", WEB_ROOT)

    return app


def _api(service: SessionService) -> APIRouter:
    router = APIRouter(prefix="/api")

    async def state() -> sc.SessionStateModel:
        return service.state_model()

    # -- state ------------------------------------------------------------------

    @router.get("/state", response_model=sc.SessionStateModel, tags=["state"])
    async def get_state() -> sc.SessionStateModel:
        """The whole snapshot: counters, the active set, the config, the policy."""
        return await state()

    @router.websocket("/stream")
    async def stream(websocket: WebSocket) -> None:
        """Push a `StreamMessage` on every change, plus one on connect.

        Frames are coalesced rather than queued for a slow client: this is a
        state stream, so the newest snapshot is the only one worth having.
        """
        await websocket.accept()
        with service.subscribe() as queue:
            await websocket.send_json(
                sc.StreamMessage(sequence=0, at=_now(), state=service.state_model()).model_dump(
                    mode="json"
                )
            )
            try:
                while True:
                    message = await queue.get()
                    await websocket.send_json(message.model_dump(mode="json"))
            except WebSocketDisconnect:
                return

    # -- session lifecycle ------------------------------------------------------

    @router.post("/session/arm", response_model=sc.SessionStateModel, tags=["session"])
    async def arm() -> sc.SessionStateModel:
        """Validate everything and start a new session. Counters start at zero."""
        async with service.publishing():
            service.arm()
        return await state()

    @router.post("/session/stop", response_model=sc.SessionStateModel, tags=["session"])
    async def stop(reason: str = "stopped by the operator") -> sc.SessionStateModel:
        async with service.publishing():
            await service.set_free_run(False, 250)
            service.stop(reason)
        return await state()

    @router.post(
        "/session/recording/start", response_model=sc.SessionStateModel, tags=["session"]
    )
    async def start_recording() -> sc.SessionStateModel:
        """Record from the next trial on. Opens a session directory if configured."""
        async with service.publishing():
            service.start_recording()
        return await state()

    @router.post(
        "/session/recording/pause", response_model=sc.SessionStateModel, tags=["session"]
    )
    async def pause_recording() -> sc.SessionStateModel:
        """Keep running, stop recording. A pausing trial runs but scores nothing."""
        async with service.publishing():
            service.pause_recording()
        return await state()

    @router.post(
        "/session/recording/resume", response_model=sc.SessionStateModel, tags=["session"]
    )
    async def resume_recording() -> sc.SessionStateModel:
        async with service.publishing():
            service.resume_recording()
        return await state()

    @router.post(
        "/session/recording/stop", response_model=sc.SessionStateModel, tags=["session"]
    )
    async def stop_recording() -> sc.SessionStateModel:
        """Close the record. The session keeps running."""
        async with service.publishing():
            service.stop_recording()
        return await state()

    # -- the trial loop ---------------------------------------------------------

    @router.post("/trial/next", response_model=sc.TrialSpecModel, tags=["trial"])
    async def next_trial() -> sc.TrialSpecModel:
        """Select the next trial type and publish it.

        Everything about the trial is latched here, ``recording`` included.
        Refused while a trial is already in flight - report or cancel it first,
        which is what stops one result being attributed to another trial.
        """
        async with service.publishing():
            return service.next_trial()

    @router.post("/trial/outcome", response_model=sc.TrialRecordModel, tags=["trial"])
    async def report_outcome(report: sc.OutcomeReportModel) -> sc.TrialRecordModel:
        """Report how the trial in flight ended. The primary inbound message.

        The reply says whether it was *accepted* as well as counted, and why
        not when it was not.
        """
        async with service.publishing():
            return service.report_outcome(report)

    @router.post("/trial/cancel", response_model=sc.TrialRecordModel, tags=["trial"])
    async def cancel_trial(body: sc.CancelTrialModel) -> sc.TrialRecordModel:
        """End the trial in flight as CANCELLED.

        Recorded rather than dropped, so a gap in the trial numbering never has
        to be explained afterwards.
        """
        async with service.publishing():
            return service.cancel_trial(body.reason)

    # -- sets -------------------------------------------------------------------

    @router.get("/sets", response_model=sc.SetsModel, tags=["sets"])
    async def get_sets() -> sc.SetsModel:
        """Every set, plus whether the switch chain from the active one holds up."""
        return service.sets_model()

    @router.put("/sets/{name}", response_model=sc.SetsModel, tags=["sets"])
    async def put_set(name: str, body: sc.TrialTypeSetModel) -> sc.SetsModel:
        """Add or replace a set, with its trial types and its switch rule."""
        if body.name != name:
            raise ServiceError(
                f"the path says {name!r} and the body says {body.name!r}; "
                f"renaming a set is a delete and a put",
                kind="sets",
                status=400,
            )
        async with service.publishing():
            return service.put_set(body)

    @router.delete("/sets/{name}", response_model=sc.SetsModel, tags=["sets"])
    async def delete_set(name: str) -> sc.SetsModel:
        async with service.publishing():
            return service.delete_set(name)

    @router.post("/sets/{name}/load", response_model=sc.SessionStateModel, tags=["sets"])
    async def load_set(name: str) -> sc.SessionStateModel:
        """Make `name` active. Its block starts from nothing; counters are banked."""
        async with service.publishing():
            service.load_set(name)
        return await state()

    # -- config -----------------------------------------------------------------

    @router.get("/config", response_model=sc.SessionConfigModel, tags=["config"])
    async def get_config() -> sc.SessionConfigModel:
        return sc.SessionConfigModel.of(service.config)

    @router.patch("/config", response_model=sc.ConfigUpdateResult, tags=["config"])
    async def patch_config(patch: sc.ConfigPatch) -> sc.ConfigUpdateResult:
        """Change part of the config, and hear what the change cost.

        The accept flags and the stop rules take effect on the next trial. The
        ordering, the round count and avoid-repeat rebuild the bag, which
        restarts the round. The rest is refused while a session runs.
        """
        async with service.publishing():
            return service.update_config(patch)

    @router.post("/config/reset-rounds", response_model=sc.SessionStateModel, tags=["config"])
    async def reset_rounds() -> sc.SessionStateModel:
        """Refill the bag and clear the round and set-progress counters."""
        async with service.publishing():
            service.reset_rounds()
        return await state()

    @router.post("/config/reset-counters", response_model=sc.SessionStateModel, tags=["config"])
    async def reset_counters() -> sc.SessionStateModel:
        """Clear every outcome tally, in every set. The bag and round are left alone."""
        async with service.publishing():
            service.reset_counters()
        return await state()

    # -- policy -----------------------------------------------------------------

    @router.get("/policy", response_model=sc.PolicyInfoModel, tags=["policy"])
    async def get_policy(source: bool = False) -> sc.PolicyInfoModel:
        """The running policy, its content hash, and its last snapshot()."""
        return service.policy_info(with_source=source)

    @router.post("/policy/check", response_model=sc.PolicyCheckResult, tags=["policy"])
    async def check_policy(body: sc.PolicySourceModel) -> sc.PolicyCheckResult:
        """Import and smoke-run source text without touching the session.

        Diagnostics carry line numbers so an editor can mark the offending line.
        """
        return service.check_policy(body.name, body.source)

    @router.put("/policy", response_model=sc.PolicyInfoModel, tags=["policy"])
    async def load_policy(body: sc.PolicySourceModel) -> sc.PolicyInfoModel:
        """Store source text and run it from the next arm onwards.

        Checked first, always: a syntax error must never reach a session.
        """
        async with service.publishing():
            return service.load_policy_source(body.name, body.source)

    @router.delete("/policy", response_model=sc.PolicyInfoModel, tags=["policy"])
    async def clear_policy() -> sc.PolicyInfoModel:
        """Go back to the declarative behaviour."""
        async with service.publishing():
            return service.clear_policy()

    # -- events -----------------------------------------------------------------

    @router.post("/events/note", response_model=sc.OkModel, tags=["events"])
    async def note(body: sc.NoteModel) -> sc.OkModel:
        """Append an experimenter's note to the session's event stream."""
        service.note(body.text)
        return sc.OkModel()

    # -- debug ------------------------------------------------------------------

    @router.get("/debug/sim", response_model=sc.SimSettingsModel, tags=["debug"])
    async def get_sim() -> sc.SimSettingsModel:
        return service.sim

    @router.put("/debug/sim", response_model=sc.SimSettingsModel, tags=["debug"])
    async def put_sim(body: sc.SimSettingsModel) -> sc.SimSettingsModel:
        """Retune the simulated subject. The RNG keeps its place."""
        async with service.publishing():
            service.set_sim(body)
        return service.sim

    @router.post("/debug/step", response_model=sc.StepResult, tags=["debug"])
    async def step(body: sc.StepRequest) -> sc.StepResult:
        """Run whole simulated trials through the real loop, and return the state."""
        async with service.publishing():
            ran = service.step(body.trials)
        return sc.StepResult(
            trials=ran,
            stopped=not service.session.running,
            stop_reason=service.session.stop_reason,
            state=await state(),
        )

    @router.get("/debug/free-run", response_model=sc.FreeRunStatus, tags=["debug"])
    async def get_free_run() -> sc.FreeRunStatus:
        return service.free_run_status()

    @router.put("/debug/free-run", response_model=sc.FreeRunStatus, tags=["debug"])
    async def put_free_run(body: sc.FreeRunModel) -> sc.FreeRunStatus:
        """Step the simulator on a timer until it is stopped or the session ends."""
        status = await service.set_free_run(body.running, body.interval_ms)
        await service.publish()
        return status

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
