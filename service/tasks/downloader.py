import os
import re
import json
import sys
import time
import logging
import subprocess
import traceback
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse

from .models import Task
from ..utils.errors import classify_error
from ..utils.subtitles import normalize_srt_inplace
from ..utils.dependencies import CREATE_NO_WINDOW
import site_configs

logger = logging.getLogger(__name__)

# --------- Constants (could be in config) ---------
PROBE_TIMEOUT_DEFAULT = 40
PROBE_TIMEOUT_TWITTER = 55
PROBE_TIMEOUT_MISSAV = 180

def execute_download(manager: Any, task: Task):
    """Core download logic extracted from tasks.py with full parity"""
    task.attempts += 1
    info = None

    # Decision: skip probe?
    if task.skip_probe and task.info_cache and isinstance(task.info_cache, dict):
        title = task.info_cache.get('title') or 'video'
        manager._update_task(task, status='downloading', stage='fast_start', title=title)
        task.log.append('[fast-path] skip_probe=1，使用前端缓存信息')
        info = {'title': title}
    else:
        manager._update_task(task, status='downloading', stage='fetch_info')
        try:
            info = _probe_info(manager, task)
        except Exception as e:
            code, msg = classify_error(str(e))
            manager._update_task(task, status='error', error_code=code, error_message=msg)
            raise e

    title = (info.get('title') if isinstance(info, dict) else None) or 'video'
    safe_title = _safe_filename(title)
    base_template = task.filename_template.replace('%(title)s', safe_title)
    manager._update_task(task, title=title)

    # Subtitles only
    if getattr(task, 'subtitles_only', False):
        _execute_subtitle_download(manager, task, base_template)
        return

    # Thumbnail only
    if getattr(task, 'mode', '') == 'thumbnail_only':
        _execute_thumbnail_download(manager, task, base_template)
        return

    # Media download
    _execute_media_download(manager, task, base_template)

def _probe_info(manager: Any, task: Task) -> Dict[str, Any]:
    cmd = [manager.ytdlp_path, '--skip-download', '--dump-single-json', '--no-warnings', '--no-check-certificate']

    # Proxy logic
    try:
        import config
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
    except ImportError:
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')

    if proxy_url:
        cmd += ['--proxy', proxy_url]
    if task.geo_bypass:
        cmd.append('--geo-bypass')

    lower_url = (task.url or '').lower()
    is_missav = 'missav.ws' in lower_url or 'missav.com' in lower_url
    is_twitter = 'twitter.com' in lower_url or 'x.com' in lower_url

    if is_missav:
        # 使用 --impersonate 而非 --extractor-args
        cmd += ['--impersonate', 'chrome',
                '--socket-timeout', '120', '--extractor-retries', '8', '--http-chunk-size', '4M',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--add-header', 'Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                '--add-header', 'Accept-Language:en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                '--add-header', 'Referer:https://missav.ws/',
                '--add-header', 'Sec-Ch-Ua:"Chromium";v="120", "Google Chrome";v="120"',
                '--add-header', 'Sec-Ch-Ua-Mobile:?0',
                '--add-header', 'Sec-Fetch-Dest:document',
                '--add-header', 'Sec-Fetch-Mode:navigate',
                '--add-header', 'Sec-Fetch-Site:same-origin',
                '--add-header', 'Upgrade-Insecure-Requests:1',
                '--sleep-interval', '5', '--max-sleep-interval', '15']
        logger.info('[PROBE] missav 探测 - 添加 Cloudflare 绕过参数 (--impersonate chrome)')

    cmd.append(task.url)

    # Cookie policy
    try_browser = (
        (os.environ.get('LUMINA_FORCE_BROWSER_COOKIES') or os.environ.get('UMD_FORCE_BROWSER_COOKIES','')).lower() in ('1','true','yes') and
        (os.environ.get('LUMINA_DISABLE_BROWSER_COOKIES') or os.environ.get('UMD_DISABLE_BROWSER_COOKIES','')).lower() not in ('1','true','yes') and
        not getattr(task, 'subtitles_only', False)
    )
    if os.path.exists(manager.cookies_file):
        cmd += ['--cookies', manager.cookies_file]
        logger.info(f"[PROBE] 使用 cookies.txt 文件: {manager.cookies_file}")
    elif try_browser:
        try:
            cmd += ['--cookies-from-browser', 'chrome']
            logger.info("[PROBE] FORCE=1 且无 cookies.txt -> 尝试浏览器自动提取 (chrome)")
        except Exception:
            logger.warning("[PROBE] 浏览器 cookies 提取初始化失败，继续无 cookies")
    else:
        # Log cookie status
        if os.environ.get('LUMINA_DISABLE_BROWSER_COOKIES','').lower() in ('1','true','yes'):
            logger.info("[PROBE] 未使用 cookies (已显式禁用浏览器提取, 无 cookies.txt)")
        else:
            logger.info("[PROBE] 未使用 cookies (无 cookies.txt 且未设置 FORCE)")

    timeout_probe = PROBE_TIMEOUT_TWITTER if is_twitter else (PROBE_TIMEOUT_MISSAV if is_missav else PROBE_TIMEOUT_DEFAULT)

    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=timeout_probe, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        err_text = (r.stderr or r.stdout or "yt-dlp probe failed")
        if 'Could not copy Chrome cookie database' in err_text and '--cookies-from-browser' in ' '.join(cmd):
            logger.warning('[PROBE] 浏览器 cookie 复制失败，回退为无 cookies 再试一次')
            cmd_no_cookie = [c for c in cmd if c not in ('--cookies-from-browser','chrome')]
            r2 = subprocess.run(cmd_no_cookie, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=timeout_probe, creationflags=CREATE_NO_WINDOW)
            if r2.returncode != 0:
                raise RuntimeError(r2.stderr or r2.stdout or err_text)
            result = json.loads(r2.stdout)
        else:
            raise RuntimeError(err_text)
    else:
        result = json.loads(r.stdout)

    if result is None:
        raise RuntimeError("yt-dlp 返回 null")
    return result

def _execute_subtitle_download(manager: Any, task: Task, base_template: str):
    out_base = os.path.join(manager.download_dir, f"{base_template}")
    args = [manager.ytdlp_path, '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '--skip-download', '--convert-subs', 'srt', '-o', out_base]

    try:
        import config
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
    except ImportError:
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
    if proxy_url:
        args += ['--proxy', proxy_url]

    if task.subtitles:
        args += ['--write-subs', '--sub-langs', ','.join(task.subtitles)]
    if task.auto_subtitles:
        args += ['--write-auto-subs']
    if task.geo_bypass:
        args.append('--geo-bypass')

    if os.path.exists(manager.cookies_file):
        args += ['--cookies', manager.cookies_file]

    ffmpeg_path = manager.ffmpeg_locator()
    if ffmpeg_path:
        args += ['--ffmpeg-location', ffmpeg_path]
    args.append(task.url)

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)
    manager.procs[task.id] = proc

    if proc.stdout:
        for line in iter(proc.stdout.readline, ''):
            if task.canceled:
                try: proc.kill()
                except Exception: pass
                manager._update_task(task, status='canceled', stage=None)
                break
            line = line.rstrip('\n')
            if line: task.log.append(line)

    proc.wait()
    manager.procs.pop(task.id, None)

    if proc.returncode != 0:
        raise RuntimeError(f"字幕下载失败 (exit={proc.returncode})")

    chosen = None
    for fname in os.listdir(manager.download_dir):
        if fname.startswith(os.path.basename(base_template)) and fname.endswith('.srt'):
            chosen = os.path.join(manager.download_dir, fname)
            break
    if not chosen:
        raise RuntimeError('找不到生成的字幕文件')

    task.file_path = chosen
    try:
        manager._update_task(task, stage='merging', progress=85.0)
        normalize_srt_inplace(chosen)
    except Exception as ne:
        task.log.append(f'[subtitle] 合并单行失败: {ne}')
    manager._update_task(task, status='finished', progress=100.0, stage=None)

def _execute_thumbnail_download(manager: Any, task: Task, base_template: str):
    out_base = os.path.join(manager.download_dir, f"{base_template}.%(ext)s")
    args = [manager.ytdlp_path, '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '--skip-download', '--write-thumbnail', '--convert-thumbnails', 'jpg', '-o', out_base]

    try:
        import config
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
    except ImportError:
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
    if proxy_url:
        args += ['--proxy', proxy_url]
    if task.geo_bypass:
        args.append('--geo-bypass')

    if os.path.exists(manager.cookies_file):
        args += ['--cookies', manager.cookies_file]

    ffmpeg_path = manager.ffmpeg_locator()
    if ffmpeg_path:
        args += ['--ffmpeg-location', ffmpeg_path]
    args.append(task.url)

    manager._update_task(task, status='downloading', stage='thumbnail')
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)
    manager.procs[task.id] = proc

    if proc.stdout:
        for line in iter(proc.stdout.readline, ''):
            if task.canceled:
                try: proc.kill()
                except Exception: pass
                manager._update_task(task, status='canceled', stage=None)
                break
            line = line.rstrip('\n')
            if line: task.log.append(line)

    proc.wait()
    manager.procs.pop(task.id, None)

    if proc.returncode != 0:
        raise RuntimeError(f"封面下载失败 (exit={proc.returncode})")

    chosen = None
    for fname in os.listdir(manager.download_dir):
        if fname.startswith(os.path.basename(base_template)) and fname.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            chosen = os.path.join(manager.download_dir, fname)
            break
    task.file_path = chosen
    manager._update_task(task, status='finished', progress=100.0, stage=None)

def _execute_media_download(manager: Any, task: Task, base_template: str):
    q = getattr(task, 'quality', 'auto')
    mode = getattr(task, 'mode', 'merged')

    if mode == 'audio_only':
        forced_container = 'm4a'
    else:
        forced_container = None

    out_path_template = os.path.join(manager.download_dir, f"{base_template}.%(ext)s")
    task.file_path = out_path_template

    direct_selector = None
    if task.video_format and task.audio_format and mode == 'merged':
        direct_selector = f"{task.video_format}+{task.audio_format}"
    elif task.video_format and mode == 'video_only':
        direct_selector = task.video_format
    elif task.audio_format and mode == 'audio_only':
        direct_selector = task.audio_format

    def build_adaptive_selector() -> str:
        q_loc = getattr(task, 'quality', 'best')
        m_loc = getattr(task, 'mode', 'merged')
        if isinstance(q_loc, str) and '[' in q_loc and ']' in q_loc:
            return q_loc
        
        # 处理 height<=X 格式（来自前端的质量选择）
        if isinstance(q_loc, str) and 'height<=' in q_loc:
            import re
            height_match = re.search(r'height<=(\d+)', q_loc)
            if height_match:
                h = height_match.group(1)
                if m_loc == 'audio_only':
                    return 'bestaudio/best'
                elif m_loc == 'video_only':
                    return f'bestvideo[height<=?{h}]/bestvideo'
                else:
                    return f'bv[height<=?{h}]+ba/best[height<=?{h}]/b'
        
        if m_loc == 'audio_only':
            return 'bestaudio/best'
        if m_loc == 'video_only':
            if q_loc == 'best8k': return 'bestvideo[height<=?4320]/bestvideo'
            if q_loc == 'best4k': return 'bestvideo[height<=?2160]/bestvideo'
            if q_loc in ('best','auto'): return 'bestvideo[height<=?1080]/bestvideo'
            if q_loc == '640p': return 'bestvideo[height<=?640]/bestvideo'
            return 'bestvideo[height<=?720]/bestvideo'

        if q_loc == 'best8k': return 'bv[height<=?4320]+ba/best[height<=?4320]/b'
        if q_loc == 'best4k': return 'bv[height<=?2160]+ba/best[height<=?2160]/b'
        if q_loc in ('best','auto'): return 'bv[height<=?1080]+ba/best[height<=?1080]/b'
        if q_loc == 'fast': return 'bv[height<=?720]+ba/best[height<=?720]/b'
        if q_loc == '640p': return 'bv[height<=?640]+ba/best[height<=?640]/b'
        return 'bv+ba/b'

    format_selector = direct_selector or build_adaptive_selector()
    adaptive_selector = None if direct_selector is None else build_adaptive_selector()

    def build_args(conc: int, chunk: str, use_aria: bool=False, extra_args: List[str]=None,
                   timeout: int=15, retries: int=20, fragment_retries: int=50, retry_sleep: int=2) -> List[str]:
        fs_str = str(format_selector) if format_selector else 'best'
        a = [str(manager.ytdlp_path), '-f', fs_str,
             '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
             '--socket-timeout', str(timeout), '--retries', str(retries),
             '--fragment-retries', str(fragment_retries), '--retry-sleep', str(retry_sleep),
             '--force-ipv4', '--concurrent-fragments', str(conc), '--http-chunk-size', chunk,
             '--hls-prefer-native', '--no-continue',  # 禁用续传，避免因过期URL导致403
             '-o', out_path_template]

        try:
            import config
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
        except ImportError:
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
        if proxy_url:
            a += ['--proxy', proxy_url]

        if forced_container and mode == 'audio_only':
            a += ['--merge-output-format', forced_container]
        if task.geo_bypass:
            a.append('--geo-bypass')
        if extra_args:
            a += extra_args
        if os.path.exists(manager.cookies_file):
            a += ['--cookies', manager.cookies_file]

        ffmpeg_path = manager.ffmpeg_locator()
        if ffmpeg_path:
            a += ['--ffmpeg-location', ffmpeg_path]
        if getattr(task, 'write_thumbnail', False):
            a += ['--write-thumbnail', '--convert-thumbnails', 'jpg']

        if use_aria:
            a += ['--downloader', 'http:aria2c', '--downloader', 'https:aria2c',
                  '--downloader-args', 'aria2c:-x16 -s16 -k1M -m16 --retry-wait=2 --summary-interval=1']
        a.append(task.url)
        return a

    def run_once(args: List[str], label: str) -> tuple[int, list[str]]:
        env = None
        if manager.aria2c_path:
            env = os.environ.copy()
            aria_dir = os.path.dirname(manager.aria2c_path)
            if aria_dir and aria_dir not in env.get('PATH', ''):
                env['PATH'] = aria_dir + os.pathsep + env['PATH']

        logger.info(f"Task {task.id} 媒体下载[{label}]: {' '.join(args)}")
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding='utf-8', errors='ignore', env=env,
                                creationflags=CREATE_NO_WINDOW)
        manager.procs[task.id] = proc
        task.log.append(label)
        recent: list[str] = []
        try:
            if proc.stdout:
                for raw in iter(proc.stdout.readline, ''):
                    if task.canceled:
                        try: proc.kill()
                        except Exception: pass
                        manager._update_task(task, status='canceled', stage=None)
                        return 130, recent
                    line = (raw or '').rstrip('\n')
                    if not line: continue
                    task.log.append(line)
                    recent.append(line)
                    if len(recent) > 400: recent = recent[-400:]

                    line_str = str(line)
                    m = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line_str) or re.search(r"\((\d{1,3})%\)", line_str)
                    if m:
                        pct = float(m.group(1))
                        if task.first_progress_ts is None:
                            task.first_progress_ts = time.time()
                        manager._update_task(task, progress=pct, stage='downloading')
                    elif 'Merging formats' in line_str or 'Merger' in line_str:
                        manager._update_task(task, stage='merging')
        finally:
            proc.wait()
            manager.procs.pop(task.id, None)
        return proc.returncode, recent

    fast_start = (os.environ.get('LUMINA_FAST_START') or os.environ.get('UMD_FAST_START','')).lower() in ('1','true','yes')
    site_conf = site_configs.get_site_config(task.url)
    sc_args = site_conf.get_download_args(fast_mode=fast_start)

    init_conc = sc_args.get('concurrency', 4)
    init_chunk = sc_args.get('chunk_size', '4M')
    
    # 对于 YouTube，使用适中的并发数以平衡速度和稳定性
    is_youtube = 'youtube.com' in task.url or 'youtu.be' in task.url
    if is_youtube:
        init_conc = 4  # YouTube 使用4个并发
        init_chunk = '4M'
    elif fast_start and init_conc < 8:
        init_conc = 8
        init_chunk = '8M'

    use_aria_initial = sc_args.get('use_aria2c')
    if use_aria_initial is None:
        use_aria_initial = _should_use_aria2c(manager, task.url)

    extra_download_args = sc_args.get('args', [])
    if sc_args.get('impersonate'):
        extra_download_args += ['--impersonate', sc_args['impersonate']]

    to_timeout = sc_args.get('timeout', 15)
    to_retries = sc_args.get('retries', 20)
    to_frag_retries = sc_args.get('fragment_retries', 50)

    downloader_desc = "aria2c" if use_aria_initial else "内置下载器"
    rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=use_aria_initial, extra_args=extra_download_args,
                                     timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                          f"[speed] 使用{downloader_desc} (并发={init_conc}, 块={init_chunk}, IPv4)")

    # 调试：记录首次下载结果
    logger.info(f"Task {task.id} 首次下载结果: rc={rc}, output_lines={len(recent)}")
    if rc != 0:
        task.log.append(f"[debug] 首次下载失败 (exit={rc}), skip_probe={task.skip_probe}")
        if recent:
            task.log.append("[debug] 首次下载最后5行输出:")
            for line in recent[-5:]:
                task.log.append(f"  > {line}")

    if rc != 0 and task.skip_probe:
        joined_tail = '\n'.join(recent[-40:]).lower()
        if any(k in joined_tail for k in ['requested format not available','no such format','unable to download video data','404']):
            info = _probe_info(manager, task)
            format_selector = build_adaptive_selector()
            rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                             timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                                  '[fallback] 补 probe 后重试')

    if rc != 0 and direct_selector is not None and adaptive_selector:
        format_selector = adaptive_selector
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] 自适应格式首次尝试')

    # Merge corruption fallback
    if rc != 0 and mode == 'merged' and _is_merge_corruption(recent):
        try:
            height_cap_match = re.search(r"height<=\??(\d+)", str(format_selector))
            cap = height_cap_match.group(1) if height_cap_match else None
            if cap:
                fallback_selector = f"bv[ext=mp4][height<=?{cap}]+ba[ext=m4a]/best[height<=?{cap}]/b"
            else:
                fallback_selector = "bv[ext=mp4]+ba[ext=m4a]/best/b"
            task.log.append(f"[retry] 合并失败疑似损坏，使用保守格式回退: {fallback_selector}")
            logger.warning(f"Task {task.id} 首次合并失败，回退格式选择器重试")
            format_selector = fallback_selector
            rc, recent = run_once(build_args(4, '4M', use_aria=False, extra_args=extra_download_args,
                                             timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                                  '[retry] 回退格式重试 (mp4/m4a 优先)')
        except Exception as _fb_e:
            task.log.append(f"[retry] 回退格式构建异常: {_fb_e}")

    # SSL EOF fallback
    if rc != 0 and _has_ssl_eof(recent):
        task.log.append('[net] 检测到 SSLEOF/连接被对端提前关闭，降低并发与增大分块后重试…')
        rc, recent = run_once(build_args(2, '8M', use_aria=False, extra_args=extra_download_args, timeout=to_timeout), '[speed] 内置下载器降级重试 (并发=2, 块=8M, IPv4)')

    if rc != 0 and _has_ssl_eof(recent):
        if manager.aria2c_path:
            task.log.append('[net] 仍失败，切换 aria2c 兜底重试…')
            rc, recent = run_once(build_args(2, '8M', use_aria=True, extra_args=extra_download_args, timeout=to_timeout), '[speed] 使用 aria2c 兜底 (-x16 -s16 -k1M)')

    if rc != 0:
        _check_partial_success(manager, task, base_template)
        # If rc became 0, skip re-raise
        if task.status == 'finished': rc = 0

    if rc != 0:
        # 记录 yt-dlp 输出的最后几行，帮助诊断问题
        if recent:
            task.log.append('[debug] yt-dlp 最后输出:')
            for line in recent[-20:]:
                task.log.append(f'  | {line}')
        
        # 检测常见错误模式
        joined_output = '\n'.join(recent[-60:]).lower() if recent else ''
        
        if 'sign in to confirm' in joined_output or 'bot' in joined_output:
            task.log.append('[error] YouTube 需要登录验证，请更新 cookies.txt')
            raise RuntimeError("YouTube 需要登录验证 - 请更新 cookies.txt")
        
        if 'video unavailable' in joined_output or 'private video' in joined_output:
            task.log.append('[error] 视频不可用或已被删除')
            raise RuntimeError("视频不可用或已被删除")
        
        if 'age-restricted' in joined_output or 'age restricted' in joined_output:
            task.log.append('[error] 视频有年龄限制，需要登录的 cookies')
            raise RuntimeError("视频有年龄限制 - 需要登录的 cookies")
            
        if 'http error 403' in joined_output or '403 forbidden' in joined_output or 'error 403:' in joined_output:
            task.log.append('[error] 访问被拒绝 (403)，可能是地区限制或需要登录')
            raise RuntimeError("访问被拒绝 (403) - 可能是地区限制")
        
        if 'http error 429' in joined_output or 'too many requests' in joined_output:
            task.log.append('[error] 请求过于频繁，被限流 (429)')
            raise RuntimeError("请求过于频繁 (429) - 请稍后重试")
        
        if 'connection reset' in joined_output or '10054' in joined_output:
            task.log.append('[error] 网络连接被重置，可能是代理或网络问题')
            raise RuntimeError("网络连接被重置 - 检查代理设置")
        
        # If already retried merge corruption, give more specific error
        if _is_merge_corruption(recent):
            task.log.append('[retry] 回退后仍发生合并/输入解析失败，建议降低质量或更新 yt-dlp')
        raise RuntimeError(f"媒体下载失败 (exit={rc})")

    _finalize_download(manager, task, base_template, mode)

def _has_ssl_eof(lines: list[str]) -> bool:
    text = '\n'.join(lines).lower()
    return ('eof occurred in violation of protocol' in text) or ('ssleof' in text) or ('tlsv1' in text) or ('10054' in text) or ('connection reset' in text)

def _should_use_aria2c(manager: Any, url: str) -> bool:
    if manager.aria2c_path is None: return False
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ''
        host = host.lower()
        blocked = ('youtube.com', 'youtu.be', 'googlevideo.com')
        return not any(h in host for h in blocked)
    except Exception:
        return True

def _check_partial_success(manager: Any, task: Task, base_template: str):
    base_name_tmp = os.path.basename(base_template)
    for fname in os.listdir(manager.download_dir):
        if not fname.startswith(base_name_tmp + '.'): continue
        if re.search(r"\.f\d+\.", fname): continue
        if '%(ext)s' in fname: continue
        fullp = os.path.join(manager.download_dir, fname)
        if os.path.isfile(fullp) and os.path.getsize(fullp) > 100 * 1024:
            task.log.append('[partial-ok] 发现已生成合并文件且大小正常')
            task.file_path = fullp
            _finalize_download(manager, task, base_template, task.mode)
            break

def _finalize_download(manager: Any, task: Task, base_template: str, mode: str):
    """Complete download finalization with file resolution, renaming, and meta generation"""
    # Resolve actual file path
    base_name = os.path.basename(base_template)
    merged_candidate = None
    component_files = []
    comp_re = re.compile(rf"^{re.escape(base_name)}\.f(\d+)\.")
    for fname in os.listdir(manager.download_dir):
        if not fname.startswith(base_name + '.') or '%(ext)s' in fname:
            continue
        fullp = os.path.join(manager.download_dir, fname)
        if comp_re.search(fname):
            component_files.append(fullp)
        else:
            merged_candidate = fullp

    if merged_candidate and os.path.exists(merged_candidate):
        task.file_path = merged_candidate
        task.log.append(f"[detect] 发现已合并文件: {os.path.basename(merged_candidate)}")
    elif component_files:
        # Try component merge first
        if _component_merge(manager, task, base_template, component_files):
            pass  # Already handled in component_merge
        else:
            # Fallback to using latest component
            try:
                component_files.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
            except Exception:
                pass
            task.file_path = component_files[0]
            task.log.append(f"[detect] 未发现合并文件，组件文件数: {len(component_files)}，暂用: {os.path.basename(task.file_path)}")
            task.log.append("[component-scan] 组件文件: " + ', '.join(os.path.basename(p) for p in component_files))

    _fill_media_metadata(manager, task)

    # Audio fallback if no audio codec detected in merged mode
    component_merged = False
    if mode == 'merged' and not task.canceled:
        no_audio = not getattr(task, 'acodec', None)
        if no_audio:
            if _audio_fallback(manager, task, base_template):
                component_merged = True

    # Final metadata fill
    _fill_media_metadata(manager, task)

    suffix_applied = False
    # Rename file with resolution suffix
    if task.file_path and os.path.exists(task.file_path):
        original_path = task.file_path
        root_name, ext = os.path.splitext(os.path.basename(original_path))
        height_val = task.height
        if height_val and isinstance(height_val, int):
            if not re.search(r"_(\d{3,4})p$", root_name):
                new_root = f"{root_name}_{height_val}p"
                new_name = new_root + ext
                new_path = os.path.join(manager.download_dir, new_name)
                try:
                    if not os.path.exists(new_path):
                        os.rename(original_path, new_path)
                        task.file_path = new_path
                        task.log.append(f"[rename] 已添加分辨率后缀 -> {os.path.basename(new_path)}")
                        suffix_applied = True
                except Exception as re_err:
                    task.log.append(f"[rename] 添加高度后缀失败: {re_err}")

    # Write meta file
    if task.file_path and os.path.exists(task.file_path):
        _write_meta_file(manager, task, task.file_path, suffix_applied)

    manager._update_task(task, status='finished', progress=100.0, stage=None)

def _fill_media_metadata(manager: Any, task: Task):
    fp = task.file_path
    if not fp or not os.path.exists(fp): return

    ffmpeg_path = manager.ffmpeg_locator()
    probe_bin = 'ffprobe'
    if ffmpeg_path:
        if os.path.isdir(ffmpeg_path):
            cand = os.path.join(ffmpeg_path, 'ffprobe.exe')
            if os.path.exists(cand): probe_bin = cand
        else:
            cand = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
            if os.path.exists(cand): probe_bin = cand

    fields = {}
    try:
        # Width/Height/Vcodec
        vc_cmd = [probe_bin, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', fp]
        p = subprocess.run(vc_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=10, creationflags=CREATE_NO_WINDOW)
        vals = [v.strip() for v in (p.stdout or '').strip().split('\n') if v.strip()]
        if len(vals) >= 3:
            if vals[0].isdigit(): fields['width'] = int(vals[0])
            if vals[1].isdigit(): fields['height'] = int(vals[1])
            fields['vcodec'] = vals[2]

        # Acodec
        ac_cmd = [probe_bin, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', fp]
        pa = subprocess.run(ac_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=6, creationflags=CREATE_NO_WINDOW)
        if pa.returncode == 0 and pa.stdout.strip():
            fields['acodec'] = pa.stdout.strip().split('\n')[0]

        fields['filesize'] = os.path.getsize(fp)
    except Exception: pass

    if fields: manager._update_task(task, **fields)

def _safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip().strip('.')
    if len(name) > 150:
        name = name[:150]
    return name or 'video'


def _classify_media_file(manager: Any, fp: str) -> str:
    """Simple file classification: video | audio | unknown"""
    try:
        ffmpeg_path = manager.ffmpeg_locator()
        probe_bin = 'ffprobe'
        if ffmpeg_path:
            if os.path.isdir(ffmpeg_path):
                cand = os.path.join(ffmpeg_path, 'ffprobe.exe')
                if os.path.exists(cand):
                    probe_bin = cand
            else:
                cand = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
                if os.path.exists(cand):
                    probe_bin = cand

        cmd_v = [probe_bin, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', fp]
        pv = subprocess.run(cmd_v, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=6, creationflags=CREATE_NO_WINDOW)
        if pv.returncode == 0 and pv.stdout.strip():
            return 'video'

        cmd_a = [probe_bin, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', fp]
        pa = subprocess.run(cmd_a, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=6, creationflags=CREATE_NO_WINDOW)
        if pa.returncode == 0 and pa.stdout.strip():
            return 'audio'

        return 'unknown'
    except Exception:
        return 'unknown'


def _is_merge_corruption(lines: List[str]) -> bool:
    """Check if lines indicate merge corruption"""
    if not lines:
        return False
    txt = '\n'.join(lines[-60:]).lower()
    return ('invalid data found when processing input' in txt) or ('error opening input files' in txt)


def _component_merge(manager: Any, task: Task, base_template: str, components: List[str]) -> bool:
    """Merge separate video+audio components using ffmpeg"""
    try:
        # Classify components
        video_parts = []
        audio_parts = []
        for fp in components:
            kind = _classify_media_file(manager, fp)
            if kind == 'video':
                video_parts.append(fp)
            elif kind == 'audio':
                audio_parts.append(fp)

        if not video_parts or not audio_parts:
            return False

        # Get latest video and audio
        try:
            video_parts.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
            audio_parts.sort(key=lambda p: os.stat(p).st_mtime, reverse=True)
        except Exception:
            pass

        vfile = video_parts[0]
        afile = audio_parts[0]

        # Find ffmpeg
        ffmpeg_loc = manager.ffmpeg_locator()
        ffmpeg_bin = None
        if ffmpeg_loc:
            if os.path.isdir(ffmpeg_loc):
                cand = os.path.join(ffmpeg_loc, 'ffmpeg.exe')
                if os.path.exists(cand):
                    ffmpeg_bin = cand
                else:
                    cand2 = os.path.join(ffmpeg_loc, 'ffmpeg')
                    if os.path.exists(cand2):
                        ffmpeg_bin = cand2
            else:
                ffmpeg_bin = ffmpeg_loc

        if not ffmpeg_bin:
            task.log.append('[component-merge] 未找到 ffmpeg，无法组件合并')
            return False

        # Build merge command
        base_name = os.path.basename(base_template)
        merged_out = os.path.join(manager.download_dir, f"{base_name}.mkv")
        merge_cmd = [
            ffmpeg_bin, '-y',
            '-i', vfile,
            '-i', afile,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-map', '0:v:0',
            '-map', '1:a:0?',
            merged_out
        ]

        task.log.append('[component-merge] 检测到独立视频+音频组件，尝试直接合并')
        task.log.append('[component-merge] ffmpeg 命令: ' + ' '.join(merge_cmd))
        logger.info(f"Task {task.id} 组件合并: {' '.join(merge_cmd)}")

        pm = subprocess.run(merge_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)

        if pm.returncode == 0 and os.path.exists(merged_out):
            task.file_path = merged_out
            task.log.append('[component-merge] 合并成功 -> ' + os.path.basename(merged_out))
            _fill_media_metadata(manager, task)
            return True
        else:
            task.log.append(f"[component-merge] 合并失败(exit={pm.returncode}) {pm.stderr[-160:]}")
            return False

    except Exception as ce:
        task.log.append(f'[component-merge] 处理异常: {ce}')
        return False


def _audio_fallback(manager: Any, task: Task, base_template: str) -> bool:
    """Download bestaudio and merge with existing video"""
    try:
        if not task.file_path or not os.path.exists(task.file_path):
            task.log.append('[audio-fallback] 视频文件丢失，放弃补救')
            return False

        task.log.append('[audio-fallback] 未检测到音频轨，尝试下载音频并合并...')

        # Find ffmpeg
        ffmpeg_loc = manager.ffmpeg_locator()
        ffmpeg_bin = None
        if ffmpeg_loc:
            if os.path.isdir(ffmpeg_loc):
                cand = os.path.join(ffmpeg_loc, 'ffmpeg.exe')
                if os.path.exists(cand):
                    ffmpeg_bin = cand
                else:
                    cand2 = os.path.join(ffmpeg_loc, 'ffmpeg')
                    if os.path.exists(cand2):
                        ffmpeg_bin = cand2
            else:
                ffmpeg_bin = ffmpeg_loc

        if not ffmpeg_bin:
            task.log.append('[audio-fallback] 找不到 ffmpeg，放弃补救')
            return False

        # Build audio download args
        base_name = os.path.basename(base_template)
        audio_template = os.path.join(manager.download_dir, f"{base_name}.audio.%(ext)s")
        audio_args = [
            manager.ytdlp_path, '-f', 'bestaudio/best',
            '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '-o', audio_template
        ]

        if os.path.exists(manager.cookies_file):
            audio_args += ['--cookies', manager.cookies_file]

        # Proxy
        try:
            import config
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
        except ImportError:
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
        if proxy_url:
            audio_args += ['--proxy', proxy_url]

        audio_args += ['--ffmpeg-location', ffmpeg_bin]
        audio_args.append(task.url)

        task.log.append('[audio-fallback] 执行音频补抓: ' + ' '.join(audio_args))
        logger.info(f"Task {task.id} 补抓音频: {' '.join(audio_args)}")

        manager.procs[task.id] = proc_a = subprocess.Popen(audio_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                           text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)
        if proc_a.stdout:
            for l in iter(proc_a.stdout.readline, ''):
                if task.canceled:
                    try: proc_a.kill()
                    except Exception: pass
                    manager._update_task(task, status='canceled', stage=None)
                    break
                if not l:
                    continue
                task.log.append('[A] ' + l.rstrip())
        proc_a.wait()
        try:
            manager.procs.pop(task.id, None)
        except Exception:
            pass

        if proc_a.returncode != 0:
            task.log.append(f'[audio-fallback] 音频下载失败(exit={proc_a.returncode})')
            return False

        # Find audio file
        audio_file = None
        for fname in os.listdir(manager.download_dir):
            if fname.startswith(base_name + '.audio.'):
                audio_file = os.path.join(manager.download_dir, fname)
                break

        if not audio_file:
            task.log.append('[audio-fallback] 未找到音频文件，放弃补救')
            return False

        # Merge with ffmpeg
        merged_out = os.path.join(manager.download_dir, f"{base_name}.mkv")
        if os.path.abspath(merged_out) == os.path.abspath(task.file_path):
            merged_out = task.file_path + '.mkv'

        merge_cmd = [
            ffmpeg_bin, '-y',
            '-i', task.file_path,
            '-i', audio_file,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-map', '0:v:0',
            '-map', '1:a:0?',
            merged_out
        ]

        task.log.append('[audio-fallback] ffmpeg 合并命令: ' + ' '.join(merge_cmd))
        logger.info(f"Task {task.id} 音频补救合并: {' '.join(merge_cmd)}")

        p_merge = subprocess.run(merge_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', creationflags=CREATE_NO_WINDOW)

        if p_merge.returncode != 0:
            task.log.append(f'[audio-fallback] 合并失败(exit={p_merge.returncode}) {p_merge.stderr[-200:]}')
            return False

        task.file_path = merged_out
        task.log.append('[audio-fallback] 合并成功，更新文件路径为 MKV')
        _fill_media_metadata(manager, task)
        return True

    except Exception as fallback_err:
        task.log.append(f'[audio-fallback] 处理异常: {fallback_err}')
        return False


def _write_meta_file(manager: Any, task: Task, file_path: str, suffix_applied: bool):
    """Write meta.json file with complete metadata"""
    try:
        # Determine meta mode: task override > env > default
        raw_mode = (task.meta_mode or '').strip().lower() or os.environ.get('META_MODE') or ''

        # PyInstaller default off
        if not raw_mode and getattr(sys, 'frozen', False):
            raw_mode = 'off'

        if not raw_mode:
            if os.environ.get('LUMINA_DISABLE_META','').lower() in ('1','true','yes'):
                raw_mode = 'off'
            else:
                raw_mode = 'sidecar'

        if raw_mode not in ('off', 'sidecar', 'folder'):
            raw_mode = 'sidecar'

        if raw_mode == 'off':
            task.log.append('[meta] META_MODE=off，跳过元数据文件写入')
            return

        meta = {
            'task_id': task.id,
            'source_url': task.url,
            'title': task.title,
            'requested_quality': getattr(task, 'quality', None),
            'mode': getattr(task, 'mode', None),
            'height': task.height,
            'width': task.width,
            'vcodec': task.vcodec,
            'acodec': task.acodec,
            'filesize': task.filesize,
            'final_file': task.file_path,
            'renamed_with_height': suffix_applied,
            'created_at': task.created_at,
            'completed_at': time.time(),
            'meta_mode': raw_mode,
        }

        if raw_mode == 'sidecar':
            meta_path = file_path + '.meta.json'
        else:  # folder mode
            base_meta_dir = os.environ.get('LUMINA_META_DIR') or os.path.join(os.path.dirname(file_path), '_meta')
            try:
                os.makedirs(base_meta_dir, exist_ok=True)
            except Exception:
                pass
            media_base = os.path.basename(file_path)
            meta_path = os.path.join(base_meta_dir, media_base + '.json')

        with open(meta_path, 'w', encoding='utf-8') as mf:
            json.dump(meta, mf, ensure_ascii=False, indent=2)
        task.log.append(f"[meta] 写入元数据 ({raw_mode}) -> {os.path.basename(meta_path)}")

    except Exception as me:
        task.log.append(f"[meta] 元数据写入失败: {me}")
