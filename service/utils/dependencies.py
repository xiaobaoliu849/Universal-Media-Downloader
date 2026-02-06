import os
import sys
import logging
import subprocess
import shutil
try:
    import config
except ImportError:
    # 尝试添加根目录到 sys.path
    sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    import config

logger = logging.getLogger(__name__)

# 定义一个全局的、只在Windows上生效的创建标志，用于隐藏子进程窗口
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0

_ffmpeg_path_cache = None

def get_ffmpeg_path():
    """返回 ffmpeg 可执行文件路径。"""
    global _ffmpeg_path_cache
    if _ffmpeg_path_cache not in (None, False):
        return _ffmpeg_path_cache

    candidates = []
    # 1) 配置中解析的打包路径
    candidates.append(config.FFMPEG_BUNDLED_PATH)
    # 2) 与可执行文件同级目录下的 ffmpeg/bin/ffmpeg.exe (处理 resource_path 失效或目录被复制走的情况)
    try:
        exe_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(sys.modules['__main__'].__file__))
        candidates.append(os.path.join(exe_dir, 'ffmpeg', 'bin', 'ffmpeg.exe'))
        candidates.append(os.path.join(exe_dir, 'ffmpeg', 'ffmpeg.exe'))
    except Exception:
        pass
    # 3) 尝试 _MEIPASS 路径 (one-file 解包)
    if hasattr(sys, '_MEIPASS'):
        mp = getattr(sys, '_MEIPASS')
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

def detect_aria2c() -> str | None:
    """自动检测 aria2c 可执行文件路径"""
    # 允许通过环境变量显式禁用，避免在某些环境弹出额外窗口
    if os.environ.get('LUMINA_DISABLE_ARIA2C','').lower() in ('1','true','yes'):
        return None
    # 优先使用环境变量指定路径
    p = os.environ.get('ARIA2C_PATH')
    if p and os.path.exists(p):
        return p
    # 尝试常见的打包路径
    try:
        # 假设在项目根目录下有 aria2 文件夹
        basedir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        bundled = os.path.join(basedir, 'aria2', 'aria2-1.36.0-win-64bit-build1', 'aria2c.exe')
        if os.path.exists(bundled):
            return bundled
            
        # 针对打包后的情况
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            bundled = os.path.join(exe_dir, 'aria2', 'aria2-1.36.0-win-64bit-build1', 'aria2c.exe')
            if os.path.exists(bundled):
                return bundled
    except Exception:
        pass
        
    # 尝试 PATH 中的可执行文件
    w = shutil.which('aria2c') or shutil.which('aria2c.exe')
    if w:
        return w
    return None

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
