#!/usr/bin/env -S uv run -s
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "fastapi>=0.104.0",
#     "uvicorn>=0.24.0",
#     "websockets>=12.0",
# ]
# ///
"""
Real-time dashboard for the webcam pipeline demo.
Features progressive UI stages and giant visual indicators visible from 20 feet.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse, Response

import db

app = FastAPI(title="Webcam Pipeline Dashboard")

CHUNKS_DIR = Path(os.environ.get("CHUNKS_DIR", "./chunks"))
PROCESSED_DIR = Path(os.environ.get("PROCESSED_DIR", "./processed"))
DB_PATH = Path(os.environ.get("DB_PATH", "./pipeline.db"))
SCRIPT_DIR = Path(__file__).parent

# Initialize database on startup
db.init_db(DB_PATH)

CATEGORIES = {
    "left_hand_raised": {"emoji": "👈", "color": "#10b981", "label": "Left Hand", "icon": "hand-left"},
    "right_hand_raised": {"emoji": "👉", "color": "#3b82f6", "label": "Right Hand", "icon": "hand-right"},
    "both_hands_raised": {"emoji": "🙌", "color": "#8b5cf6", "label": "Both Hands", "icon": "hands"},
    "no_detection": {"emoji": "👤", "color": "#64748b", "label": "No Detection", "icon": "user"},
}


def get_stats() -> dict:
    """Get current pipeline statistics from database and filesystem."""
    # Get database stats
    db_stats = db.get_full_stats(DB_PATH)

    stats = {
        "stage": db_stats["stage"],
        "pending": 0,
        "pending_files": [],
        "categories": {},
        "latest_video": None,
        "latest_thumb": None,
        "recent_events": [],
        "total_processed": 0,
        "session": db_stats["session"],
        "latest_detection": db_stats["latest"],
    }

    # Get pending chunks from filesystem
    if CHUNKS_DIR.exists():
        pending = sorted(CHUNKS_DIR.glob("*.mp4"), key=lambda p: p.name)
        stats["pending"] = len(pending)
        stats["pending_files"] = [p.name for p in pending[-3:]]

    # Use database counts
    db_counts = db_stats["counts"]

    # Count by category and find latest video
    latest_mtime = 0
    thumbs_dir = PROCESSED_DIR / "thumbnails"

    for cat_name, cat_info in CATEGORIES.items():
        cat_dir = PROCESSED_DIR / cat_name
        files = []
        if cat_dir.exists():
            files = sorted(
                cat_dir.glob("*.mp4"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )

        # Use DB count if available, else file count
        db_count = db_counts.get(cat_name, {}).get("count", 0)
        file_count = len(files)
        count = max(db_count, file_count)

        stats["categories"][cat_name] = {
            "count": count,
            **cat_info,
        }
        stats["total_processed"] += count

        # Track latest video
        if files:
            mtime = files[0].stat().st_mtime
            if mtime > latest_mtime:
                latest_mtime = mtime
                stats["latest_video"] = {
                    "category": cat_name,
                    "filename": files[0].name,
                    "path": f"/video/{cat_name}/{files[0].name}",
                    **cat_info,
                }
                # Check for thumbnail
                thumb_name = files[0].stem + ".jpg"
                thumb_path = thumbs_dir / thumb_name
                if thumb_path.exists():
                    stats["latest_thumb"] = f"/thumb/{thumb_name}"

            # Add recent events
            for f in files[:4]:
                thumb_name = f.stem + ".jpg"
                thumb_exists = (thumbs_dir / thumb_name).exists() if thumbs_dir.exists() else False
                stats["recent_events"].append({
                    "filename": f.name,
                    "category": cat_name,
                    "thumb": f"/thumb/{thumb_name}" if thumb_exists else None,
                    "mtime": f.stat().st_mtime,
                    **cat_info,
                })

    stats["recent_events"] = sorted(
        stats["recent_events"],
        key=lambda x: x["mtime"],
        reverse=True
    )[:8]

    return stats


@app.get("/video/{category}/{filename}")
async def serve_video(category: str, filename: str, request: Request):
    """Serve video files with caching."""
    video_path = PROCESSED_DIR / category / filename
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video not found")

    # Generate ETag from file stats
    stat = video_path.stat()
    etag = f'"{stat.st_mtime}-{stat.st_size}"'

    # Check If-None-Match for 304 response
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    return FileResponse(
        video_path,
        media_type="video/mp4",
        headers={
            "Cache-Control": "public, max-age=3600",
            "ETag": etag,
        }
    )


@app.get("/thumb/{filename}")
async def serve_thumb(filename: str, request: Request):
    """Serve thumbnail images with caching."""
    thumb_path = PROCESSED_DIR / "thumbnails" / filename
    if not thumb_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    # Generate ETag from file stats
    stat = thumb_path.stat()
    etag = f'"{stat.st_mtime}-{stat.st_size}"'

    # Check If-None-Match for 304 response
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)

    return FileResponse(
        thumb_path,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=86400",  # 24 hours for thumbnails
            "ETag": etag,
        }
    )


@app.post("/api/stage/{stage}")
async def set_stage(stage: int, source: str = "expanso"):
    """Set the current pipeline stage (called by pipelines on activation).

    Args:
        stage: Pipeline stage 0-4
        source: 'expanso' (from Expanso Cloud) or 'local' (from TUI debug mode)
    """
    if stage < 0 or stage > 4:
        raise HTTPException(status_code=400, detail="Stage must be 0-4")
    if source not in ("expanso", "local"):
        source = "expanso"
    db.set_pipeline_stage(stage, DB_PATH, source=source)
    return {"status": "ok", "stage": stage, "source": source}


@app.get("/api/stage")
async def get_stage():
    """Get the current pipeline stage."""
    return {"stage": db.get_pipeline_stage(DB_PATH)}


@app.get("/api/stats")
async def get_api_stats():
    """Get full stats as JSON."""
    return get_stats()


@app.get("/api/pipelines")
async def get_pipelines():
    """Return all pipeline YAML configs."""
    pipelines_dir = SCRIPT_DIR / "pipelines"
    pipelines = []
    if pipelines_dir.exists():
        for yaml_file in sorted(pipelines_dir.glob("*.yaml")):
            pipelines.append({
                "name": yaml_file.stem,
                "filename": yaml_file.name,
                "content": yaml_file.read_text(),
            })
    return pipelines


@app.get("/api/pipeline/{filename}")
async def get_pipeline(filename: str):
    """Return a specific pipeline YAML."""
    yaml_path = SCRIPT_DIR / "pipelines" / filename
    if yaml_path.exists() and yaml_path.suffix == ".yaml":
        return PlainTextResponse(yaml_path.read_text(), media_type="text/yaml")
    return {"error": "not found"}


def compute_delta(old_stats: dict, new_stats: dict) -> dict | None:
    """Compute minimal delta between two stats objects."""
    if old_stats is None:
        return None  # Need full update

    delta = {}
    for key, value in new_stats.items():
        old_value = old_stats.get(key)
        if old_value != value:
            # For nested dicts, check if they actually changed
            if isinstance(value, dict) and isinstance(old_value, dict):
                if json.dumps(value, default=str) != json.dumps(old_value, default=str):
                    delta[key] = value
            else:
                delta[key] = value

    return delta if delta else None


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates with delta compression."""
    await websocket.accept()

    try:
        last_stats = None
        message_count = 0
        last_activity = time.time()

        while True:
            stats = get_stats()

            # Add server timestamp for latency measurement
            stats["server_ts"] = int(time.time() * 1000)

            # Every 10th message or first message: send full state
            if message_count % 10 == 0 or last_stats is None:
                await websocket.send_json({"type": "full", "data": stats})
                last_stats = stats.copy()
                last_activity = time.time()
            else:
                # Send delta only
                delta = compute_delta(last_stats, stats)
                if delta:
                    await websocket.send_json({"type": "delta", "data": delta})
                    last_stats = stats.copy()
                    last_activity = time.time()

            message_count += 1

            # Adaptive polling: faster when active, slower when idle
            idle_time = time.time() - last_activity
            if idle_time < 5:
                await asyncio.sleep(0.2)  # 200ms when active
            elif idle_time < 30:
                await asyncio.sleep(0.3)  # 300ms normal
            else:
                await asyncio.sleep(0.5)  # 500ms when idle

    except WebSocketDisconnect:
        pass


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Render the dashboard."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Expanso Pipeline Demo</title>
    <style>
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-tertiary: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --accent-purple: #8b5cf6;
            --accent-amber: #f59e0b;
            --accent-cyan: #06b6d4;
            --border: rgba(255,255,255,0.1);
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }
        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0 20px;
        }
        .logo { display: flex; align-items: center; gap: 12px; }
        .logo-icon {
            width: 50px; height: 50px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.8em;
        }
        .logo-text h1 {
            font-size: 1.8em;
            background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .logo-text p { font-size: 0.85em; color: var(--text-muted); }

        .header-right { display: flex; align-items: center; gap: 16px; }
        .stage-badge {
            padding: 10px 20px;
            background: var(--bg-secondary);
            border: 2px solid var(--border);
            border-radius: 12px;
            font-size: 1em;
            font-weight: 700;
        }
        .stage-badge.active { border-color: var(--accent-green); }

        /* Connection/Latency indicator */
        .connection-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 14px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 12px;
            font-size: 0.85em;
        }
        .latency-bar {
            width: 50px;
            height: 6px;
            background: var(--bg-tertiary);
            border-radius: 3px;
            overflow: hidden;
        }
        .latency-fill {
            height: 100%;
            width: 100%;
            transition: background 0.2s;
        }
        .latency-fill.good { background: var(--accent-green); }
        .latency-fill.fair { background: var(--accent-amber); }
        .latency-fill.poor { background: #ef4444; }
        .latency-value { font-family: monospace; min-width: 45px; }

        /* Stage progress indicator */
        .stage-progress {
            display: flex;
            gap: 8px;
            align-items: center;
            margin-bottom: 16px;
            padding: 16px;
            background: var(--bg-secondary);
            border-radius: 16px;
            border: 1px solid var(--border);
        }
        .stage-step {
            flex: 1;
            padding: 12px 8px;
            background: var(--bg-tertiary);
            border-radius: 8px;
            text-align: center;
            font-size: 0.75em;
            color: var(--text-muted);
            transition: background 0.15s, border-color 0.15s, color 0.15s;
            border: 2px solid transparent;
        }
        .stage-step.active {
            background: rgba(16,185,129,0.2);
            border-color: var(--accent-green);
            color: var(--text-primary);
        }
        .stage-step.completed {
            background: rgba(16,185,129,0.1);
            color: var(--accent-green);
        }
        .stage-step .step-num {
            font-size: 1.5em;
            font-weight: 900;
            display: block;
            margin-bottom: 4px;
        }
        .stage-step .step-label { font-weight: 600; }
        .stage-step .step-source {
            font-size: 0.85em;
            margin-top: 4px;
            opacity: 0.7;
        }
        .status-badge {
            display: flex; align-items: center; gap: 8px;
            padding: 10px 20px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 20px;
            font-size: 0.9em; font-weight: 600;
        }
        .status-dot {
            width: 10px; height: 10px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 1.5s infinite;
        }
        .status-dot.disconnected { background: #ef4444; animation: none; }
        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }
            50% { opacity: 0.8; box-shadow: 0 0 0 10px rgba(16,185,129,0); }
        }

        /* Main Layout */
        .main-layout {
            display: grid;
            grid-template-columns: 1fr 400px;
            gap: 24px;
        }
        @media (max-width: 1200px) { .main-layout { grid-template-columns: 1fr; } }

        /* Video Section */
        .video-section {
            background: var(--bg-secondary);
            border-radius: 24px;
            padding: 24px;
            border: 1px solid var(--border);
            position: relative;
            overflow: hidden;
        }
        .video-container {
            position: relative;
            aspect-ratio: 16/9;
            background: #000;
            border-radius: 16px;
            overflow: hidden;
        }
        .video-container video {
            width: 100%;
            height: 100%;
            object-fit: contain;
            transition: opacity 0.1s ease-in-out;
            background: #000;
        }
        .video-container video.active { z-index: 2; }
        .video-container video.preloading { z-index: 1; }

        /* Buffering indicator overlay */
        .buffer-overlay {
            position: absolute;
            inset: 0;
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(0,0,0,0.7);
            z-index: 10;
            gap: 16px;
        }
        .buffer-overlay.visible { display: flex; }
        .buffer-spinner {
            width: 50px;
            height: 50px;
            border: 4px solid rgba(255,255,255,0.2);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .buffer-text { font-size: 1.1em; color: white; }

        /* Buffer health indicator */
        .buffer-health {
            position: absolute;
            bottom: 12px;
            right: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 12px;
            background: rgba(0,0,0,0.6);
            border-radius: 8px;
            font-size: 0.75em;
            z-index: 15;
            color: white;
        }
        .buffer-bar {
            width: 50px;
            height: 6px;
            background: rgba(255,255,255,0.2);
            border-radius: 3px;
            overflow: hidden;
        }
        .buffer-fill {
            height: 100%;
            background: var(--accent-green);
            transition: width 0.2s, background 0.2s;
        }
        .buffer-fill.warning { background: var(--accent-amber); }
        .buffer-fill.danger { background: #ef4444; }

        /* Empty state (Stage 0) */
        .empty-state {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, rgba(59,130,246,0.1), rgba(139,92,246,0.1));
            gap: 20px;
        }
        .empty-state.hidden { display: none; }
        .empty-icon { font-size: 5em; opacity: 0.3; }
        .empty-text { font-size: 1.5em; color: var(--text-muted); text-align: center; }
        .empty-subtext { font-size: 1em; color: var(--text-muted); opacity: 0.7; }

        /* Giant Detection Indicator - BELOW video, not overlay */
        .detection-giant {
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px 0;
            margin-top: 16px;
            background: var(--bg-tertiary);
            border-radius: 16px;
            min-height: 180px;
        }
        .detection-giant.visible { display: flex; }
        .detection-giant svg {
            width: 300px;
            height: 160px;
            filter: drop-shadow(0 0 40px currentColor) drop-shadow(0 0 20px currentColor);
            animation: detectPulse 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        @keyframes detectPulse {
            0% { transform: scale(0.3) rotate(-10deg); opacity: 0; }
            60% { transform: scale(1.15) rotate(3deg); }
            100% { transform: scale(1) rotate(0deg); opacity: 1; }
        }
        /* Continuous glow animation while visible */
        .detection-giant.visible svg {
            animation: detectPulse 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), glowPulse 1.5s ease-in-out infinite 0.3s;
        }
        @keyframes glowPulse {
            0%, 100% { filter: drop-shadow(0 0 30px currentColor) drop-shadow(0 0 15px currentColor); }
            50% { filter: drop-shadow(0 0 60px currentColor) drop-shadow(0 0 30px currentColor); }
        }

        /* Color flash overlay */
        .flash-overlay {
            position: absolute;
            inset: 0;
            opacity: 0;
            pointer-events: none;
            z-index: 5;
            transition: opacity 0.15s;
        }
        .flash-overlay.flash {
            animation: flashAnim 0.6s ease-out;
        }
        @keyframes flashAnim {
            0% { opacity: 0.7; }
            30% { opacity: 0.4; }
            100% { opacity: 0; }
        }

        /* Pulsing border - much more dramatic */
        .video-section.detecting {
            animation: borderPulse 0.8s ease-in-out infinite;
        }
        @keyframes borderPulse {
            0%, 100% {
                box-shadow: 0 0 0 6px transparent, 0 0 40px var(--detect-color, var(--accent-green));
            }
            50% {
                box-shadow: 0 0 0 6px var(--detect-color, var(--accent-green)), 0 0 80px var(--detect-color, var(--accent-green));
            }
        }

        /* Scoreboard */
        .scoreboard {
            display: none;
            grid-template-columns: 1fr auto 1fr;
            gap: 20px;
            margin-top: 24px;
            padding: 24px;
            background: var(--bg-tertiary);
            border-radius: 16px;
            align-items: center;
        }
        .scoreboard.visible { display: grid; }
        .score-side {
            text-align: center;
            padding: 20px;
            border-radius: 12px;
            background: rgba(0,0,0,0.2);
        }
        .score-side.left { border: 3px solid var(--accent-green); }
        .score-side.right { border: 3px solid var(--accent-blue); }
        .score-label {
            font-size: 1.5em;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 10px;
        }
        .score-value {
            font-size: 5em;
            font-weight: 900;
            font-family: 'SF Mono', monospace;
            line-height: 1;
        }
        .score-side.left .score-label { color: var(--accent-green); }
        .score-side.left .score-value { color: var(--accent-green); }
        .score-side.right .score-label { color: var(--accent-blue); }
        .score-side.right .score-value { color: var(--accent-blue); }
        .score-vs {
            font-size: 2em;
            font-weight: 900;
            color: var(--text-muted);
        }

        /* Stats row */
        .stats-row {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-top: 20px;
        }
        .stat-card {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
        }
        .stat-label { font-size: 0.75em; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; }
        .stat-value { font-size: 1.8em; font-weight: bold; font-family: monospace; margin-top: 4px; }

        /* Sidebar */
        .sidebar { display: flex; flex-direction: column; gap: 20px; }

        /* Category cards */
        .category-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }
        .cat-card {
            background: var(--bg-secondary);
            border: 3px solid var(--border);
            border-radius: 20px;
            padding: 24px;
            text-align: center;
            transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
        }
        .cat-card.active {
            transform: scale(1.05);
            box-shadow: 0 10px 40px rgba(0,0,0,0.4);
        }
        .cat-icon {
            font-size: 3em;
            margin-bottom: 8px;
        }
        .cat-count {
            font-size: 3em;
            font-weight: 900;
            font-family: monospace;
        }
        .cat-label {
            font-size: 0.9em;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 4px;
        }

        /* Event log */
        .event-log {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 20px;
            flex: 1;
            min-height: 300px;
            display: flex;
            flex-direction: column;
        }
        .event-log-header {
            font-size: 0.9em;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
            margin-bottom: 16px;
        }
        .event-list {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .event-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px;
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            border-left: 4px solid var(--border);
        }
        .event-item.new { animation: slideIn 0.15s ease-out; }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-20px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .event-thumb {
            width: 64px; height: 36px;
            border-radius: 6px;
            background: var(--bg-tertiary);
            overflow: hidden;
            flex-shrink: 0;
            position: relative;
        }
        .event-thumb img { width: 100%; height: 100%; object-fit: cover; }
        .event-thumb.loading::after {
            content: '';
            position: absolute;
            inset: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent);
            animation: shimmer 1.5s infinite;
        }
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        .event-details { flex: 1; }
        .event-category { font-weight: 600; }
        .event-time { font-size: 0.8em; color: var(--text-muted); }

        /* Confetti container */
        .confetti-container {
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 100;
            overflow: hidden;
        }
        .confetti {
            position: absolute;
            width: 12px;
            height: 12px;
            opacity: 0;
        }
        .confetti.animate {
            animation: confettiFall 3s ease-out forwards;
        }
        @keyframes confettiFall {
            0% { transform: translateY(-100px) rotate(0deg); opacity: 1; }
            100% { transform: translateY(100vh) rotate(720deg); opacity: 0; }
        }

        /* Performance display */
        .perf-display {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: rgba(0,0,0,0.8);
            padding: 12px 20px;
            border-radius: 10px;
            font-family: monospace;
            font-size: 0.85em;
            color: var(--accent-green);
            z-index: 50;
        }

        /* Tab styles */
        .tab-nav {
            display: flex;
            gap: 8px;
            margin-bottom: 24px;
        }
        .tab-btn {
            padding: 12px 24px;
            border: none;
            background: var(--bg-secondary);
            color: var(--text-muted);
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            border-radius: 12px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .tab-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); }
        .tab-btn.active {
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            color: white;
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }

        /* Pipelines tab */
        .pipeline-card {
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 16px;
            margin-bottom: 20px;
            overflow: hidden;
        }
        .pipeline-header {
            padding: 20px;
            background: var(--bg-tertiary);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .pipeline-title { font-size: 1.2em; font-weight: 700; }
        .btn-copy {
            padding: 10px 20px;
            background: var(--accent-blue);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-copy:hover { background: #2563eb; }
        .pipeline-code {
            padding: 20px;
            background: var(--bg-primary);
            font-family: monospace;
            font-size: 0.85em;
            line-height: 1.6;
            overflow-x: auto;
            white-space: pre;
        }
    </style>
</head>
<body>
    <div class="confetti-container" id="confetti-container"></div>

    <div class="container">
        <header class="header">
            <div class="logo">
                <div class="logo-icon">🚀</div>
                <div class="logo-text">
                    <h1>Expanso Pipeline Demo</h1>
                    <p>Edge Computing in Action</p>
                </div>
            </div>
            <div class="header-right">
                <div class="connection-indicator">
                    <div class="latency-bar">
                        <div class="latency-fill good" id="latency-fill"></div>
                    </div>
                    <span class="latency-value" id="latency-value">--ms</span>
                </div>
                <div class="stage-badge" id="stage-badge">Stage: <span id="stage-num">0</span></div>
                <div class="status-badge">
                    <span class="status-dot" id="status-dot"></span>
                    <span id="status-text">Connecting...</span>
                </div>
            </div>
        </header>

        <nav class="tab-nav">
            <button class="tab-btn active" onclick="switchTab('dashboard')">
                <span>📊</span> Dashboard
            </button>
            <button class="tab-btn" onclick="switchTab('pipelines')">
                <span>🔧</span> Pipelines
            </button>
        </nav>

        <!-- Dashboard Tab -->
        <div id="tab-dashboard" class="tab-content active">
            <!-- Stage Progress Indicator -->
            <div class="stage-progress" id="stage-progress">
                <div class="stage-step" data-stage="1">
                    <span class="step-num">1</span>
                    <span class="step-label">Capture</span>
                    <span class="step-source" id="stage1-source"></span>
                </div>
                <div class="stage-step" data-stage="2">
                    <span class="step-num">2</span>
                    <span class="step-label">Detection</span>
                    <span class="step-source" id="stage2-source"></span>
                </div>
                <div class="stage-step" data-stage="3">
                    <span class="step-num">3</span>
                    <span class="step-label">Counting</span>
                    <span class="step-source" id="stage3-source"></span>
                </div>
                <div class="stage-step" data-stage="4">
                    <span class="step-num">4</span>
                    <span class="step-label">Alerts</span>
                    <span class="step-source" id="stage4-source"></span>
                </div>
            </div>

            <div class="main-layout">
                <div class="video-section" id="video-section">
                    <div class="video-container" id="video-container">
                        <!-- Double-buffered video players for seamless playback -->
                        <video id="video-player-a" autoplay muted playsinline style="position:absolute;inset:0;width:100%;height:100%;"></video>
                        <video id="video-player-b" autoplay muted playsinline style="position:absolute;inset:0;width:100%;height:100%;opacity:0;"></video>

                        <!-- Empty state overlay -->
                        <div class="empty-state" id="empty-state">
                            <div class="empty-icon">🎬</div>
                            <div class="empty-text">Deploy a pipeline to begin</div>
                            <div class="empty-subtext">Go to Pipelines tab and deploy Stage 1</div>
                        </div>

                        <!-- Flash overlay for detections -->
                        <div class="flash-overlay" id="flash-overlay"></div>

                        <!-- Buffering overlay -->
                        <div class="buffer-overlay" id="buffer-overlay">
                            <div class="buffer-spinner"></div>
                            <div class="buffer-text">Buffering...</div>
                        </div>

                        <!-- Buffer health indicator -->
                        <div class="buffer-health" id="buffer-health">
                            <div class="buffer-bar">
                                <div class="buffer-fill" id="buffer-fill"></div>
                            </div>
                            <span id="buffer-label">0/3</span>
                        </div>
                    </div>

                    <!-- Giant detection indicator - BELOW video -->
                    <div class="detection-giant" id="detection-giant">
                        <!-- SVG will be inserted here -->
                    </div>

                    <!-- Scoreboard (Stage 3+) -->
                    <div class="scoreboard" id="scoreboard">
                        <div class="score-side left">
                            <div class="score-label">Left Hand</div>
                            <div class="score-value" id="score-left">0</div>
                        </div>
                        <div class="score-vs">VS</div>
                        <div class="score-side right">
                            <div class="score-label">Right Hand</div>
                            <div class="score-value" id="score-right">0</div>
                        </div>
                    </div>

                    <!-- Real-time metrics row -->
                    <div class="stats-row" style="margin-bottom: 12px;">
                        <div class="stat-card">
                            <div class="stat-label">Update Rate</div>
                            <div class="stat-value" id="update-rate">--/s</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Latency</div>
                            <div class="stat-value" id="latency-stat">--ms</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Buffer</div>
                            <div class="stat-value" id="buffer-stat">0/3</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Queue</div>
                            <div class="stat-value" id="queue-stat">0</div>
                        </div>
                    </div>

                    <!-- Stats row -->
                    <div class="stats-row">
                        <div class="stat-card">
                            <div class="stat-label">Total Processed</div>
                            <div class="stat-value" id="total-processed">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Pending</div>
                            <div class="stat-value" id="pending-count">0</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Avg Time</div>
                            <div class="stat-value" id="avg-time">--</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">Session</div>
                            <div class="stat-value" id="session-duration">0:00</div>
                        </div>
                    </div>
                </div>

                <div class="sidebar">
                    <div class="category-grid" id="category-grid"></div>

                    <div class="event-log">
                        <div class="event-log-header">Recent Activity</div>
                        <div class="event-list" id="event-list">
                            <div style="color: var(--text-muted); text-align: center; padding: 40px;">
                                Waiting for detections...
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Pipelines Tab -->
        <div id="tab-pipelines" class="tab-content">
            <div id="pipelines-container">
                <div style="color: var(--text-muted); text-align: center; padding: 60px;">
                    Loading pipelines...
                </div>
            </div>
        </div>
    </div>

    <div class="perf-display" id="perf-display">
        Processing: <span id="perf-time">--</span>ms
    </div>

    <script>
        // SVG icons for giant detection display - designed to be visible from 20+ feet
        const HAND_SVGS = {
            left_hand_raised: `<svg viewBox="0 0 200 200" style="color: #10b981;">
                <!-- Glowing background circle -->
                <circle cx="100" cy="85" r="70" fill="rgba(16,185,129,0.15)"/>
                <circle cx="100" cy="85" r="55" fill="rgba(16,185,129,0.2)"/>
                <!-- Large pointing hand (left) -->
                <g transform="translate(100,85)">
                    <!-- Hand base -->
                    <ellipse cx="15" cy="0" rx="30" ry="25" fill="rgba(16,185,129,0.3)" stroke="#10b981" stroke-width="4"/>
                    <!-- Pointing finger -->
                    <path d="M-15,0 L-60,0" stroke="#10b981" stroke-width="12" stroke-linecap="round"/>
                    <!-- Arrow head -->
                    <path d="M-50,-18 L-70,0 L-50,18" stroke="#10b981" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </g>
                <!-- Large label -->
                <text x="100" y="175" text-anchor="middle" fill="#10b981" font-size="28" font-weight="900" font-family="system-ui">LEFT</text>
            </svg>`,
            right_hand_raised: `<svg viewBox="0 0 200 200" style="color: #3b82f6;">
                <!-- Glowing background circle -->
                <circle cx="100" cy="85" r="70" fill="rgba(59,130,246,0.15)"/>
                <circle cx="100" cy="85" r="55" fill="rgba(59,130,246,0.2)"/>
                <!-- Large pointing hand (right) -->
                <g transform="translate(100,85)">
                    <!-- Hand base -->
                    <ellipse cx="-15" cy="0" rx="30" ry="25" fill="rgba(59,130,246,0.3)" stroke="#3b82f6" stroke-width="4"/>
                    <!-- Pointing finger -->
                    <path d="M15,0 L60,0" stroke="#3b82f6" stroke-width="12" stroke-linecap="round"/>
                    <!-- Arrow head -->
                    <path d="M50,-18 L70,0 L50,18" stroke="#3b82f6" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </g>
                <!-- Large label -->
                <text x="100" y="175" text-anchor="middle" fill="#3b82f6" font-size="28" font-weight="900" font-family="system-ui">RIGHT</text>
            </svg>`,
            both_hands_raised: `<svg viewBox="0 0 200 200" style="color: #8b5cf6;">
                <!-- Glowing background -->
                <ellipse cx="100" cy="75" rx="85" ry="60" fill="rgba(139,92,246,0.15)"/>
                <ellipse cx="100" cy="75" rx="70" ry="45" fill="rgba(139,92,246,0.2)"/>
                <!-- Two raised hands -->
                <g transform="translate(55,75)">
                    <ellipse cx="0" cy="15" rx="22" ry="18" fill="rgba(139,92,246,0.3)" stroke="#8b5cf6" stroke-width="3"/>
                    <path d="M0,0 L0,-40" stroke="#8b5cf6" stroke-width="10" stroke-linecap="round"/>
                    <path d="M-12,-30 L0,-45 L12,-30" stroke="#8b5cf6" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </g>
                <g transform="translate(145,75)">
                    <ellipse cx="0" cy="15" rx="22" ry="18" fill="rgba(139,92,246,0.3)" stroke="#8b5cf6" stroke-width="3"/>
                    <path d="M0,0 L0,-40" stroke="#8b5cf6" stroke-width="10" stroke-linecap="round"/>
                    <path d="M-12,-30 L0,-45 L12,-30" stroke="#8b5cf6" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
                </g>
                <!-- Large label -->
                <text x="100" y="175" text-anchor="middle" fill="#8b5cf6" font-size="24" font-weight="900" font-family="system-ui">BOTH HANDS!</text>
            </svg>`,
        };

        const COLORS = {
            left_hand_raised: '#10b981',
            right_hand_raised: '#3b82f6',
            both_hands_raised: '#8b5cf6',
            no_detection: '#64748b',
        };

        const LABELS = {
            left_hand_raised: 'Left Hand',
            right_hand_raised: 'Right Hand',
            both_hands_raised: 'Both Hands',
            no_detection: 'No Detection',
        };

        let ws;
        let currentVideo = null;
        let currentStage = 0;
        let lastDetectionVideo = null;  // Track which video we last showed effects for
        let seenEvents = new Set();

        // Video queue for simulating live stream
        let videoQueue = [];
        let playedVideos = new Set();
        let isPlaying = false;

        // Multi-video preload buffer (3 videos ahead for zero-gap playback)
        const PRELOAD_BUFFER_SIZE = 3;
        let preloadBuffer = [];  // Array of {path, element, ready, category}
        let activePlayer = 'a';
        let bufferCheckInterval = null;

        function switchTab(name) {
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            event.target.closest('.tab-btn').classList.add('active');
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.getElementById('tab-' + name).classList.add('active');

            if (name === 'pipelines') loadPipelines();
        }

        async function loadPipelines() {
            try {
                const res = await fetch('/api/pipelines');
                const pipelines = await res.json();

                let html = '';
                pipelines.forEach((p, i) => {
                    html += `
                        <div class="pipeline-card">
                            <div class="pipeline-header">
                                <div class="pipeline-title">Stage ${i+1}: ${p.name}</div>
                                <button class="btn-copy" onclick="copyPipeline('${p.name}')">Copy YAML</button>
                            </div>
                            <div class="pipeline-code">${escapeHtml(p.content)}</div>
                        </div>
                    `;
                });
                document.getElementById('pipelines-container').innerHTML = html;
            } catch (e) {
                document.getElementById('pipelines-container').innerHTML =
                    '<div style="color: #ef4444; text-align: center; padding: 40px;">Error loading pipelines</div>';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function copyPipeline(name) {
            const res = await fetch('/api/pipeline/' + name + '.yaml');
            const yaml = await res.text();
            navigator.clipboard.writeText(yaml);
            alert('Copied to clipboard!');
        }

        function triggerFlash(category) {
            const flash = document.getElementById('flash-overlay');
            const color = COLORS[category] || COLORS.no_detection;
            flash.style.background = color;
            flash.classList.remove('flash');
            void flash.offsetWidth; // Trigger reflow
            flash.classList.add('flash');
        }

        function showGiantIndicator(category) {
            const giant = document.getElementById('detection-giant');
            if (HAND_SVGS[category]) {
                giant.innerHTML = HAND_SVGS[category];
                giant.classList.add('visible');
                setTimeout(() => giant.classList.remove('visible'), 2000);
            }
        }

        function triggerConfetti() {
            const container = document.getElementById('confetti-container');
            const colors = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444'];

            for (let i = 0; i < 50; i++) {
                const confetti = document.createElement('div');
                confetti.className = 'confetti';
                confetti.style.left = Math.random() * 100 + '%';
                confetti.style.background = colors[Math.floor(Math.random() * colors.length)];
                confetti.style.animationDelay = Math.random() * 0.5 + 's';
                container.appendChild(confetti);

                setTimeout(() => confetti.classList.add('animate'), 10);
                setTimeout(() => confetti.remove(), 3500);
            }
        }

        function updateStageUI(stage, hasVideo, stageSource) {
            currentStage = stage;
            document.getElementById('stage-num').textContent = stage;

            const stageBadge = document.getElementById('stage-badge');
            stageBadge.classList.toggle('active', stage > 0);

            // Update stage progress indicator
            document.querySelectorAll('.stage-step').forEach(step => {
                const stepStage = parseInt(step.dataset.stage);
                step.classList.remove('active', 'completed');
                if (stepStage < stage) {
                    step.classList.add('completed');
                } else if (stepStage === stage) {
                    step.classList.add('active');
                }
            });

            // Show source info (expanso or local TUI)
            if (stageSource) {
                const sourceEl = document.getElementById(`stage${stage}-source`);
                if (sourceEl) {
                    sourceEl.textContent = stageSource === 'expanso' ? '(Expanso)' : '(Local)';
                }
            }

            // Only show empty state if stage is 0 AND no video is available
            // Once we have video, never show empty state again
            const showEmpty = (stage === 0) && !hasVideo && !currentVideo;
            document.getElementById('empty-state').classList.toggle('hidden', !showEmpty);
            document.getElementById('scoreboard').classList.toggle('visible', stage >= 3);
        }

        function formatDuration(seconds) {
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins}:${secs.toString().padStart(2, '0')}`;
        }

        function updateDashboard(data) {
            // Update stage - pass hasVideo to prevent empty state showing when we have video
            if (data.stage !== undefined) {
                updateStageUI(data.stage, !!data.latest_video, data.stage_source);
            }

            // Update stats
            document.getElementById('total-processed').textContent = data.total_processed;
            document.getElementById('pending-count').textContent = data.pending;

            if (data.session) {
                document.getElementById('session-duration').textContent =
                    formatDuration(data.session.duration_seconds || 0);
            }

            // Update scoreboard
            if (data.categories) {
                const leftCount = data.categories.left_hand_raised?.count || 0;
                const rightCount = data.categories.right_hand_raised?.count || 0;
                document.getElementById('score-left').textContent = leftCount;
                document.getElementById('score-right').textContent = rightCount;
            }

            // Update category cards
            let catHtml = '';
            for (const [name, info] of Object.entries(data.categories || {})) {
                const isActive = data.latest_video?.category === name;
                const color = COLORS[name];
                catHtml += `
                    <div class="cat-card ${isActive ? 'active' : ''}"
                         style="border-color: ${isActive ? color : 'var(--border)'}">
                        <div class="cat-icon">${info.emoji}</div>
                        <div class="cat-count" style="color: ${color}">${info.count}</div>
                        <div class="cat-label">${LABELS[name]}</div>
                    </div>
                `;
            }
            document.getElementById('category-grid').innerHTML = catHtml;

            // Handle new detection - trigger effects when we have a NEW video with a detection
            if (data.latest_video && data.latest_video.category !== 'no_detection') {
                const cat = data.latest_video.category;
                const videoPath = data.latest_video.path;

                // Trigger effects if this is a NEW video (not just same category)
                if (videoPath !== lastDetectionVideo) {
                    lastDetectionVideo = videoPath;

                    // Stage 2+: Show flash and giant indicator
                    if (currentStage >= 2) {
                        triggerFlash(cat);
                        showGiantIndicator(cat);

                        // Pulsing border
                        const section = document.getElementById('video-section');
                        section.style.setProperty('--detect-color', COLORS[cat]);
                        section.classList.add('detecting');
                        setTimeout(() => section.classList.remove('detecting'), 3000);
                    }

                    // Stage 4: Confetti for both hands
                    if (currentStage >= 4 && cat === 'both_hands_raised') {
                        triggerConfetti();
                    }
                }
            }

            // Build video queue from recent events (for continuous playback)
            if (data.recent_events?.length > 0) {
                data.recent_events.forEach(e => {
                    const path = `/video/${e.category}/${e.filename}`;
                    if (!playedVideos.has(path) && !videoQueue.find(v => v.path === path)) {
                        videoQueue.push({ path, category: e.category });
                    }
                });
                // Keep queue sorted by filename (oldest first for playback order)
                videoQueue.sort((a, b) => a.path.localeCompare(b.path));
                // Limit queue size
                while (videoQueue.length > 10) {
                    const removed = videoQueue.shift();
                    playedVideos.add(removed.path);
                }
            }

            // Start playing if not already
            if (!isPlaying && videoQueue.length > 0) {
                playNextVideo();
            }

            // Update perf display
            if (data.latest_detection?.processing_time_ms) {
                document.getElementById('perf-time').textContent =
                    Math.round(data.latest_detection.processing_time_ms);
            }

            // Update event log
            const events = data.recent_events?.slice(0, 8) || [];
            if (events.length > 0) {
                const newEvents = events.filter(e => !seenEvents.has(e.filename));

                if (seenEvents.size === 0 || newEvents.length > 3) {
                    // Full refresh
                    let html = '';
                    events.forEach(e => {
                        seenEvents.add(e.filename);
                        const color = COLORS[e.category];
                        const hasThumb = !!e.thumb;
                        html += `
                            <div class="event-item" style="border-left-color: ${color}">
                                <div class="event-thumb ${hasThumb ? '' : 'loading'}">
                                    ${hasThumb ? `<img src="${e.thumb}" onload="this.parentElement.classList.remove('loading')">` : ''}
                                </div>
                                <div class="event-details">
                                    <div class="event-category" style="color: ${color}">${LABELS[e.category]}</div>
                                    <div class="event-time">${e.filename}</div>
                                </div>
                            </div>
                        `;
                    });
                    document.getElementById('event-list').innerHTML = html;
                } else {
                    // Prepend new items
                    newEvents.reverse().forEach(e => {
                        seenEvents.add(e.filename);
                        const color = COLORS[e.category];
                        const hasThumb = !!e.thumb;
                        const div = document.createElement('div');
                        div.className = 'event-item new';
                        div.style.borderLeftColor = color;
                        div.innerHTML = `
                            <div class="event-thumb ${hasThumb ? '' : 'loading'}">
                                ${hasThumb ? `<img src="${e.thumb}" onload="this.parentElement.classList.remove('loading')">` : ''}
                            </div>
                            <div class="event-details">
                                <div class="event-category" style="color: ${color}">${LABELS[e.category]}</div>
                                <div class="event-time">${e.filename}</div>
                            </div>
                        `;
                        const list = document.getElementById('event-list');
                        list.insertBefore(div, list.firstChild);

                        // Trim old items
                        while (list.children.length > 8) {
                            list.removeChild(list.lastChild);
                        }
                    });
                }
            }
        }

        function getActiveVideo() {
            return document.getElementById('video-player-' + activePlayer);
        }

        function getInactiveVideo() {
            return document.getElementById('video-player-' + (activePlayer === 'a' ? 'b' : 'a'));
        }

        // Buffer health UI
        function updateBufferUI() {
            const readyCount = preloadBuffer.filter(b => b.ready).length;
            const fill = document.getElementById('buffer-fill');
            const label = document.getElementById('buffer-label');

            const pct = (readyCount / PRELOAD_BUFFER_SIZE) * 100;
            fill.style.width = pct + '%';
            label.textContent = readyCount + '/' + PRELOAD_BUFFER_SIZE;

            fill.classList.remove('warning', 'danger');
            if (readyCount === 0) fill.classList.add('danger');
            else if (readyCount < 2) fill.classList.add('warning');
        }

        function showBuffering() {
            document.getElementById('buffer-overlay').classList.add('visible');
        }

        function hideBuffering() {
            document.getElementById('buffer-overlay').classList.remove('visible');
        }

        // Fill preload buffer with upcoming videos
        function fillPreloadBuffer() {
            // Clean up any entries that are no longer needed
            while (preloadBuffer.length > 0 && playedVideos.has(preloadBuffer[0].path)) {
                const old = preloadBuffer.shift();
                if (old.element && old.element.parentNode) {
                    old.element.parentNode.removeChild(old.element);
                }
            }

            // Fill buffer up to PRELOAD_BUFFER_SIZE
            let bufferIdx = 0;
            for (let i = 0; i < videoQueue.length && preloadBuffer.length < PRELOAD_BUFFER_SIZE; i++) {
                const videoInfo = videoQueue[i];

                // Skip if already in buffer
                if (preloadBuffer.find(b => b.path === videoInfo.path)) continue;
                // Skip if already played
                if (playedVideos.has(videoInfo.path)) continue;

                // Create hidden video element for preloading
                const video = document.createElement('video');
                video.preload = 'auto';
                video.muted = true;
                video.playsInline = true;
                video.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;opacity:0;z-index:0;';
                document.getElementById('video-container').appendChild(video);

                const entry = {
                    path: videoInfo.path,
                    element: video,
                    ready: false,
                    category: videoInfo.category
                };
                preloadBuffer.push(entry);

                video.src = videoInfo.path;
                video.load();

                video.addEventListener('canplaythrough', () => {
                    entry.ready = true;
                    updateBufferUI();
                    // If we're waiting to play and this is the next video, play it
                    if (isPlaying && preloadBuffer[0] === entry && entry.ready) {
                        hideBuffering();
                    }
                }, { once: true });

                video.addEventListener('error', () => {
                    // Mark as ready to skip it
                    entry.ready = true;
                    entry.error = true;
                    updateBufferUI();
                }, { once: true });
            }

            updateBufferUI();
        }

        function playNextVideo() {
            if (videoQueue.length === 0 && preloadBuffer.length === 0) {
                isPlaying = false;
                return;
            }

            isPlaying = true;
            document.getElementById('empty-state').classList.add('hidden');

            // Get next video from buffer
            let nextEntry = preloadBuffer[0];

            // If buffer is empty but queue has items, we need to wait
            if (!nextEntry && videoQueue.length > 0) {
                fillPreloadBuffer();
                nextEntry = preloadBuffer[0];
            }

            if (!nextEntry) {
                isPlaying = false;
                return;
            }

            // If not ready yet, show buffering and wait
            if (!nextEntry.ready) {
                showBuffering();
                // Freeze current video on last frame instead of going black
                const current = getActiveVideo();
                if (current.duration > 0) {
                    current.currentTime = current.duration - 0.05;
                    current.pause();
                }
                return; // Will be called again when video is ready
            }

            hideBuffering();

            // Skip errored entries
            if (nextEntry.error) {
                preloadBuffer.shift();
                if (nextEntry.element && nextEntry.element.parentNode) {
                    nextEntry.element.parentNode.removeChild(nextEntry.element);
                }
                playNextVideo();
                return;
            }

            // Remove from queue and buffer
            const videoPath = nextEntry.path;
            videoQueue = videoQueue.filter(v => v.path !== videoPath);
            preloadBuffer.shift();
            playedVideos.add(videoPath);
            currentVideo = videoPath;

            const current = getActiveVideo();
            const nextVideo = nextEntry.element;

            // Crossfade: show next, hide current
            nextVideo.style.opacity = '1';
            nextVideo.style.zIndex = '2';
            current.style.opacity = '0';
            current.style.zIndex = '1';

            // Start playback
            nextVideo.play().then(() => {
                // Clean up old video element after transition
                setTimeout(() => {
                    if (current.id.includes('player')) {
                        current.src = '';
                        current.load();
                    }
                }, 200);
            }).catch(() => {
                // Playback failed, try next
                if (nextVideo.parentNode) nextVideo.parentNode.removeChild(nextVideo);
                playNextVideo();
            });

            // Make this the active player
            nextVideo.id = 'video-player-' + (activePlayer === 'a' ? 'b' : 'a');
            activePlayer = activePlayer === 'a' ? 'b' : 'a';

            // Set up ended handler for new active video
            nextVideo.addEventListener('ended', () => {
                if (nextVideo.parentNode) nextVideo.parentNode.removeChild(nextVideo);
                playNextVideo();
            }, { once: true });

            // Refill buffer
            fillPreloadBuffer();
        }

        // Set up event handlers for initial video players
        ['a', 'b'].forEach(id => {
            const video = document.getElementById('video-player-' + id);

            video.addEventListener('ended', () => {
                playNextVideo();
            });

            video.addEventListener('error', () => {
                setTimeout(playNextVideo, 100);
            });
        });

        // Periodically check buffer and refill
        setInterval(() => {
            if (videoQueue.length > 0) {
                fillPreloadBuffer();
            }
        }, 500);

        // State for delta updates
        let lastKnownState = {};

        // Metrics tracking
        const metrics = {
            networkLatency: 0,
            latencyHistory: [],
            messagesReceived: 0,
            lastMessageTime: Date.now(),
            updateRate: 0,
        };

        function updateMetricsDisplay() {
            // Update latency displays (header and stats row)
            const latencyEl = document.getElementById('latency-value');
            const latencyStat = document.getElementById('latency-stat');
            const latencyText = metrics.networkLatency + 'ms';
            if (latencyEl) latencyEl.textContent = latencyText;
            if (latencyStat) latencyStat.textContent = latencyText;

            // Update latency bar
            const latencyFill = document.getElementById('latency-fill');
            if (latencyFill) {
                latencyFill.classList.remove('good', 'fair', 'poor');
                if (metrics.networkLatency < 100) {
                    latencyFill.classList.add('good');
                } else if (metrics.networkLatency < 300) {
                    latencyFill.classList.add('fair');
                } else {
                    latencyFill.classList.add('poor');
                }
            }

            // Update rate display
            const rateEl = document.getElementById('update-rate');
            if (rateEl) {
                rateEl.textContent = metrics.updateRate.toFixed(1) + '/s';
            }

            // Sync buffer stat with buffer UI
            const bufferStat = document.getElementById('buffer-stat');
            const bufferLabel = document.getElementById('buffer-label');
            if (bufferStat && bufferLabel) {
                bufferStat.textContent = bufferLabel.textContent;
            }

            // Update queue stat
            const queueStat = document.getElementById('queue-stat');
            if (queueStat) {
                queueStat.textContent = videoQueue.length;
            }
        }

        function handleMessage(msg) {
            const now = Date.now();

            // Track metrics
            metrics.messagesReceived++;
            const timeSinceLastMsg = now - metrics.lastMessageTime;
            metrics.lastMessageTime = now;

            // Calculate update rate (rolling average)
            if (timeSinceLastMsg > 0 && timeSinceLastMsg < 5000) {
                metrics.updateRate = metrics.updateRate * 0.8 + (1000 / timeSinceLastMsg) * 0.2;
            }

            // Handle full or delta message
            if (msg.type === 'full') {
                lastKnownState = msg.data;
            } else if (msg.type === 'delta') {
                // Merge delta into last known state
                lastKnownState = {...lastKnownState, ...msg.data};
            } else {
                // Legacy format (direct stats object)
                lastKnownState = msg;
            }

            // Calculate network latency from server timestamp
            if (lastKnownState.server_ts) {
                metrics.networkLatency = Math.max(0, now - lastKnownState.server_ts);
                metrics.latencyHistory.push(metrics.networkLatency);
                if (metrics.latencyHistory.length > 20) metrics.latencyHistory.shift();
            }

            // Update dashboard with merged state
            updateDashboard(lastKnownState);
            updateMetricsDisplay();
        }

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);

            ws.onopen = () => {
                document.getElementById('status-dot').classList.remove('disconnected');
                document.getElementById('status-text').textContent = 'LIVE';
                document.getElementById('status-text').style.color = '#10b981';
            };

            ws.onclose = () => {
                document.getElementById('status-dot').classList.add('disconnected');
                document.getElementById('status-text').textContent = 'Reconnecting...';
                document.getElementById('status-text').style.color = '';
                setTimeout(connect, 2000);
            };

            ws.onmessage = (e) => handleMessage(JSON.parse(e.data));
        }

        connect();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    import socket
    import subprocess

    port = int(os.environ.get("PORT", "8181"))

    # Get the machine's IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = socket.gethostname()

    # Get Tailscale IP if available
    ts_ip = None
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            ts_ip = result.stdout.strip().split('\n')[0]
    except Exception:
        pass

    print(f"\n  Dashboard running at http://{ip}:{port}")
    if ts_ip:
        print(f"                     http://{ts_ip}:{port}")
    print()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
