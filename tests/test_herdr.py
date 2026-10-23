"""The real Herdr wrapper against a stub `herdr` executable on PATH.

The stub replays canned responses in order -- each {"exit", "stdout",
"stderr"} -- and logs its argv, so these tests cover the subprocess and
parsing path that FakeHerdr skips."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

from corral import ops
from corral.herdr import Herdr, HerdrError
from tests.fake_herdr import FakeHerdr

STUB = f"""#!{sys.executable}
import json, os, sys
plan = os.environ["STUB_HERDR_PLAN"]
with open(plan) as f:
    queue = json.load(f)
with open(plan + ".log", "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
r = queue.pop(0) if queue else {{"exit": 0, "stdout": '{{"result": {{}}}}'}}
with open(plan, "w") as f:
    json.dump(queue, f)
sys.stdout.write(r.get("stdout", ""))
sys.stderr.write(r.get("stderr", ""))
sys.exit(r.get("exit", 0))
"""


SERVER_STUB = f"""#!{sys.executable}
import json, os, sys, time
d = os.environ["STUB_SERVER_DIR"]
marker, info = os.path.join(d, "running"), os.path.join(d, "info.json")
with open(os.path.join(d, "log"), "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:2] == ["status"]:
    sys.exit(0 if os.path.exists(marker) else 1)
if sys.argv[1:2] == ["server"]:
    null = os.stat(os.devnull)
    fds = [(os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (null.st_dev, null.st_ino)
           for fd in (0, 1, 2)]
    with open(info, "w") as f:
        json.dump({{"sid": os.getsid(0), "devnull": fds}}, f)
    if os.environ.get("STUB_SERVER_NEVER") != "1":
        time.sleep(float(os.environ.get("STUB_SERVER_DELAY", "0")))
        open(marker, "w").close()
"""


def err(code: str, message: str = "boom") -> str:
    return json.dumps({"error": {"code": code, "message": message}, "id": "cli:x"}) + "\n"


def ok(result: dict) -> str:
    return json.dumps({"result": result}) + "\n"


@pytest.fixture
def stub(tmp_path: Path, monkeypatch):
    """stub(*responses) queues responses; stub.calls() is the argv log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "herdr"
    exe.write_text(STUB)
    exe.chmod(0o755)
    plan = tmp_path / "plan.json"
    plan.write_text("[]")
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_HERDR_PLAN", str(plan))

    class Stub:
        def __call__(self, *responses: dict) -> None:
            plan.write_text(json.dumps(list(responses)))

        def calls(self) -> list[list[str]]:
            log = Path(f"{plan}.log")
            return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    return Stub()


def test_error_code_is_read_from_stderr(stub):
    stub({"exit": 1, "stderr": err("agent_pane_busy", "pane w1:p2 is not an available shell")})
    with pytest.raises(HerdrError) as e:
        Herdr().call("agent", "start", "x")
    assert e.value.code == "agent_pane_busy"
    assert e.value.message == "pane w1:p2 is not an available shell"


def test_error_code_on_stdout_still_parsed(stub):
    stub({"exit": 1, "stdout": err("tab_not_found")})
    with pytest.raises(HerdrError) as e:
        Herdr().call("tab", "rename", "t9", "x")
    assert e.value.code == "tab_not_found"


def test_error_in_body_with_exit_zero_raises(stub):
    stub({"exit": 0, "stderr": err("pane_not_found")})
    with pytest.raises(HerdrError) as e:
        Herdr().call("pane", "close", "p9")
    assert e.value.code == "pane_not_found"


def test_non_json_failure_keeps_the_text(stub):
    stub({"exit": 2, "stderr": "error: unrecognized subcommand\n"})
    with pytest.raises(HerdrError) as e:
        Herdr().call("bogus")
    assert e.value.code == ""
    assert e.value.message == "error: unrecognized subcommand"


def test_success_returns_result(stub):
    stub({"stdout": ok({"workspaces": [{"workspace_id": "w1", "label": "api", "tab_count": 2}]})})
    [w] = Herdr().workspaces()
    assert (w.id, w.label, w.tab_count) == ("w1", "api", 2)
    assert stub.calls() == [["workspace", "list"]]


def test_agent_get_not_found_is_none(stub):
    stub({"exit": 1, "stderr": err("agent_not_found", "agent target nope not found")})
    assert Herdr().agent_get("nope") is None


def test_agent_get_other_errors_raise(stub):
    stub({"exit": 1, "stderr": err("server_unreachable")})
    with pytest.raises(HerdrError):
        Herdr().agent_get("x")


def test_start_agent_retries_busy_pane(stub):
    busy = {"exit": 1, "stderr": err("agent_pane_busy", "pane w1:p2 is not an available shell")}
    stub(busy, busy, {"stdout": ok({})})
    name = ops.start_agent(Herdr(), "claude-opus-high", "claude", "w1:p2", 1000, ["--x"])
    assert name == "claude-opus-high"
    starts = stub.calls()
    assert len(starts) == 3
    assert starts[0][:3] == ["agent", "start", "claude-opus-high"]
    assert starts[0][-2:] == ["--", "--x"]


def test_start_agent_name_taken_falls_back(stub):
    stub({"exit": 1, "stderr": err("agent_name_taken")}, {"stdout": ok({})})
    name = ops.start_agent(Herdr(), "claude-opus-high", "claude", "w1:p2", 1000, [])
    assert name == "claude-w1-p2"
    assert [c[2] for c in stub.calls()] == ["claude-opus-high", "claude-w1-p2"]


def test_start_agent_gives_up_on_other_errors(stub):
    stub({"exit": 1, "stderr": err("agent_start_failed")})
    with pytest.raises(HerdrError) as e:
        ops.start_agent(Herdr(), "a", "claude", "w1:p2", 1000, [])
    assert e.value.code == "agent_start_failed"
    assert len(stub.calls()) == 1


def test_fake_errors_match_real_ones(stub, herdr):
    """FakeHerdr raises what the real wrapper raises for the same herdr output."""
    from tests.fake_herdr import fail

    stub({"exit": 1, "stderr": err("tab_not_found", "tab t9 not found")})
    with pytest.raises(HerdrError) as real:
        Herdr().rename_tab("t9", "x")
    with pytest.raises(HerdrError) as fake:
        herdr.rename_tab("t9", "x")
    assert (fake.value.code, fake.value.message) == (real.value.code, real.value.message)
    assert str(fail("tab_not_found", "tab t9 not found")) == str(real.value)


def test_agent_kinds_are_read_from_help(stub):
    help_text = (
        "Options:\n      --kind <KIND>\n          Supported agent kind\n\n"
        "          [possible values: pi, claude, codex, gemini]\n\n      --pane <ID>\n"
    )
    stub({"stdout": help_text})
    assert Herdr().agent_kinds() == ["pi", "claude", "codex", "gemini"]
    stub({"stdout": "no kinds here"})
    assert "claude" in Herdr().agent_kinds()  # the built-in fallback
    assert "claude" in Herdr("/no/such/herdr").agent_kinds()


@pytest.fixture
def server_stub(tmp_path: Path, monkeypatch):
    """A `herdr` whose `status` answers once a marker file exists and whose
    `server` records how it was started, then creates the marker after
    $STUB_SERVER_DELAY seconds (never, with STUB_SERVER_NEVER=1). Separate
    from `stub`: a detached server would race the next `status` poll for
    `stub`'s shared response queue."""
    bin_dir = tmp_path / "server-bin"
    bin_dir.mkdir()
    exe = bin_dir / "herdr"
    exe.write_text(SERVER_STUB)
    exe.chmod(0o755)
    state = tmp_path / "server-state"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_SERVER_DIR", str(state))

    class ServerStub:
        marker = state / "running"
        info = state / "info.json"
        log = state / "log"

        def calls(self) -> list[list[str]]:
            if not self.log.exists():
                return []
            return [json.loads(x) for x in self.log.read_text().splitlines()]

    return ServerStub()


def test_start_server_when_already_running_starts_nothing(server_stub):
    server_stub.marker.touch()
    assert Herdr().start_server() is True
    assert server_stub.calls() == [["status"]]


def test_start_server_starts_a_detached_server_and_polls(server_stub, monkeypatch):
    monkeypatch.setenv("STUB_SERVER_DELAY", "0.3")
    assert Herdr().start_server() is True
    calls = server_stub.calls()
    assert calls[0] == ["status"]
    assert calls.count(["server"]) == 1
    assert calls.count(["status"]) > 1  # it polled until the server answered
    info = json.loads(server_stub.info.read_text())
    assert info["sid"] != os.getsid(0)  # its own session
    assert info["devnull"] == [True, True, True]  # no shared stdin, stdout or stderr


def test_start_server_gives_up_after_timeout(server_stub, monkeypatch):
    monkeypatch.setenv("STUB_SERVER_NEVER", "1")
    t = time.monotonic()
    assert Herdr().start_server(timeout=0.5) is False
    assert time.monotonic() - t < 2
    assert server_stub.calls().count(["server"]) == 1


def test_start_server_without_herdr_on_path():
    t = time.monotonic()
    assert Herdr("/no/such/herdr").start_server() is False
    assert time.monotonic() - t < 1


def test_fake_start_server(herdr):
    herdr.unavailable = True
    assert herdr.start_server() is True
    assert herdr.available()
    assert herdr.calls == [("start_server",)]

    running = FakeHerdr()
    assert running.start_server() is True
    assert running.calls == []

    broken = FakeHerdr()
    broken.unavailable = broken.server_fails = True
    assert broken.start_server() is False
    assert not broken.available()
