# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting and stopping, and what gets written to disk.

**Arming and recording are two switches, deliberately.** A session can run
without recording — that is what a warm-up is — and recording can be paused
mid-session without losing where the round had got to.
"""

from __future__ import annotations

import grpc

from triald.api.service import SessionService
from triald.api.servicers import state_message
from triald.api.servicers.refusals import answering
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    service_pb2_grpc,
    session_pb2,
)

#: What `Stop` records when the caller gives no reason. Kept out of the proto:
#: an empty `reason` means "not said", and the daemon says what that means.
DEFAULT_STOP_REASON = "stopped by the operator"


class SessionServicer(service_pb2_grpc.SessionServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def Arm(self, request, context) -> session_pb2.SessionState:
        """Validate everything and start a new session. Counters start at zero."""

        async def run():
            async with self.service.publishing():
                self.service.arm()
            return state_message(self.service)

        return await answering(context, run)

    async def Stop(self, request, context) -> session_pb2.SessionState:
        """End the session. The reason is recorded and shown."""

        async def run():
            async with self.service.publishing():
                # Free-run first: a simulator still stepping into a stopped
                # session would keep the rig moving after it was told to stop.
                await self.service.set_free_run(False, 250)
                self.service.stop(request.reason or DEFAULT_STOP_REASON)
            return state_message(self.service)

        return await answering(context, run)

    async def StartRecording(self, request, context) -> session_pb2.SessionState:
        """Record from the next trial on. Opens a session directory if configured."""
        return await self._switch(context, self.service.start_recording)

    async def PauseRecording(self, request, context) -> session_pb2.SessionState:
        """Keep running, stop recording. A pausing trial runs but scores nothing."""
        return await self._switch(context, self.service.pause_recording)

    async def ResumeRecording(self, request, context) -> session_pb2.SessionState:
        return await self._switch(context, self.service.resume_recording)

    async def StopRecording(self, request, context) -> session_pb2.SessionState:
        """Close the record. The session keeps running."""
        return await self._switch(context, self.service.stop_recording)

    async def _switch(self, context, flip) -> session_pb2.SessionState:
        """The four recording switches: flip one, publish, answer with the state."""

        async def run():
            async with self.service.publishing():
                flip()
            return state_message(self.service)

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_SessionServicer_to_server(SessionServicer(service), server)
