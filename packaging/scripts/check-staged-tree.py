# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tree that is about to be packaged, run.

Every other test in this repository runs the daemon out of a checkout with uv
building the environment. This is the only thing that runs *the interpreter that
is about to be shipped*, with the dependencies that are about to be shipped, and
it is where the failures peculiar to packaging show up: a `uvicorn[standard]`
extra that resolved differently, a web asset that never made it into the wheel,
a launcher whose shebang names the build machine, a systemd unit that passes a
flag the CLI does not have.

Run by packaging/Makefile's `check`, which every package target depends on --
finding this out on a Pi is finding it out too late.
"""

from __future__ import annotations

import shlex
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

#: The unit as it will be installed, read rather than restated. Its ExecStart is
#: the one command line nobody runs during development and everybody runs on a
#: rig, which is exactly how it came to name `--config` for a file that is a
#: rig config -- a flag that wants a session config JSON. Nothing caught that,
#: because nothing was packaged.
UNIT = Path(__file__).resolve().parents[1] / "systemd" / "triald.service"


def main() -> int:
    import triald

    print(f"  python  {sys.version.split()[0]}")
    print(f"  triald  {getattr(triald, '__version__', 'unversioned')}")

    # Every runtime dependency, imported rather than assumed.
    import google.protobuf
    import grpc
    import httpx  # noqa: F401
    import uvicorn

    print(
        f"  grpcio {grpc.__version__}, protobuf {google.protobuf.__version__}, "
        f"uvicorn {uvicorn.__version__}"
    )

    # In the package and deliberately not in `dependencies` -- see RIG_EXTRAS in
    # packaging/Makefile. Without numpy, "scriptable in Python" is a hollow
    # promise, and a policy that will not load is discovered at 2 a.m.
    import numpy
    import scipy

    print(f"  numpy {numpy.__version__}, scipy {scipy.__version__}")

    # The core imports with nothing installed, which is the property that makes
    # `dependencies = []` worth defending. Checked here because the staged tree
    # is the one place where "installed" and "not installed" are both real.
    from triald.rig_configuration import RigConfiguration
    from triald.session import Session  # noqa: F401

    the_application_the_unit_would_build()
    the_command_line_the_unit_runs(RigConfiguration)
    return 0


def the_application_the_unit_would_build() -> None:
    """The daemon, built the way `triald serve` builds it, pointed somewhere safe.

    Temporary directories because this runs as whoever is packaging, and
    /var/lib/braemons is the daemon user's.
    """
    from triald.api import SessionService
    from triald.api.grpc_server import build_servicers
    from triald.api.web_edge import rpcs_of
    from triald.cli import demo_experiment

    with tempfile.TemporaryDirectory() as scratch:
        here = Path(scratch)
        store, config = demo_experiment()
        service = SessionService(
            store,
            config,
            policy_dir=here / "policies",
            results_dir=here / "sessions",
        )
        # The dispatch table rather than a list of routes: it is built from the
        # descriptor in the wheel, so this asks whether the *packaged* proto
        # and the *packaged* servicers still agree — which is the thing that
        # goes wrong when a build misses a file.
        addresses = set(rpcs_of(build_servicers(service)))
        expected = (
            "/triald.v1.Session/Arm",
            "/triald.v1.Trial/Next",
            "/triald.v1.Trial/ReportOutcome",
            "/triald.v1.State/ReadState",
        )
        for address in expected:
            assert address in addresses, f"{address} is not served: {sorted(addresses)}"
        print(f"  {len(addresses)} rpcs, including the ones the panels call")

    # Package data, which has gone missing from a wheel before and is invisible
    # until a browser asks for it.
    web = files("triald") / "web"
    for asset in ("index.html", "application_shell.js", "triald_user_interface.css"):
        assert (web / asset).is_file(), f"{asset} is not in the package"
    print("  the web UI: shell, script and stylesheet")


def the_command_line_the_unit_runs(rig_configuration_class: type) -> None:
    """Parse the unit's own ExecStart, with the conffile that ships beside it.

    Two things this catches and nothing else does: a flag the unit passes that
    the CLI does not have -- which is how the unit shipped naming `--config` for
    a rig config -- and a conffile the parser refuses, since the rig config
    names unknown keys rather than ignoring them.
    """
    from triald.cli import _build_parser

    execstart = ""
    for line in UNIT.read_text().splitlines():
        if line.startswith("ExecStart="):
            execstart = line[len("ExecStart=") :]
    assert execstart, f"{UNIT} has no ExecStart"

    program, *arguments = shlex.split(execstart)
    assert program.endswith("/bin/triald"), f"ExecStart does not run the launcher: {program}"

    # SystemExit rather than an assertion: argparse's own refusal is the answer,
    # and its message names the flag.
    parsed = _build_parser().parse_args(arguments)
    assert parsed.command == "serve", f"the unit runs `{parsed.command}`, not `serve`"

    conffile = Path(__file__).resolve().parents[1] / "etc" / "triald-rig-config.toml"
    assert parsed.rig_config == Path("/etc/braemons/triald-rig-config.toml"), (
        f"the unit's --rig-config is {parsed.rig_config}, which is not where the "
        f"package installs {conffile.name}"
    )
    rig = rig_configuration_class.load_from_toml_file(conffile)
    print(f"  the unit's command line parses; its conffile binds {rig.host}:{rig.port}")


if __name__ == "__main__":
    sys.exit(main())
