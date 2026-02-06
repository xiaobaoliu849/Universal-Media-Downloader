"""
TaskManager: 任务队列管理器
负责任务的队列管理、工作线程调度，将具体下载逻辑委托给 downloader 模块
"""
import threading
import queue
import time
import uuid
import os
import logging
import traceback
from typing import Dict, List, Any, Optional, Callable

from .models import Task
from ..utils.errors import classify_error

logger = logging.getLogger(__name__)


class TaskManager:
    """任务管理器：管理下载任务队列和工作线程"""

    def __init__(self, ytdlp_path: str, ffmpeg_locator: Callable, download_dir: str, cookies_file: str):
        self.ytdlp_path = ytdlp_path
        self.ffmpeg_locator = ffmpeg_locator
        self.download_dir = download_dir
        self.cookies_file = cookies_file

        self.tasks: Dict[str, Task] = {}
        self.tasks_lock = threading.Lock()
        self.queue: queue.Queue = queue.Queue()
        self.max_workers = 2
        self.workers: List[threading.Thread] = []
        self.procs: Dict[str, Any] = {}  # task_id -> subprocess.Popen
        self._stop = False

        # 延迟导入下载器和依赖检测
        from ..utils.dependencies import detect_aria2c
        self.aria2c_path: Optional[str] = detect_aria2c()

        self._start_workers()

    def _start_workers(self):
        """启动工作线程"""
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, name=f'dl-worker-{i}', daemon=True)
            t.start()
            self.workers.append(t)
        logger.info(f"TaskManager: 启动 {self.max_workers} 个下载线程")

    def _worker_loop(self):
        """工作线程主循环"""
        # 延迟导入下载执行器
        from .downloader import execute_download

        while not self._stop:
            try:
                task_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            task = self.get_task(task_id)
            if not task:
                self.queue.task_done()
                continue

            if task.status == 'canceled' or task.canceled:
                self.queue.task_done()
                continue

            try:
                execute_download(self, task)
            except Exception as e:
                code, msg = classify_error(str(e))
                self._update_task(task, status='error', error_code=code, error_message=msg)
                logger.error(f"Task {task.id} 失败: {msg}\n{traceback.format_exc()}")
            finally:
                self.queue.task_done()

    def add_task(self, **kwargs) -> Task:
        """添加新任务到队列"""
        task_id = str(uuid.uuid4())
        task = Task(id=task_id, **kwargs)

        mode = kwargs.get('mode', 'merged')
        quality = kwargs.get('quality', 'best')
        subtitles_only = kwargs.get('subtitles_only', False)
        logger.info(f"[TASK_ADD] 任务 {task_id} 创建 - Mode: {mode}, Quality: '{quality}', Subtitles_only: {subtitles_only}")

        with self.tasks_lock:
            self.tasks[task_id] = task
        self.queue.put(task_id)
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取指定任务"""
        with self.tasks_lock:
            return self.tasks.get(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有任务"""
        with self.tasks_lock:
            return [t.to_dict() for t in self.tasks.values()]

    def cleanup_finished_tasks(self) -> int:
        """清理已完成/错误/取消的任务，返回清理数量"""
        removed_count = 0
        with self.tasks_lock:
            finished_task_ids = [
                task_id for task_id, task in self.tasks.items()
                if task.status in ['finished', 'error', 'canceled']
            ]
            for task_id in finished_task_ids:
                del self.tasks[task_id]
                removed_count += 1
        logger.info(f"清除了 {removed_count} 个已完成/错误的任务")
        return removed_count

    def _update_task(self, task: Task, **fields):
        """更新任务字段"""
        with self.tasks_lock:
            for k, v in fields.items():
                setattr(task, k, v)
            task.updated_at = time.time()

    def stop(self):
        """停止所有工作线程"""
        self._stop = True
        for w in self.workers:
            w.join(timeout=2)


# 模块级单例
_task_manager: Optional[TaskManager] = None


def init_task_manager(ytdlp_path: str, ffmpeg_locator: Callable, download_dir: str, cookies_file: str) -> TaskManager:
    """初始化全局 TaskManager 单例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager(ytdlp_path, ffmpeg_locator, download_dir, cookies_file)
    return _task_manager


def get_task_manager() -> Optional[TaskManager]:
    """获取全局 TaskManager 单例"""
    return _task_manager


def cancel_task(task_id: str) -> bool:
    """取消指定任务"""
    if not _task_manager:
        return False

    t = _task_manager.get_task(task_id)
    if not t:
        return False

    # 终止正在运行的进程
    try:
        p = _task_manager.procs.get(task_id)
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass
    except Exception:
        pass

    # 标记取消
    if t.status not in ('finished', 'error', 'canceled'):
        t.canceled = True
        t.status = 'canceled'
        t.stage = None
        t.log.append('[canceled] 标记取消')

    # 清理进程表
    try:
        _task_manager.procs.pop(task_id, None)
    except Exception:
        pass

    return True


__all__ = ['TaskManager', 'init_task_manager', 'get_task_manager', 'cancel_task']
