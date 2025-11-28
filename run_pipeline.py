#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Pipeline orchestrator - starts capture, processor, and dashboard together.
"""

import atexit
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

def get_ip():
    """Get the machine's IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostname()

# ANSI colors
C = {
    "capture": "\033[94m",    # Blue
    "process": "\033[92m",    # Green
    "dashboard": "\033[95m",  # Magenta
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}

processes: dict[str, subprocess.Popen] = {}


def cleanup():
    """Kill all child processes."""
    for name, proc in processes.items():
        if proc.poll() is None:
            print(f"{C['dim']}Stopping {name}...{C['reset']}")
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()


def signal_handler(signum, frame):
    print(f"\n{C['bold']}Shutting down...{C['reset']}")
    cleanup()
    sys.exit(0)


def main():
    # Register cleanup
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"""
{C['bold']}╔═══════════════════════════════════════════════════════════╗
║         WEBCAM PIPELINE - EXPANSO DEMO                    ║
╚═══════════════════════════════════════════════════════════╝{C['reset']}
""")

    scripts = [
        ("capture", "capture_video.py"),
        ("process", "process_chunks.py"),
        ("dashboard", "dashboard.py"),
    ]

    # Start each script
    for name, script in scripts:
        script_path = SCRIPT_DIR / script
        if not script_path.exists():
            print(f"Error: {script} not found")
            return 1

        print(f"{C[name]}[{name.upper()}]{C['reset']} Starting...")

        proc = subprocess.Popen(
            ["uv", "run", "-s", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        processes[name] = proc
        time.sleep(1)  # Stagger startup

    ip = get_ip()
    print(f"""
{C['bold']}All processes started!{C['reset']}

  {C['dashboard']}Dashboard:{C['reset']} http://{ip}:8181

  Press {C['bold']}Ctrl+C{C['reset']} to stop all processes.
""")

    # Read output from all processes
    import select
    exited = set()

    while True:
        # Check if any process died (only report once)
        for name, proc in list(processes.items()):
            if proc.poll() is not None and name not in exited:
                exited.add(name)
                print(f"{C['bold']}[{name.upper()}] Process exited with code {proc.returncode}{C['reset']}")
                # Read remaining output
                if proc.stdout:
                    remaining = proc.stdout.read()
                    if remaining:
                        for line in remaining.split('\n'):
                            if line.strip():
                                print(f"{C[name]}[{name.upper():^9}]{C['reset']} {line}")

        # Non-blocking read from all processes
        readable = []
        for name, proc in processes.items():
            if proc.stdout and proc.poll() is None:
                readable.append((name, proc.stdout))

        if not readable:
            time.sleep(0.1)
            continue

        fds = [fd for _, fd in readable]
        ready, _, _ = select.select(fds, [], [], 0.1)

        for name, fd in readable:
            if fd in ready:
                line = fd.readline()
                if line:
                    line = line.rstrip()
                    # Filter very noisy lines
                    if any(skip in line for skip in [
                        "Downloading", "Installed ", " packages in",
                        "libav", "bitrate=N/A", "speed=",
                    ]):
                        continue
                    # Print with color
                    print(f"{C[name]}[{name.upper():^9}]{C['reset']} {line}")


if __name__ == "__main__":
    sys.exit(main() or 0)
