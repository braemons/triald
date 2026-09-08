# SPDX-License-Identifier: AGPL-3.0-or-later
"""The box's settings: what is read, and what is refused.

The reason this file exists is a bug it would have caught. The packaged systemd
unit passed ``--config /etc/braemons/triald-rig-config.toml`` -- a rig config
handed to the flag that takes a *session* config JSON -- so the unit as shipped
could not have started the daemon. Nothing tested the packaged unit, because
nothing was packaged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from triald.rig_configuration import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    RigConfiguration,
    RigConfigurationError,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "triald-rig-config.toml"
    path.write_text(text)
    return path


def test_a_laptop_with_no_rig_config_gets_the_defaults(tmp_path):
    """A missing file is not an error. It is most machines."""
    rig = RigConfiguration.load_from_toml_file(tmp_path / "nothing-here.toml")

    assert rig.host == DEFAULT_HOST
    assert rig.port == DEFAULT_PORT
    assert rig.results_directory is None
    # None rather than the path asked for: `source` is where the settings came
    # from, and they came from nowhere.
    assert rig.source is None


def test_the_defaults_bind_to_localhost_and_not_to_everything():
    """A policy is Python in the daemon's process, so the API is remote code
    execution by design. The default must never be 0.0.0.0."""
    assert RigConfiguration().host == "127.0.0.1"


def test_what_the_packaged_conffile_says_is_what_the_daemon_gets(tmp_path):
    path = write(
        tmp_path,
        """
        host = "0.0.0.0"
        port = 8421
        results_directory = "/var/lib/braemons/triald/sessions"
        policy_directory = "/var/lib/braemons/triald/policies"
        """,
    )

    rig = RigConfiguration.load_from_toml_file(path)

    assert rig.host == "0.0.0.0"
    assert rig.port == 8421
    assert rig.results_directory == Path("/var/lib/braemons/triald/sessions")
    assert rig.policy_directory == Path("/var/lib/braemons/triald/policies")
    assert rig.source == path


def test_an_empty_file_is_the_defaults_but_remembers_where_it_came_from(tmp_path):
    """The distinction matters to `serve`, which prints the source: a rig whose
    config is empty and a rig with no config are different situations."""
    path = write(tmp_path, "")

    rig = RigConfiguration.load_from_toml_file(path)

    assert rig.host == DEFAULT_HOST
    assert rig.source == path


def test_an_empty_string_path_means_unset_rather_than_the_current_directory(tmp_path):
    """`results_directory = ""` is how somebody comments a setting out without
    deleting it. Path("") is Path("."), which would silently write session
    records into whatever directory the daemon started in."""
    rig = RigConfiguration.load_from_toml_file(write(tmp_path, 'results_directory = ""'))

    assert rig.results_directory is None


def test_a_typo_is_named_rather_than_ignored(tmp_path):
    path = write(tmp_path, 'reslts_directory = "/var/lib/braemons/triald"')

    with pytest.raises(RigConfigurationError) as refusal:
        RigConfiguration.load_from_toml_file(path)

    assert "reslts_directory" in str(refusal.value)
    # And says what it would have accepted, since the whole failure mode is
    # somebody's setting quietly not taking effect.
    assert "results_directory" in str(refusal.value)


def test_a_file_that_is_not_toml_is_refused_by_name(tmp_path):
    path = write(tmp_path, "host: 127.0.0.1\n")

    with pytest.raises(RigConfigurationError) as refusal:
        RigConfiguration.load_from_toml_file(path)

    assert str(path) in str(refusal.value)


def test_a_port_that_is_not_a_port_is_refused(tmp_path):
    with pytest.raises(RigConfigurationError):
        RigConfiguration.load_from_toml_file(write(tmp_path, "port = 70000"))

    with pytest.raises(RigConfigurationError):
        RigConfiguration.load_from_toml_file(write(tmp_path, 'port = "8420"'))


def test_a_boolean_is_not_a_port_even_though_python_says_it_is_an_int(tmp_path):
    """`True == 1` in Python, and 1 is a valid port. `port = true` is not."""
    with pytest.raises(RigConfigurationError):
        RigConfiguration.load_from_toml_file(write(tmp_path, "port = true"))


def test_the_host_must_be_a_string(tmp_path):
    with pytest.raises(RigConfigurationError):
        RigConfiguration.load_from_toml_file(write(tmp_path, "host = 127"))


def test_reading_it_needs_nothing_installed():
    """The core declares `dependencies = []` and this is part of the core.

    Not a style point: it is why `triald.stimulus`, the policy API and the
    simulator can be imported on a machine with nothing on it. A pydantic model
    here for a file with six keys would end that quietly.
    """
    import triald.rig_configuration as module

    # Read rather than mocked: a mock would only prove the mock works. tomllib,
    # dataclasses and pathlib are stdlib and are the whole import list.
    source = Path(module.__file__).read_text()
    for third_party in ("pydantic", "fastapi", "httpx", "yaml", "tomlkit"):
        assert f"import {third_party}" not in source, f"{third_party} is not free here"
