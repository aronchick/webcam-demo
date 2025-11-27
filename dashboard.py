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
Real-time dashboard for the webcam chunking pipeline.
Polished UI with WebSocket updates, video playback, and annotated thumbnails.
"""

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse

app = FastAPI(title="Webcam Pipeline Dashboard")

CHUNKS_DIR = Path(os.environ.get("CHUNKS_DIR", "./chunks"))
PROCESSED_DIR = Path(os.environ.get("PROCESSED_DIR", "./processed"))

CATEGORIES = {
    "left_hand_raised": {"emoji": "👈", "color": "#10b981", "label": "Left Hand", "icon": "hand-left"},
    "right_hand_raised": {"emoji": "👉", "color": "#3b82f6", "label": "Right Hand", "icon": "hand-right"},
    "both_hands_raised": {"emoji": "🙌", "color": "#8b5cf6", "label": "Both Hands", "icon": "hands"},
    "no_detection": {"emoji": "👤", "color": "#64748b", "label": "No Detection", "icon": "user"},
}


def get_stats() -> dict:
    """Get current pipeline statistics."""
    stats = {
        "pending": 0,
        "pending_files": [],
        "categories": {},
        "latest_video": None,
        "latest_thumb": None,
        "recent_events": [],
        "total_processed": 0,
    }

    # Get pending chunks
    if CHUNKS_DIR.exists():
        pending = sorted(CHUNKS_DIR.glob("*.mp4"), key=lambda p: p.name)
        stats["pending"] = len(pending)
        stats["pending_files"] = [p.name for p in pending[-3:]]

    # Count by category and find latest
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

        count = len(files)
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
async def serve_video(category: str, filename: str):
    """Serve video files."""
    video_path = PROCESSED_DIR / category / filename
    if video_path.exists():
        return FileResponse(video_path, media_type="video/mp4")
    return {"error": "not found"}


@app.get("/thumb/{filename}")
async def serve_thumb(filename: str):
    """Serve thumbnail images."""
    thumb_path = PROCESSED_DIR / "thumbnails" / filename
    if thumb_path.exists():
        return FileResponse(thumb_path, media_type="image/jpeg")
    return {"error": "not found"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates."""
    await websocket.accept()

    try:
        last_stats = None
        while True:
            stats = get_stats()
            stats_json = json.dumps(stats, default=str)
            if stats_json != last_stats:
                await websocket.send_json(stats)
                last_stats = stats_json
            await asyncio.sleep(0.4)
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
    <title>Webcam Pipeline</title>
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
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0 25px;
        }
        .logo { display: flex; align-items: center; gap: 12px; }
        .logo-icon {
            width: 44px; height: 44px;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-purple));
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5em;
        }
        .logo-text h1 {
            font-size: 1.5em;
            background: linear-gradient(90deg, var(--accent-blue), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .logo-text p { font-size: 0.75em; color: var(--text-muted); }
        .status-badge {
            display: flex; align-items: center; gap: 8px;
            padding: 8px 16px;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 20px;
            font-size: 0.8em; font-weight: 600;
        }
        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 1.5s infinite;
        }
        .status-dot.disconnected { background: #ef4444; animation: none; }
        @keyframes pulse {
            0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(16,185,129,0.4); }
            50% { opacity: 0.8; box-shadow: 0 0 0 8px rgba(16,185,129,0); }
        }

        /* Main Grid */
        .main-grid {
            display: grid;
            grid-template-columns: 1fr 380px;
            gap: 24px;
        }
        @media (max-width: 1024px) { .main-grid { grid-template-columns: 1fr; } }

        /* Video Section */
        .video-section {
            background: var(--bg-secondary);
            border-radius: 20px;
            padding: 20px;
            border: 1px solid var(--border);
        }
        .video-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 16px;
        }
        .video-title { color: var(--text-secondary); font-weight: 600; }
        .video-badge {
            padding: 6px 14px;
            border-radius: 16px;
            font-size: 0.85em;
            font-weight: 600;
            display: none;
        }
        .video-container {
            position: relative;
            aspect-ratio: 16/9;
            background: #000;
            border-radius: 16px;
            overflow: hidden;
        }
        video { width: 100%; height: 100%; object-fit: contain; }
        .video-overlay {
            position: absolute;
            inset: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(0,0,0,0.8);
            gap: 12px;
        }
        .video-overlay.hidden { display: none; }
        .video-overlay-icon { font-size: 3em; opacity: 0.3; }
        .video-overlay-text { color: var(--text-muted); }

        /* Scanning line effect */
        .scan-line {
            position: absolute;
            left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, transparent, var(--accent-blue), transparent);
            animation: scan 2.5s linear infinite;
            opacity: 0.6;
        }
        @keyframes scan {
            0% { top: -5%; }
            100% { top: 105%; }
        }

        /* Detection overlay */
        .detection-overlay {
            position: absolute;
            bottom: 16px; left: 16px; right: 16px;
            background: rgba(15,23,42,0.9);
            backdrop-filter: blur(12px);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid var(--border);
            display: none;
            animation: slideUp 0.3s ease-out;
        }
        .detection-overlay.visible { display: flex; align-items: center; gap: 16px; }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .detection-icon {
            width: 48px; height: 48px;
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.5em;
        }
        .detection-info h3 { font-size: 1em; text-transform: uppercase; letter-spacing: 0.05em; }
        .detection-info p { font-size: 0.8em; color: var(--text-muted); margin-top: 2px; }

        /* Thumbnail preview - fixed size to prevent jumping */
        .thumb-preview {
            margin-top: 16px;
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 12px;
            height: 100px;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .thumb-preview.empty { opacity: 0.3; }
        .thumb-preview img {
            max-width: 140px;
            max-height: 70px;
            border-radius: 6px;
            object-fit: contain;
        }
        .thumb-label {
            font-size: 0.7em;
            color: var(--text-muted);
            margin-top: 6px;
            text-align: center;
        }

        /* Video interstitial */
        .video-interstitial {
            position: absolute;
            inset: 0;
            display: none;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: linear-gradient(135deg, rgba(59,130,246,0.1), rgba(139,92,246,0.1));
            gap: 12px;
        }
        .video-interstitial.visible { display: flex; }
        .interstitial-spinner {
            width: 40px; height: 40px;
            border: 3px solid var(--bg-tertiary);
            border-top-color: var(--accent-blue);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .interstitial-text { color: var(--text-muted); font-size: 0.9em; }

        /* Stats row */
        .stats-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 16px;
        }
        .stat-card {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 16px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .stat-label { font-size: 0.7em; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; }
        .stat-value { font-size: 1.5em; font-weight: bold; font-family: monospace; }
        .stat-icon { font-size: 1.5em; opacity: 0.3; }

        /* Sidebar */
        .sidebar { display: flex; flex-direction: column; gap: 16px; }

        /* Pending card */
        .pending-card {
            background: linear-gradient(135deg, rgba(245,158,11,0.15), rgba(245,158,11,0.05));
            border: 1px solid rgba(245,158,11,0.3);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
        }
        .pending-label { font-size: 0.75em; color: var(--accent-amber); text-transform: uppercase; letter-spacing: 0.1em; }
        .pending-count {
            font-size: 3em;
            font-weight: bold;
            color: var(--accent-amber);
            text-shadow: 0 0 30px rgba(245,158,11,0.3);
            font-family: monospace;
        }
        .pending-files { font-size: 0.7em; color: var(--text-muted); margin-top: 8px; }

        /* Category grid */
        .category-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }
        .cat-card {
            background: var(--bg-secondary);
            border: 2px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            transition: all 0.3s;
        }
        .cat-card.active {
            background: var(--bg-tertiary);
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }
        .cat-icon {
            width: 56px; height: 56px;
            margin: 0 auto 12px;
            border-radius: 50%;
            background: rgba(255,255,255,0.05);
            display: flex; align-items: center; justify-content: center;
            font-size: 1.8em;
            transition: transform 0.3s;
        }
        .cat-card.active .cat-icon { transform: scale(1.1); }
        .cat-count { font-size: 2em; font-weight: bold; font-family: monospace; }
        .cat-label { font-size: 0.75em; color: var(--text-muted); text-transform: uppercase; margin-top: 4px; }

        /* Event log */
        .event-log {
            flex: 1;
            background: var(--bg-secondary);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px;
            min-height: 280px;
            display: flex;
            flex-direction: column;
        }
        .event-log-header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 12px;
        }
        .event-log-title {
            font-size: 0.8em;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }
        .event-list {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .event-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 12px;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            animation: fadeIn 0.3s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .event-thumb {
            width: 48px; height: 27px;
            border-radius: 4px;
            background: var(--bg-tertiary);
            overflow: hidden;
            flex-shrink: 0;
        }
        .event-thumb img { width: 100%; height: 100%; object-fit: cover; }
        .event-details { flex: 1; min-width: 0; }
        .event-name { font-size: 0.85em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .event-time { font-size: 0.7em; color: var(--text-muted); }
        .event-badge {
            font-size: 0.7em;
            padding: 3px 8px;
            border-radius: 8px;
            font-weight: 600;
        }

        /* Footer */
        .footer {
            text-align: center;
            padding: 30px;
            color: var(--text-muted);
            font-size: 0.8em;
        }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="logo">
                <div class="logo-icon">📹</div>
                <div class="logo-text">
                    <h1>Webcam Pipeline</h1>
                    <p>Real-time pose classification</p>
                </div>
            </div>
            <div class="status-badge">
                <span class="status-dot" id="status-dot"></span>
                <span id="status-text">Connecting...</span>
            </div>
        </header>

        <main class="main-grid">
            <div class="video-section">
                <div class="video-header">
                    <span class="video-title">Latest Processed Chunk</span>
                    <span class="video-badge" id="video-badge"></span>
                </div>
                <div class="video-container">
                    <video id="video-player" autoplay muted playsinline></video>
                    <div class="scan-line"></div>
                    <div class="video-overlay" id="video-overlay">
                        <div class="video-overlay-icon">📹</div>
                        <div class="video-overlay-text">Waiting for processed chunks...</div>
                    </div>
                    <div class="video-interstitial" id="video-interstitial">
                        <div class="interstitial-spinner"></div>
                        <div class="interstitial-text">Loading next clip...</div>
                    </div>
                    <div class="detection-overlay" id="detection-overlay">
                        <div class="detection-icon" id="detection-icon">👈</div>
                        <div class="detection-info">
                            <h3 id="detection-label">Left Hand</h3>
                            <p>Detected in latest chunk</p>
                        </div>
                    </div>
                </div>
                <div class="thumb-preview empty" id="thumb-preview">
                    <img id="thumb-img" src="" alt="Detection thumbnail" style="display:none">
                    <div class="thumb-label">Annotated detection frame</div>
                </div>
                <div class="stats-row">
                    <div class="stat-card">
                        <div>
                            <div class="stat-label">Total Processed</div>
                            <div class="stat-value" id="total-processed">0</div>
                        </div>
                        <div class="stat-icon">📊</div>
                    </div>
                    <div class="stat-card">
                        <div>
                            <div class="stat-label">Chunk Duration</div>
                            <div class="stat-value">3s</div>
                        </div>
                        <div class="stat-icon">⏱️</div>
                    </div>
                </div>
            </div>

            <div class="sidebar">
                <div class="pending-card">
                    <div class="pending-label">Chunks Pending</div>
                    <div class="pending-count" id="pending-count">0</div>
                    <div class="pending-files" id="pending-files">No pending chunks</div>
                </div>

                <div class="category-grid" id="category-grid"></div>

                <div class="event-log">
                    <div class="event-log-header">
                        <span class="event-log-title">🕐 Recent Activity</span>
                    </div>
                    <div class="event-list" id="event-list">
                        <div style="color: var(--text-muted); text-align: center; padding: 40px;">
                            Waiting for activity...
                        </div>
                    </div>
                </div>
            </div>
        </main>

        <footer class="footer">
            Powered by MediaPipe · FFmpeg · FastAPI · Expanso
        </footer>
    </div>

    <script>
        let ws;
        let currentVideo = null;
        let reconnectAttempts = 0;
        let videoEnded = false;

        const categories = {
            left_hand_raised: { emoji: '👈', color: '#10b981', label: 'Left Hand' },
            right_hand_raised: { emoji: '👉', color: '#3b82f6', label: 'Right Hand' },
            both_hands_raised: { emoji: '🙌', color: '#8b5cf6', label: 'Both Hands' },
            no_detection: { emoji: '👤', color: '#64748b', label: 'No Detection' },
        };

        // Video end handler - show interstitial instead of looping
        document.addEventListener('DOMContentLoaded', () => {
            const video = document.getElementById('video-player');
            video.addEventListener('ended', () => {
                videoEnded = true;
                document.getElementById('video-interstitial').classList.add('visible');
                document.getElementById('detection-overlay').classList.remove('visible');
            });
            video.addEventListener('play', () => {
                document.getElementById('video-interstitial').classList.remove('visible');
            });
        });

        function connect() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${location.host}/ws`);

            ws.onopen = () => {
                document.getElementById('status-dot').classList.remove('disconnected');
                document.getElementById('status-text').textContent = 'LIVE';
                document.getElementById('status-text').style.color = '#10b981';
                reconnectAttempts = 0;
            };

            ws.onclose = () => {
                document.getElementById('status-dot').classList.add('disconnected');
                document.getElementById('status-text').textContent = 'Reconnecting...';
                document.getElementById('status-text').style.color = '';
                setTimeout(connect, Math.min(1000 * Math.pow(2, reconnectAttempts++), 10000));
            };

            ws.onmessage = (e) => updateDashboard(JSON.parse(e.data));
        }

        function updateDashboard(data) {
            // Pending
            document.getElementById('pending-count').textContent = data.pending;
            document.getElementById('pending-files').textContent =
                data.pending_files.length ? data.pending_files.join(' → ') : 'No pending chunks';

            // Total processed
            document.getElementById('total-processed').textContent = data.total_processed;

            // Categories
            let catHtml = '';
            for (const [name, info] of Object.entries(categories)) {
                const catData = data.categories[name] || { count: 0 };
                const isActive = data.latest_video?.category === name;
                catHtml += `
                    <div class="cat-card ${isActive ? 'active' : ''}"
                         style="border-color: ${isActive ? info.color : 'var(--border)'}">
                        <div class="cat-icon" style="background: ${info.color}22">${info.emoji}</div>
                        <div class="cat-count" style="color: ${info.color}">${catData.count}</div>
                        <div class="cat-label">${info.label}</div>
                    </div>
                `;
            }
            document.getElementById('category-grid').innerHTML = catHtml;

            // Video player - only update if new video or video ended
            if (data.latest_video && (data.latest_video.path !== currentVideo || videoEnded)) {
                currentVideo = data.latest_video.path;
                videoEnded = false;
                const video = document.getElementById('video-player');
                video.src = currentVideo;
                video.load();
                video.play().catch(() => {}); // Ignore autoplay errors

                document.getElementById('video-overlay').classList.add('hidden');
                document.getElementById('video-interstitial').classList.remove('visible');

                const cat = categories[data.latest_video.category];
                const badge = document.getElementById('video-badge');
                badge.style.display = 'inline-block';
                badge.style.background = cat.color;
                badge.style.color = '#fff';
                badge.textContent = `${cat.emoji} ${cat.label}`;

                // Detection overlay
                const overlay = document.getElementById('detection-overlay');
                overlay.classList.add('visible');
                document.getElementById('detection-icon').textContent = cat.emoji;
                document.getElementById('detection-icon').style.background = cat.color + '33';
                document.getElementById('detection-label').textContent = cat.label;
                document.getElementById('detection-label').style.color = cat.color;
            }

            // Thumbnail - fixed size, always visible
            const thumbPreview = document.getElementById('thumb-preview');
            const thumbImg = document.getElementById('thumb-img');
            if (data.latest_thumb) {
                thumbImg.src = data.latest_thumb;
                thumbImg.style.display = 'block';
                thumbPreview.classList.remove('empty');
            } else {
                thumbImg.style.display = 'none';
                thumbPreview.classList.add('empty');
            }

            // Event log
            let eventHtml = '';
            for (const event of data.recent_events.slice(0, 6)) {
                const cat = categories[event.category];
                const timeAgo = Math.floor((Date.now() - event.mtime * 1000) / 1000);
                const timeStr = timeAgo < 60 ? `${timeAgo}s ago` : `${Math.floor(timeAgo/60)}m ago`;
                eventHtml += `
                    <div class="event-item">
                        <div class="event-thumb">
                            ${event.thumb ? `<img src="${event.thumb}" alt="">` : ''}
                        </div>
                        <div class="event-details">
                            <div class="event-name">${event.filename}</div>
                            <div class="event-time">${timeStr}</div>
                        </div>
                        <span class="event-badge" style="background: ${cat.color}22; color: ${cat.color}">
                            ${cat.emoji}
                        </span>
                    </div>
                `;
            }
            document.getElementById('event-list').innerHTML = eventHtml ||
                '<div style="color: var(--text-muted); text-align: center; padding: 40px;">Waiting for activity...</div>';
        }

        connect();
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8080"))
    print(f"\n  Dashboard running at http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
