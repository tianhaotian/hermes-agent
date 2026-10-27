"""Drive the real plugin command in a PTY and verify real PM admission/config writes."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
import hermes_yaml as yaml

OUT = Path(os.environ.get("CURSES_EVIDENCE", Path(__file__).parent))
OUT.mkdir(parents=True, exist_ok=True)
HOME = OUT / "picker-home"
HOME.mkdir(exist_ok=True)
PLUGIN = "curses-integration-probe"
plugin = HOME / "plugins" / PLUGIN
plugin.mkdir(parents=True, exist_ok=True)
(plugin / "plugin.yaml").write_text(
    f"name: {PLUGIN}\nversion: 1.0.0\ndescription: PTY integration fixture\n", encoding="utf-8")
(plugin / "__init__.py").write_text("def register(ctx):\n    pass\n", encoding="utf-8")
config = HOME / "config.yaml"
assert not config.exists(), "Use a fresh evidence directory for each run"
config.write_text("plugins:\n  enabled: []\n  disabled: []\n", encoding="utf-8")
env = dict(os.environ, HERMES_HOME=str(HOME), TERM="xterm-256color", PYTHONUNBUFFERED="1")
env["PYTHONPATH"] = str(ROOT)
code = """
import json, sys
if sys.argv[1].startswith('shared-'):
    from hermes_cli.curses_ui import curses_checklist
    print('PROBE ' + json.dumps({'target': 0, 'total': 2}), flush=True)
    initial = {1} if sys.argv[1] == 'shared-cancel' else set()
    result = curses_checklist('Shared checklist probe', ['first', 'second'], initial)
    assert result == {1}, result
else:
    from hermes_cli import plugins_cmd as pc
    from hermes_cli.plugins_cmd_toggle import cmd_toggle
    keys = [entry[5] for entry in pc._discover_all_plugins()]
    target = keys.index('curses-integration-probe')
    total = len(keys) + len(pc._provider_categories())
    print('PROBE ' + json.dumps({'target': target, 'total': total}), flush=True)
    cmd_toggle()
print('PROBE_DONE', flush=True)
"""
CHILD = OUT / "picker_child.py"
CHILD.write_text(code, encoding="utf-8")


class PosixTerminal:
    def __init__(self, args):
        import fcntl
        import pty
        import struct
        import termios
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(ROOT)
            os.execve(args[0], args, env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))

    def read(self, size):
        return os.read(self.fd, size).decode("utf-8", errors="replace")

    def write(self, text):
        os.write(self.fd, text.encode("utf-8"))

    def close(self):
        import signal
        if os.waitpid(self.pid, os.WNOHANG)[0] == 0:
            os.kill(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)
        os.close(self.fd)


def drive(name, toggle):
    args = [sys.executable, str(CHILD), name]
    if os.name == "nt":
        from winpty import PtyProcess
        child = PtyProcess.spawn(subprocess.list2cmdline(args), cwd=str(ROOT), env=env,
                                 dimensions=(40, 160))
    else:
        child = PosixTerminal(args)
    events = queue.Queue()
    chunks = []

    def read():
        try:
            while True:
                text = child.read(4096)
                if not text:
                    break
                chunks.append(text)
                events.put(text)
        except Exception:
            pass  # EOF and PTY close are reported by the waiter's missing sentinel.
        finally:
            events.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    observed = ""

    def until(needle, timeout=240):
        nonlocal observed
        deadline = time.monotonic() + timeout
        while needle not in observed:
            part = events.get(timeout=max(0.01, deadline - time.monotonic()))
            if part is None:
                raise AssertionError(f"PTY exited before {needle!r}: {observed[-5000:]}")
            observed += part

    def send(text):
        child.write(text)

    try:
        until("SPACE toggle")
        assert "Toggle # (or Enter to confirm):" not in observed
        start = observed.index("PROBE ") + len("PROBE ")
        info, _ = json.JSONDecoder().raw_decode(observed[start:])
        if name == "shared-confirm":
            send("\x1b[B \r")
        elif name == "shared-cancel":
            send(" \x1b")
        elif toggle:
            up = info["total"] - info["target"]
            send("k" * up if up < info["target"] else "j" * info["target"])
            until(PLUGIN)
            send(" ")
        if not name.startswith("shared-"):
            send("\x1b")
        until("PROBE_DONE")
        assert "Plugin selection refused" not in observed
        return yaml.safe_load(config.read_text(encoding="utf-8"))["plugins"]
    finally:
        (OUT / f"{name}.terminal.txt").write_text("".join(chunks), encoding="utf-8")
        child.close()
        reader.join(timeout=2)


enabled = drive("enable", True)
assert PLUGIN in enabled["enabled"] and PLUGIN not in enabled["disabled"], enabled
disabled = drive("disable", True)
assert PLUGIN not in disabled["enabled"] and PLUGIN in disabled["disabled"], disabled
before = config.read_bytes()
unchanged = drive("unchanged", False)
assert config.read_bytes() == before
drive("shared-confirm", False)
drive("shared-cancel", False)
assert config.read_bytes() == before
result = {"platform": sys.platform, "python": sys.version, "interpreter": sys.executable,
          "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "enable": enabled, "disable": disabled, "unchanged": unchanged,
          "scenarios_passed": 5}
(OUT / "picker-e2e.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result, indent=2))
