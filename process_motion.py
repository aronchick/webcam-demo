#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "opencv-python>=4.8.0",
# ]
# ///
"""
Lightweight motion detector - designed for Raspberry Pi.

Uses simple frame differencing (no ML) to detect motion intensity.
Much faster than pose detection and creates cool motion visualizations.

Categories:
  - high_motion/   : Lots of movement (>15% of frame)
  - medium_motion/ : Moderate movement (5-15% of frame)
  - low_motion/    : Minimal movement (1-5% of frame)
  - no_motion/     : Static scene (<1% of frame)

Environment Variables:
    INPUT_DIR: Directory to watch for new chunks (default: "./chunks")
    OUTPUT_DIR: Base directory for sorted output (default: "./processed")
    POLL_INTERVAL: Seconds between directory scans (default: 1)
    MOTION_THRESHOLD: Pixel difference threshold 0-255 (default: 25)
"""

import os

# Suppress OpenCV warnings
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"

import shutil
import signal
import sys
import time
from pathlib import Path

import cv2
import numpy as np


class MotionClassifier:
    """Classifies video chunks based on motion intensity."""

    def __init__(self, threshold: int = 25):
        self.threshold = threshold

    def compute_motion(self, frame1, frame2) -> tuple[float, np.ndarray]:
        """
        Compute motion between two frames.
        Returns (motion_percent, motion_mask).
        """
        # Convert to grayscale
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

        # Apply slight blur to reduce noise
        gray1 = cv2.GaussianBlur(gray1, (5, 5), 0)
        gray2 = cv2.GaussianBlur(gray2, (5, 5), 0)

        # Compute absolute difference
        diff = cv2.absdiff(gray1, gray2)

        # Threshold to get motion mask
        _, motion_mask = cv2.threshold(diff, self.threshold, 255, cv2.THRESH_BINARY)

        # Calculate percentage of pixels with motion
        total_pixels = motion_mask.shape[0] * motion_mask.shape[1]
        motion_pixels = cv2.countNonZero(motion_mask)
        motion_percent = (motion_pixels / total_pixels) * 100

        return motion_percent, motion_mask

    def create_motion_visualization(
        self, frame: np.ndarray, motion_mask: np.ndarray, motion_percent: float
    ) -> np.ndarray:
        """Create a cool visualization showing motion areas."""
        vis = frame.copy()

        # Create colored motion overlay (cyan/magenta gradient based on intensity)
        motion_color = np.zeros_like(frame)

        # Use motion mask to create heat-like effect
        motion_mask_3ch = cv2.cvtColor(motion_mask, cv2.COLOR_GRAY2BGR)

        # Color based on motion intensity
        if motion_percent > 15:
            color = (0, 0, 255)  # Red for high motion
            label = "HIGH MOTION"
        elif motion_percent > 5:
            color = (0, 165, 255)  # Orange for medium
            label = "MEDIUM MOTION"
        elif motion_percent > 1:
            color = (0, 255, 255)  # Yellow for low
            label = "LOW MOTION"
        else:
            color = (128, 128, 128)  # Gray for none
            label = "STATIC"

        # Apply colored overlay on motion areas
        motion_overlay = np.zeros_like(frame)
        motion_overlay[motion_mask > 0] = color

        # Blend with original
        vis = cv2.addWeighted(vis, 0.7, motion_overlay, 0.3, 0)

        # Add motion percentage bar
        bar_width = int((motion_percent / 30) * (frame.shape[1] - 40))
        bar_width = max(10, min(bar_width, frame.shape[1] - 40))
        cv2.rectangle(vis, (20, 20), (20 + bar_width, 40), color, -1)
        cv2.rectangle(vis, (20, 20), (frame.shape[1] - 20, 40), (255, 255, 255), 2)

        # Add label
        cv2.putText(
            vis, f"{label} ({motion_percent:.1f}%)",
            (25, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2
        )

        return vis

    def classify_video(
        self, video_path: Path, thumbs_dir: Path | None = None
    ) -> tuple[str, Path | None]:
        """
        Classify a video by motion intensity.
        Returns (classification, thumbnail_path or None).
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"  Error: Could not open {video_path}")
            return "no_motion", None

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Sample every few frames for efficiency
        sample_interval = max(1, int(fps / 5))  # ~5 samples per second

        motion_values = []
        prev_frame = None
        best_frame = None
        best_motion_mask = None
        best_motion_percent = 0
        frame_num = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_num % sample_interval == 0:
                if prev_frame is not None:
                    motion_percent, motion_mask = self.compute_motion(prev_frame, frame)
                    motion_values.append(motion_percent)

                    # Keep the frame with most motion for thumbnail
                    if motion_percent > best_motion_percent:
                        best_motion_percent = motion_percent
                        best_frame = frame.copy()
                        best_motion_mask = motion_mask.copy()

                prev_frame = frame.copy()

            frame_num += 1

        cap.release()

        # Determine classification based on average motion
        if not motion_values:
            classification = "no_motion"
        else:
            avg_motion = sum(motion_values) / len(motion_values)
            max_motion = max(motion_values)

            # Use combination of average and max for classification
            if avg_motion > 15 or max_motion > 25:
                classification = "high_motion"
            elif avg_motion > 5 or max_motion > 15:
                classification = "medium_motion"
            elif avg_motion > 1 or max_motion > 5:
                classification = "low_motion"
            else:
                classification = "no_motion"

        # Save thumbnail with motion visualization
        thumb_path = None
        if thumbs_dir and best_frame is not None and best_motion_mask is not None:
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            vis = self.create_motion_visualization(
                best_frame, best_motion_mask, best_motion_percent
            )
            thumb = cv2.resize(vis, (320, 180))
            thumb_path = thumbs_dir / f"{video_path.stem}.jpg"
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        elif thumbs_dir and best_frame is None:
            # No motion detected - save middle frame
            cap = cv2.VideoCapture(str(video_path))
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 2)
            ret, frame = cap.read()
            cap.release()
            if ret:
                thumbs_dir.mkdir(parents=True, exist_ok=True)
                thumb = cv2.resize(frame, (320, 180))
                thumb_path = thumbs_dir / f"{video_path.stem}.jpg"
                cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

        return classification, thumb_path


def main() -> int:
    # Configuration from environment
    input_dir = Path(os.environ.get("INPUT_DIR", "./chunks"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "./processed"))
    poll_interval = float(os.environ.get("POLL_INTERVAL", "1"))
    threshold = int(os.environ.get("MOTION_THRESHOLD", "25"))

    # Create output directories
    folders = ["high_motion", "medium_motion", "low_motion", "no_motion"]
    for folder in folders:
        (output_dir / folder).mkdir(parents=True, exist_ok=True)

    # Thumbnails directory
    thumbs_dir = output_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    print(f"""
Starting MOTION detector (lightweight for Raspberry Pi):
  Input: {input_dir}
  Output: {output_dir}
  Poll interval: {poll_interval}s
  Motion threshold: {threshold}

Categories: high_motion | medium_motion | low_motion | no_motion

Watching for new chunks... (Ctrl+C to stop)
""")

    classifier = MotionClassifier(threshold=threshold)
    processed_files: set[str] = set()
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        print("\nShutting down...")
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        while running:
            if not input_dir.exists():
                time.sleep(poll_interval)
                continue

            # Find new video files
            video_files = sorted(input_dir.glob("*.mp4"), key=lambda p: p.name)

            for i, video_path in enumerate(video_files):
                if video_path.name in processed_files:
                    continue

                # Only process if newer chunk exists or file is old enough
                has_newer_file = i < len(video_files) - 1
                try:
                    file_age = time.time() - video_path.stat().st_mtime
                except OSError:
                    continue
                if not has_newer_file and file_age < 3:
                    continue

                # Validate file can be opened
                cap = cv2.VideoCapture(str(video_path))
                if not cap.isOpened():
                    cap.release()
                    continue
                cap.release()

                print(f"Processing: {video_path.name}")

                # Classify the video
                classification, thumb_path = classifier.classify_video(
                    video_path, thumbs_dir=thumbs_dir
                )

                # Move to appropriate folder
                if not video_path.exists():
                    processed_files.add(video_path.name)
                    print(f"  Skipped (file no longer exists)")
                    continue

                dest = output_dir / classification / video_path.name
                try:
                    shutil.move(str(video_path), str(dest))
                    thumb_info = f" [thumb: {thumb_path.name}]" if thumb_path else ""
                    print(f"  -> {classification}/ {thumb_info}")
                except Exception as e:
                    print(f"  Error moving file: {e}")
                finally:
                    processed_files.add(video_path.name)

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
