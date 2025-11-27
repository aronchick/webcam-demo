#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Webcam video capture script that chunks video into 5-second segments.
Designed to run as a subprocess via Expanso.

Environment Variables:
    VIDEO_DEVICE: Device identifier (default: "0" on Mac, "/dev/video0" on Linux)
    VIDEO_FORMAT: Input format (default: "avfoundation" on Mac, "v4l2" on Linux)
    OUTPUT_DIR: Directory for video chunks (default: "./chunks")
    CHUNK_DURATION: Duration of each chunk in seconds (default: 3)
    VIDEO_SIZE: Resolution (default: "1280x720")
    FRAMERATE: Frames per second (default: 30 for MacBook compatibility)
"""

import os
import platform
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_platform_defaults() -> dict:
    """Return platform-specific defaults for video capture."""
    system = platform.system()
    if system == "Darwin":
        return {
            "format": "avfoundation",
            "device": "0",
        }
    elif system == "Linux":
        return {
            "format": "v4l2",
            "device": "/dev/video0",
        }
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def list_devices() -> None:
    """List available video devices for the current platform."""
    system = platform.system()
    if system == "Darwin":
        cmd = ["ffmpeg", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
        subprocess.run(cmd, capture_output=False)
    elif system == "Linux":
        print("Available video devices:")
        for dev in Path("/dev").glob("video*"):
            print(f"  {dev}")
    else:
        print(f"Device listing not supported on {system}")


def build_ffmpeg_command(
    video_format: str,
    device: str,
    output_dir: Path,
    chunk_duration: int,
    video_size: str,
    framerate: int,
) -> list[str]:
    """Build the ffmpeg command for chunked video capture."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_pattern = output_dir / f"chunk_{timestamp}_%04d.mp4"

    cmd = ["ffmpeg"]

    # Platform-specific input options
    if platform.system() == "Darwin":
        # macOS: explicitly set framerate to avoid unsupported default
        # Most MacBook cameras support 15 or 30 fps
        cmd.extend([
            "-f", video_format,
            "-framerate", str(framerate),
            "-video_size", video_size,
            "-i", device,
        ])
    else:
        # Linux v4l2
        cmd.extend([
            "-f", video_format,
            "-framerate", str(framerate),
            "-video_size", video_size,
            "-i", device,
        ])

    cmd.extend([
        # Output framerate (downsample from camera rate)
        "-r", str(framerate),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        # Force keyframe at segment boundaries for clean cuts
        "-g", str(framerate * chunk_duration),
        "-force_key_frames", f"expr:gte(t,n_forced*{chunk_duration})",
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-reset_timestamps", "1",
        "-strftime", "0",
        str(output_pattern),
    ])
    return cmd


def main() -> int:
    defaults = get_platform_defaults()

    # Configuration from environment variables
    video_format = os.environ.get("VIDEO_FORMAT", defaults["format"])
    device = os.environ.get("VIDEO_DEVICE", defaults["device"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "./chunks"))
    chunk_duration = int(os.environ.get("CHUNK_DURATION", "3"))
    video_size = os.environ.get("VIDEO_SIZE", "1280x720")
    framerate = int(os.environ.get("FRAMERATE", "30"))  # MacBook cameras need 30fps

    # Handle --list-devices flag
    if "--list-devices" in sys.argv:
        list_devices()
        return 0

    # Clean and create output directory
    if output_dir.exists():
        for old_file in output_dir.glob("*.mp4"):
            old_file.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = build_ffmpeg_command(
        video_format, device, output_dir, chunk_duration, video_size, framerate
    )

    print(f"""
Starting video capture:
  Platform: {platform.system()}
  Format: {video_format}
  Device: {device}
  Output: {output_dir}
  Chunk duration: {chunk_duration}s
  Resolution: {video_size}
  Framerate: {framerate} fps

Press Ctrl+C to stop...
""", flush=True)

    # Run ffmpeg, forwarding signals for clean shutdown
    process = subprocess.Popen(cmd, stderr=subprocess.STDOUT)

    def signal_handler(signum, frame):
        process.send_signal(signal.SIGINT)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    return process.wait()


if __name__ == "__main__":
    sys.exit(main())
