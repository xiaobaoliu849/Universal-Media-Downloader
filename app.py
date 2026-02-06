import logging, os, sys, subprocess, json, traceback, re, datetime, shutil, uuid, queue, threading, time
from typing import Optional, Dict, Any, Callable
from flask import Flask, request, Response, render_template, jsonify
from werkzeug.exceptions import HTTPException, NotFound
import webbrowser
from threading import Timer
from collections import OrderedDict
from functools import wraps
from urllib.parse import urlparse

# --- Import config ---
try:
    import config
except ImportError:
    print("Error: config.py not found.")
    sys.exit(1)

# --- Service Imports ---
from service.utils.dependencies import get_ffmpeg_path, get_ytdlp_version, update_ytdlp, check_ytdlp_update
from service.utils.common import validate_url, sanitize_input, retry_on_failure, _safe_get_json
from service.utils.errors import classify_error
from service.tasks.manager import init_task_manager, get_task_manager, cancel_task
from service.web.routes_api import api_bp
from service.web.routes_ui import ui_bp

try:
    from flask_cors import CORS
except ImportError:
    CORS = None

# --- Logger Setup ---
def setup_logging():
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    root_logger = logging.getLogger()
    if root_logger.hasHandlers(): root_logger.handlers.clear()
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(log_format))
    file_handler = logging.FileHandler(os.path.join(config.LOG_DIR, f'app_{datetime.datetime.now().strftime("%Y%m%d")}.log'), encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(log_format))
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    return logging.getLogger(__name__)

logger = setup_logging()

# --- App initialization ---
app = Flask(__name__, template_folder=config.resource_path('templates'), static_folder=config.resource_path('static'))
if CORS: CORS(app)

# Register Blueprints
app.register_blueprint(api_bp)
app.register_blueprint(ui_bp)

# --- Task Manager Initialization ---
@app.before_request
def _ensure_tm():
    if get_task_manager() is None:
        init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)

# --- Common Constants ---
UI_VERSION = "3.1.0"
LANGUAGE_CODES = {'en': '英语', 'zh-CN': '简体中文', 'zh-Hant': '繁体中文', 'ja': '日语', 'ko': '韩语', 'de': '德语', 'fr': '法语', 'es': '西班牙语', 'ru': '俄语'}

# --- Legacy routes (mapped to new logic or proxying) ---
@app.route('/info')
def video_info_legacy():
    # This should be moved to service/web/routes_api.py in the future
    url = request.args.get('url')
    if not url or not validate_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    # Simple proxy to yt-dlp for now or use a service helper
    return jsonify({'error': 'Use /api/info instead'}), 410

@app.route('/diag/yt')
def diag_yt():
    test_url = request.args.get('url')
    if not test_url or not validate_url(test_url):
        return jsonify({'error': 'Invalid URL'}), 400

    # Diagnostic logic...
    return jsonify({'status': 'ok', 'url': test_url})

def open_browser():
    port = int(os.environ.get('UMD_PORT', config.SERVER_PORT))
    if os.environ.get('UMD_NO_BROWSER','').lower() not in ('1','true','yes','on'):
        webbrowser.open_new(f"http://127.0.0.1:{port}")

if __name__ == '__main__':
    logger.info("🚀 Starting Universal Media Downloader (Refactored)...")

    # Initialize Task Manager early
    init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)

    port = int(os.environ.get('UMD_PORT', config.SERVER_PORT))
    Timer(1, open_browser).start()

    app.config['JSON_AS_ASCII'] = False
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)
