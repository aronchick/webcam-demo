# Webcam Pipeline Demo - Expanso Edge Computing Showcase

## Overview

This demo showcases **Expanso** for deploying intelligent data pipelines at the edge using a Raspberry Pi with webcam for real-time video processing and ML inference.

**Key workflow:**
1. Run `./demo.py` to start services and clear data
2. Deploy pipelines progressively via **Expanso Cloud** (cloud.expanso.io)
3. Watch the dashboard update as each pipeline stage is deployed
4. Press Ctrl+C to end demo (automatically clears data)

---

## Quick Start

### 1. Install Expanso Edge Agent

```bash
# On Raspberry Pi (or any Linux device)
curl -fsSL https://get.expanso.io/edge/install.sh | sh

# Bootstrap with your network token from cloud.expanso.io
expanso-edge bootstrap --token YOUR_BOOTSTRAP_TOKEN
```

### 2. Run the Demo

```bash
./demo.py
```

This will:
- Clear all historical data (chunks/, processed/)
- Start the web dashboard on port 8181
- Clean up data when you press Ctrl+C

### 3. Deploy Pipelines via Expanso Cloud

Open https://cloud.expanso.io and deploy pipelines progressively:

| Stage | Pipeline | What Happens |
|-------|----------|--------------|
| 1 | Video Capture | Webcam feed appears, no detection |
| 2 | ML Detection | Gesture recognition starts working |
| 3 | Counting | Left vs Right score tracking |
| 4 | Alerts | Visual effects on gestures |

---

## Demo Script Usage

```bash
./demo.py              # Start demo (dashboard only, deploy via Expanso Cloud)
./demo.py --debug      # Debug mode: interactive menu for local testing
./demo.py status       # Check if services are running
./demo.py clear        # Clear all data
```

**Normal mode** (default):
- Clears `chunks/` and `processed/` directories
- Starts the web dashboard on port 8181
- Monitors dashboard and restarts if it crashes
- Clears all data on exit (Ctrl+C)

**Debug mode** (`--debug`):
- Interactive TUI with menu for local pipeline testing
- Press 1-6 to start/stop individual services
- Useful for testing without Expanso Cloud

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXPANSO CLOUD (cloud.expanso.io)                  │
│                                                                          │
│   Create and deploy pipelines here:                                      │
│   - Pipeline 1: Video Capture                                            │
│   - Pipeline 2: ML Detection                                             │
│   - Pipeline 3: Counting                                                 │
│   - Pipeline 4: Alerts                                                   │
│                                                                          │
│   Monitor telemetry, metrics, and agent health                          │
└────────────────────────────────────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      RASPBERRY PI (Edge Agent)                           │
│                                                                          │
│   expanso-edge              ./demo.py                                    │
│   (receives pipelines)      (manages demo)                              │
│                                                                          │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│   │   Webcam    │───▶│  Pipeline   │───▶│  Dashboard  │                 │
│   │   Input     │    │  Processing │    │  Port 8181  │                 │
│   └─────────────┘    └─────────────┘    └─────────────┘                 │
│                                                                          │
│   ./chunks/            ./processed/                                      │
│   (video chunks)       (classified output)                              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
webcam-demo/
├── CLAUDE.md                    # This documentation
├── demo.py                      # Demo script (normal + debug modes)
├── demo.sh                      # Thin wrapper for ./demo.py
│
├── # Core Processing Scripts (run by Expanso pipelines)
├── capture_video.py             # FFmpeg webcam capture (3s chunks)
├── process_chunks.py            # MediaPipe pose detection
├── process_motion.py            # OpenCV motion detection (lightweight)
│
├── # Dashboards
├── dashboard.py                 # Web dashboard (pose detection)
├── dashboard_motion.py          # Web dashboard (motion detection)
│
├── # Pipeline Orchestrators (standalone, no Expanso)
├── run_pipeline.py              # Full pipeline (for testing)
├── run_motion_pipeline.py       # Motion pipeline (for testing)
│
├── # Reference Pipeline Configs
├── pipelines/
│   ├── 01-capture.yaml          # Video capture config
│   ├── 02-detection.yaml        # ML detection config
│   ├── 03-counting.yaml         # Counting config
│   └── 04-alerts.yaml           # Alerts config
│
├── # Runtime Directories (auto-created, auto-cleared)
├── chunks/                      # Incoming video chunks
└── processed/                   # Classified output
    ├── left_hand_raised/
    ├── right_hand_raised/
    ├── both_hands_raised/
    ├── no_detection/
    └── thumbnails/
```

---

## Pipeline Stages (Deploy via Expanso Cloud)

### Stage 1: Video Capture
**Purpose:** Start webcam capture, show video in dashboard

The pipeline runs `capture_video.py` which:
- Captures webcam at 30fps, 1280x720
- Segments into 3-second MP4 chunks
- Writes to `./chunks/` directory

**Dashboard shows:** Video feed, but categories show 0 (no detection yet)

### Stage 2: ML Detection
**Purpose:** Add real-time pose detection

The pipeline runs `process_chunks.py` which:
- Reads chunks from `./chunks/`
- Uses MediaPipe for pose detection
- Classifies: left_hand_raised, right_hand_raised, both_hands_raised, no_detection
- Generates annotated thumbnails
- Moves to `./processed/{category}/`

**Dashboard shows:** Live detections, category counts updating

### Stage 3: Counting & Statistics
**Purpose:** Track cumulative gesture counts

Adds statistics tracking:
- Left vs Right score
- Session duration
- Gestures per minute
- Running tallies

**Dashboard shows:** Score panel, session stats

### Stage 4: Alerts & Triggers
**Purpose:** Visual effects on gestures

Triggers on detection:
- Left hand: Green flash
- Right hand: Blue flash
- Both hands: Purple celebration
- Optional webhook integration

**Dashboard shows:** Full visual effects, alert animations

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_DEVICE` | `/dev/video0` | Camera device |
| `VIDEO_SIZE` | `1280x720` | Capture resolution |
| `FRAMERATE` | `30` | Target FPS |
| `CHUNK_DURATION` | `3` | Seconds per chunk |
| `PORT` | `8181` | Dashboard port |
| `CONFIDENCE_THRESHOLD` | `0.5` | ML detection threshold |

---

## Hardware Requirements

### Raspberry Pi
- Raspberry Pi 4 or 5 (2GB+ RAM recommended)
- USB webcam or Pi Camera Module
- 16GB+ microSD
- Network connection for Expanso Cloud

### Desktop Development
- Any modern laptop with webcam
- Works on macOS, Linux, Windows (WSL2)

---

## Testing Without Expanso

To test the pipeline locally without Expanso:

```bash
# Full pose detection pipeline
./run_pipeline.py

# Lightweight motion pipeline (for Pi)
./run_motion_pipeline.py
```

These run capture, processing, and dashboard together as subprocesses.

---

## Troubleshooting

### Camera Not Found
```bash
# List cameras
uv run -s capture_video.py --list-devices

# Set specific device
export VIDEO_DEVICE=/dev/video1
```

### Expanso Agent Issues
```bash
# Check status
expanso-edge status

# View logs
expanso-edge logs -f

# Re-bootstrap
expanso-edge bootstrap --token YOUR_TOKEN
```

### Dashboard Not Loading
- Check port 8181 is free
- Try `./demo.py status`
- Check if uv is installed: `uv --version`

---

## Links

- **Expanso Cloud:** https://cloud.expanso.io
- **Expanso Docs:** https://docs.expanso.io
- **MediaPipe:** https://ai.google.dev/edge/mediapipe
- **FFmpeg:** https://ffmpeg.org
