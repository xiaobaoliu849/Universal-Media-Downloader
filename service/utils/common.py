import logging
import time
import traceback
from functools import wraps
from urllib.parse import urlparse
from typing import Any, Callable, Optional, Dict

logger = logging.getLogger(__name__)

def _safe_get_json(req) -> Dict[str, Any]:
    """某些 Pylance 版本下 flask.Request 缺少 get_json/ json 属性的类型提示，添加轻量安全封装"""
    try:
        gj = getattr(req, 'get_json', None)
        if callable(gj):  # 优先使用 get_json
            data = gj(silent=True)
            if isinstance(data, dict):
                return data
            return {}
        # 退回直接属性 json
        raw = getattr(req, 'json', None)
        if isinstance(raw, dict):
            return raw
        return {}
    except Exception:
        return {}

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
