import logging, os, sys, subprocess, json, traceback, re, datetime, shutil, uuid, queue, threading, time
from typing import Optional, Dict, Any, Callable
from flask import Flask, request, Response, render_template, jsonify
from typing import Any, Optional as _Optional

# 某些 Pylance 版本下 flask.Request 缺少 get_json/ json 属性的类型提示，添加轻量安全封装
def _safe_get_json(req) -> dict[str, Any]:  # type: ignore[override]
    try:
        gj = getattr(req, 'get_json', None)
        if callable(gj):  # 优先使用 get_json
            data = gj(silent=True)  # type: ignore[arg-type]
            if isinstance(data, dict):
                return data  # type: ignore[return-value]
            return {}
        # 退回直接属性 json
        raw = getattr(req, 'json', None)
        if isinstance(raw, dict):
            return raw
        return {}
    except Exception:
        return {}
from werkzeug.exceptions import HTTPException, NotFound
import webbrowser
from threading import Timer
from collections import OrderedDict
from functools import wraps
from urllib.parse import urlparse
import json as _json

# --- 导入配置 (单次导入，避免重复导致的 Pylance 假警告) ---
try:
    import config  # 本地模块，需保证启动时工作目录包含项目根
except ImportError:
    print("错误：配置文件 config.py 未找到。请确保该文件与 app.py 位于同一目录。")
    sys.exit(1)

# --- 主应用代码 ---
try:
    from flask_cors import CORS
except ImportError:
    CORS = None

# 定义一个全局的、只在Windows上生效的创建标志，用于隐藏子进程窗口
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0



# --- 安全验证函数 ---
def validate_url(url: str) -> bool:
    """验证URL格式和安全性"""
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    if len(url) > 2048:  # 防止过长的URL
        return False

    try:
        parsed = urlparse(url)
        # 检查基本URL结构
        if not parsed.scheme or not parsed.netloc:
            return False

        # 只允许http和https协议
        if parsed.scheme.lower() not in ('http', 'https'):
            return False

        # 检查主机名是否有效
        hostname = parsed.hostname
        if not hostname or len(hostname) > 253:
            return False

        # 防止本地网络访问（可选的安全措施）
        if hostname in ('localhost', '127.0.0.1', '0.0.0.0') or hostname.startswith('192.168.') or hostname.startswith('10.') or hostname.startswith('172.'):
            logger.warning(f"阻止访问本地网络地址: {hostname}")
            return False

        return True
    except Exception:
        return False

def sanitize_input(text: str, max_length: int = 1000) -> str:
    """清理输入文本，防止注入攻击"""
    if not text or not isinstance(text, str):
        return ""

    # 移除控制字符
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

    # 限制长度
    if len(text) > max_length:
        text = text[:max_length]

    # 移除潜在的shell注入字符
    dangerous_chars = [';', '&', '|', '`', '$', '(', ')', '<', '>', '"', "'"]
    for char in dangerous_chars:
        text = text.replace(char, '')

    return text.strip()

# --- 缓存 ---
_ffmpeg_path_cache = None

class LRUCache:
    """LRU缓存实现，支持TTL和最大大小限制"""
    def __init__(self, max_size: int = 50, ttl: int = 3600):
        self.cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                return None
            self.cache.move_to_end(key)
            return value
        return None

    def set(self, key: str, value: Any) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, time.time())
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def clear_expired(self) -> int:
        """清理过期条目，返回清理的数量"""
        expired_keys = []
        current_time = time.time()
        for key, (_, timestamp) in self.cache.items():
            if current_time - timestamp > self.ttl:
                expired_keys.append(key)

        for key in expired_keys:
            del self.cache[key]

        return len(expired_keys)

    def size(self) -> int:
        """返回当前缓存大小"""
        return len(self.cache)

# 视频信息缓存：最大50个条目，TTL 1小时
video_info_cache = LRUCache(max_size=50, ttl=3600)
LAST_TWITTER_PREFLIGHT: dict[str, Any] | None = None  # 记录最近一次 twitter 预探测结果供 /diag/proxy 诊断

# ---------------- In-flight 请求合并 (防止同一 URL 被频繁重复探测) ----------------
# 现象: 用户或前端在信息获取期间多次点击，日志出现同一 URL 多个连续 primary 阶段进程，造成:
#   1) 额外的网络/站点压力，可能加剧风控 (特别是 Twitter/X)
#   2) 本地同时跑多个 yt-dlp 子进程，浪费 CPU/带宽
# 方案: 维护一个 URL -> Inflight 结构。后续相同 URL 请求等待首个请求完成，或在超时后返回“进行中”。
# 细节:
#   * 正向结果仍进入 video_info_cache，等待方收到 result 并标记 coalesced:true
#   * 若首个请求失败，也广播错误，使等待方即时返回相同错误（并受负面缓存保护）
#   * 防止首个请求异常中断未释放: 使用 try/finally 置位 event
#   * 防止长时间卡死: 等待方最多等待 18s (可调)，超过则返回 202 in_progress，前端可稍后再试
#   * 过期清理: 结果发布后 3 秒清理 inflight 记录，避免内存常驻

class _InfoInflight:
    __slots__ = ('event','result','error','start','waiters','stage')
    def __init__(self):
        import threading as _th, time as _time
        self.event: 'threading.Event' = _th.Event()  # type: ignore[name-defined]
        self.result: Optional[dict[str,Any]] = None
        self.error: Optional[dict[str,Any]] = None
        self.start: float = _time.time()
        self.waiters: int = 0
        self.stage: str = 'initial'

_INFO_INFLIGHT: dict[str,_InfoInflight] = {}
_INFO_INFLIGHT_LOCK = threading.Lock()

def _get_inflight(url: str) -> Optional[_InfoInflight]:
    with _INFO_INFLIGHT_LOCK:
        return _INFO_INFLIGHT.get(url)

def _create_inflight(url: str) -> _InfoInflight:
    with _INFO_INFLIGHT_LOCK:
        inf = _INFO_INFLIGHT.get(url)
        if inf:
            return inf
        inf = _InfoInflight()
        _INFO_INFLIGHT[url] = inf
        return inf

def _publish_and_cleanup_inflight(url: str, inf: _InfoInflight):
    # 发布结果给等待者并安排清理
    try:
        inf.event.set()
    finally:
        def _cleanup():
            with _INFO_INFLIGHT_LOCK:
                # 仅在该对象仍是当前条目的情况下移除
                cur = _INFO_INFLIGHT.get(url)
                if cur is inf:
                    _INFO_INFLIGHT.pop(url, None)
        try:
            Timer(3, _cleanup).start()
        except Exception:
            _cleanup()


def _force_cleanup_inflight(url: str, inf: _InfoInflight, error_payload: Optional[dict[str, Any]] = None):
    """强制结束一个 inflight 记录，用于探测进程异常卡死时清理。"""
    if error_payload:
        try:
            inf.error = dict(error_payload)
        except Exception:
            pass
    _publish_and_cleanup_inflight(url, inf)
    with _INFO_INFLIGHT_LOCK:
        cur = _INFO_INFLIGHT.get(url)
        if cur is inf:
            _INFO_INFLIGHT.pop(url, None)

def retry_on_failure(max_retries: int = 3, backoff_factor: float = 2.0, exceptions: tuple = (Exception,)):
    """指数退避重试装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = backoff_factor ** attempt
                        logger.warning(f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries + 1})，{wait_time:.1f}秒后重试: {e}")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"{func.__name__} 最终失败 (尝试 {max_retries + 1} 次): {e}")
            # 避免 raise None 触发类型检查错误
            if last_exception is not None:
                raise last_exception
            raise RuntimeError(f"{func.__name__} 执行失败且未捕获具体异常")
        return wrapper
    return decorator

def get_ffmpeg_path():
    """返回 ffmpeg 可执行文件路径。

    改进: 在打包后可能由于工作目录变化导致原先的 resource_path 解析失败/或用户把 ffmpeg 目录移动。
    这里增加多路径穷举 + 详细日志，便于诊断 '找不到 ffmpeg' 问题。
    """
    global _ffmpeg_path_cache
    if _ffmpeg_path_cache not in (None, False):
        return _ffmpeg_path_cache

    candidates = []
    # 1) 配置中解析的打包路径
    candidates.append(config.FFMPEG_BUNDLED_PATH)
    # 2) 与可执行文件同级目录下的 ffmpeg/bin/ffmpeg.exe (处理 resource_path 失效或目录被复制走的情况)
    try:
        exe_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))
        candidates.append(os.path.join(exe_dir, 'ffmpeg', 'bin', 'ffmpeg.exe'))
        candidates.append(os.path.join(exe_dir, 'ffmpeg', 'ffmpeg.exe'))
    except Exception:
        pass
    # 3) 尝试 _MEIPASS 路径 (one-file 解包)
    if hasattr(sys, '_MEIPASS'):
        mp = getattr(sys, '_MEIPASS')  # type: ignore[attr-defined]
        candidates.append(os.path.join(mp, 'ffmpeg', 'bin', 'ffmpeg.exe'))
    # 4) PATH 中的 ffmpeg
    candidates.append(config.FFMPEG_SYSTEM_PATH)

    checked = []
    for cand in candidates:
        if not cand or cand in checked:
            continue
        checked.append(cand)
        if not os.path.exists(cand):
            continue
        try:
            r = subprocess.run([cand, '-version'], capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=4)
            if r.returncode == 0:
                _ffmpeg_path_cache = cand
                logger.info(f"[FFMPEG] 选用: {cand}")
                return cand
        except Exception:
            continue
    logger.warning(f"[FFMPEG] 未找到可用 ffmpeg (已检查 {len(candidates)} 个候选)")
    _ffmpeg_path_cache = False
    return None

# --- yt-dlp 版本检查和更新 ---
def get_ytdlp_version():
    """获取当前 yt-dlp 版本"""
    try:
        result = subprocess.run([config.YTDLP_PATH, '--version'], capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"当前 yt-dlp 版本: {version}")
            return version
        else:
            logger.warning("无法获取 yt-dlp 版本")
            return None
    except Exception as e:
        logger.error(f"获取 yt-dlp 版本失败: {e}")
        return None

def check_ytdlp_update():
    """检查 yt-dlp 是否有更新"""
    try:
        # 获取当前版本
        current_version = get_ytdlp_version()
        if not current_version:
            return {'error': '无法获取当前版本'}

        # 检查最新版本 (使用 --update-to 检查)
        result = subprocess.run([config.YTDLP_PATH, '--update-to', 'stable'], capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, timeout=30)

        if 'yt-dlp is up to date' in result.stdout:
            return {'status': 'up_to_date', 'current_version': current_version}
        elif 'Updated yt-dlp to' in result.stdout:
            # 已经更新了，获取新版本
            new_version = get_ytdlp_version()
            return {'status': 'updated', 'old_version': current_version, 'new_version': new_version}
        else:
            # 需要更新但未自动更新
            return {'status': 'update_available', 'current_version': current_version}

    except Exception as e:
        logger.error(f"检查 yt-dlp 更新失败: {e}")
        return {'error': str(e)}

def update_ytdlp():
    """强制更新 yt-dlp 到最新稳定版"""
    try:
        logger.info("开始更新 yt-dlp...")
        result = subprocess.run([config.YTDLP_PATH, '--update-to', 'stable'], capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, timeout=60)

        if result.returncode == 0:
            if 'Updated yt-dlp to' in result.stdout:
                new_version = get_ytdlp_version()
                logger.info(f"yt-dlp 更新成功，新版本: {new_version}")
                return {'success': True, 'message': '更新成功', 'new_version': new_version}
            elif 'yt-dlp is up to date' in result.stdout:
                current_version = get_ytdlp_version()
                return {'success': True, 'message': '已是最新版本', 'current_version': current_version}
            else:
                return {'success': False, 'message': '更新过程无明确结果'}
        else:
            error_msg = result.stderr or result.stdout
            logger.error(f"yt-dlp 更新失败: {error_msg}")
            return {'success': False, 'message': f'更新失败: {error_msg}'}

    except Exception as e:
        logger.error(f"yt-dlp 更新异常: {e}")
        return {'success': False, 'message': f'更新异常: {str(e)}'}

LANGUAGE_CODES = {'en': '英语', 'zh-CN': '简体中文', 'zh-Hant': '繁体中文', 'ja': '日语', 'ko': '韩语', 'de': '德语', 'fr': '法语', 'es': '西班牙语', 'ru': '俄语'}

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
app = Flask(__name__, template_folder=config.resource_path('templates'), static_folder=config.resource_path('static'))
if CORS: CORS(app)

# 预热线程：减少首个任务冷启动开销
def _background_prewarm():
    try:
        logger.info('[PREWARM] 启动预热线程')
        # 预热 yt-dlp
        try:
            subprocess.run([config.YTDLP_PATH, '--version'], capture_output=True, timeout=10, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            logger.debug(f'[PREWARM] yt-dlp 预热忽略: {e}')
        # 预热 ffmpeg
        ff = get_ffmpeg_path()
        if ff:
            try:
                subprocess.run([ff, '-version'], capture_output=True, timeout=6, creationflags=CREATE_NO_WINDOW)
            except Exception:
                pass
        logger.info('[PREWARM] 完成')
    except Exception as e:
        logger.debug(f'[PREWARM] 异常: {e}')

try:
    threading.Thread(target=_background_prewarm, daemon=True).start()
except Exception:
    pass

# UI 版本标记（帮助确认前端是否加载到最新模板）
UI_VERSION = "3.0.0"  # 2025-09 重大重构版本
_BUILD_META = {}
try:
    _meta_path = os.path.join(os.path.dirname(__file__), 'build_meta.json')
    if os.path.exists(_meta_path):
        with open(_meta_path, 'r', encoding='utf-8', errors='ignore') as _mf:
            _BUILD_META = _json.load(_mf)
            logger.info(f"[INIT] 载入构建元数据: {_BUILD_META}")
    else:
        logger.info("[INIT] 未找到 build_meta.json (源码运行或未嵌入版本信息)")
except Exception as _be:
    logger.warning(f"[INIT] 读取 build_meta.json 失败: {_be}")
try:
    _tpl_search = None
    jl = getattr(app, 'jinja_loader', None)
    # some loaders expose 'searchpath', some 'search_path', some neither
    if jl is not None:
        _tpl_search = getattr(jl, 'searchpath', None) or getattr(jl, 'search_path', None)
    logger.info(f"[INIT] Template search path: {_tpl_search if _tpl_search else 'N/A'} UI_VERSION={UI_VERSION}")
except Exception:
    logger.info(f"[INIT] Template search path: <unavailable> UI_VERSION={UI_VERSION}")

# 抑制大量 /queue_status 访问日志噪音
class _SuppressQueueStatusFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        msg = record.getMessage()
        if 'GET /queue_status' in msg:
            return False
        if 'GET /.well-known/appspecific/com.chrome.devtools.json' in msg:
            # Chrome / Edge devtools 探测请求, 忽略
            return False
        return True

try:
    _wlog = logging.getLogger('werkzeug')
    _wlog.addFilter(_SuppressQueueStatusFilter())
except Exception:
    pass

# --- 新任务管理与错误分类模块集成 ---
# 为了在打包或某些启动目录下仍能找到同目录的模块, 这里显式把脚本所在目录加入 sys.path
try:
    _APP_DIR = os.path.dirname(os.path.abspath(__file__))
    if _APP_DIR not in sys.path:
        sys.path.insert(0, _APP_DIR)
except Exception:
    pass

try:
    from errors import classify_error  # type: ignore
    import tasks as tasks_mod  # type: ignore
except Exception as _im_err:
    logger.error(f"初始化扩展模块失败: {_im_err}")
    classify_error = None
    tasks_mod = None

# Flask 3.x 已移除 before_first_request，改为“导入阶段尝试 + before_request 一次性”策略
_TM_INIT_DONE = False
_TM_INIT_LOCK = threading.Lock()

def _ensure_task_manager_initialized():
    global _TM_INIT_DONE
    if _TM_INIT_DONE:
        return
    with _TM_INIT_LOCK:
        if _TM_INIT_DONE:
            return
        try:
            tm = _get_task_manager()
            if tm is None and tasks_mod and getattr(tasks_mod, 'init_task_manager', None):
                tasks_mod.init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)
                tm = _get_task_manager()
            if tm:
                logger.info("[INIT] TaskManager 就绪 (lazy one-time)")
                _TM_INIT_DONE = True
            else:
                logger.error("[INIT] TaskManager 初始化失败 (lazy one-time)")
        except Exception as _e:
            logger.error(f"[INIT] TaskManager 初始化异常: {_e}")

# 1) 导入阶段不再强制初始化，避免未定义顺序异常；改为懒加载 + 启动阶段显式初始化。

# 2) 作为兜底，在每次请求前检查一次（成本极低）
@app.before_request  # type: ignore[attr-defined]
def _tm_guard():
    if not _TM_INIT_DONE:
        _ensure_task_manager_initialized()

# 统一获取 TaskManager，避免 from x import var 的绑定时序问题
def _get_task_manager():
    try:
        tm = tasks_mod.task_manager if (tasks_mod and getattr(tasks_mod, 'task_manager', None) is not None) else None
        if tm is None and tasks_mod and getattr(tasks_mod, 'init_task_manager', None):
            try:
                logger.warning("[LAZY_INIT] TaskManager 未在启动阶段创建，进行延迟初始化…")
                tm = tasks_mod.init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)
                if tm:
                    logger.info("[LAZY_INIT] TaskManager 延迟初始化成功")
            except Exception as _late_err:
                logger.error(f"[LAZY_INIT] TaskManager 延迟初始化失败: {_late_err}")
                tm = None
        return tm
    except Exception:
        return None

# --- 通用工具函数 ---
def _extract_root_cause(msg: str) -> str:
    if not msg:
        return "未知错误"
    # 常见可读性提升
    lower = msg.lower()
    if 'could not copy' in lower and 'cookie database' in lower:
        return '无法复制浏览器 cookies。请完全关闭所有浏览器窗口（Chrome/Edge 等）后再重试。'
    # 分类模式
    if any(x in lower for x in ['sign in to confirm', 'not a bot', 'consent required']):
        return '需要登录验证（YouTube 验证/风控），请更新 cookies.txt'
    if 'you must provide at least one url' in lower:
        return '内部命令构建缺少URL（可能是前端传参丢失）'
    if 'this video is private' in lower:
        return '视频是私有的（需要登录有权限账号）'
    if 'members-only content' in lower or 'join this channel' in lower:
        return '频道会员专属内容，需要对应会员账号'
    if 'age-restricted' in lower or 'confirm your age' in lower:
        return '年龄限制视频，需要已验证成年账号的 cookies'
    if 'this video is not available in your country' in lower or 'region' in lower and 'available' in lower:
        return '区域限制（尝试切换 VPN 节点或 geo-bypass）'
    if 'http error 429' in lower or 'too many requests' in lower:
        return '请求过于频繁，被限流（休息/换节点）'
    if 'http error 410' in lower:
        return '资源暂时不可用（410 Gone），可能接口策略变化或风控'
    if 'incompleteread' in lower or 'timed out' in lower or 'timeout' in lower:
        return '网络超时或连接被重置（检查网络/VPN/限流）'
    if 'unable to extract' in lower and 'info' in lower:
        return '解析失败（可能是 yt-dlp 版本过旧，尝试更新）'
    # 默认：取首行
    return msg.split('\n')[0][:400]

# 辅助: 尝试用 classify_error 得到 error_code
def _classify_with_code(msg: str):
    if not msg:
        return None, '未知错误'
    if classify_error:
        code, friendly = classify_error(msg)
        return code, friendly
    return None, _extract_root_cause(msg)

# --- 全局异常捕获 (统一返回 JSON，避免前端只看到 500) ---
@app.errorhandler(Exception)
def global_exception_handler(e):
    # 对 HTTPException 不强制转 500, 保留其原始状态码
    if isinstance(e, HTTPException):
        # 仅对 404 做更友好处理（避免被误认为 500）
        if isinstance(e, NotFound):
            # 尝试区分 API vs 前端路由
            accept_json = request.path.startswith('/api/') or request.path.startswith('/diag') or 'application/json' in request.headers.get('Accept','')
            if accept_json:
                return jsonify({'error': 'not_found', 'path': request.path}), 404
            # 非 API: 返回前端页面(单页应用可选策略) 这里仍返回 JSON 以简单化
            return jsonify({'error': 'not_found', 'path': request.path}), 404
        # 其他 HTTPException 直接返回原生响应
        return e
    err_text = ''.join(traceback.format_exception_only(type(e), e)).strip()
    logger.error(f"[GLOBAL_ERROR] {err_text}\n{traceback.format_exc()}")
    return jsonify({'error': _extract_root_cause(str(e)), 'detail': err_text}), 500

@retry_on_failure(max_retries=2, backoff_factor=1.5, exceptions=(subprocess.TimeoutExpired, ConnectionError, OSError))
def get_video_info(url, is_playlist=False):
    """获取视频信息，添加超时和缓存机制。为播放列表单独处理。"""
    # 对播放列表禁用缓存，因为内容可能经常变化
    if not is_playlist:
        cache_key = url
        cached_result = video_info_cache.get(cache_key)
        if cached_result is not None:
            logger.info("使用缓存的视频信息")
            return cached_result

    # 基础命令
    cmd = [config.YTDLP_PATH, '--no-warnings', '--dump-json', '--no-check-certificate',
           '--socket-timeout', '15', '--extractor-retries', '3']

    # 为播放列表使用 --flat-playlist 提高效率
    if is_playlist:
        cmd.extend(['--flat-playlist'])
    else:
        # 单个视频不处理播放列表，加快速度
        cmd.extend(['--no-playlist'])

    cmd.append(url)

    # 添加 Cookies
    # 遵循环境变量设置：UMD_DISABLE_BROWSER_COOKIES / UMD_FORCE_BROWSER_COOKIES
    disable_browser = os.environ.get('UMD_DISABLE_BROWSER_COOKIES','').lower() in ('1','true','yes')
    force_browser = os.environ.get('UMD_FORCE_BROWSER_COOKIES','').lower() in ('1','true','yes')

    if os.path.exists(config.COOKIES_FILE) and not disable_browser:
        cmd.extend(['--cookies', config.COOKIES_FILE])
        logger.info(f"[GET_VIDEO_INFO] 使用cookies.txt文件: {config.COOKIES_FILE}")
    elif force_browser and not disable_browser:
        try:
            cmd.extend(['--cookies-from-browser', 'chrome'])
            logger.info("[GET_VIDEO_INFO] FORCE_BROWSER_COOKIES=1，尝试Chrome浏览器cookies")
        except Exception as e:
            logger.warning(f"[GET_VIDEO_INFO] 浏览器cookies提取失败: {e}")
    elif disable_browser:
        logger.info("[GET_VIDEO_INFO] UMD_DISABLE_BROWSER_COOKIES=1，跳过浏览器cookies提取")
    else:
        logger.info("[GET_VIDEO_INFO] 未找到cookies.txt文件，且未强制使用浏览器cookies")

    try:
        process = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                               errors='ignore', creationflags=CREATE_NO_WINDOW, timeout=30)

        if process.returncode != 0:
            raise Exception(f"获取视频信息失败: {process.stderr}")

        lines = process.stdout.strip().split('\n')

        # 检查是否是播放列表的响应
        first_line_data = json.loads(lines[0])
        is_playlist_response = first_line_data.get('_type') == 'playlist' or 'playlist' in first_line_data

        if is_playlist_response:
            # 如果是播放列表，我们已经用了 --flat-playlist，直接处理
            info = [json.loads(line) for line in lines if line.strip()]
            info = [i for i in info if i is not None]  # 过滤掉 None 值
            if not info:
                raise Exception("获取播放列表信息失败，返回空数据")
            playlist_title = info[0].get('playlist_title') or info[0].get('title', '未知播放列表')
            for entry in info:
                entry['is_playlist'] = True
                entry['playlist_title'] = playlist_title
            return info
        else:
            # 单个视频
            info = json.loads(lines[0])
            if info is None:
                raise Exception("获取视频信息失败，返回空值")
            if not is_playlist:
                video_info_cache.set(url, info)
            return info

    except subprocess.TimeoutExpired:
        raise Exception("获取视频信息超时")
    except json.JSONDecodeError:
        raise Exception("视频信息解析失败")








@app.route('/')
def index():
    return render_template('index.html', ui_version=UI_VERSION)

@app.route('/info')
def video_info_route():
    url = request.args.get('url')
    if not url: return jsonify({'error': '缺少URL参数'}), 400

    # 安全验证
    if not validate_url(url):
        return jsonify({'error': '无效的URL格式'}), 400

    try:
        logger.info(f"收到信息获取请求 - URL: {url}")
        # 判断是否包含播放列表参数
        is_playlist = 'list=' in url

        if is_playlist:
            # 播放列表统一使用 flat 模式，仅返回条目基础信息
            info = get_video_info(url, is_playlist=True)
            if not isinstance(info, list):
                info = info.get('entries', []) if info else []
            playlist_title = '未知播放列表'
            if info and isinstance(info[0], dict):
                playlist_title = info[0].get('playlist_title') or info[0].get('title', playlist_title)
            videos = []
            for entry in info:
                if not entry: continue
                videos.append({
                    'id': entry.get('id'),
                    'url': entry.get('webpage_url', entry.get('url')),
                    'title': entry.get('title', '未知标题')
                })
            return jsonify({'type': 'playlist', 'title': playlist_title, 'videos': videos, 'playlist_url': url})

        # 单视频
        info = get_video_info(url, is_playlist=False)
        if isinstance(info, list) and info:
            info = info[0]

        # 类型防御：yt-dlp 可能返回 dict / list (播放列表)；这里只需要主视频字典
        if not isinstance(info, dict) and isinstance(info, list) and info:
            info = info[0]
        if not isinstance(info, dict):
            info = {}
        title = info.get('title', '未知标题')  # type: ignore[assignment]
        manual_subs = info.get('subtitles', {}) or {}  # type: ignore[assignment]
        auto_captions = info.get('automatic_captions', {}) or {}  # type: ignore[assignment]
        sub_options = []
        found_langs = set()

        # 人工字幕优先
        for lang_code in sorted(manual_subs.keys()):
            simple_lang_code = lang_code.split('-')[0]
            if simple_lang_code in found_langs:
                continue
            display_name = LANGUAGE_CODES.get(simple_lang_code, simple_lang_code)
            sub_options.append({'value': lang_code, 'text': f'{display_name} (人工)'})
            found_langs.add(simple_lang_code)

        # 自动字幕（若人工同语种已存在则跳过）
        for lang_code in sorted(auto_captions.keys()):
            simple_lang_code = lang_code.split('-')[0]
            if simple_lang_code in found_langs:
                continue
            display_name = LANGUAGE_CODES.get(simple_lang_code, simple_lang_code)
            sub_options.append({'value': lang_code, 'text': f'{display_name} (自动)'})
            found_langs.add(simple_lang_code)

        return jsonify({
            'type': 'video',
            'title': title,
            'id': info.get('id'),  # type: ignore[call-arg]
            'url': info.get('webpage_url', url),  # type: ignore[call-arg]
            'sub_options': sub_options
        })
    except Exception as e:
        logger.error(f"获取信息失败: {traceback.format_exc()}")
        return jsonify({'error': _extract_root_cause(str(e)), 'raw': str(e)}), 500

@app.route('/add_to_queue', methods=['POST'])
def add_to_queue():
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500

    # 使用 get_json 代替直接访问 request.json (对类型检查 & 容错更友好)
    data = _safe_get_json(request)
    if not isinstance(data, dict):  # 再次防御
        data = {}
    videos = data.get('videos', [])  # type: ignore[assignment]
    quality = data.get('quality', 'best')  # type: ignore[assignment]
    req_vfmt = data.get('video_format')  # type: ignore[assignment]
    req_afmt = data.get('audio_format')  # type: ignore[assignment]
    task_type = data.get('task_type', 'video')  # type: ignore[assignment]
    sub_lang = data.get('sub_lang')  # type: ignore[assignment]
    download_mode = data.get('download_mode', 'merged')  # type: ignore[assignment]

    if not videos:
        return jsonify({'error': '没有要添加的项目'}), 400

    added_count = 0
    for video in videos:
        if not video or not video.get('url'):
            logger.warning(f"跳过无效任务（缺少URL）：{video.get('title', '未知标题')}")
            continue

        # 适配 TaskManager 的 add_task 方法
        if task_type == 'subtitle':
            tm.add_task(
                url=video['url'],
                title=f"[字幕] {video['title']}",
                subtitles_only=True,
                subtitles=[sub_lang] if sub_lang else []
            )
        else:
            tm.add_task(
                url=video['url'],
                title=video['title'],
                quality=quality,
                video_format=req_vfmt,
                audio_format=req_afmt,
                mode=download_mode
            )
        
        logger.info(f"任务 ({video['title']}) 已通过旧API添加到队列")
        added_count += 1

    if added_count > 0:
        return jsonify({'message': f'{added_count} 个任务已添加到队列'})
    else:
        return jsonify({'error': '未能添加任何有效任务'}), 400

@app.route('/queue_status')
def queue_status():
    tm = _get_task_manager()
    if not tm:
        return jsonify([])
    
    tasks_list = tm.list_tasks()
    status_order = {'downloading': 0, 'merging': 1, 'queued': 2, 'finished': 3, 'error': 4, 'canceled': 5}
    sorted_tasks = sorted(tasks_list, key=lambda x: status_order.get(x['status'], 99))
    
    return jsonify(sorted_tasks)

@app.route('/clear_finished', methods=['POST'])
def clear_finished():
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    
    removed_count = tm.cleanup_finished_tasks()
    logger.info(f"通过旧API清除了 {removed_count} 个任务")
    return jsonify({'message': '已清除已完成的任务'})

@app.route('/diag/yt')
def diag_yt():
    """诊断指定 YouTube URL 的可访问性、cookies、生效的 ffmpeg、出口 IP。
    前端调用: /diag/yt?url=...  返回 JSON 方便排查 500 的根因。
    """
    test_url = request.args.get('url')
    if not test_url:
        return jsonify({'error': '缺少 url 参数'}), 400

    # 安全验证
    if not validate_url(test_url):
        return jsonify({'error': '无效的URL格式'}), 400

    result = {
        'input_url': test_url,
        'ffmpeg_path': get_ffmpeg_path() or None,
        'has_cookies_file': os.path.exists(config.COOKIES_FILE),
        'yt_dlp_returncode': None,
        'yt_dlp_short_error': None,
        'yt_dlp_stdout_first_line': None,
        'suspect_auth': False,
        'suspect_region': False,
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z'
    }

    # 基础探测命令: 不做下载, 只 dump JSON
    cmd = [config.YTDLP_PATH, '--no-warnings', '--skip-download', '--dump-single-json', '--no-check-certificate', '--socket-timeout', '15', '--extractor-retries', '2', '--no-playlist', test_url]
    if result['has_cookies_file']:
        cmd.extend(['--cookies', config.COOKIES_FILE])
    else:
        # 不直接用自动提取，避免阻塞；用户需要自己准备 cookies
        pass

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW, timeout=35)
        result['yt_dlp_returncode'] = proc.returncode
        if proc.stdout:
            first_line = proc.stdout.strip().split('\n')[0]
            result['yt_dlp_stdout_first_line'] = first_line[:400]
        if proc.returncode != 0:
            stderr_msg = (proc.stderr or '').strip()
            code, friendly = _classify_with_code(stderr_msg)
            result['yt_dlp_short_error'] = friendly
            if code:
                result['error_code'] = code
            low = stderr_msg.lower()
            if 'sign in to confirm' in low or 'consent' in low or 'bot' in low:
                result['suspect_auth'] = True
            if 'this video is not available in your country' in low or 'country' in low or 'region' in low:
                result['suspect_region'] = True
        else:
            # 尝试解析 JSON 取一些字段
            try:
                data = json.loads(proc.stdout.strip())
                result['video_id'] = data.get('id')
                result['title'] = data.get('title')
                result['uploader'] = data.get('uploader')
                result['age_limit'] = data.get('age_limit')
                result['availability'] = data.get('availability')
            except Exception as je:
                result['parse_warning'] = f'JSON 解析失败: {je}'
        return jsonify(result)
    except subprocess.TimeoutExpired:
        result['yt_dlp_short_error'] = '超时 (timeout)'
        return jsonify(result), 504
    except Exception as e:
        result['yt_dlp_short_error'] = f'内部异常: {e}'
        return jsonify(result), 500

@app.route('/diag/routes')
def list_routes():
    output = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint != 'static':
            try:
                mset = getattr(rule, 'methods', None)
                if mset is None:
                    methods_list = []
                else:
                    try:
                        methods_list = sorted([m for m in mset if m not in {'HEAD','OPTIONS'}])  # type: ignore[iterable]
                    except Exception:
                        methods_list = []
                output.append({'rule': str(rule), 'methods': methods_list, 'endpoint': rule.endpoint})
            except Exception:
                output.append({'rule': str(rule), 'methods': [], 'endpoint': getattr(rule,'endpoint', '?')})
    return jsonify({'count': len(output), 'routes': output})

@app.route('/diag/raw_formats')
def diag_raw_formats():
    """快速列出指定 URL 的原始格式高度/编码，用于分析为什么看不到 4K/8K。
    只做信息获取，不下载。"""
    url = request.args.get('url','').strip()
    if not url:
        return jsonify({'error':'缺少 url'}), 400

    # 安全验证
    if not validate_url(url):
        return jsonify({'error': '无效的URL格式'}), 400
    cmd = [config.YTDLP_PATH, '--skip-download', '--dump-single-json', '--no-warnings', '--no-check-certificate', '--no-playlist', url]
    if os.path.exists(config.COOKIES_FILE):
        cmd += ['--cookies', config.COOKIES_FILE]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=45, creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0:
            return jsonify({'error':'yt-dlp失败','stderr':(proc.stderr or proc.stdout)[:800]}), 502
        info = json.loads(proc.stdout)
        formats = info.get('formats') or []
        compact = []
        for f in formats:
            compact.append({
                'id': f.get('format_id'),
                'height': f.get('height'),
                'fps': f.get('fps'),
                'vcodec': f.get('vcodec'),
                'acodec': f.get('acodec'),
                'note': f.get('format_note'),
                'filesize': f.get('filesize') or f.get('filesize_approx')
            })
        max_h = max([c['height'] for c in compact if c.get('height')], default=None)
        return jsonify({'title': info.get('title'), 'video_id': info.get('id'), 'max_height': max_h, 'count': len(compact), 'formats': compact})
    except subprocess.TimeoutExpired:
        return jsonify({'error':'timeout'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/diag/template')
def diag_template():
    """返回 index.html 实际文件路径与时间戳，帮助诊断缓存 / 打包路径问题"""
    try:
        tpl_path = os.path.join(config.resource_path('templates'), 'index.html')
        info = None
        if os.path.exists(tpl_path):
            stat = os.stat(tpl_path)
            with open(tpl_path, 'rb') as f:
                head = f.read(160)
            info = {
                'path': tpl_path,
                'size': stat.st_size,
                'mtime': stat.st_mtime,
                'head_snippet': head.decode('utf-8','ignore')[:140]
            }
        return jsonify({'ui_version': UI_VERSION, 'template': info})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/diag/ytdlp_version')
def diag_ytdlp_version():
    """获取 yt-dlp 版本信息"""
    try:
        current_version = get_ytdlp_version()
        update_info = check_ytdlp_update()

        result = {
            'current_version': current_version,
            'update_status': update_info.get('status', 'unknown'),
            'path': config.YTDLP_PATH,
            'exists': os.path.exists(config.YTDLP_PATH)
        }

        if 'old_version' in update_info:
            result['old_version'] = update_info['old_version']
        if 'new_version' in update_info:
            result['new_version'] = update_info['new_version']

        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/diag/cookie_strategy')
def diag_cookie_strategy():
    cookies_file_exists = os.path.exists(config.COOKIES_FILE)
    force = os.environ.get('UMD_FORCE_BROWSER_COOKIES','').lower() in ('1','true','yes')
    disable = os.environ.get('UMD_DISABLE_BROWSER_COOKIES','').lower() in ('1','true','yes')
    if cookies_file_exists:
        mode = 'file'
    elif disable:
        mode = 'none'
    elif force:
        mode = 'browser'
    else:
        mode = 'none'
    return jsonify({
        'cookies_file_exists': cookies_file_exists,
        'force_browser_env': force,
        'disable_browser_env': disable,
        'effective_mode': mode,
        'cookies_file': config.COOKIES_FILE
    })

@app.route('/diag/version')
def diag_version():
    return jsonify({
        'ui_version': UI_VERSION,
        'build_meta': _BUILD_META,
        'python': sys.version,
        'cwd': os.getcwd(),
        'ffmpeg_path': get_ffmpeg_path() or None
    })

@app.route('/diag/update_ytdlp', methods=['POST'])
def diag_update_ytdlp():
    """手动更新 yt-dlp 到最新版本"""
    try:
        result = update_ytdlp()
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新异常: {str(e)}'}), 500

@app.route('/download')
def download():
    # 统一弃用说明：前端应迁移到 /api/stream_task
    # 返回 410 Gone 以便旧前端明确感知需要升级
    payload = {
        'error': 'endpoint_deprecated',
        'message': '此下载端点已弃用，请升级前端并改用 /api/stream_task (SSE) 获取进度。',
        'replacement': '/api/stream_task',
        'example': '/api/stream_task?url=...&mode=merged&quality=best'
    }
    return jsonify(payload), 410


@app.route('/api/stream_task')
def api_stream_task():
    """创建一个 TaskManager 任务并通过 SSE 实时输出日志与进度。
    参数:
      url: 视频 URL
      mode: merged|video_only|audio_only|subtitles
      quality: best|best4k|best8k|fast|height<=720 等
      subtitles: 可选，逗号分隔语言 (仅当 mode=merged 且需要字幕)
      subtitles_only: true 仅下载字幕
    返回: text/event-stream
    """
    url = request.args.get('url','').strip()
    mode = request.args.get('mode','merged').strip()
    quality = request.args.get('quality','best').strip()
    # 新增: 直接传递格式 ID (来自前端 quality_pairs)
    video_format = request.args.get('video_format')
    audio_format = request.args.get('audio_format')
    subtitles = request.args.get('subtitles')
    subtitles_only = request.args.get('subtitles_only','false').lower() in ('1','true','yes') or mode == 'subtitles'
    if mode == 'subtitles':  # 兼容旧前端值
        mode = 'merged'  # TaskManager 内部通过 subtitles_only 判断
        subtitles_only = True
    # 新增：meta (0/1/off/sidecar/folder)。前端简单勾选 -> 1=sidecar, 0=off
    meta_param = request.args.get('meta')  # 可能是 '0','1','off','sidecar','folder'
    meta_mode = None
    if meta_param:
        mp = meta_param.strip().lower()
        if mp in ('0','off','false','no'):
            meta_mode = 'off'
        elif mp in ('1','yes','true','on','sidecar'):
            meta_mode = 'sidecar'
        elif mp in ('folder','dir','directory'):
            meta_mode = 'folder'
        # 其它值忽略，继续使用环境策略
    
    # 新增：封面图下载
    write_thumbnail = request.args.get('thumbnail', '0').lower() in ('1', 'true', 'yes')

    if not url:
        return Response('data: {"error":"缺少 url"}\n\n', mimetype='text/event-stream')
    if not validate_url(url):
        return Response('data: {"error":"无效的URL格式"}\n\n', mimetype='text/event-stream')
    tm = _get_task_manager()
    if not tm:
        return Response('data: {"error":"任务系统未初始化"}\n\n', mimetype='text/event-stream')

    # 建立任务
    # 新增：跳过 probe 支持 (前端把 /api/info 的缓存核心字段发送过来)
    skip_probe = request.args.get('skip_probe','0').lower() in ('1','true','yes')
    info_cache_raw = request.args.get('info_cache')
    info_cache = None
    if info_cache_raw:
        # 两阶段解析：直接解析 -> URL 解码再解析
        raw_first = info_cache_raw
        parse_err = None
        for attempt in (0,1):
            trial = raw_first if attempt == 0 else None
            if attempt == 1:
                try:
                    from urllib.parse import unquote
                    trial = unquote(raw_first)
                except Exception as _uqe:
                    parse_err = _uqe
                    trial = None
            if not trial:
                continue
            try:
                info_cache = json.loads(trial)
                if attempt == 1:
                    logger.info('[API_STREAM_TASK] info_cache 经过 URL 解码后解析成功')
                break
            except Exception as e:
                parse_err = e
                info_cache = None
        if info_cache is None and parse_err:
            logger.warning(f'[API_STREAM_TASK] info_cache 解析失败: {parse_err}')
    if skip_probe and not isinstance(info_cache, dict):
        logger.info('[API_STREAM_TASK] skip_probe=1 但 info_cache 无效，回退至正常探测路径')
    logger.info(f"[API_STREAM_TASK] skip_probe={skip_probe} info_cache_keys={list(info_cache.keys()) if isinstance(info_cache, dict) else None}")
    task = tm.add_task(url=url, mode=mode, quality=quality, subtitles_only=subtitles_only,
                       subtitles=subtitles.split(',') if subtitles else [],
                       video_format=video_format, audio_format=audio_format,
                       meta_mode=meta_mode, skip_probe=skip_probe, info_cache=info_cache,
                       write_thumbnail=write_thumbnail)

    def event_stream():
        last_offset = 0
        logger.info(f"[API_STREAM_TASK] SSE 开始推送 task_id={task.id}")
        first_progress_logged = False
        client_disconnected = False
        yield f'data: {{"task_id":"{task.id}","status":"queued"}}\n\n'
        # 轮询任务日志
        while True:
            try:
                current = tm.get_task(task.id)
                if not current:
                    yield 'data: {"error":"任务丢失"}\n\n'
                    break
                # 输出增量日志
                if len(current.log) > last_offset:
                    new_slice = current.log[last_offset:]
                    for line in new_slice:
                        if (not first_progress_logged) and ('[timing] time_to_first_progress=' in line or 'download' in line.lower()):
                            first_progress_logged = True
                            logger.info(f"[API_STREAM_TASK] 首次进度日志出现 task_id={task.id}")
                        yield 'data: '+ json.dumps({'type':'log','line': line[-800:]}, ensure_ascii=False) + '\n\n'
                    last_offset = len(current.log)
                # 输出状态快照
                payload = {
                    'type':'status',
                    'task_id': current.id,
                    'status': current.status,
                    'stage': current.stage,
                    'progress': round(current.progress,2),
                    'file_path': current.file_path,
                    'vcodec': current.vcodec,
                    'acodec': current.acodec,
                    'width': current.width,
                    'height': current.height
                }
                yield 'data: '+ json.dumps(payload, ensure_ascii=False) + '\n\n'
                if current.status in ('finished','error','canceled'):
                    break
            except GeneratorExit:
                client_disconnected = True
                logger.info(f"[API_STREAM_TASK] 客户端断开 task_id={task.id}")
                break
            except Exception as e:
                logger.error(f"[stream_task] SSE 循环异常: {e}")
                yield 'data: {"error":"内部异常"}\n\n'
                break
            time.sleep(1.0)
        # 只有在非客户端主动断开时才发送结束事件，避免 GeneratorExit 后继续 yield 触发 RuntimeError
        if not client_disconnected:
            yield 'data: {"event":"end"}\n\n'
    return Response(event_stream(), mimetype='text/event-stream')

@app.route('/ping')
def ping():
    return jsonify({'status': 'ok', 'time': datetime.datetime.utcnow().isoformat() + 'Z'})

# ---------------- 新 API: /api/info 结构化格式列表 ----------------
@app.route('/api/info', methods=['POST'])
def api_info():
    data = _safe_get_json(request)
    url = (data.get('url') or '').strip()
    geo_bypass = bool(data.get('geo_bypass'))
    if not url:
        return jsonify({'error': '缺少 url', 'error_code': 'invalid_input'}), 400

    # 安全验证
    if not validate_url(url):
        return jsonify({'error': '无效的URL格式', 'error_code': 'invalid_url'}), 400

    logger.info(f"[api_info] url={url}")

    # -------- In-flight 合并: 若已有相同 URL 正在探测，进入等待 --------
    existing_inflight = _get_inflight(url)
    stale_limit = float(getattr(config, 'INFO_INFLIGHT_STALE_SEC', 0) or 0)
    if existing_inflight and stale_limit > 0:
        age = time.time() - existing_inflight.start
        if age > stale_limit:
            logger.warning(f"[api_info] 发现陈旧探测 (stage={existing_inflight.stage}, age={age:.1f}s) -> 强制重启 url={url}")
            _force_cleanup_inflight(url, existing_inflight, {
                'error': '上一次信息探测耗时过长，已自动重启',
                'error_code': 'info_probe_stale',
                'stale': True,
                'stage': existing_inflight.stage,
                'age_seconds': round(age, 1),
                '_status': 504
            })
            existing_inflight = None
    if existing_inflight:
        existing_inflight.waiters += 1
        # 动态等待：Twitter/X 给更长窗口以避免大量 202 (primary+hardened 可能就 >18s)
        site_wait_default = getattr(config, 'INFO_MAX_WAIT_DEFAULT', 18.0)
        site_wait_twitter = getattr(config, 'INFO_MAX_WAIT_TWITTER', 40.0)
        dynamic_wait = site_wait_twitter if ('twitter.com' in url.lower() or 'x.com' in url.lower()) else site_wait_default
        max_wait = float(data.get('max_wait', dynamic_wait))
        logger.info(f"[api_info] 发现进行中的探测, waiters={existing_inflight.waiters} stage={existing_inflight.stage} 等待最多 {max_wait}s url={url}")
        finished = existing_inflight.event.wait(timeout=max_wait)
        if finished:
            # 复用首个请求的结果或错误
            if existing_inflight.result is not None:
                payload = dict(existing_inflight.result)
                payload['coalesced'] = True
                return jsonify(payload)
            if existing_inflight.error is not None:
                err_payload = dict(existing_inflight.error)
                err_payload['coalesced'] = True
                status = err_payload.pop('_status', 502)
                return jsonify(err_payload), status
            # 边界: 设置了 event 但无结果 (异常路径) -> 作为未知失败
            return jsonify({'error':'未知错误(合并路径)','error_code':'inflight_unknown','coalesced':True}), 500
        else:
            # 超时仍未完成: 返回进行中提示 (202 Accepted)，附带当前阶段
            remain = max(1, int(max_wait))
            return jsonify({'in_progress': True, 'message': '信息获取仍在进行, 稍后重试', 'url': url, 'suggest_retry_sec': remain, 'current_stage': existing_inflight.stage}), 202

    # 创建新的 inflight 记录 (首个请求)
    inflight = _create_inflight(url)

    # 检测网站类型，采用不同的策略
    is_adult_site = any(domain in url.lower() for domain in ['pornhub.com', 'xvideos.com', 'xnxx.com', 'youporn.com'])
    is_twitter = 'twitter.com' in url.lower() or 'x.com' in url.lower()
    is_youtube = 'youtube.com' in url.lower() or 'youtu.be' in url.lower()

    # -------- Twitter/X 预探测 (preflight) --------
    def _twitter_preflight(host: str = 'x.com') -> dict[str, Any]:
        import socket, ssl
        result: dict[str, Any] = {'host': host}
        # 读取环境控制参数（允许打包后用户在 .env 配置）
        _pf_tcp_timeout = float(os.environ.get('UMD_TWITTER_PREFLIGHT_TCP_TIMEOUT', '2.5') or '2.5')
        if _pf_tcp_timeout < 0.8:  # 防守：最低 0.8s
            _pf_tcp_timeout = 0.8
        _pf_ip_limit = int(os.environ.get('UMD_TWITTER_PREFLIGHT_IP_LIMIT', '1') or '1')
        if _pf_ip_limit < 1:
            _pf_ip_limit = 1
        elif _pf_ip_limit > 5:
            _pf_ip_limit = 5  # 防止过度探测
        try:
            t0 = time.time()
            addrs = socket.getaddrinfo(host, 443)
            result['dns_ms'] = int((time.time() - t0) * 1000)
            v4: list[str] = []
            v6: list[str] = []
            for a in addrs:
                try:
                    ip_raw = a[4][0]
                    ip = str(ip_raw)
                    if ':' in ip:
                        if ip not in v6:
                            v6.append(ip)
                    else:
                        if ip not in v4:
                            v4.append(ip)
                except Exception:
                    continue
            if v4:
                result['ipv4'] = v4[:3]
            if v6:
                result['ipv6'] = v6[:3]
        except Exception as e:
            result['dns_error'] = str(e)
            return result

        def _try(ip: str):
            rec: dict[str, Any] = {'ip': ip}
            s = None
            try:
                family = socket.AF_INET6 if ':' in ip else socket.AF_INET
                s = socket.socket(family, socket.SOCK_STREAM)
                s.settimeout(_pf_tcp_timeout)
                t1 = time.time()
                s.connect((ip, 443))
                rec['tcp_ms'] = int((time.time() - t1) * 1000)
                ctx = ssl.create_default_context()
                t2 = time.time()
                ss = ctx.wrap_socket(s, server_hostname=host)
                try:
                    ss.do_handshake()
                    rec['tls_ms'] = int((time.time() - t2) * 1000)
                finally:
                    try:
                        ss.close()
                    except Exception:
                        pass
            except Exception as ex:
                rec['error'] = str(ex)[:160]
            finally:
                try:
                    if s:
                        s.close()
                except Exception:
                    pass
            return rec

        for ip in result.get('ipv4', [])[:_pf_ip_limit]:
            result.setdefault('probes', []).append(_try(ip))
        for ip in result.get('ipv6', [])[:max(1, min(1, _pf_ip_limit))]:  # IPv6 保守一个
            result.setdefault('probes', []).append(_try(ip))
        result['tcp_timeout_sec'] = _pf_tcp_timeout
        result['ip_limit'] = _pf_ip_limit
        return result

    preflight = None
    # lenient: 即使预探测失败也继续；strict: 失败直接 502；默认 strict
    _pf_mode = os.environ.get('UMD_TWITTER_PREFLIGHT_MODE', 'strict').lower().strip() or 'strict'
    if _pf_mode not in ('strict','lenient'):
        _pf_mode = 'strict'
    preflight_enabled_env = os.environ.get('UMD_TWITTER_PREFLIGHT','1').lower() not in ('0','false','no')
    # 新增: 预探测缓存 (减少频繁握手超时) key: host 固定 x.com TTL 可配置, 默认 30s
    _PREFLIGHT_CACHE_KEY = '_twitter_preflight_cache'
    preflight_cache_ttl = int(os.environ.get('UMD_TWITTER_PREFLIGHT_TTL','30') or '30')
    _now_ts = time.time()
    # 结构: {'ts': float, 'data': {...}}
    _pf_cache = video_info_cache.get(_PREFLIGHT_CACHE_KEY)
    if is_twitter and data.get('preflight', True) and preflight_enabled_env:
        try:
            proxy_url = getattr(config, 'PROXY_URL', '')
            # 若未配置代理且检测到常见本地端口 33210 正在监听，可尝试自动推断 (仅一次)
            if not proxy_url:
                try:
                    import socket as _sk
                    _auto_sock = _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM)
                    _auto_sock.settimeout(0.25)
                    if _auto_sock.connect_ex(('127.0.0.1', 33210)) == 0:
                        proxy_url = 'http://127.0.0.1:33210'
                        if preflight is None:
                            preflight = {'auto_proxy': proxy_url}
                        else:
                            preflight['auto_proxy'] = proxy_url
                    _auto_sock.close()
                except Exception:
                    pass
            # 命中缓存直接复用
            if _pf_cache and (_now_ts - _pf_cache.get('ts',0) < preflight_cache_ttl):
                preflight = dict(_pf_cache.get('data') or {})
                preflight['cache_hit'] = True
            else:
                preflight = _twitter_preflight('x.com')
            probe_list = preflight.get('probes') or []
            direct_all_failed = preflight.get('dns_error') or (probe_list and all('error' in p for p in probe_list))
            proxy_pass = False
            # 如果配置了代理，再做一次代理 HEAD 检测 (requests)，若代理成功则放行
            if proxy_url:
                try:
                    import requests  # type: ignore
                    test_url = 'https://x.com/robots.txt'
                    rp = requests.head(test_url, timeout=6, proxies={'http': proxy_url, 'https': proxy_url}, allow_redirects=True)
                    preflight['proxy_status_code'] = rp.status_code
                    proxy_pass = rp.status_code in (200,301,302,400,401,403,404)
                except Exception as rex:
                    preflight['proxy_error'] = str(rex)[:160]
            # 记录最近一次预探测
            try:
                global LAST_TWITTER_PREFLIGHT
                LAST_TWITTER_PREFLIGHT = dict(preflight)
                LAST_TWITTER_PREFLIGHT['timestamp'] = datetime.datetime.utcnow().isoformat() + 'Z'
                # 写入缓存 (仅非 cache_hit 情况, 或更新为最新)
                video_info_cache.set(_PREFLIGHT_CACHE_KEY, {'ts': _now_ts, 'data': preflight})
            except Exception:
                pass
            if direct_all_failed and not proxy_pass:
                if _pf_mode == 'strict':
                    logger.warning(f"[api_info] twitter 预探测失败(直连+代理都不通) mode=strict url={url} preflight={preflight}")
                    inflight.error = {'error': 'Twitter 网络不可达(预探测失败)', 'error_code': 'twitter_network_block', 'preflight': preflight, '_status': 502}
                    _publish_and_cleanup_inflight(url, inflight)
                    return jsonify({'error': 'Twitter 网络不可达(预探测失败)', 'error_code': 'twitter_network_block', 'preflight': preflight}), 502
                else:
                    # lenient: 记录警告但继续后续阶段，让 yt-dlp 亲自尝试；附带 degrade 标记
                    preflight['degraded'] = True
                    logger.warning(f"[api_info] twitter 预探测失败但 lenient 放行 url={url} preflight={preflight}")
            else:
                logger.info(f"[api_info] twitter 预探测放行 mode={_pf_mode} direct_failed={bool(direct_all_failed)} proxy_pass={proxy_pass} preflight={preflight}")
        except Exception as _pf_err:
            logger.warning(f"[api_info] twitter 预探测异常(忽略继续): {_pf_err}")

    # ---------- 新增: 统一多阶段探测 + 缓存 ----------
    cache_key = f"api_info::{url}"
    # Negative failure cache (避免短时间内重复打同一失败 URL 导致风控加重)
    neg_cache_key = f"api_info_fail::{url}"
    neg_rec = video_info_cache.get(neg_cache_key)
    if neg_rec:
        # 结构: {'last_err': str, 'ts': float, 'count': int}
        now_ts = time.time()
        # 升级冷却：失败次数超过阈值采用更长冷却
        base_cd = getattr(config, 'INFO_NEG_COOLDOWN_BASE', 180)
        escalated_cd = getattr(config, 'INFO_NEG_COOLDOWN_ESCALATED', 420)
        escalate_threshold = getattr(config, 'INFO_NEG_ESCALATE_THRESHOLD', 3)
        fails = neg_rec.get('count', 1)
        cooldown = escalated_cd if fails >= escalate_threshold else base_cd
        if now_ts - neg_rec.get('ts', 0) < cooldown:
            logger.info(f"[api_info] 负面缓存命中 (剩余 {int(cooldown-(now_ts-neg_rec.get('ts',0)))}s) url={url}")
            remain = int(cooldown-(now_ts-neg_rec.get('ts',0)))
            resp_payload = {
                'error': neg_rec.get('last_err') or '最近多次失败, 稍后再试',
                'error_code': 'recent_fail',
                'cooldown_remain': remain,
                'retry_after_seconds': remain,
                'fail_count': neg_rec.get('count', 1),
                'cooldown_escalated': True if fails >= escalate_threshold else False,
                'site_type': 'twitter' if ('twitter.com' in url.lower() or 'x.com' in url.lower()) else 'general'
            }
            r = jsonify(resp_payload)
            try:
                r.headers['Retry-After'] = str(remain)
            except Exception:
                pass
            return r, 429
    cached = video_info_cache.get(cache_key)
    if cached:
        logger.info("[api_info] 命中缓存结果")
        info = cached
        inflight.result = {'cached': True}  # 仅占位，稍后补充完整 payload
        _publish_and_cleanup_inflight(url, inflight)
    else:
        attempts: list[dict[str,Any]] = []

        def build_cmd(primary: bool, force_no_playlist: bool=False, hardened: bool=False, extended: bool=False, ip_family: str|None=None):
            base = [config.YTDLP_PATH, '--skip-download', '--dump-single-json', '--no-warnings', '--no-check-certificate']
            
            # 快速模式配置
            fast_mode = os.environ.get('UMD_FAST_INFO','').lower() in ('1','true','yes')
            if fast_mode:
                default_timeout = int(os.environ.get('INFO_SOCKET_TIMEOUT', '15'))
                default_retries = int(os.environ.get('INFO_EXTRACTOR_RETRIES', '2'))
                default_retry_sleep = int(os.environ.get('INFO_RETRY_SLEEP', '1'))
            else:
                default_timeout = 30
                default_retries = 5
                default_retry_sleep = 3
            
            # 通用/站点差异
            if is_adult_site:
                timeout = default_timeout if fast_mode else 30
                retries = default_retries if fast_mode else 5
                base += ['--no-playlist','--socket-timeout',str(timeout),'--extractor-retries',str(retries),'--http-chunk-size','1M','--force-ipv4',
                         '--user-agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                         '--sleep-interval','2','--max-sleep-interval','5','--referer','https://www.google.com/',
                         '--add-header','Accept-Language:en-US,en;q=0.9']
                if primary:
                    logger.info('[api_info] 成人站初次命令构建')
            elif is_twitter:
                # Twitter/X 延长超时, 强化 UA 与 header (extended 阶段再追加更多)
                timeout = default_timeout + 5 if fast_mode else 40
                retries = default_retries if fast_mode else 4
                base += ['--no-playlist','--socket-timeout',str(timeout),'--extractor-retries',str(retries),
                         '--user-agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0',
                         '--add-header','Referer:https://x.com/','--add-header','Accept-Language:en-US,en;q=0.9']
                if extended:
                    base += ['--socket-timeout','55','--extractor-retries','6',
                             '--add-header','Accept:*/*','--add-header','Origin:https://x.com']
            elif is_youtube:
                # 初次对 YouTube 单视频优先添加 --no-playlist (如 URL 带 list= 则后续 fallback 去掉)
                if force_no_playlist or primary:
                    base += ['--no-playlist']
                timeout = default_timeout
                retries = default_retries
                retry_sleep = default_retry_sleep
                fragment_retries = 5 if fast_mode else 10
                base += ['--socket-timeout',str(timeout),'--extractor-retries',str(retries),'--retry-sleep',str(retry_sleep),'--fragment-retries',str(fragment_retries)]
                # 增强反爬措施
                base += ['--user-agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36']
                base += ['--add-header','Accept-Language:en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7']
                base += ['--add-header','Referer:https://www.youtube.com/']
                if extended:
                    # extended 阶段更强的反爬措施
                    ext_timeout = default_timeout + 10 if fast_mode else 60
                    ext_retries = default_retries + 2 if fast_mode else 8
                    ext_retry_sleep = default_retry_sleep + 1 if fast_mode else 5
                    ext_fragment_retries = 8 if fast_mode else 15
                    base += ['--socket-timeout',str(ext_timeout),'--extractor-retries',str(ext_retries),'--retry-sleep',str(ext_retry_sleep),'--fragment-retries',str(ext_fragment_retries)]
                    base += ['--user-agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0']
                    base += ['--add-header','Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7']
                    base += ['--add-header','Accept-Encoding:gzip, deflate, br']
                    base += ['--add-header','Cache-Control:max-age=0']
                    base += ['--add-header','DNT:1']
                    base += ['--add-header','Origin:https://www.youtube.com']
                    base += ['--sleep-interval','3','--max-sleep-interval','7']
            else:
                base += ['--no-playlist','--socket-timeout','15','--extractor-retries','3']
            if hardened:
                base += ['--ignore-errors','--retry-sleep','2','--fragment-retries','10']
            # IP 家族策略: 默认不强制；可按阶段注入 --force-ipv4 / --force-ipv6
            if ip_family == 'v4':
                base += ['--force-ipv4']
            elif ip_family == 'v6':
                base += ['--force-ipv6']
            # 代理支持: 如果配置了 PROXY_URL
            try:
                proxy_url = getattr(config, 'PROXY_URL', '')
                if proxy_url:
                    base += ['--proxy', proxy_url]
            except Exception:
                pass
            if geo_bypass:
                base.append('--geo-bypass')
            # Cookie 策略：优先使用 cookies.txt 文件（如果存在且未被禁用）
            # 遵循环境变量设置：UMD_DISABLE_BROWSER_COOKIES / UMD_FORCE_BROWSER_COOKIES
            disable_browser = os.environ.get('UMD_DISABLE_BROWSER_COOKIES','').lower() in ('1','true','yes')
            force_browser = os.environ.get('UMD_FORCE_BROWSER_COOKIES','').lower() in ('1','true','yes')

            if os.path.exists(config.COOKIES_FILE) and not disable_browser:
                base += ['--cookies', config.COOKIES_FILE]
                logger.info(f"[API_INFO] 使用cookies.txt文件: {config.COOKIES_FILE}")
            elif force_browser and not disable_browser:
                try:
                    # 尝试从 Chrome 获取 cookies
                    base += ['--cookies-from-browser', 'chrome']
                    logger.info("[API_INFO] FORCE_BROWSER_COOKIES=1，尝试Chrome浏览器cookies")
                except Exception:
                    try:
                        # 回退到 Edge
                        base += ['--cookies-from-browser', 'edge']
                        logger.info("[API_INFO] 尝试Edge浏览器cookies")
                    except Exception as e:
                        logger.warning(f"[API_INFO] 浏览器cookies提取失败: {e}，继续无cookies")
            elif disable_browser:
                logger.info("[API_INFO] UMD_DISABLE_BROWSER_COOKIES=1，跳过浏览器cookies提取")
            else:
                logger.info("[API_INFO] 未找到cookies.txt文件，且未强制使用浏览器cookies")
            base.append(url)
            return base

        def run_once(tag: str, cmd: list[str], timeout_s: int, ip_family: str|None=None):
            logger.info(f"[api_info] 运行阶段 {tag}: {' '.join(cmd)}")
            start = time.time()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=timeout_s, creationflags=CREATE_NO_WINDOW)
                duration = round(time.time()-start,2)
                attempt_rec = {'stage': tag, 'returncode': proc.returncode, 'time': duration}
                if ip_family:
                    attempt_rec['ip_family'] = ip_family
                if proc.returncode != 0:
                    stderr_msg = (proc.stderr or '').strip() or proc.stdout[:400]
                    attempt_rec['stderr_head'] = stderr_msg[:220]
                    # 分类错误类别
                    cat = 'unknown'
                    sm = stderr_msg.lower() if stderr_msg else ''
                    if 'timed out' in sm or 'timeout' in sm:
                        cat = 'timeout'
                    elif 'connectionreset' in sm or '10054' in sm or 'reset' in sm or ('connection aborted' in sm and 'filenotfounderror' in sm):
                        cat = 'connection_reset'
                    elif '403' in sm or 'forbidden' in sm:
                        cat = 'forbidden'
                    elif '429' in sm or 'too many' in sm or 'rate' in sm:
                        cat = 'rate_limited'
                    attempt_rec['category'] = cat
                    # 新增: 失败阶段额外日志记录首段错误信息，便于问题诊断
                    if stderr_msg:
                        logger.warning(f"[api_info] 阶段 {tag} 失败 rc={proc.returncode} 错误前缀: {stderr_msg[:180]}")
                else:
                    attempt_rec['stdout_len'] = len(proc.stdout)
                attempts.append(attempt_rec)
                if proc.returncode == 0:
                    try:
                        data_obj = json.loads(proc.stdout)
                        return data_obj
                    except Exception as je:
                        attempt_rec['parse_error'] = str(je)
                        logger.warning(f"[api_info] 阶段 {tag} JSON 解析失败: {je}")
                        return None
                return None
            except subprocess.TimeoutExpired:
                attempts.append({'stage': tag, 'timeout': True})
                logger.warning(f"[api_info] 阶段 {tag} 超时 (>{timeout_s}s)")
                return None
            except Exception as ex:
                attempts.append({'stage': tag, 'exception': str(ex)})
                logger.warning(f"[api_info] 阶段 {tag} 发生异常: {ex}")
                return None

        info = None
        # 快速模式：减少阶段数和超时时间
        fast_mode = os.environ.get('UMD_FAST_INFO','').lower() in ('1','true','yes')
        max_stages = int(os.environ.get('INFO_MAX_STAGES', '2' if fast_mode else '5'))
        
        # 智能早期退出：检测到这些错误立即停止后续阶段
        def should_stop_early(stderr_msg: str) -> bool:
            """检测是否应该立即停止后续阶段"""
            if not stderr_msg:
                return False
            lower_msg = stderr_msg.lower()
            # 年龄限制/需要登录 - 不会通过重试解决
            if 'sign in to confirm' in lower_msg or 'confirm your age' in lower_msg:
                return True
            # 私有视频/会员专属 - 不会通过重试解决
            if 'private' in lower_msg or 'members-only' in lower_msg:
                return True
            # 视频不存在/已删除 - 不会通过重试解决
            if 'video unavailable' in lower_msg or 'has been removed' in lower_msg:
                return True
            # 不支持的网站 - 不会通过重试解决
            if 'unsupported url' in lower_msg:
                return True
            return False
        
        # Stage 1: Primary (Twitter 用 50, YouTube 单视频优先 --no-playlist)
        if is_twitter:
            primary_timeout = getattr(config, 'INFO_STAGE_TIMEOUT_PRIMARY_TWITTER', 55)
            hardened_timeout = getattr(config, 'INFO_STAGE_TIMEOUT_HARDENED_TWITTER', 65)
            extended_timeout = getattr(config, 'INFO_STAGE_TIMEOUT_EXTENDED_TWITTER', 80)
            v6_timeout = getattr(config, 'INFO_STAGE_TIMEOUT_V6_TWITTER', 85)
        else:
            primary_timeout = 50
            hardened_timeout = 60
            extended_timeout = 70
            v6_timeout = 75
        
        # 快速模式：减少超时时间
        if fast_mode:
            primary_timeout = min(primary_timeout, 20)
            hardened_timeout = min(hardened_timeout, 25)
            extended_timeout = min(extended_timeout, 30)
            v6_timeout = min(v6_timeout, 30)
        # Jitter: Twitter primary 前随机退避几百毫秒, 减少并发同时命中
        if is_twitter:
            import random as _rnd, time as _time
            jmin = getattr(config, 'INFO_TWITTER_JITTER_MS_MIN', 200)
            jmax = getattr(config, 'INFO_TWITTER_JITTER_MS_MAX', 900)
            if jmax > jmin and jmin >= 0:
                jitter_ms = _rnd.randint(jmin, jmax)
                _time.sleep(jitter_ms/1000.0)
                logger.info(f"[api_info] twitter primary jitter {jitter_ms}ms")
        inflight.stage = 'primary'
        info = run_once('primary', build_cmd(primary=True, force_no_playlist=True if is_youtube else False), primary_timeout)
        
        # 智能早期退出检查
        stage_count = 1
        if not info and attempts and should_stop_early(attempts[-1].get('stderr_head', '')):
            logger.info(f"[api_info] 检测到无法通过重试解决的错误，跳过后续阶段")
        # Stage 2: 若失败且是 YouTube 且 URL 可能是 playlist / 或未知原因，去掉 --no-playlist 再试
        elif not info and is_youtube and stage_count < max_stages:
            stage_count += 1
            inflight.stage = 'youtube_no_restrict'
            info = run_once('youtube_no_restrict', build_cmd(primary=False, force_no_playlist=False), min(55, primary_timeout + 5))
            if not info and attempts and should_stop_early(attempts[-1].get('stderr_head', '')):
                logger.info(f"[api_info] 检测到无法通过重试解决的错误，跳过后续阶段")
        # Stage 3: 加强参数 (ignore-errors / fragment retry)
        if not info and stage_count < max_stages and not (attempts and should_stop_early(attempts[-1].get('stderr_head', ''))):
            stage_count += 1
            # 优先尝试 IPv4 hardened (对部分线路更稳定)
            inflight.stage = 'hardened'
            info = run_once('hardened', build_cmd(primary=False, force_no_playlist=True if is_youtube else False, hardened=True, ip_family='v4'), hardened_timeout, ip_family='v4')
        # Stage 3b: Twitter/X extended (更长超时 + 额外 header)
        if not info and is_twitter and stage_count < max_stages and not (attempts and should_stop_early(attempts[-1].get('stderr_head', ''))):
            stage_count += 1
            inflight.stage = 'extended'
            info = run_once('extended', build_cmd(primary=False, force_no_playlist=False, hardened=True, extended=True, ip_family='v4'), extended_timeout, ip_family='v4')
        # Stage 3c: YouTube extended (模拟浏览器行为)
        if not info and is_youtube and stage_count < max_stages and not (attempts and should_stop_early(attempts[-1].get('stderr_head', ''))):
            stage_count += 1
            inflight.stage = 'youtube_extended'
            info = run_once('youtube_extended', build_cmd(primary=False, force_no_playlist=False, hardened=True, extended=True, ip_family='v4'), extended_timeout, ip_family='v4')
        # Stage 3d: Twitter/X IPv6 兜底 (某些运营商对 v4 出口被限 / 质量差)
        if not info and is_twitter and stage_count < max_stages and not (attempts and should_stop_early(attempts[-1].get('stderr_head', ''))):
            stage_count += 1
            inflight.stage = 'twitter_v6'
            info = run_once('twitter_v6', build_cmd(primary=False, force_no_playlist=False, hardened=True, extended=True, ip_family='v6'), v6_timeout, ip_family='v6')
        # Stage 3e: YouTube IPv6 兜底
        if not info and is_youtube and stage_count < max_stages and not (attempts and should_stop_early(attempts[-1].get('stderr_head', ''))):
            stage_count += 1
            inflight.stage = 'youtube_v6'
            info = run_once('youtube_v6', build_cmd(primary=False, force_no_playlist=False, hardened=True, extended=True, ip_family='v6'), v6_timeout, ip_family='v6')
        
        # 记录实际使用的阶段数
        if info:
            logger.info(f"[api_info] 成功获取信息，使用了 {stage_count} 个阶段")
        # 移除 legacy_helper 退回阶段以减少一次额外进程调用 (加快失败短路)
        if not info:
            # 所有阶段都失败
            # 解析出最有代表性的错误
            err_snippet = ''
            for a in attempts:
                if a.get('stderr_head'):
                    err_snippet = a['stderr_head']
                    break
            code, friendly = _classify_with_code(err_snippet or '获取信息失败')
            site_type = 'adult' if is_adult_site else 'twitter' if is_twitter else ('youtube' if is_youtube else 'general')
            # 识别 Unsupported URL 专用友好提示
            low_err = (err_snippet or '').lower()
            if 'unsupported url' in low_err:
                code = 'unsupported_url'
                # 为用户提供更明确提示（不进入长冷却，避免误伤用户反复尝试）
                friendly = '该站点暂不支持或未被 yt-dlp 解析 (Unsupported URL)'
                # 对不支持的站点缩短冷却 (例如 30s) 避免长时间阻塞
                short_cd = 30
                video_info_cache.set(neg_cache_key, {
                    'last_err': friendly,
                    'ts': time.time(),
                    'count': (neg_rec.get('count',0)+1) if neg_rec else 1,
                    'short_cd': True,
                    'custom_cooldown': short_cd
                })
                err_resp = {
                    'error': friendly,
                    'error_code': code,
                    'attempts': attempts,
                    'site_type': site_type,
                    'hint': '请确认 URL 所属站点是否被 yt-dlp 支持，或等待后续版本扩展。',
                    'unsupported': True
                }
                inflight.error = {**err_resp, '_status': 400}
                _publish_and_cleanup_inflight(url, inflight)
                return jsonify(err_resp), 400
            # 写入负面缓存
            video_info_cache.set(neg_cache_key, {
                'last_err': friendly,
                'ts': time.time(),
                'count': (neg_rec.get('count',0)+1) if neg_rec else 1
            })
            err_resp = {
                'error': friendly,
                'error_code': code or 'unknown',
                'attempts': attempts,
                'site_type': site_type
            }
            inflight.error = {**err_resp, '_status': 502}
            _publish_and_cleanup_inflight(url, inflight)
            return jsonify(err_resp), 502
        # 缓存成功结果
        video_info_cache.set(cache_key, info)
        # 成功清理负面缓存
        if neg_rec:
            # 覆盖为一个轻量标记以清空失败影响 (若缓存无删除能力)
            try:
                video_info_cache.set(neg_cache_key, {'cleared': True, 'ts': time.time(), 'count': 0})
            except Exception:
                pass
        if attempts:
            logger.info(f"[api_info] 探测成功 (stages={len(attempts)}) 缓存写入")

    formats = info.get('formats') or []
    structured = []
    max_effective_height = None
    # 预处理: 收集纯视频轨 & 纯音频轨, 便于后续 quality_pairs 计算
    video_tracks: list[dict[str,Any]] = []
    audio_tracks: list[dict[str,Any]] = []
    for f in formats:
        raw_height = f.get('height')
        note = f.get('format_note') or ''
        # 从 format_note 中提取类似 2160p / 4320p 的标记
        note_height = None
        import re as _re
        # 确保 note 是字符串类型
        note_str = str(note) if note is not None else ''
        m = _re.search(r'(\d{3,4})p', note_str)
        if m:
            try:
                note_height = int(m.group(1))
            except Exception:
                note_height = None
        effective_height = raw_height
        # 如果 note 中的高度存在且比 raw_height 大，则采用 note_height
        if note_height and (not raw_height or note_height > raw_height):
            effective_height = note_height
        if effective_height:
            if not max_effective_height or effective_height > max_effective_height:
                max_effective_height = effective_height
        entry = {
            'format_id': f.get('format_id'),
            'ext': f.get('ext'),
            'vcodec': f.get('vcodec'),
            'acodec': f.get('acodec'),
            'height': raw_height,
            'effective_height': effective_height,
            'width': f.get('width'),
            'fps': f.get('fps'),
            'filesize': f.get('filesize') or f.get('filesize_approx'),
            'quality': f.get('quality'),
            'format_note': note,
            'tbr': f.get('tbr'),
        }
        structured.append(entry)
        vc = (f.get('vcodec') or '').lower()
        ac = (f.get('acodec') or '').lower()
        if vc and vc != 'none' and (not ac or ac == 'none') and effective_height:
            video_tracks.append({**entry, 'effective_height': effective_height})
        if ac and ac != 'none' and (not vc or vc == 'none'):
            audio_tracks.append(entry)

    # 生成 quality_pairs: {height: {video: format_id, audio: format_id}}
    quality_pairs: dict[int, dict[str,str]] = {}
    if video_tracks and audio_tracks:
        # 音频优选规则: 先按 abr(或 tbr) 逆序; 再偏好 m4a/mp4 容器; 再偏好 aac/opus
        def audio_rank(a: dict[str,Any]):
            abr = a.get('abr') or a.get('tbr') or 0
            ext = (a.get('ext') or '').lower()
            acodec = (a.get('acodec') or '').lower()
            # m4a/mp4 优先, 其次 webm/opus
            ext_score = 2 if ext in ('m4a','mp4') else (1 if ext in ('webm','ogg') else 0)
            codec_score = 2 if ('aac' in acodec or 'mp4a' in acodec) else (1 if ('opus' in acodec) else 0)
            return (abr, ext_score, codec_score)
        # 预先选出一个最佳音频供所有高度复用 (大多数情况)
        best_audio = sorted(audio_tracks, key=audio_rank, reverse=True)[0]
        # 视频优选规则: 每个高度选一个: 优先 avc(h264)/mp4 -> vp9/webm -> av01；若 fps 更高优先，其次码率(tbr)
        def video_rank(v: dict[str,Any]):
            vcodec = (v.get('vcodec') or '').lower()
            ext = (v.get('ext') or '').lower()
            tbr = v.get('tbr') or 0
            fps = v.get('fps') or 0
            # 编码打分: h264 > vp9 > av1 > 其他
            if 'avc' in vcodec or 'h264' in vcodec:
                codec_score = 3
            elif 'vp9' in vcodec:
                codec_score = 2
            elif 'av01' in vcodec or 'av1' in vcodec:
                codec_score = 1
            else:
                codec_score = 0
            # 容器打分 mp4>webm>其他
            if ext == 'mp4':
                ext_score = 2
            elif ext == 'webm':
                ext_score = 1
            else:
                ext_score = 0
            return (v.get('effective_height') or 0, codec_score, fps, tbr, ext_score)
        # 按高度分组
        by_height: dict[int, list[dict[str,Any]]] = {}
        for vt in video_tracks:
            h = vt.get('effective_height') or 0
            if not h:
                continue
            by_height.setdefault(h, []).append(vt)
        for h, items in by_height.items():
            # 选最佳视频
            best_video = sorted(items, key=video_rank, reverse=True)[0]
            quality_pairs[h] = {
                'video': str(best_video.get('format_id')),
                'audio': str(best_audio.get('format_id'))
            }
        # 额外: default_best 标记最高高度的配对
        if quality_pairs:
            top_h = max(quality_pairs.keys())
            quality_pairs['default_best'] = quality_pairs.get(top_h, {})  # type: ignore[index]

    # 能力标记
    has_8k = any((item.get('effective_height') or 0) >= 4320 for item in structured)
    has_4k = any(2160 <= (item.get('effective_height') or 0) < 4320 for item in structured)
    has_hdr = any('hdr' in (item.get('format_note') or '').lower() for item in structured)
    has_av1 = any('av01' in (item.get('vcodec') or '').lower() for item in structured)

    subtitles = []
    subs = info.get('subtitles') or {}
    for lang, entries in subs.items():
        subtitles.append({'lang': lang, 'count': len(entries)})
    auto_subtitles = []
    autos = info.get('automatic_captions') or {}
    for lang, entries in autos.items():
        auto_subtitles.append({'lang': lang, 'count': len(entries)})

    payload = {
        'video_id': info.get('id'),
        'title': info.get('title'),
        'uploader': info.get('uploader'),
        'duration': info.get('duration'),
        'thumbnail': info.get('thumbnail'),
        'formats': structured,
        'max_height': max_effective_height,
        'subtitles': subtitles,
        'auto_subtitles': auto_subtitles,
        'capabilities': {
            '8k': has_8k,
            '4k': has_4k,
            'hdr': has_hdr,
            'av1': has_av1
        },
        # 注意: quality_pairs 原始键包含 int (高度) 与 'default_best' 字符串混合，
        # Flask JSONProvider 在 dumps 时默认 sort_keys=True 会触发 Python 对键排序，
        # 造成 int 与 str 不可比较 -> TypeError: '<' not supported between instances of 'str' and 'int'
        # 因此这里统一转换为字符串键。
        'quality_pairs': {str(k): v for k, v in quality_pairs.items()} if quality_pairs else {},
        'geo_bypass': geo_bypass
    }
    # 如果是缓存命中可附加标记
    if cached:
        payload['cached'] = True
    # 将完整 payload 发布给等待者 (不含 HTTP status)
    if inflight and inflight.result is None:
        try:
            inflight.result = dict(payload)
        except Exception:
            inflight.result = {'ok': True}
        _publish_and_cleanup_inflight(url, inflight)
    return jsonify(payload)
    return jsonify(payload)

@app.route('/diag/proxy')
def diag_proxy():
    """诊断当前代理可用性与最近的 twitter 预探测。
    返回: proxy_url, head 测试结果 (x.com / youtube), 最近预探测快照。
    """
    proxy_url = getattr(config, 'PROXY_URL', '') or os.environ.get('UMD_PROXY','')
    report: dict[str, Any] = {
        'proxy_url': proxy_url or None,
        'tests': [],
        'last_twitter_preflight': LAST_TWITTER_PREFLIGHT
    }
    if not proxy_url:
        report['message'] = '未配置代理 (设置 UMD_PROXY 环境变量即可)'
        return jsonify(report)
    try:
        import requests  # type: ignore
        test_targets = [
            ('x.com', 'https://x.com/robots.txt'),
            ('youtube', 'https://www.youtube.com/robots.txt')
        ]
        for name, tgt in test_targets:
            t0 = time.time()
            rec: dict[str, Any] = {'target': name, 'url': tgt}
            try:
                r = requests.head(tgt, timeout=8, proxies={'http': proxy_url, 'https': proxy_url}, allow_redirects=True)
                rec['status_code'] = r.status_code
                rec['elapsed_ms'] = int((time.time()-t0)*1000)
                rec['ok'] = r.status_code in (200,301,302,400,401,403,404)
            except Exception as e:
                rec['error'] = str(e)[:160]
            report['tests'].append(rec)
    except Exception as e:
        report['import_error'] = str(e)
    return jsonify(report)

# ---------------- 任务创建 & 查询 API (第一阶段最小版) ----------------
@app.route('/api/tasks', methods=['POST'])
def api_create_task():
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    data = _safe_get_json(request)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': '缺少 url', 'error_code': 'invalid_input'}), 400
    video_format = data.get('video_format')
    audio_format = data.get('audio_format')
    subtitles = data.get('subtitles') or []
    auto_subtitles = bool(data.get('auto_subtitles'))
    prefer_container = data.get('prefer_container') or 'mp4'
    filename_template = data.get('filename_template') or '%(title)s'
    retry = int(data.get('retry') or 3)
    geo_bypass = True if (data.get('geo_bypass') is None) else bool(data.get('geo_bypass'))
    # 新增：模式/质量/仅字幕
    mode = data.get('mode') or 'merged'
    quality = data.get('quality') or 'best'
    subtitles_only = bool(data.get('subtitles_only'))

    # DEBUG: 记录接收到的参数
    logger.info(f"[API_TASK] 创建任务 - URL: {url[:100]}..., Mode: {mode}, Quality: '{quality}', Subtitles_only: {subtitles_only}, Data keys: {list(data.keys())}")
    
    skip_probe = bool(data.get('skip_probe'))
    info_cache = data.get('info_cache') if isinstance(data.get('info_cache'), dict) else None
    # 新增：封面图下载
    write_thumbnail = bool(data.get('write_thumbnail'))
    
    task = tm.add_task(url=url, video_format=video_format, audio_format=audio_format,
                       subtitles=subtitles, auto_subtitles=auto_subtitles,
                       prefer_container=prefer_container, filename_template=filename_template,
                       retry=retry, geo_bypass=geo_bypass,
                       mode=mode, quality=quality, subtitles_only=subtitles_only,
                       skip_probe=skip_probe, info_cache=info_cache, write_thumbnail=write_thumbnail)
    return jsonify({'task_id': task.id, 'status': task.status})

@app.route('/api/tasks/<task_id>', methods=['GET'])
def api_get_task(task_id):
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    t = tm.get_task(task_id)
    if not t:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify(t.to_dict())

@app.route('/api/tasks', methods=['GET'])
def api_list_tasks():
    tm = _get_task_manager()
    if not tm:
        app.logger.warning('task_manager 未初始化，/api/tasks 返回空列表')
        return jsonify([])
    try:
        return jsonify(tm.list_tasks())
    except Exception as e:
        app.logger.error(f'/api/tasks 列表失败: {e}')
        return jsonify([])

@app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
def api_cancel_task(task_id):
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    # 使用 tasks_mod 的取消函数以确保引用的是模块内当前实例
    if tasks_mod and getattr(tasks_mod, 'cancel_task', None):
        if tasks_mod.cancel_task(task_id):
            return jsonify({'task_id': task_id, 'status': 'canceled'})
    return jsonify({'error': '无法取消任务（可能不存在或已结束）'}), 400

@app.route('/api/tasks/<task_id>/log')
def api_task_log(task_id):
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    t = tm.get_task(task_id)
    if not t:
        return jsonify({'error': '任务不存在'}), 404
    offset = int(request.args.get('offset', 0))
    log_slice = t.log[offset:]
    return jsonify({'task_id': task_id, 'offset': offset, 'next_offset': offset + len(log_slice), 'lines': log_slice})

@app.route('/api/tasks/<task_id>/full_log')
def api_task_full_log(task_id):
    """调试用：返回任务完整日志（不截断）。发布版本可以考虑移除或增加鉴权。"""
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    t = tm.get_task(task_id)
    if not t:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify({'task_id': task_id, 'lines': t.log, 'status': t.status, 'stage': t.stage})

@app.route('/api/tasks/cleanup', methods=['POST'])
def api_tasks_cleanup():
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    payload = _safe_get_json(request)
    max_keep = int(payload.get('max_keep', 200))
    remove_active = bool(payload.get('remove_active', False))
    if max_keep <= 0:
        # 兼容前端老版本：当 max_keep=0 时，视为请求清空所有（包括活跃任务）
        remove_active = True
    removed = 0
    removed_active = 0
    with tm.tasks_lock:
        # 1) 终态清理
        finished_ids = [tid for tid, tk in tm.tasks.items() if tk.status in ('finished','error','canceled')]
        if max_keep <= 0:
            # 清空所有终态
            for rid in finished_ids:
                tm.tasks.pop(rid, None)
                removed += 1
        elif len(finished_ids) > max_keep:
            # 按创建时间排序，保留最新 max_keep 条
            finished_sorted = sorted(finished_ids, key=lambda i: tm.tasks[i].created_at)
            to_remove = finished_sorted[0:len(finished_ids)-max_keep]
            for rid in to_remove:
                tm.tasks.pop(rid, None)
                removed += 1
        # 2) 可选: 移除活动任务（前端用户明确请求时）
        if remove_active:
            active_ids = [tid for tid, tk in tm.tasks.items() if tk.status in ('queued','downloading','merging')]
            for aid in active_ids:
                try:
                    # 尝试通过模块级取消，确保子进程被杀死
                    if tasks_mod and getattr(tasks_mod, 'cancel_task', None):
                        tasks_mod.cancel_task(aid)
                except Exception:
                    pass
                tm.tasks.pop(aid, None)
                removed_active += 1
    return jsonify({'removed': removed, 'removed_active': removed_active, 'max_keep': max_keep, 'remove_active': remove_active})


# ---- 文件/目录辅助操作 API ----
@app.route('/api/open_download_dir', methods=['POST'])
def api_open_download_dir():
    """在操作系统文件管理器中打开下载目录 (Windows: Explorer)。"""
    try:
        dl_dir = config.DOWNLOAD_DIR
        if sys.platform.startswith('win'):
            subprocess.Popen(['explorer', dl_dir])  # nosec - 本地受信环境
        elif sys.platform.startswith('darwin'):
            subprocess.Popen(['open', dl_dir])
        else:
            subprocess.Popen(['xdg-open', dl_dir])
        return jsonify({'success': True, 'path': dl_dir})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/reveal_file', methods=['POST'])
def api_reveal_file():
    """在资源管理器中选中指定文件。传入 JSON: {"name":"文件名或相对路径"}
    为安全起见仅允许位于 DOWNLOAD_DIR 内部。"""
    data = _safe_get_json(request)
    name = data.get('name')
    if not name:
        return jsonify({'error': '缺少 name'}), 400
    dl_dir = os.path.abspath(config.DOWNLOAD_DIR)
    target = os.path.abspath(os.path.join(dl_dir, name))
    if not target.startswith(dl_dir):
        return jsonify({'error': '非法路径'}), 400
    if not os.path.exists(target):
        return jsonify({'error': '文件不存在'}), 404
    try:
        if sys.platform.startswith('win'):
            subprocess.Popen(['explorer', '/select,', target])  # 注意逗号后跟路径 (Windows Explorer 语法)
        elif sys.platform.startswith('darwin'):
            subprocess.Popen(['open', '-R', target])
        else:
            # Linux 下没有统一“选中文件”语义，退化为打开目录
            subprocess.Popen(['xdg-open', os.path.dirname(target)])
        return jsonify({'success': True, 'file': target})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/last_finished_file')
def api_last_finished_file():
    """返回最近一个完成状态任务的文件路径。"""
    tm = _get_task_manager()
    if not tm:
        return jsonify({'error': '任务系统未初始化'}), 500
    latest = None
    with tm.tasks_lock:
        for t in tm.tasks.values():
            if t.status == 'finished' and t.file_path and os.path.exists(t.file_path):
                if latest is None or t.updated_at > latest.updated_at:  # type: ignore[attr-defined]
                    latest = t
    if not latest:
        return jsonify({'found': False})
    return jsonify({'found': True, 'file': latest.file_path, 'task_id': latest.id, 'title': latest.title})



def open_browser():
    try:
        port = int(os.environ.get('UMD_PORT', getattr(config, 'SERVER_PORT', 33210)))
    except Exception:
        port = 33210
    # 支持通过环境变量禁止自动打开浏览器 (批处理/无人值守场景)
    if os.environ.get('UMD_NO_BROWSER','').lower() in ('1','true','yes','on'):  # type: ignore[arg-type]
        logger.info('[BOOT] 检测到 UMD_NO_BROWSER=1, 跳过自动打开浏览器')
        return
    webbrowser.open_new(f"http://127.0.0.1:{port}")

if __name__ == '__main__':
    logger.info("🚀 正在初始化Universal Media Downloader...")
    get_ffmpeg_path()
    # 初始化新任务管理器
    try:
        if tasks_mod and getattr(tasks_mod, 'init_task_manager', None):
            tasks_mod.init_task_manager(config.YTDLP_PATH, get_ffmpeg_path, config.DOWNLOAD_DIR, config.COOKIES_FILE)
            logger.info("任务管理器已初始化")
        else:
            logger.error("tasks_mod.init_task_manager 不可用")
    except Exception as tm_err:
        logger.error(f"任务管理器初始化失败: {tm_err}")

    if not os.path.exists(config.COOKIES_FILE):
        logger.warning("="*50)
        logger.warning("未找到 cookies.txt 文件！请注意需要登录的网站可能下载失败。")
        logger.warning("="*50)
    
    # 从配置模块读取端口
    port = int(os.environ.get('UMD_PORT', config.SERVER_PORT))
    logger.info(f"服务器即将启动在 http://127.0.0.1:{port} (UI_VERSION={UI_VERSION})")
    # 如果代理端口与服务器端口冲突，给出提示
    try:
        proxy_url = getattr(config, 'PROXY_URL', '')
        if proxy_url:
            import re
            m = re.match(r'^[a-zA-Z0-9+]+://[^:]+:(\d+)$', proxy_url.strip())
            if m and m.group(1) == str(port):
                logger.warning(f"[WARN] 代理端口({m.group(1)}) 与服务器监听端口相同，容易混淆：请确认代理软件是否真的监听该端口，且不要把本地服务端口当成代理端口。")
    except Exception:
        pass
    Timer(1, open_browser).start()
    
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['JSON_AS_ASCII'] = False
    
    @app.after_request
    def after_request(response):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    
    logger.info("🎬 Universal Media Downloader启动成功！")
    # 启动时打印所有路由，帮助诊断 404
    try:
        for rule in app.url_map.iter_rules():
            if rule.endpoint != 'static':
                logger.info(f"[ROUTE] {rule.methods} {rule}")
    except Exception as _e:
        logger.warning(f"无法列出路由: {_e}")

    @app.route('/diag/task_manager')
    def diag_task_manager():
        tm = _get_task_manager()
        if not tm:
            return jsonify({'initialized': False, 'reason': 'task_manager is None'}), 200
        try:
            with tm.tasks_lock:
                stats = {
                    'initialized': True,
                    'tasks_total': len(tm.tasks),
                    'queued': len([t for t in tm.tasks.values() if t.status == 'queued']),
                    'downloading': len([t for t in tm.tasks.values() if t.status == 'downloading']),
                    'merging': len([t for t in tm.tasks.values() if t.status == 'merging']),
                    'finished': len([t for t in tm.tasks.values() if t.status == 'finished']),
                    'error': len([t for t in tm.tasks.values() if t.status == 'error']),
                    'canceled': len([t for t in tm.tasks.values() if t.status == 'canceled']),
                    'worker_threads': [th.name for th in getattr(tm, 'workers', []) if th.is_alive()],
                    'aria2c_path': getattr(tm, 'aria2c_path', None),
                }
            return jsonify(stats), 200
        except Exception as de:
            return jsonify({'initialized': True, 'error': str(de)}), 200
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)

    # 诊断：TaskManager 状态 (放在 run 之后不会被执行，需放在文件尾部之前；因此复制到 whoami 上方)

    # NOTE: 上面的 app.run 会阻塞，因此 /diag/task_manager 路由应在其之前定义。如果打包运行通过其他入口 (如 flask run) 则也会生效。


# 轻量级运行时自检（放在文件末尾添加，不影响流程）
@app.route('/whoami')
def whoami():
    return jsonify({
        'ui_version': UI_VERSION,
        'pid': os.getpid(),
        'cwd': os.getcwd(),
        'template_searchpath': getattr(app.jinja_loader, 'searchpath', None),
        'routes': [r.rule for r in app.url_map.iter_rules() if r.endpoint != 'static'][:40]
    })

import sys, os; print('PYPATH_DEBUG', sys.path[:5])

