# SPDX-License-Identifier: AGPL-3.0-or-later
"""`trialctl` keeps the family's rules for a `<name>ctl`.

`contracts/DAEMON_LAYOUT.md` lists them. These are the ones that need no
daemon: which rig, the version, and how a failure reads to a script.
"""

from __future__ import annotations

import json
import socket

import pytest
from triald_client import ConfigPatch
from triald_client.command_line_interface import ExitStatus, build_parser, main


def a_port_nobody_listens_on() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_the_rig_is_the_flag_then_the_environment_then_localhost(monkeypatch):
    monkeypatch.delenv("BRAEMONS_RIG", raising=False)
    assert build_parser().parse_args(["state"]).rig == "localhost"
    monkeypatch.setenv("BRAEMONS_RIG", "rig-a.local")
    assert build_parser().parse_args(["state"]).rig == "rig-a.local"
    assert build_parser().parse_args(["--rig", "rig-b", "state"]).rig == "rig-b"


def test_the_version_is_the_commands_own(capsys):
    with pytest.raises(SystemExit) as exit:
        main(["--version"])
    assert exit.value.code == 0
    assert capsys.readouterr().out.startswith("trialctl ")


def test_nothing_answering_is_unavailable_as_json_on_stderr(capsys):
    port = a_port_nobody_listens_on()
    status = main(["--rig", f"127.0.0.1:{port}", "--timeout", "0.2", "state"])
    assert status == ExitStatus.UNAVAILABLE == 3
    failure = json.loads(capsys.readouterr().err)
    assert failure["error"] == "unavailable"
    assert failure["detail"]


def test_a_command_missing_its_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as exit:
        main(["sets", "load"])
    assert exit.value.code == ExitStatus.USAGE == 2


# -- against a daemon ------------------------------------------------------------
#
# Every rpc the client has is reachable from here; these run the ones that take
# structured input, because that is where a CLI can get a type wrong.


def trialctl(rig, capsys, *arguments: str):
    status = main(["--rig", rig.address, *arguments])
    captured = capsys.readouterr()
    return status, json.loads(captured.out) if captured.out else None, captured.err


def test_a_trial_is_run_by_hand_next_then_report(running, capsys):
    status, spec, _ = trialctl(running, capsys, "trial", "next")
    assert status == ExitStatus.OK
    status, record, _ = trialctl(
        running, capsys, "trial", "report", str(spec["trial_number"]), "hit",
        "reaction_time_ms=412", "note=by hand",
    )  # fmt: skip
    assert status == ExitStatus.OK
    assert record["outcome"]["code"] == 1
    assert record["outcome"]["reaction_time_ms"] == 412


def test_a_trial_in_flight_can_be_cancelled(running, capsys):
    trialctl(running, capsys, "trial", "next")
    status, record, _ = trialctl(running, capsys, "trial", "cancel", "testing")
    assert status == ExitStatus.OK
    assert record["outcome"]["code"] == 10  # CANCELLED, as its .tdr code


def test_an_outcome_that_is_not_one_is_a_usage_error(running, capsys):
    status, _, err = trialctl(running, capsys, "trial", "report", "1", "brilliant")
    assert status == ExitStatus.USAGE
    assert "TrialOutcome" in json.loads(err)["detail"]


def test_a_set_printed_by_sets_get_can_be_put_back_under_another_name(idle, capsys, tmp_path):
    active = next(one["name"] for one in trialctl(idle, capsys, "sets", "list")[1]["sets"])
    _, written, _ = trialctl(idle, capsys, "sets", "get", active)
    (tmp_path / "copy.json").write_text(json.dumps(written))
    status, sets, err = trialctl(
        idle, capsys, "sets", "put", str(tmp_path / "copy.json"), "--name", "from_trialctl"
    )
    assert status == ExitStatus.OK, err
    assert "from_trialctl" in {one["name"] for one in sets["sets"]}
    idle.delete_set("from_trialctl")


def test_the_session_config_is_patched_by_name(idle, capsys):
    was = idle.read_config().rounds
    status, result, _ = trialctl(idle, capsys, "session-config", "set", f"rounds={was + 1}")
    assert status == ExitStatus.OK
    assert result["changed"] == ["rounds"]
    idle.update_config(ConfigPatch(rounds=was))


def test_a_misspelt_setting_is_refused_rather_than_ignored(idle, capsys):
    status, _, err = trialctl(idle, capsys, "session-config", "set", "rounsd=3")
    assert status == ExitStatus.USAGE
    assert "rounsd" in json.loads(err)["detail"]


def test_rounds_and_counters_reset(running, capsys):
    assert trialctl(running, capsys, "reset", "rounds")[0] == ExitStatus.OK
    assert trialctl(running, capsys, "reset", "counters")[0] == ExitStatus.OK


def test_one_sim_dial_moves_and_the_others_stay(idle, capsys):
    was = idle.read_sim()
    status, dials, _ = trialctl(idle, capsys, "sim", "set", "hit_rate=0.5")
    assert status == ExitStatus.OK
    assert dials["hit_rate"] == 0.5
    assert dials["early_rate"] == was.early_rate
    idle.write_sim(was)


def test_the_sim_free_runs_and_stops(running, capsys):
    assert trialctl(running, capsys, "sim", "free-run", "start", "--interval-ms", "50")[1][
        "running"
    ]
    assert not trialctl(running, capsys, "sim", "free-run", "stop")[1]["running"]
    assert trialctl(running, capsys, "sim", "free-run", "status")[0] == ExitStatus.OK
