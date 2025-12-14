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
    VIDEO_SIZE: Resolution (default: "640x360", downsampled 50% to save bandwidth)
    FRAMERATE: Frames per second (default: 30 for MacBook compatibility)
    DB_PATH: Path to SQLite database (default: "./pipeline.db")
"""

import os
import platform
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Import database module for stage tracking
try:
    import db
    HAS_DB = True
except ImportError:
    HAS_DB = False


def is_raspberry_pi() -> bool:
    """Detect if running on a Raspberry Pi."""
    try:
        with open("/proc/cpuinfo") as f:
            return "Raspberry Pi" in f.read() or "BCM" in f.read()
    except Exception:
        return False


def get_platform_defaults() -> dict:
    """Return platform-specific defaults for video capture."""
    system = platform.system()
    if system == "Darwin":
        return {
            "format": "avfoundation",
            "device": "0",
            "video_size": "1280x720",
            "framerate": 30,
        }
    elif system == "Linux":
        # Use absolute minimum on Pi to prevent overload
        if is_raspberry_pi():
            return {
                "format": "v4l2",
                "device": "/dev/video0",
                "video_size": "320x240",
                "framerate": 10,
            }
        return {
            "format": "v4l2",
            "device": "/dev/video0",
            "video_size": "640x480",
            "framerate": 15,
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


def has_hw_encoder() -> bool:
    """Check if Pi hardware encoder is available."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        return "h264_v4l2m2m" in result.stdout
    except Exception:
        return False


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

    # Use hardware encoder on Pi, software on Mac/other
    use_hw = platform.system() == "Linux" and has_hw_encoder()

    if use_hw:
        # Raspberry Pi hardware H.264 encoder - much lower CPU usage
        # 200kbps is plenty for 320x240@10fps
        cmd.extend([
            "-c:v", "h264_v4l2m2m",
            "-pix_fmt", "yuv420p",
            "-b:v", "200k",
        ])
    else:
        # Software encoder for Mac/other
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
        ])

    cmd.extend([
        "-r", str(framerate),
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

    # Configuration from environment variables (with platform-aware defaults)
    video_format = os.environ.get("VIDEO_FORMAT", defaults["format"])
    device = os.environ.get("VIDEO_DEVICE", defaults["device"])
    output_dir = Path(os.environ.get("OUTPUT_DIR", "./chunks"))
    chunk_duration = int(os.environ.get("CHUNK_DURATION", "3"))
    video_size = os.environ.get("VIDEO_SIZE", defaults.get("video_size", "1280x720"))
    framerate = int(os.environ.get("FRAMERATE", str(defaults.get("framerate", 30))))
    db_path = Path(os.environ.get("DB_PATH", "./pipeline.db"))

    # Set pipeline stage to 1 (capture active)
    # Check if EXPANSO_PIPELINE env var is set to determine source
    source = "expanso" if os.environ.get("EXPANSO_PIPELINE") else "local"
    if HAS_DB:
        db.init_db(db_path)
        db.set_pipeline_stage(1, db_path, source=source)
        db.start_session(db_path)

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

    # Detect encoder type for status display
    use_hw = platform.system() == "Linux" and has_hw_encoder()
    encoder = "h264_v4l2m2m (hardware)" if use_hw else "libx264 (software)"

    print(f"""
Starting video capture:
  Platform: {platform.system()}
  Format: {video_format}
  Device: {device}
  Output: {output_dir}
  Chunk duration: {chunk_duration}s
  Resolution: {video_size}
  Framerate: {framerate} fps
  Encoder: {encoder}

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
