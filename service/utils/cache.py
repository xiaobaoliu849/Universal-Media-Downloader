import time
import threading
from collections import OrderedDict
from typing import Any, Optional, Dict
from threading import Timer

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

# ---------------- In-flight 请求合并 (防止同一 URL 被频繁重复探测) ----------------
class _InfoInflight:
    __slots__ = ('event','result','error','start','waiters','stage')
    def __init__(self):
        self.event: threading.Event = threading.Event()
        self.result: Optional[dict[str,Any]] = None
        self.error: Optional[dict[str,Any]] = None
        self.start: float = time.time()
        self.waiters: int = 0
        self.stage: str = 'initial'

_INFO_INFLIGHT: Dict[str, _InfoInflight] = {}
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
