# SPDX-License-Identifier: AGPL-3.0-or-later
"""A synthetic subject, so a policy can be run over 500 trials in a second.

**Not a model of behaviour and not meant to be.** It exists so that logic can
be checked before anything is connected to a rig, and so the panels can be
driven with no hardware at all. It is the same loop: a step goes through
`triald.runner.run_trial`, exactly as a real session does.
"""

from __future__ import annotations

import grpc

from triald.api import convert
from triald.api.service import SessionService, SimSettings
from triald.api.servicers import state_message
from triald.api.servicers.refusals import answering
from triald.v1 import (  # ty: ignore[unresolved-import]  (resolved at runtime by __init__'s __path__)
    debug_pb2,
    service_pb2_grpc,
)


class DebugServicer(service_pb2_grpc.DebugServicer):
    def __init__(self, service: SessionService) -> None:
        self.service = service

    async def ReadSim(self, request, context) -> debug_pb2.SimSettings:
        return convert.sim_settings_to_wire(self.service.sim)

    async def WriteSim(self, request, context) -> debug_pb2.SimSettings:
        """Retune the simulated subject. The RNG keeps its place."""

        async def run():
            async with self.service.publishing():
                self.service.set_sim(convert.sim_settings_from_wire(request, SimSettings))
            return convert.sim_settings_to_wire(self.service.sim)

        return await answering(context, run)

    async def Step(self, request, context) -> debug_pb2.StepResult:
        """Run whole simulated trials through the real loop, and answer with the state."""

        async def run():
            async with self.service.publishing():
                ran = self.service.step(request.trials)
            result = debug_pb2.StepResult(
                trials=ran,
                # What was asked for and what happened are different numbers:
                # a session that hit its stop rule on trial three of fifty ran
                # three, and says so rather than reporting fifty.
                stopped=not self.service.session.running,
                state=state_message(self.service),
            )
            if self.service.session.stop_reason is not None:
                result.stop_reason = self.service.session.stop_reason
            return result

        return await answering(context, run)

    async def ReadFreeRun(self, request, context) -> debug_pb2.FreeRunStatus:
        return convert.free_run_to_wire(self.service.free_run_status())

    async def WriteFreeRun(self, request, context) -> debug_pb2.FreeRunStatus:
        """Step the simulator on a timer until it is stopped or the session ends."""

        async def run():
            status = await self.service.set_free_run(request.running, request.interval_ms)
            await self.service.publish()
            return convert.free_run_to_wire(status)

        return await answering(context, run)


def register(service: SessionService, server: grpc.aio.Server) -> None:
    service_pb2_grpc.add_DebugServicer_to_server(DebugServicer(service), server)
