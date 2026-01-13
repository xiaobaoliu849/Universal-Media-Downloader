# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture & Structure

- **Core Functionality**: A Flask-based web interface for `yt-dlp` to download media from various platforms (YouTube, X/Twitter, etc.).
- **Backend**:
  - `app.py`: Entry point, Flask app initialization, and API routes.
  - `tasks.py`: Core logic for `TaskManager`. Handles queuing, threading, and subprocess management for `yt-dlp`, `ffmpeg`, and `aria2c`.
  - `config.py`: Configuration loading, environment variable handling (`.env`), and path resolution for bundled resources (PyInstaller compatibility).
  - `downloader.py`: Simple wrapper for direct `yt-dlp` execution (multiprocessing support).
  - `site_configs.py`: Site-specific download configurations (concurrency, chunk size).
- **Frontend**: `templates/` (HTML) and `static/` (JS/CSS). Uses Server-Sent Events (SSE) for real-time progress updates.
- **Data Flow**:
  1. User submits URL via Web UI.
  2. `app.py` receives request, calls `task_manager.add_task()`.
  3. `TaskManager` (in `tasks.py`) queues task, worker thread picks it up.
  4. Worker executes `yt-dlp` via `subprocess`.
  5. Progress is parsed from stdout and streamed back to client via SSE (`/api/stream_task`).

## Common Commands

- **Install Dependencies**: `pip install -r requirements.txt`
- **Run Development Server**: `python app.py` (Runs on http://localhost:5001)
- **Build (Windows)**: Run `build.bat` or `pyinstaller build_app.spec`
- **Clean Build**: `rd /s /q build dist` (Windows) or `rm -rf build dist` (Unix)

## Development Guidelines

- **Path Handling**: Always use `config.resource_path()` when referencing bundled binaries (`yt-dlp`, `ffmpeg`, `aria2c`, `cookies.txt`) to ensure compatibility with PyInstaller (frozen) builds.
- **Task Management**:
  - All heavy lifting (downloading, merging) happens in `tasks.py`.
  - Use `TaskManager` to interact with running tasks.
  - Progress updates rely on parsing stdout from `yt-dlp`.
- **Environment**:
  - Supports `.env` file for local configuration (loaded in `config.py`).
  - Key env vars: `UMD_PORT`, `UMD_PROXY`, `UMD_DOWNLOAD_DIR`, `META_MODE`.
- **Cookies**: The app handles `cookies.txt` prioritization (File > Browser extraction). See `config.py` and `tasks.py` for logic.
- **Subprocesses**: When adding new subprocess calls, ensure `creationflags=subprocess.CREATE_NO_WINDOW` is used on Windows to prevent console window popping up in the packaged app.

## Key APIs

- `GET /api/stream_task`: SSE endpoint for real-time task progress.
- `GET /api/tasks`: List all tasks.
- `POST /api/tasks/<id>/cancel`: Cancel a running task.
- `GET /diag/*`: Diagnostic endpoints for debugging.
