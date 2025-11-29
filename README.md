# Expanso Webcam Pipeline Demo

A progressive demo showcasing **[Expanso Cloud](https://cloud.expanso.io)** for deploying intelligent edge computing pipelines. Watch as each pipeline deployment adds new capabilities in real-time.

**[View Full Documentation](https://aronchick.github.io/webcam-demo/)**

---

## How It Works

1. **Start the demo** on your edge device (Raspberry Pi)
2. **Deploy pipelines** progressively via [cloud.expanso.io](https://cloud.expanso.io)
3. **Watch the dashboard** update as each pipeline activates

---

## Quick Start

```bash
# 1. Clone and enter directory
git clone https://github.com/aronchick/webcam-demo.git
cd webcam-demo

# 2. Start the demo (dashboard + Expanso agent)
./demo.sh

# 3. Open dashboard URL in browser (displayed in terminal)

# 4. Go to cloud.expanso.io and deploy pipelines!
```

---

## Demo Stages

| Stage | Deploy This Pipeline | What Happens |
|-------|---------------------|--------------|
| 0 | *(none)* | Empty state - "Deploy a pipeline to begin" |
| 1 | `01-capture` | Video feed appears |
| 2 | `02-detection` | **Giant hand icons flash** on gesture detection |
| 3 | `03-counting` | **Stadium scoreboard** shows LEFT vs RIGHT |
| 4 | `04-alerts` | **Confetti explosion** on both-hands gesture |

---

## Running the Demo

### Step 1: Start the Demo
```bash
./demo.sh
```
This starts the dashboard and waits for pipelines from Expanso Cloud.

### Step 2: Deploy Pipelines via Expanso Cloud

1. Open [cloud.expanso.io](https://cloud.expanso.io)
2. Navigate to your edge device
3. Deploy pipelines one at a time:
   - First: `01-capture.yaml` → Video appears
   - Then: `02-detection.yaml` → Detection starts
   - Then: `03-counting.yaml` → Scoreboard appears
   - Finally: `04-alerts.yaml` → Confetti enabled

### Step 3: Demo the Features

- **Raise LEFT hand** → Green flash + giant left arrow
- **Raise RIGHT hand** → Blue flash + giant right arrow
- **Raise BOTH hands** → Purple flash + confetti (Stage 4)

### Step 4: End the Demo
Press `Ctrl+C` - all data is automatically cleared.

---

## Local Debugging (Without Expanso Cloud)

For development and testing without Expanso Cloud:

```bash
# Interactive debug menu
./debug.sh

# Or run specific components:
./debug.sh dashboard    # Dashboard only
./debug.sh full         # Full local pipeline
./debug.sh stage 2      # Manually set stage
```

This runs everything locally - useful for testing but **not for demos**.

---

## File Structure

```
webcam-demo/
├── demo.sh              # DEMO: Start here for demos
├── debug.sh             # DEV: Local testing without Expanso
├── dashboard.py         # Web dashboard UI
├── capture_video.py     # Stage 1: Video capture
├── process_chunks.py    # Stage 2: ML detection
├── db.py               # SQLite storage
└── pipelines/          # YAML configs for Expanso Cloud
    ├── 01-capture.yaml
    ├── 02-detection.yaml
    ├── 03-counting.yaml
    └── 04-alerts.yaml
```

---

## Hardware Requirements

**Recommended:** Raspberry Pi 5 (4GB+ RAM) with USB webcam

Also works on: Linux, macOS, Windows (WSL2)

---

## Troubleshooting

### Camera not found
```bash
uv run -s capture_video.py --list-devices
export VIDEO_DEVICE=/dev/video1  # Use correct device
```

### Dashboard won't start
```bash
pkill -f dashboard.py
./demo.sh
```

### No detections
- Good lighting required
- Stand 3-6 feet from camera
- Raise hand clearly above shoulder

---

## Links

- **Expanso Cloud:** https://cloud.expanso.io
- **Documentation:** https://aronchick.github.io/webcam-demo/
- **Expanso Docs:** https://docs.expanso.io

---

## License

MIT
