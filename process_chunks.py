#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mediapipe>=0.10.0",
#     "opencv-python>=4.8.0",
# ]
# ///
"""
Video chunk processor that detects human poses and sorts videos by hand position.

Watches for new video chunks and classifies them:
  - left_hand_raised/   : Person with left hand raised
  - right_hand_raised/  : Person with right hand raised
  - both_hands_raised/  : Person with both hands raised
  - no_detection/       : No person detected or neither hand raised

Environment Variables:
    INPUT_DIR: Directory to watch for new chunks (default: "./chunks")
    OUTPUT_DIR: Base directory for sorted output (default: "./processed")
    POLL_INTERVAL: Seconds between directory scans (default: 1)
    SAMPLE_RATE: Frames to sample per second of video (default: 1)
    CONFIDENCE_THRESHOLD: Min pose detection confidence (default: 0.5)
    DB_PATH: Path to SQLite database (default: "./pipeline.db")
"""

import os

# Suppress OpenCV/ffmpeg warnings (must be set before importing cv2)
os.environ["OPENCV_LOG_LEVEL"] = "ERROR"
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"  # AV_LOG_QUIET

import shutil
import signal
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp

# Import our database module
import db


# MediaPipe pose landmark indices
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_WRIST = 15
RIGHT_WRIST = 16


class PoseClassifier:
    """Classifies video chunks based on human pose detection."""

    def __init__(self, confidence_threshold: float = 0.5):
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        self.pose = self.mp_pose.Pose(
            static_image_mode=True,
            model_complexity=1,
            min_detection_confidence=confidence_threshold,
        )
        self.confidence_threshold = confidence_threshold
        self.last_annotated_frame = None
        self.last_detection_result = None

    def is_hand_raised(self, landmarks, wrist_idx: int, shoulder_idx: int) -> bool:
        """Check if hand is raised (wrist Y < shoulder Y in image coords)."""
        wrist = landmarks.landmark[wrist_idx]
        shoulder = landmarks.landmark[shoulder_idx]

        # Y coordinates: 0 is top, 1 is bottom
        # Hand is raised if wrist is above shoulder (smaller Y value)
        # Adding margin to avoid false positives from slight movements
        margin = 0.05
        return wrist.y < (shoulder.y - margin)

    def classify_frame(self, frame, save_annotated: bool = False):
        """
        Classify a single frame.
        Returns: ('left'|'right'|'both'|'none'|None, annotated_frame or None)
        """
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.pose.process(rgb_frame)

        annotated = None
        if save_annotated and results.pose_landmarks:
            annotated = frame.copy()
            # Draw pose landmarks
            self.mp_drawing.draw_landmarks(
                annotated,
                results.pose_landmarks,
                self.mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=self.mp_drawing_styles.get_default_pose_landmarks_style()
            )
            # Draw boxes around raised hands
            h, w = frame.shape[:2]
            landmarks = results.pose_landmarks.landmark

            left_raised = self.is_hand_raised(results.pose_landmarks, LEFT_WRIST, LEFT_SHOULDER)
            right_raised = self.is_hand_raised(results.pose_landmarks, RIGHT_WRIST, RIGHT_SHOULDER)

            # Draw box around left hand if raised
            if left_raised:
                lw = landmarks[LEFT_WRIST]
                cx, cy = int(lw.x * w), int(lw.y * h)
                cv2.rectangle(annotated, (cx - 40, cy - 40), (cx + 40, cy + 40), (0, 255, 0), 3)
                cv2.putText(annotated, "LEFT", (cx - 30, cy - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

            # Draw box around right hand if raised
            if right_raised:
                rw = landmarks[RIGHT_WRIST]
                cx, cy = int(rw.x * w), int(rw.y * h)
                cv2.rectangle(annotated, (cx - 40, cy - 40), (cx + 40, cy + 40), (255, 0, 0), 3)
                cv2.putText(annotated, "RIGHT", (cx - 30, cy - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

        if not results.pose_landmarks:
            return None, annotated

        landmarks = results.pose_landmarks
        left_raised = self.is_hand_raised(landmarks, LEFT_WRIST, LEFT_SHOULDER)
        right_raised = self.is_hand_raised(landmarks, RIGHT_WRIST, RIGHT_SHOULDER)

        if left_raised and right_raised:
            return "both", annotated
        elif left_raised:
            return "left", annotated
        elif right_raised:
            return "right", annotated
        else:
            return "none", annotated

    def classify_video(self, video_path: Path, sample_rate: int = 1,
                       thumbs_dir: Path | None = None) -> tuple[str, Path | None]:
        """
        Classify a video by sampling frames.
        Returns (classification, thumbnail_path or None).
        """
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            print(f"  Error: Could not open {video_path}")
            return "no_detection", None

        fps = cap.get(cv2.CAP_PROP_FPS) or 5
        frame_interval = max(1, int(fps / sample_rate))

        classifications = []
        best_frame = None
        best_annotated = None
        frame_num = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_num % frame_interval == 0:
                # Save annotated frame for first detection
                save_annotated = thumbs_dir is not None and best_annotated is None
                result, annotated = self.classify_frame(frame, save_annotated=save_annotated)
                if result:
                    classifications.append(result)
                    if annotated is not None and best_annotated is None:
                        best_annotated = annotated
                        best_frame = frame

            frame_num += 1

        cap.release()

        # Determine classification
        if not classifications:
            classification = "no_detection"
        else:
            from collections import Counter
            counts = Counter(classifications)

            classification = "no_detection"
            for priority in ["both", "left", "right", "none"]:
                if priority in counts:
                    min_count = max(2, len(classifications) * 0.3)
                    if priority != "none" and counts[priority] >= min_count:
                        classification = priority
                        break
                    elif priority == "none":
                        classification = "no_detection"
                        break

        # Save thumbnail if we have one
        thumb_path = None
        if thumbs_dir and best_annotated is not None:
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            thumb_path = thumbs_dir / f"{video_path.stem}.jpg"
            # Resize for thumbnail
            thumb = cv2.resize(best_annotated, (320, 180))
            cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        elif thumbs_dir and best_frame is None:
            # No detection - save middle frame without annotation
            cap = cv2.VideoCapture(str(video_path))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.set(cv2.CAP_PROP_POS_FRAMES, total // 2)
            ret, frame = cap.read()
            cap.release()
            if ret:
                thumbs_dir.mkdir(parents=True, exist_ok=True)
                thumb_path = thumbs_dir / f"{video_path.stem}.jpg"
                thumb = cv2.resize(frame, (320, 180))
                cv2.imwrite(str(thumb_path), thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])

        return classification, thumb_path

    def close(self):
        self.pose.close()


def get_output_folder(classification: str) -> str:
    """Map classification to folder name."""
    mapping = {
        "left": "left_hand_raised",
        "right": "right_hand_raised",
        "both": "both_hands_raised",
        "none": "no_detection",
        "no_detection": "no_detection",
    }
    return mapping.get(classification, "no_detection")


def main() -> int:
    # Configuration from environment
    input_dir = Path(os.environ.get("INPUT_DIR", "./chunks"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "./processed"))
    poll_interval = float(os.environ.get("POLL_INTERVAL", "1"))
    sample_rate = int(os.environ.get("SAMPLE_RATE", "1"))
    confidence = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))
    db_path = Path(os.environ.get("DB_PATH", "./pipeline.db"))

    # Initialize database
    db.init_db(db_path)
    db.start_session(db_path)
    db.set_pipeline_stage(2, db_path)  # Stage 2 = detection active

    # Create output directories
    folders = [
        "left_hand_raised",
        "right_hand_raised",
        "both_hands_raised",
        "no_detection",
    ]
    for folder in folders:
        (output_dir / folder).mkdir(parents=True, exist_ok=True)

    # Thumbnails directory
    thumbs_dir = output_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    print(f"""
Starting chunk processor:
  Input: {input_dir}
  Output: {output_dir}
  Poll interval: {poll_interval}s
  Sample rate: {sample_rate} frame(s)/sec
  Confidence threshold: {confidence}

Watching for new chunks... (Ctrl+C to stop)
""")

    classifier = PoseClassifier(confidence_threshold=confidence)
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

            # Find new video files, sorted by name (oldest first)
            video_files = sorted(input_dir.glob("*.mp4"), key=lambda p: p.name)

            for i, video_path in enumerate(video_files):
                if video_path.name in processed_files:
                    continue

                # Only process if a newer chunk exists (proves this one is complete)
                # Exception: process anyway if file is old enough (>3 seconds)
                has_newer_file = i < len(video_files) - 1
                try:
                    file_age = time.time() - video_path.stat().st_mtime
                except OSError:
                    continue
                if not has_newer_file and file_age < 3:
                    continue  # Wait for next chunk or file to age

                # Validate file can be opened (safety check)
                cap = cv2.VideoCapture(str(video_path))
                if not cap.isOpened():
                    cap.release()
                    continue
                cap.release()

                print(f"Processing: {video_path.name}")

                # Classify the video and generate thumbnail (with timing)
                start_time = time.time()
                classification, thumb_path = classifier.classify_video(
                    video_path, sample_rate, thumbs_dir=thumbs_dir
                )
                processing_time_ms = (time.time() - start_time) * 1000
                folder = get_output_folder(classification)

                # Record detection in database
                db.record_detection(
                    category=folder,
                    filename=video_path.name,
                    confidence=confidence,
                    processing_time_ms=processing_time_ms,
                    db_path=db_path,
                )

                # Move to appropriate folder (check file still exists)
                if not video_path.exists():
                    processed_files.add(video_path.name)  # Mark as done to prevent retries
                    print(f"  Skipped (file no longer exists)")
                    continue

                dest = output_dir / folder / video_path.name
                try:
                    shutil.move(str(video_path), str(dest))
                    thumb_info = f" [thumb: {thumb_path.name}]" if thumb_path else ""
                    print(f"  -> {folder}/ ({classification}) [{processing_time_ms:.0f}ms]{thumb_info}")
                except Exception as e:
                    print(f"  Error moving file: {e}")
                finally:
                    # Always mark as processed to prevent endless retries
                    processed_files.add(video_path.name)

            time.sleep(poll_interval)

    finally:
        classifier.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
