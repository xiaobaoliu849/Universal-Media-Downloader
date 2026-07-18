import logging, os, sys, subprocess, json, traceback, re, datetime, shutil, uuid, queue, threading, time, importlib
from typing import Optional, Dict, Any, Callable
from flask import Flask, request, Response, render_template, jsonify
from werkzeug.exceptions import HTTPException, NotFound
import webbrowser
from threading import Timer
from collections import OrderedDict
from functools import wraps
from urllib.parse import urlparse

# --- Import Path Hygiene ---
# 某些 Windows 环境会把打包版 dist/_internal 或旧发布目录混入 PYTHONPATH，
# 导致源码模式下 import 到旧的 service 包。这里强制把项目根目录放到最前，
# 并移除当前仓库下 dist/release 的潜在污染路径。
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_normalized_root = os.path.normcase(os.path.normpath(_PROJECT_ROOT))
_cleaned_sys_path = []
for _entry in list(sys.path):
    try:
        _norm = os.path.normcase(os.path.normpath(os.path.abspath(_entry or '.')))
    except Exception:
        _cleaned_sys_path.append(_entry)
        continue
    if _norm == _normalized_root:
        continue
    if _norm.startswith(os.path.join(_normalized_root, 'dist')) or _norm.startswith(os.path.join(_normalized_root, 'release')):
        continue
    if _norm.endswith(os.path.normcase(os.path.normpath(os.path.join('Universal Media Downloader', '_internal')))):
        continue
    _cleaned_sys_path.append(_entry)
sys.path[:] = [_PROJECT_ROOT] + _cleaned_sys_path


def _purge_local_pycache():
    targets = [
        os.path.join(_PROJECT_ROOT, '__pycache__'),
        os.path.join(_PROJECT_ROOT, 'service', '__pycache__'),
        os.path.join(_PROJECT_ROOT, 'service', 'tasks', '__pycache__'),
        os.path.join(_PROJECT_ROOT, 'service', 'utils', '__pycache__'),
        os.path.join(_PROJECT_ROOT, 'service', 'web', '__pycache__'),
    ]
    removed = []
    for target in targets:
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
                removed.append(target)
        except Exception:
            continue
    return removed


_PURGED_PYCACHE_DIRS = _purge_local_pycache()

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
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
if CORS: CORS(app)

# Register Blueprints
app.register_blueprint(api_bp)
app.register_blueprint(ui_bp)


@app.after_request
def _disable_cache(resp):
    try:
        path = request.path or ''
    except Exception:
        path = ''
    if path == '/' or path.startswith('/static/'):
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp

# --- Task Manager Initialization ---
@app.before_request
def _ensure_tm():
    if get_task_manager() is None:
        init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)

# --- Common Constants ---
UI_VERSION = "3.1.0"
LANGUAGE_CODES = {'en': '英语', 'zh-CN': '简体中文', 'zh-Hant': '繁体中文', 'ja': '日语', 'ko': '韩语', 'de': '德语', 'fr': '法语', 'es': '西班牙语', 'ru': '俄语'}

def open_browser():
    port = int(os.environ.get('UMD_PORT', config.SERVER_PORT))
    if os.environ.get('UMD_NO_BROWSER','').lower() not in ('1','true','yes','on'):
        try:
            static_ver = str(int(os.path.getmtime(config.resource_path(os.path.join('static', 'main.js')))))
        except Exception:
            static_ver = str(int(time.time()))
        webbrowser.open_new(f"http://127.0.0.1:{port}/?v={static_ver}")

if __name__ == '__main__':
    logger.info("🚀 Starting Universal Media Downloader (Refactored)...")
    
    # 调试：输出关键路径信息
    logger.info(f"[INIT] cwd: {os.getcwd()}")
    logger.info(f"[INIT] python: {sys.executable}")
    logger.info(f"[INIT] sys.path[0]: {sys.path[0] if sys.path else ''}")
    logger.info(f"[INIT] purged_pycache: {_PURGED_PYCACHE_DIRS}")
    for mod_name in ('app', 'config', 'service.web.routes_ui', 'service.web.routes_api', 'service.tasks.downloader'):
        try:
            mod = importlib.import_module(mod_name)
            logger.info(f"[INIT] module {mod_name}: {getattr(mod, '__file__', 'n/a')}")
        except Exception as mod_err:
            logger.warning(f"[INIT] module {mod_name} import failed: {mod_err}")
    logger.info(f"[INIT] YTDLP_PATH: {config.YTDLP_PATH}")
    logger.info(f"[INIT] COOKIES_FILE: {config.COOKIES_FILE}")
    logger.info(f"[INIT] DOWNLOAD_DIR: {config.DOWNLOAD_DIR}")
    logger.info(f"[INIT] Cookies exists: {os.path.exists(config.COOKIES_FILE)}")

    # Initialize Task Manager early
    init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)

    port = int(os.environ.get('UMD_PORT', config.SERVER_PORT))
    Timer(1, open_browser).start()

    app.config['JSON_AS_ASCII'] = False
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)
