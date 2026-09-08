# SPDX-License-Identifier: AGPL-3.0-or-later
"""The box, as opposed to the experiment.

Two different things have been called "config" here, and the systemd unit ran
into the difference: it passed
``--config /etc/braemons/triald-rig-config.toml`` to a flag that wants a
*session* config JSON -- the trial types, the switch rules, the seed. Those are
an experiment. What an installed daemon needs first is the box: where to bind,
where the results go, where uploaded policies are kept. Nobody edits a rig's
bind address between blocks, and nobody edits trial types by logging into a Pi.

So the two stay apart, and this is the second one. Same shape and the same path
convention as ``/etc/braemons/statemachined-rig-config.toml`` and vstimd's --
one directory of settings per rig, which is what makes a rig one thing to back
up.

**tomllib and nothing else.** ``triald``'s core declares ``dependencies = []``
on purpose: the domain logic, the simulator and the policy API import with
nothing installed. A pydantic model here would quietly end that, for a file with
six keys in it. The checking below is by hand and says what it refused.

Everything is optional, including the file. A daemon started with no rig config
at all runs on the defaults below, which is what `triald serve` on a laptop has
always done.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: Where a package puts it, and what the systemd unit names. The braemons
#: convention rather than triald's own: every daemon's conffile is
#: ``/etc/braemons/<daemon>-rig-config.toml``.
DEFAULT_CONFIGURATION_PATH = Path("/etc/braemons/triald-rig-config.toml")

#: Localhost, never 0.0.0.0, and the same reasoning as the ``--host`` flag's: a
#: policy is Python running in the daemon's process, so the API is remote code
#: execution by design. Exposing it is a thing somebody types, not a thing they
#: discover.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420


class RigConfigurationError(Exception):
    """The file was found and is not usable. Named field, named reason."""


@dataclass
class RigConfiguration:
    """One box's settings. Read at startup, never written by the daemon."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    #: Session records go here. ``None`` means nothing is written to disk, which
    #: is the right default for a laptop and the wrong one for a rig -- so the
    #: packaged conffile sets it and `triald serve` says so when it is unset.
    results_directory: Path | None = None

    #: Where policies uploaded through the API are stored.
    policy_directory: Path | None = None

    #: A session config JSON to load at startup, and a policy to load with it.
    #: Both optional: an empty daemon is a daemon waiting to be told what the
    #: experiment is, which is how a rig comes up after a reboot.
    session_config: Path | None = None
    policy: Path | None = None

    #: Where this file came from, for the log line and for error messages. Not
    #: read from the file itself.
    source: Path | None = field(default=None, compare=False)

    @classmethod
    def load_from_toml_file(cls, path: Path) -> RigConfiguration:
        """The file at `path`, or the defaults if there is no file there.

        A missing file is not an error: the daemon runs on a laptop as well as
        on a rig, and the package's conffile is the only reason one exists. A
        file that is *there* and unreadable is an error -- the alternative is a
        daemon that silently ignores what somebody wrote and binds somewhere
        else.
        """
        if not path.exists():
            return cls(source=None)

        try:
            with path.open("rb") as handle:
                document = tomllib.load(handle)
        except OSError as exc:
            raise RigConfigurationError(f"{path}: cannot be read: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise RigConfigurationError(f"{path}: is not valid TOML: {exc}") from exc

        return cls._from_document(document, source=path)

    @classmethod
    def _from_document(cls, document: dict, source: Path | None) -> RigConfiguration:
        known = {
            "host",
            "port",
            "results_directory",
            "policy_directory",
            "session_config",
            "policy",
        }
        # Named rather than ignored. A typo'd key in a conffile is somebody's
        # setting not taking effect, and finding that out from behaviour is
        # worse than finding it out from a refusal.
        unknown = sorted(set(document) - known)
        if unknown:
            raise RigConfigurationError(
                f"{source}: unknown setting(s) {', '.join(unknown)}. "
                f"Known: {', '.join(sorted(known))}"
            )

        def a_string(key: str, default: str) -> str:
            value = document.get(key, default)
            if not isinstance(value, str):
                raise RigConfigurationError(f"{source}: {key} must be a string, not {value!r}")
            return value

        def a_port(key: str, default: int) -> int:
            value = document.get(key, default)
            # `True` is an int in Python and is not a port.
            if not isinstance(value, int) or isinstance(value, bool):
                raise RigConfigurationError(f"{source}: {key} must be a number, not {value!r}")
            if not 1 <= value <= 65535:
                raise RigConfigurationError(f"{source}: {key} is not a port: {value}")
            return value

        def a_path(key: str) -> Path | None:
            value = document.get(key)
            if value is None or value == "":
                return None
            if not isinstance(value, str):
                raise RigConfigurationError(f"{source}: {key} must be a path, not {value!r}")
            return Path(value)

        return cls(
            host=a_string("host", DEFAULT_HOST),
            port=a_port("port", DEFAULT_PORT),
            results_directory=a_path("results_directory"),
            policy_directory=a_path("policy_directory"),
            session_config=a_path("session_config"),
            policy=a_path("policy"),
            source=source,
        )
