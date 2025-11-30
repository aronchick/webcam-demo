#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "textual>=0.85.0",
# ]
# ///
"""
Webcam Pipeline Demo

Usage:
    ./demo.py           # Demo mode: dashboard only
    ./demo.py --debug   # Debug mode: interactive menu
    ./demo.py test      # Run unit tests
"""

import argparse
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

# Debug log file
DEBUG_LOG = Path("/tmp/demo_debug.log")

def debug(msg: str) -> None:
    """Write to debug log file."""
    with open(DEBUG_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")

# Clear debug log on start
DEBUG_LOG.write_text(f"=== Demo started {datetime.now()} ===\n")


# =============================================================================
# Core Logic (UI-independent, testable)
# =============================================================================

CHUNKS_DIR = Path("chunks")
PROCESSED_DIR = Path("processed")
DATA_DIR = Path("data")


@dataclass
class ProcessManager:
    """Manages subprocesses."""

    processes: dict[str, subprocess.Popen] = field(default_factory=dict)

    def is_running(self, name: str) -> bool:
        return name in self.processes and self.processes[name].poll() is None

    def kill(self, name: str) -> bool:
        """Kill a process. Returns True if it was running."""
        debug(f"kill({name})")
        if name not in self.processes:
            return False

        proc = self.processes.pop(name)
        if proc.poll() is not None:
            return False

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=2)
            return True
        except (ProcessLookupError, OSError):
            return False

    def kill_all(self) -> None:
        for name in list(self.processes.keys()):
            self.kill(name)

    def start(self, name: str, cmd: list[str]) -> tuple[bool, str]:
        """Start a process. Returns (success, message)."""
        debug(f"start({name}, {cmd})")
        if self.is_running(name):
            return True, f"{name} already running"

        try:
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            debug(f"  Popen returned, poll={proc.poll()}")

            # Don't block - just check if it died immediately
            if proc.poll() is not None:
                out = ""
                if proc.stdout:
                    out = proc.stdout.read().decode()[:300]
                debug(f"  Process died: {out}")
                return False, f"{name} failed: {out}"

            self.processes[name] = proc
            debug(f"  Process started OK, pid={proc.pid}")
            return True, f"{name} started"

        except Exception as e:
            debug(f"  Exception: {e}")
            return False, f"{name} error: {e}"

    def get_output_reader(self, name: str) -> Callable[[], str | None] | None:
        """Get a function that reads one line from process output."""
        if name not in self.processes:
            return None
        proc = self.processes[name]
        if not proc.stdout:
            return None

        def read_line() -> str | None:
            if proc.poll() is not None:
                return None
            try:
                line = proc.stdout.readline()
                if line:
                    return line.decode().rstrip()
            except Exception:
                pass
            return None

        return read_line


def clear_data() -> list[str]:
    """Clear all data directories. Returns list of actions taken."""
    debug("clear_data()")
    actions = []

    for d in [CHUNKS_DIR, PROCESSED_DIR, DATA_DIR]:
        if d.exists():
            shutil.rmtree(d)
            actions.append(f"Removed {d}")

    for f in ["pipeline.db", "pipeline.db-shm", "pipeline.db-wal"]:
        p = Path(f)
        if p.exists():
            p.unlink()
            actions.append(f"Removed {f}")

    CHUNKS_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    for cat in ["left_hand_raised", "right_hand_raised", "both_hands_raised", "no_detection", "thumbnails"]:
        (PROCESSED_DIR / cat).mkdir(exist_ok=True)

    actions.append("Created directories")
    debug(f"  actions={actions}")
    return actions


def get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


def get_tailscale_hostname() -> str | None:
    """Get Tailscale MagicDNS hostname (e.g., fepi.tailnet-name.ts.net)."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            import json
            data = json.loads(result.stdout)
            if "Self" in data and "DNSName" in data["Self"]:
                # DNSName ends with a dot, strip it
                dns_name = data["Self"]["DNSName"].rstrip(".")
                if dns_name:
                    return dns_name
    except Exception:
        pass
    return None


def check_expanso_agent() -> bool:
    try:
        result = subprocess.run(
            ["expanso-edge", "status"],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


# =============================================================================
# Unit Tests
# =============================================================================

def run_tests() -> bool:
    """Run unit tests. Returns True if all pass."""
    import tempfile

    print("Running tests...\n")
    passed = 0
    failed = 0

    # Test 1: ProcessManager.is_running returns False for unknown process
    pm = ProcessManager()
    if not pm.is_running("nonexistent"):
        print("✓ is_running returns False for unknown process")
        passed += 1
    else:
        print("✗ is_running should return False for unknown process")
        failed += 1

    # Test 2: ProcessManager.kill returns False for unknown process
    if not pm.kill("nonexistent"):
        print("✓ kill returns False for unknown process")
        passed += 1
    else:
        print("✗ kill should return False for unknown process")
        failed += 1

    # Test 3: ProcessManager.start with valid command
    success, msg = pm.start("test_sleep", ["sleep", "10"])
    if success and pm.is_running("test_sleep"):
        print("✓ start works with valid command")
        passed += 1
    else:
        print(f"✗ start failed: {msg}")
        failed += 1

    # Test 4: ProcessManager.kill works
    if pm.kill("test_sleep") and not pm.is_running("test_sleep"):
        print("✓ kill terminates running process")
        passed += 1
    else:
        print("✗ kill should terminate process")
        failed += 1

    # Test 5: ProcessManager.start with invalid command
    success, msg = pm.start("bad", ["nonexistent_command_xyz"])
    if not success:
        print("✓ start fails with invalid command")
        passed += 1
    else:
        print("✗ start should fail with invalid command")
        failed += 1
        pm.kill("bad")

    # Test 6: clear_data creates directories
    with tempfile.TemporaryDirectory() as tmpdir:
        old_cwd = os.getcwd()
        os.chdir(tmpdir)
        try:
            actions = clear_data()
            if Path("chunks").exists() and Path("processed").exists():
                print("✓ clear_data creates directories")
                passed += 1
            else:
                print("✗ clear_data should create directories")
                failed += 1
        finally:
            os.chdir(old_cwd)

    # Test 7: get_local_ip returns a string
    ip = get_local_ip()
    if isinstance(ip, str) and len(ip) > 0:
        print(f"✓ get_local_ip returns '{ip}'")
        passed += 1
    else:
        print("✗ get_local_ip should return a string")
        failed += 1

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


# =============================================================================
# Textual UI
# =============================================================================

def run_app(debug_mode: bool, port: int) -> None:
    """Run the Textual app."""
    debug(f"run_app(debug_mode={debug_mode}, port={port})")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.widgets import Footer, RichLog, Static

    class DemoApp(App):
        CSS = """
        #log { height: 1fr; border: round white; }
        #status { height: 3; border: round green; padding: 0 1; }
        #menu { height: 3; border: round cyan; padding: 0 1; }
        """

        BINDINGS = [Binding("q", "quit", "Quit")]

        def __init__(self):
            debug("DemoApp.__init__")
            super().__init__()
            self.pm = ProcessManager()
            self.local_ip = get_local_ip()
            self.tailscale_host = get_tailscale_hostname()
            self._mode = "Starting"
            debug(f"  local_ip={self.local_ip}, tailscale_host={self.tailscale_host}")

        def compose(self) -> ComposeResult:
            debug("DemoApp.compose")
            yield RichLog(id="log", wrap=True, markup=True)
            yield Static(id="status", markup=True)
            yield Static(id="menu", markup=True)
            yield Footer()

        def on_mount(self) -> None:
            debug("DemoApp.on_mount START")
            self.title = "DEBUG" if debug_mode else "DEMO"

            # Set up bindings for debug mode
            if debug_mode:
                self.bind("1", "cmd_1")
                self.bind("2", "cmd_2")
                self.bind("3", "cmd_3")
                self.bind("5", "cmd_5")
                self.bind("6", "cmd_6")

            self._update_menu()
            debug("  menu updated")

            # Initialize
            self.log_msg("Initializing...")
            for action in clear_data():
                self.log_msg(action)

            debug("  starting dashboard")
            self._do_start_dashboard()
            debug("  dashboard started")

            if not debug_mode:
                if check_expanso_agent():
                    self.log_msg("Expanso agent: RUNNING")
                else:
                    self.log_msg("Expanso agent: NOT RUNNING", "warn")

            self.set_interval(1.0, self._update_status)
            debug("DemoApp.on_mount END")

        def log_msg(self, msg: str, level: str = "info") -> None:
            debug(f"log_msg({msg}, {level})")
            try:
                log = self.query_one("#log", RichLog)
                ts = datetime.now().strftime("%H:%M:%S")
                if level == "error":
                    log.write(f"[red]{ts} {msg}[/]")
                elif level == "warn":
                    log.write(f"[yellow]{ts} {msg}[/]")
                else:
                    log.write(f"[dim]{ts}[/] {msg}")
            except Exception as e:
                debug(f"  log_msg exception: {e}")

        def _update_status(self) -> None:
            try:
                status = self.query_one("#status", Static)
                d = "●" if self.pm.is_running("dashboard") else "○"
                c = "●" if self.pm.is_running("capture") else "○"
                t = "●" if self.pm.is_running("detection") else "○"
                local_url = f"http://{self.local_ip}:{port}"
                ts_url = f"http://{self.tailscale_host}:{port}" if self.tailscale_host else ""

                if debug_mode:
                    status.update(f"[b]{self._mode}[/b] | D:{d} C:{c} T:{t} | {local_url}" + (f" | {ts_url}" if ts_url else ""))
                else:
                    status.update(f"Dashboard:{d} | {local_url}" + (f" | {ts_url}" if ts_url else ""))
            except Exception as e:
                debug(f"_update_status exception: {e}")

        def _update_menu(self) -> None:
            try:
                menu = self.query_one("#menu", Static)
                if debug_mode:
                    menu.update("[b]1[/]=Dashboard [b]2[/]=Capture [b]3[/]=Detection [b]5[/]=Clear [b]6[/]=Full [b]q[/]=Quit")
                else:
                    menu.update("[b]q[/]=Quit | Deploy at https://cloud.expanso.io")
            except Exception as e:
                debug(f"_update_menu exception: {e}")

        def _do_start(self, name: str, cmd: list[str]) -> None:
            debug(f"_do_start({name})")
            success, msg = self.pm.start(name, cmd)
            self.log_msg(msg, "info" if success else "error")
            if success:
                self._start_output_reader(name)

        def _do_start_dashboard(self) -> None:
            self._do_start("dashboard", ["uv", "run", "-s", "dashboard.py"])
            if self.pm.is_running("dashboard"):
                self.log_msg(f"Dashboard at http://{self.local_ip}:{port}")

        def _do_start_capture(self) -> None:
            self._do_start("capture", ["uv", "run", "-s", "capture_video.py"])

        def _do_start_detection(self) -> None:
            self._do_start("detection", ["uv", "run", "-s", "process_chunks.py"])

        def _start_output_reader(self, name: str) -> None:
            debug(f"_start_output_reader({name})")
            reader = self.pm.get_output_reader(name)
            if not reader:
                debug("  no reader")
                return

            def thread_fn():
                debug(f"  output reader thread started for {name}")
                while True:
                    line = reader()
                    if line is None:
                        break
                    if line:
                        self.call_from_thread(self.log_msg, f"[{name}] {line}")
                debug(f"  output reader thread ended for {name}")

            threading.Thread(target=thread_fn, daemon=True).start()

        # Actions
        def action_cmd_1(self) -> None:
            debug("action_cmd_1")
            self._mode = "Dashboard"
            self._do_start_dashboard()

        def action_cmd_2(self) -> None:
            debug("action_cmd_2")
            self._mode = "Capture"
            self._do_start_capture()

        def action_cmd_3(self) -> None:
            debug("action_cmd_3")
            self._mode = "Detection"
            self._do_start_detection()

        def action_cmd_5(self) -> None:
            debug("action_cmd_5")
            self._mode = "Cleared"
            self.pm.kill_all()
            for action in clear_data():
                self.log_msg(action)
            self._do_start_dashboard()

        def action_cmd_6(self) -> None:
            debug("action_cmd_6")
            self._mode = "Full Pipeline"
            self.pm.kill_all()
            for action in clear_data():
                self.log_msg(action)
            self._do_start_dashboard()
            self._do_start_capture()
            self._do_start_detection()

        def action_quit(self) -> None:
            debug("action_quit")
            self.pm.kill_all()
            clear_data()
            self.exit()

    debug("Creating DemoApp instance")
    app = DemoApp()
    debug("Calling app.run()")
    app.run()
    debug("app.run() returned")


# =============================================================================
# CLI
# =============================================================================

def cmd_status(port: int) -> None:
    print("Status:\n")
    print(f"  expanso-edge: {'RUNNING' if check_expanso_agent() else 'NOT RUNNING'}")
    try:
        result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
        running = f":{port}" in result.stdout
        print(f"  dashboard: {'RUNNING' if running else 'NOT RUNNING'}")
    except Exception:
        print("  dashboard: UNKNOWN")


def main():
    parser = argparse.ArgumentParser(description="Webcam Pipeline Demo")
    parser.add_argument("--port", "-p", type=int, default=8181)
    parser.add_argument("--debug", "-d", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status")
    subparsers.add_parser("clear")
    subparsers.add_parser("test")

    args = parser.parse_args()

    debug(f"main() command={args.command} debug={args.debug}")

    if args.command == "status":
        cmd_status(args.port)
    elif args.command == "clear":
        for action in clear_data():
            print(action)
    elif args.command == "test":
        success = run_tests()
        exit(0 if success else 1)
    else:
        run_app(debug_mode=args.debug, port=args.port)


if __name__ == "__main__":
    main()
