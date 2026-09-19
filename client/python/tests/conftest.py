# SPDX-License-Identifier: AGPL-3.0-or-later
"""A daemon to talk to: a real one, on a port nobody else has.

These tests are worth having because they run the *daemon*, over a real gRPC
channel: the same servicers, the same refusals and the same stream a rig gets.
A mock of the daemon would only ever assert that this client agrees with a
second description of triald written by the same hand on the same day.

The daemon lives in `daemon/`, a sibling of this project, and is run with `uv`
so that it brings its own environment — this client's environment deliberately
does not have grpcio-the-server, uvicorn or the daemon itself in it. The whole
suite skips when that is not possible, so a checkout of just the client still
runs the seam tests.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import pytest
from triald_client import DaemonIsUnavailable, TrialdClient

#: `daemon/`, three levels up from this file.
DAEMON_PROJECT = Path(__file__).resolve().parents[3] / "daemon"


def a_free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def rig():
    """A running triald, and a client pointed at it.

    `--results-dir` goes into a temporary directory so that the recording tests
    write somewhere harmless — and so that a test run never leaves a session
    directory in the repository.
    """
    if shutil.which("uv") is None:
        pytest.skip("no uv on PATH, so the daemon cannot be started")
    if not (DAEMON_PROJECT / "pyproject.toml").exists():
        pytest.skip(f"no daemon project at {DAEMON_PROJECT}")

    # `--port` is the *web* port; gRPC is one above it, which is the rule
    # `grpc_port_for` states in the daemon and `DEFAULT_PORT` states here.
    # Asking for an even free port and using both is the honest way to say so.
    port = a_free_port()
    with tempfile.TemporaryDirectory() as scratch:
        daemon = subprocess.Popen(
            [
                "uv",
                "run",
                "--directory",
                str(DAEMON_PROJECT),
                "--extra",
                "serve",
                "triald",
                "serve",
                "--port",
                str(port),
                "--results-dir",
                str(Path(scratch) / "sessions"),
                "--policy-dir",
                str(Path(scratch) / "policies"),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client = TrialdClient(f"127.0.0.1:{port + 1}")
        try:
            client.wait_until_ready(timeout_s=30)
        except DaemonIsUnavailable:
            daemon.terminate()
            pytest.skip("the daemon did not come up; is its environment synced?")
        try:
            yield client
        finally:
            client.close()
            daemon.terminate()
            daemon.wait(timeout=10)


@pytest.fixture
def idle(rig):
    """A stopped session before the test, and a stopped one after it.

    Every test here shares one daemon, because starting one costs a second and
    a suite that started thirty would be a suite nobody runs. Sharing is only
    safe if each test hands the session back the way it found it.
    """
    rig.stop("between tests")
    yield rig
    rig.stop("between tests")


@pytest.fixture
def running(idle):
    """An armed session, stopped again afterwards."""
    idle.arm()
    return idle
