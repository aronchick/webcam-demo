# Expanso Webcam Pipeline Demo

A progressive demo showcasing **Expanso Cloud** for deploying intelligent edge computing pipelines. Watch as each pipeline deployment adds new capabilities in real-time.

**[View Full Documentation](https://aronchick.github.io/webcam-demo/)**

---

## Quick Start

```bash
# 1. Clone and enter directory
git clone https://github.com/aronchick/webcam-demo.git
cd webcam-demo

# 2. Start the demo
./demo.sh

# 3. Open dashboard in browser
# URL will be displayed (e.g., http://192.168.1.100:8181)
```

---

## What This Demo Shows

| Stage | Pipeline | Visual Effect |
|-------|----------|---------------|
| 0 | None | Empty state - "Deploy a pipeline to begin" |
| 1 | **Capture** | Video feed appears |
| 2 | **Detection** | Giant hand icons flash + color pulse |
| 3 | **Counting** | Stadium scoreboard (LEFT vs RIGHT) |
| 4 | **Alerts** | Confetti explosion on both-hands |

---

## Demo Script (Step-by-Step)

### Pre-Demo Setup (5 min before)

```bash
# On your Raspberry Pi or demo machine:
cd webcam-demo
./demo.sh
```

Verify:
- [ ] Dashboard loads at displayed URL
- [ ] Shows "Deploy a pipeline to begin"
- [ ] Webcam is connected and working

---

### During the Demo

#### Step 1: Show Empty State
> "This is our edge device running the Expanso agent. The dashboard is ready, but no pipelines are deployed yet."

**Audience sees:** Empty video area with "Deploy a pipeline to begin"

---

#### Step 2: Deploy Capture Pipeline
> "Let's deploy our first pipeline - video capture."

**Action:** In Expanso Cloud, deploy the capture pipeline

```bash
# Or simulate locally:
curl -X POST http://localhost:8181/api/stage/1
```

**Audience sees:**
- Video feed appears
- Category counters show 0
- "Stage: 1" badge in header

---

#### Step 3: Deploy Detection Pipeline
> "Now let's add ML-powered pose detection to recognize hand gestures."

**Action:** Deploy the detection pipeline in Expanso Cloud

```bash
# Or simulate locally:
curl -X POST http://localhost:8181/api/stage/2
```

**Audience sees:**
- When you raise LEFT hand: **Giant green arrow flashes** + screen pulses green
- When you raise RIGHT hand: **Giant blue arrow flashes** + screen pulses blue
- When you raise BOTH hands: **Giant purple icon flashes** + screen pulses purple
- Counters increment in real-time

**Demo tip:** Stand back and raise hands dramatically. The indicators are visible from 20+ feet!

---

#### Step 4: Deploy Counting Pipeline
> "Let's add a scoreboard to track left vs right gestures."

**Action:** Deploy the counting pipeline

```bash
# Or simulate locally:
curl -X POST http://localhost:8181/api/stage/3
```

**Audience sees:**
- **Stadium-style scoreboard** appears: `LEFT: 5  VS  RIGHT: 3`
- Scores update live as you gesture

**Demo tip:** Challenge audience members to a "gesture battle"!

---

#### Step 5: Deploy Alerts Pipeline
> "Finally, let's add celebration effects for special events."

**Action:** Deploy the alerts pipeline

```bash
# Or simulate locally:
curl -X POST http://localhost:8181/api/stage/4
```

**Audience sees:**
- When BOTH hands raised: **Confetti explosion animation**

---

### Ending the Demo

Press `Ctrl+C` in the terminal running `./demo.sh`

This automatically:
- Stops all services
- Clears all data
- Resets for next demo

---

## Hardware Requirements

### Recommended: Raspberry Pi 5
- Raspberry Pi 5 (4GB+ RAM)
- USB webcam or Pi Camera
- Network connection

### Also Works On
- Any Linux machine with webcam
- macOS with webcam
- Windows with WSL2

---

## File Structure

```
webcam-demo/
├── demo.sh              # Start here! Runs the demo
├── dashboard.py         # Web dashboard (auto-started)
├── capture_video.py     # Video capture pipeline
├── process_chunks.py    # ML detection pipeline
├── db.py               # SQLite storage
└── pipelines/          # Pipeline YAML configs
    ├── 01-capture.yaml
    ├── 02-detection.yaml
    ├── 03-counting.yaml
    └── 04-alerts.yaml
```

---

## Troubleshooting

### Dashboard won't start
```bash
# Check if port is in use
ss -tlnp | grep 8181

# Kill any existing processes
pkill -f dashboard.py
```

### Camera not found
```bash
# List available cameras
uv run -s capture_video.py --list-devices

# Set specific device
export VIDEO_DEVICE=/dev/video1
./demo.sh
```

### No detections happening
- Ensure good lighting
- Stand 3-6 feet from camera
- Raise hand clearly above shoulder level

---

## Links

- **Expanso Cloud:** https://cloud.expanso.io
- **Expanso Docs:** https://docs.expanso.io
- **This Repo:** https://github.com/aronchick/webcam-demo

---

## License

MIT
