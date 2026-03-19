import os
import re
import json
import sys
import time
import logging
import subprocess
import traceback
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, urlunparse

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

_YTDLP_PLUGIN_DIR_CACHE = None

def _is_impersonate_unavailable_text(text: str) -> bool:
    t = (text or '').lower()
    return 'impersonate target' in t and 'is not available' in t

def _has_impersonate_unavailable(lines: list[str]) -> bool:
    return _is_impersonate_unavailable_text('\n'.join(lines))

def _strip_option_with_value(args: list[str], option: str) -> list[str]:
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        cur = args[i]
        if cur == option:
            i += 2
            continue
        cleaned.append(cur)
        i += 1
    return cleaned

def _strip_impersonate_args(args: list[str]) -> list[str]:
    return _strip_option_with_value(args, '--impersonate')

def _get_option_value(args: list[str], option: str) -> Optional[str]:
    i = 0
    while i < len(args):
        if args[i] == option and i + 1 < len(args):
            return args[i + 1]
        i += 1
    return None

def _replace_option_value(args: list[str], option: str, value: str) -> list[str]:
    replaced: list[str] = []
    i = 0
    changed = False
    while i < len(args):
        cur = args[i]
        if cur == option and i + 1 < len(args):
            replaced.extend([option, value])
            i += 2
            changed = True
            continue
        replaced.append(cur)
        i += 1
    if not changed:
        replaced.extend([option, value])
    return replaced

def _browser_cookie_candidates(preferred: Optional[str] = None) -> list[str]:
    env_browser = (os.environ.get('LUMINA_COOKIE_BROWSER') or os.environ.get('UMD_COOKIE_BROWSER') or '').strip().lower()
    candidates: list[str] = []

    def _add(browser: Optional[str]):
        if browser and browser not in candidates:
            candidates.append(browser)

    _add(preferred)
    _add(env_browser)
    for browser in ('chrome', 'edge', 'brave', 'firefox'):
        _add(browser)
    return candidates

def _choose_browser_cookie_source(task: Task) -> str:
    preferred = getattr(task, 'cookie_browser', None)
    return _browser_cookie_candidates(preferred)[0]

def _is_browser_cookie_copy_error_text(text: str) -> bool:
    t = (text or '').lower()
    markers = (
        'could not copy chrome cookie database',
        'could not copy edge cookie database',
        'could not copy brave cookie database',
        'could not find chrome cookies database',
        'could not find edge cookies database',
        'could not find brave cookies database',
        'could not find firefox cookies database',
        'extracting cookies from chrome',
        'extracting cookies from edge',
        'extracting cookies from brave',
        'extracting cookies from firefox',
        'failed to open cookies database',
        'could not locate runnable browser',
        'failed to decrypt with dpapi',
        'error decrypting',
    )
    return any(m in t for m in markers)

def _cookie_domain_matches_host(cookie_domain: str, host: str) -> bool:
    domain = (cookie_domain or '').strip().lstrip('.').lower()
    host = (host or '').strip().lower()
    if not domain or not host:
        return False
    return host == domain or host.endswith('.' + domain)

def _is_missav_url(url: str) -> bool:
    return 'missav' in (url or '').lower()

def _missav_origin(url: str) -> str:
    parsed = urlparse(url or '')
    scheme = parsed.scheme or 'https'
    host = (parsed.hostname or '').strip().lower()
    if not host:
        host = 'missav.ws'
    return f'{scheme}://{host}/'

def _cookiefile_domains(cookie_file: str) -> list[str]:
    domains: list[str] = []
    if not cookie_file or not os.path.exists(cookie_file):
        return domains
    try:
        with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) < 7:
                    continue
                domain = parts[0].strip().lstrip('.').lower()
                if domain and domain not in domains:
                    domains.append(domain)
    except Exception:
        return []
    return domains

def _site_cookie_candidates(url: str, cookie_file: str) -> list[str]:
    candidates: list[str] = []
    base_dir = os.path.dirname(cookie_file) if cookie_file else ''
    if cookie_file and not base_dir:
        base_dir = '.'
    if _is_missav_url(url) and base_dir:
        for name in ('cookies_missav.txt', 'cookies-missav.txt', 'missav.cookies.txt'):
            path = os.path.join(base_dir, name)
            if path not in candidates:
                candidates.append(path)
        try:
            for name in os.listdir(base_dir):
                lower = name.lower()
                if 'missav' in lower and 'cookie' in lower and lower.endswith('.txt'):
                    path = os.path.join(base_dir, name)
                    if path not in candidates:
                        candidates.append(path)
        except Exception:
            pass
    if cookie_file and cookie_file not in candidates:
        candidates.append(cookie_file)
    return candidates

def _cookiefile_has_host(cookie_file: str, url: str) -> bool:
    host = (urlparse(url).hostname or '').lower()
    if not host or not cookie_file or not os.path.exists(cookie_file):
        return False
    try:
        with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) < 7:
                    continue
                if _cookie_domain_matches_host(parts[0], host):
                    return True
    except Exception:
        return False
    return False

def _cookiefile_has_site_cookie(cookie_file: str, url: str) -> bool:
    if not cookie_file or not os.path.exists(cookie_file):
        return False
    if _is_missav_url(url):
        return any('missav' in domain for domain in _cookiefile_domains(cookie_file))
    return _cookiefile_has_host(cookie_file, url)

def _select_cookie_file(url: str, cookie_file: str) -> Optional[str]:
    for cand in _site_cookie_candidates(url, cookie_file):
        if _cookiefile_has_site_cookie(cand, url):
            return cand
    return None

def _normalize_missav_url_by_cookie(url: str, cookie_file: Optional[str]) -> str:
    if not _is_missav_url(url) or not cookie_file or not os.path.exists(cookie_file):
        return url
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        missav_domains = [d for d in _cookiefile_domains(cookie_file) if 'missav' in d]
        if not missav_domains:
            return url
        if any(_cookie_domain_matches_host(domain, host) for domain in missav_domains):
            return url
        target_host = missav_domains[0]
        port = f":{parsed.port}" if parsed.port else ''
        new_netloc = target_host + port
        return urlunparse((parsed.scheme, new_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    except Exception:
        return url

def _should_try_browser_cookies(url: str, cookie_file: str) -> bool:
    force_browser = (
        (os.environ.get('LUMINA_FORCE_BROWSER_COOKIES') or os.environ.get('UMD_FORCE_BROWSER_COOKIES', '')).lower()
        in ('1', 'true', 'yes')
    )
    disable_browser = (
        (os.environ.get('LUMINA_DISABLE_BROWSER_COOKIES') or os.environ.get('UMD_DISABLE_BROWSER_COOKIES', '')).lower()
        in ('1', 'true', 'yes')
    )
    if disable_browser:
        return False
    if force_browser:
        return True

    lower_url = (url or '').lower()
    is_missav = 'missav' in lower_url
    if not is_missav:
        return False

    if not os.path.exists(cookie_file):
        return True
    return not _cookiefile_has_host(cookie_file, url)

def _force_browser_cookies_enabled() -> bool:
    disable_browser = (
        (os.environ.get('LUMINA_DISABLE_BROWSER_COOKIES') or os.environ.get('UMD_DISABLE_BROWSER_COOKIES', '')).lower()
        in ('1', 'true', 'yes')
    )
    if disable_browser:
        return False
    return (
        (os.environ.get('LUMINA_FORCE_BROWSER_COOKIES') or os.environ.get('UMD_FORCE_BROWSER_COOKIES', '')).lower()
        in ('1', 'true', 'yes')
    )

def _has_usable_cookiefile(url: str, cookie_file: str) -> bool:
    if not cookie_file or not os.path.exists(cookie_file):
        return False
    lower_url = (url or '').lower()
    if 'missav' in lower_url:
        return _cookiefile_has_host(cookie_file, url)
    return True

def _find_ytdlp_plugin_dir() -> Optional[str]:
    global _YTDLP_PLUGIN_DIR_CACHE
    if _YTDLP_PLUGIN_DIR_CACHE is not None:
        return _YTDLP_PLUGIN_DIR_CACHE or None

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join(repo_root, 'yt-dlp-plugins'),
        os.path.join(repo_root, 'yt-dlp-plugins', 'yt-dlp-plugin-yellow-master'),
    ]
    for cand in candidates:
        if not os.path.isdir(cand):
            continue
        plugin_ns = os.path.join(cand, 'yt_dlp_plugins')
        if os.path.isdir(plugin_ns):
            _YTDLP_PLUGIN_DIR_CACHE = cand
            return cand
        try:
            for entry in os.listdir(cand):
                sub_plugin_ns = os.path.join(cand, entry, 'yt_dlp_plugins')
                if os.path.isdir(sub_plugin_ns):
                    _YTDLP_PLUGIN_DIR_CACHE = cand
                    return cand
        except Exception:
            continue

    _YTDLP_PLUGIN_DIR_CACHE = ''
    return None

def _with_plugin_dir_args(args: List[str]) -> List[str]:
    plugin_dir = _find_ytdlp_plugin_dir()
    if not plugin_dir or not args:
        return args
    return [args[0], '--plugin-dirs', plugin_dir, *args[1:]]

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
    resolved_url = _normalize_missav_url_by_cookie(task.url, _select_cookie_file(task.url, manager.cookies_file))
    if resolved_url != task.url:
        logger.info(f"[PROBE] MissAV URL 按 cookie 域名切换为: {resolved_url}")

    cmd = [str(manager.ytdlp_path), '--skip-download', '--dump-single-json', '--no-warnings', '--no-check-certificate']
    cmd = _with_plugin_dir_args(cmd)

    # Proxy logic
    try:
        import config
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
    except ImportError:
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')

    lower_url = (resolved_url or '').lower()
    is_missav = 'missav' in lower_url
    is_twitter = 'twitter.com' in lower_url or 'x.com' in lower_url
    is_youtube = 'youtube.com' in lower_url or 'youtu.be' in lower_url

    if proxy_url:
        cmd += ['--proxy', proxy_url]
    if task.geo_bypass:
        cmd.append('--geo-bypass')

    if is_missav:
        missav_origin = _missav_origin(resolved_url)
        plugin_dir = _find_ytdlp_plugin_dir()
        if plugin_dir:
            logger.info(f"[PROBE] missav 使用插件搜索目录: {plugin_dir}")
        else:
            logger.info('[PROBE] missav 未加载本地 yt-dlp 插件目录，继续使用内置提取器')

        cmd += ['--impersonate', 'chrome',
                '--force-ipv4',
                '--socket-timeout', '120', '--extractor-retries', '8',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                '--add-header', 'Accept:text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                '--add-header', 'Accept-Language:en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
                '--add-header', f'Referer:{missav_origin}',
                '--add-header', 'Sec-Ch-Ua:"Chromium";v="120", "Google Chrome";v="120"',
                '--add-header', 'Sec-Ch-Ua-Mobile:?0',
                '--add-header', 'Sec-Fetch-Dest:document',
                '--add-header', 'Sec-Fetch-Mode:navigate',
                '--add-header', 'Sec-Fetch-Site:same-origin',
                '--add-header', 'Upgrade-Insecure-Requests:1']
        logger.info('[PROBE] missav 探测 - 添加 Cloudflare 绕过参数 (--impersonate chrome)')

    if is_youtube:
        # YouTube 特殊处理：android 客户端不支持 cookies
        # 策略：使用 android 客户端，不添加 cookies
        cmd += ['--extractor-args', 'youtube:player_client=android']
        logger.info('[PROBE] YouTube: 使用 android 客户端（绕过 n challenge）')

    selected_cookie_file = _select_cookie_file(resolved_url, manager.cookies_file)
    prefer_browser = _force_browser_cookies_enabled()
    try_browser = ((prefer_browser or not selected_cookie_file) and _should_try_browser_cookies(resolved_url, manager.cookies_file)
                   and not getattr(task, 'subtitles_only', False))
    browser_cookie = _choose_browser_cookie_source(task) if try_browser else None

    # YouTube 使用 android 客户端时不添加 cookies（android 不支持 cookies）
    skip_cookies_for_youtube = is_youtube

    if skip_cookies_for_youtube:
        logger.info("[PROBE] YouTube android 模式：跳过 cookies")
    elif try_browser:
        cmd += ['--cookies-from-browser', browser_cookie or 'chrome']
        if selected_cookie_file and not _cookiefile_has_site_cookie(selected_cookie_file, resolved_url):
            logger.info(f"[PROBE] cookies.txt 不含 MissAV 站点 cookie，改为尝试浏览器 cookies ({browser_cookie})")
        else:
            logger.info(f"[PROBE] 尝试浏览器 cookies ({browser_cookie})")
    elif selected_cookie_file:
        cmd += ['--cookies', selected_cookie_file]
        logger.info(f"[PROBE] 使用站点 cookies 文件: {selected_cookie_file}")
    else:
        if os.environ.get('LUMINA_DISABLE_BROWSER_COOKIES','').lower() in ('1','true','yes'):
            logger.info("[PROBE] 未使用 cookies (已显式禁用浏览器提取, 无 cookies.txt)")
        else:
            logger.info("[PROBE] 未使用 cookies (无可用站点 cookies)")

    timeout_probe = PROBE_TIMEOUT_TWITTER if is_twitter else (PROBE_TIMEOUT_MISSAV if is_missav else PROBE_TIMEOUT_DEFAULT)

    def _run_probe(current_cmd: List[str]) -> subprocess.CompletedProcess:
        final_cmd = current_cmd + [resolved_url]
        logger.info(f"[PROBE] Final probe cmd: {final_cmd}")
        return subprocess.run(final_cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore',
                              timeout=timeout_probe, creationflags=CREATE_NO_WINDOW)

    def _parse_probe(proc: subprocess.CompletedProcess) -> Dict[str, Any]:
        out = (proc.stdout or '').strip()
        if not out:
            raise RuntimeError(proc.stderr or 'yt-dlp 返回空输出')
        result = json.loads(out)
        if result is None:
            raise RuntimeError("yt-dlp 返回 null")
        if not isinstance(result, dict):
            raise RuntimeError(f"yt-dlp 返回了非对象 JSON: {type(result).__name__}")
        return result

    probe_cmd = cmd
    r = _run_probe(probe_cmd)
    if r.returncode == 0:
        browser_used = _get_option_value(probe_cmd, '--cookies-from-browser')
        if browser_used:
            setattr(task, 'cookie_browser', browser_used)
        return _parse_probe(r)

    err_text = (r.stderr or r.stdout or 'yt-dlp probe failed')
    if '--impersonate' in probe_cmd and _is_impersonate_unavailable_text(err_text):
        logger.warning('[PROBE] 当前 yt-dlp 不支持 impersonate，移除后重试一次')
        probe_cmd = _strip_impersonate_args(probe_cmd)
        r = _run_probe(probe_cmd)
        if r.returncode == 0:
            return _parse_probe(r)
        err_text = (r.stderr or r.stdout or err_text)

    if _is_browser_cookie_copy_error_text(err_text) and '--cookies-from-browser' in probe_cmd:
            failed_browser = _get_option_value(probe_cmd, '--cookies-from-browser') or 'chrome'
            for browser in _browser_cookie_candidates(getattr(task, 'cookie_browser', None)):
                if browser == failed_browser:
                    continue
                logger.warning(f'[PROBE] 浏览器 cookie 复制失败，改试 {browser}')
                alt_cmd = _replace_option_value(probe_cmd, '--cookies-from-browser', browser)
                r = _run_probe(alt_cmd)
                alt_err = (r.stderr or r.stdout or err_text)
                if r.returncode == 0:
                    setattr(task, 'cookie_browser', browser)
                    return _parse_probe(r)
                if not _is_browser_cookie_copy_error_text(alt_err):
                    probe_cmd = alt_cmd
                    err_text = alt_err
                    break
            else:
                if is_missav and not selected_cookie_file:
                    raise RuntimeError('无法读取 MissAV 浏览器 cookies。请关闭 Chrome/Edge/Brave/Firefox 后重试，或设置 UMD_COOKIE_BROWSER=edge（或你的实际浏览器），或先在浏览器中打开 MissAV 通过 Cloudflare 后导出该站点 cookies 到 cookies_missav.txt')
                logger.warning('[PROBE] 浏览器 cookie 复制失败，回退为无 cookies 再试一次')
                probe_cmd = _strip_option_with_value(probe_cmd, '--cookies-from-browser')
                r = _run_probe(probe_cmd)
                if r.returncode == 0:
                    return _parse_probe(r)
                err_text = (r.stderr or r.stdout or err_text)

    if is_missav and _is_browser_cookie_copy_error_text(err_text):
        raise RuntimeError('未找到可用的 MissAV 浏览器 cookies。请关闭浏览器后重试，或设置 UMD_COOKIE_BROWSER=edge（或你的实际浏览器），或导出包含 missav/cf_clearance 的 cookies_missav.txt')

    if proxy_url and _is_proxy_error_text(err_text):
        logger.warning('[PROBE] 代理连接失败，回退直连重试一次')
        probe_cmd = _strip_option_with_value(probe_cmd, '--proxy')
        r = _run_probe(probe_cmd)
        if r.returncode == 0:
            return _parse_probe(r)
        err_text = (r.stderr or r.stdout or err_text)

    raise RuntimeError(err_text)

def _execute_subtitle_download(manager: Any, task: Task, base_template: str):
    resolved_url = _normalize_missav_url_by_cookie(task.url, _select_cookie_file(task.url, manager.cookies_file))
    selected_cookie_file = _select_cookie_file(resolved_url, manager.cookies_file)
    out_base = os.path.join(manager.download_dir, f"{base_template}")
    args = [manager.ytdlp_path, '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '--skip-download', '--convert-subs', 'srt', '-o', out_base]
    args = _with_plugin_dir_args(args)

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

    if not selected_cookie_file and _should_try_browser_cookies(resolved_url, manager.cookies_file):
        args += ['--cookies-from-browser', _choose_browser_cookie_source(task)]
    elif selected_cookie_file:
        args += ['--cookies', selected_cookie_file]

    ffmpeg_path = manager.ffmpeg_locator()
    if ffmpeg_path:
        args += ['--ffmpeg-location', ffmpeg_path]
    args.append(resolved_url)

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
    resolved_url = _normalize_missav_url_by_cookie(task.url, _select_cookie_file(task.url, manager.cookies_file))
    selected_cookie_file = _select_cookie_file(resolved_url, manager.cookies_file)
    out_base = os.path.join(manager.download_dir, f"{base_template}.%(ext)s")
    args = [manager.ytdlp_path, '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '--skip-download', '--write-thumbnail', '--convert-thumbnails', 'jpg', '-o', out_base]
    args = _with_plugin_dir_args(args)

    try:
        import config
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
    except ImportError:
        proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
    if proxy_url:
        args += ['--proxy', proxy_url]
    if task.geo_bypass:
        args.append('--geo-bypass')

    if not selected_cookie_file and _should_try_browser_cookies(resolved_url, manager.cookies_file):
        args += ['--cookies-from-browser', _choose_browser_cookie_source(task)]
    elif selected_cookie_file:
        args += ['--cookies', selected_cookie_file]

    ffmpeg_path = manager.ffmpeg_locator()
    if ffmpeg_path:
        args += ['--ffmpeg-location', ffmpeg_path]
    args.append(resolved_url)

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
    selected_cookie_file = _select_cookie_file(task.url, manager.cookies_file)
    effective_url = _normalize_missav_url_by_cookie(task.url, selected_cookie_file)
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
                h = int(height_match.group(1))
                if m_loc == 'audio_only':
                    return 'bestaudio/best'
                elif m_loc == 'video_only':
                    return f'bestvideo[height<=?{h}]/bestvideo/best'
                else:
                    # 改进的格式选择器，使用更简单可靠的语法
                    # bestvideo[height<=X]+bestaudio 会选择最佳视频和音频并合并
                    # 如果失败则回退到 best（最佳单一格式）
                    return f'bestvideo[height<={h}]+bestaudio/best'

        if m_loc == 'audio_only':
            return 'bestaudio/best'
        if m_loc == 'video_only':
            if q_loc == 'best8k': return 'bestvideo[height<=?4320]/bestvideo'
            if q_loc == 'best4k': return 'bestvideo[height<=?2160]/bestvideo'
            if q_loc in ('best','auto'): return 'bestvideo[height<=?1080]/bestvideo'
            if q_loc == '640p': return 'bestvideo[height<=?640]/bestvideo'
            return 'bestvideo[height<=?720]/bestvideo'

        if q_loc == 'best8k': return 'bestvideo[height<=4320]+bestaudio/best'
        if q_loc == 'best4k': return 'bestvideo[height<=2160]+bestaudio/best'
        if q_loc in ('best','auto'): return 'bestvideo[height<=1080]+bestaudio/best'
        if q_loc == 'fast': return 'bestvideo[height<=720]+bestaudio/best'
        if q_loc == '640p': return 'bestvideo[height<=640]+bestaudio/best'
        return 'best'

    format_selector = direct_selector or build_adaptive_selector()
    adaptive_selector = None if direct_selector is None else build_adaptive_selector()

    def build_args(conc: int, chunk: str, use_aria: bool=False, extra_args: Optional[List[str]]=None,
                   force_no_proxy: bool=False,
                   youtube_auth_with_cookies: bool=False,
                   force_browser_cookies: bool=False,
                   youtube_tv_client: bool=False,
                   timeout: int=15, retries: int=20, fragment_retries: int=50, retry_sleep: int=2) -> List[str]:
        fs_str = str(format_selector) if format_selector else 'best'
        a = [str(manager.ytdlp_path), '-f', fs_str,
             '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
             '--socket-timeout', str(timeout), '--retries', str(retries),
             '--fragment-retries', str(fragment_retries), '--retry-sleep', str(retry_sleep),
             '--force-ipv4', '--concurrent-fragments', str(conc), '--http-chunk-size', chunk,
             '--hls-prefer-native', '--no-continue',  # 禁用续传，避免因过期URL导致403
             '-o', out_path_template]
        a = _with_plugin_dir_args(a)

        try:
            import config
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
        except ImportError:
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
        if proxy_url and not force_no_proxy:
            a += ['--proxy', proxy_url]
        elif proxy_url and force_no_proxy:
            task.log.append('[proxy] 代理已禁用（回退直连）')

        if forced_container and mode == 'audio_only':
            a += ['--merge-output-format', forced_container]
        if task.geo_bypass:
            a.append('--geo-bypass')
        if extra_args:
            a += extra_args

        # 详细的 cookies 调试日志
        cookies_path = str(manager.cookies_file)
        cookies_exists = os.path.exists(cookies_path)
        logger.info(f"[COOKIES-DEBUG] cookies_file={cookies_path}, exists={cookies_exists}")
        task.log.append(f"[cookies] 路径: {cookies_path}, 存在: {cookies_exists}")

        # YouTube 特殊处理：
        # 默认使用 android client（通常可绕过 n challenge，且无需 cookies）
        # 若触发“Sign in to confirm you're not a bot”，会在外层切换到 cookies 鉴权重试
        is_youtube = 'youtube.com' in effective_url.lower() or 'youtu.be' in effective_url.lower()
        use_browser_cookies = (
            (os.environ.get('USE_BROWSER_COOKIES') or '').lower() in ('1', 'true', 'yes')
            or (os.environ.get('LUMINA_FORCE_BROWSER_COOKIES') or os.environ.get('UMD_FORCE_BROWSER_COOKIES', '')).lower() in ('1', 'true', 'yes')
        )
        if force_browser_cookies:
            use_browser_cookies = True
        if is_youtube:
            a = _strip_youtube_extractor_args(a)
        if is_youtube and not youtube_auth_with_cookies:
            a += ['--extractor-args', 'youtube:player_client=android']
            task.log.append('[youtube] 使用 android client（下载阶段）')
            logger.info(f"[YOUTUBE] Task {task.id}: 使用 android client，跳过 cookies")
        elif is_youtube:
            task.log.append('[youtube] 切换 cookies 鉴权模式（关闭 android client）')
            logger.info(f"[YOUTUBE] Task {task.id}: 切换 cookies 鉴权模式")
            if youtube_tv_client:
                a += ['--extractor-args', 'youtube:player_client=tv,web']
                task.log.append('[youtube] 使用 tv client（cookies 模式）')
            else:
                a += ['--extractor-args', 'youtube:player_client=web,web_safari']
            if use_browser_cookies:
                browser = _choose_browser_cookie_source(task)
                a += ['--cookies-from-browser', browser]
                task.log.append(f'[cookies] 已添加 --cookies-from-browser {browser}')
            elif cookies_exists:
                a += ['--cookies', cookies_path]
                task.log.append(f"[cookies] 已添加 --cookies 参数")
                logger.info(f"[COOKIES] 已添加到命令: --cookies {cookies_path}")
            else:
                task.log.append(f"[cookies] 警告: cookies.txt 不存在")
                logger.warning(f"[COOKIES] 文件不存在: {cookies_path}")
        else:
            if not selected_cookie_file and _should_try_browser_cookies(effective_url, manager.cookies_file):
                browser = _choose_browser_cookie_source(task)
                a += ['--cookies-from-browser', browser]
                if selected_cookie_file and not _cookiefile_has_site_cookie(selected_cookie_file, effective_url):
                    task.log.append(f'[cookies] cookies.txt 不含 MissAV 站点 cookie，改用浏览器 cookies ({browser})')
                else:
                    task.log.append(f'[cookies] 已添加 --cookies-from-browser {browser}')
            elif selected_cookie_file:
                a += ['--cookies', selected_cookie_file]
                task.log.append(f"[cookies] 已添加 --cookies 参数")
                logger.info(f"[COOKIES] 已添加到命令: --cookies {selected_cookie_file}")
            else:
                if cookies_exists:
                    task.log.append('[cookies] 警告: cookies.txt 存在，但不包含当前站点可用 cookie')
                    logger.warning(f"[COOKIES] 文件存在但不含当前站点 cookie: {cookies_path}")
                else:
                    task.log.append(f"[cookies] 警告: cookies.txt 不存在")
                    logger.warning(f"[COOKIES] 文件不存在: {cookies_path}")

        ffmpeg_path = manager.ffmpeg_locator()
        if ffmpeg_path:
            a += ['--ffmpeg-location', ffmpeg_path]
        if getattr(task, 'write_thumbnail', False):
            a += ['--write-thumbnail', '--convert-thumbnails', 'jpg']

        if use_aria:
            a += ['--downloader', 'http:aria2c', '--downloader', 'https:aria2c',
                  '--downloader-args', 'aria2c:-x16 -s16 -k1M -m16 --retry-wait=2 --summary-interval=1']
        a.append(effective_url)
        return a

    def build_youtube_minimal_args(force_no_proxy: bool=False, use_browser_cookie: bool=False, explicit_format: Optional[str]=None) -> List[str]:
        """Final fallback: keep args minimal and let yt-dlp pick default format."""
        a = [
            str(manager.ytdlp_path),
            '--no-warnings', '--no-check-certificate', '--newline', '--ignore-errors',
            '--socket-timeout', str(to_timeout), '--retries', str(to_retries),
            '-o', out_path_template,
            '--extractor-args', 'youtube:player_client=tv,web'
        ]
        a = _with_plugin_dir_args(a)
        if explicit_format:
            a += ['-f', explicit_format]

        try:
            import config
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
        except ImportError:
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
        if proxy_url and not force_no_proxy:
            a += ['--proxy', proxy_url]

        if task.geo_bypass:
            a.append('--geo-bypass')

        if use_browser_cookie:
            a += ['--cookies-from-browser', _choose_browser_cookie_source(task)]
        elif selected_cookie_file:
            a += ['--cookies', selected_cookie_file]

        ffmpeg_path = manager.ffmpeg_locator()
        if ffmpeg_path:
            a += ['--ffmpeg-location', ffmpeg_path]

        a.append(effective_url)
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
    site_conf = site_configs.get_site_config(effective_url)
    sc_args = site_conf.get_download_args(fast_mode=fast_start)

    init_conc = sc_args.get('concurrency', 4)
    init_chunk = sc_args.get('chunk_size', '4M')

    # 对于 YouTube，使用适中的并发数以平衡速度和稳定性
    is_youtube = 'youtube.com' in effective_url or 'youtu.be' in effective_url
    if is_youtube:
        init_conc = 4  # YouTube 使用4个并发
        init_chunk = '4M'
    elif fast_start and init_conc < 8:
        init_conc = 8
        init_chunk = '8M'

    use_aria_initial = sc_args.get('use_aria2c')
    if use_aria_initial is None:
        use_aria_initial = _should_use_aria2c(manager, effective_url)

    extra_download_args = list(sc_args.get('args', []))
    if sc_args.get('impersonate'):
        extra_download_args += ['--impersonate', sc_args['impersonate']]

    to_timeout = sc_args.get('timeout', 15)
    to_retries = sc_args.get('retries', 20)
    to_frag_retries = sc_args.get('fragment_retries', 50)

    downloader_desc = "aria2c" if use_aria_initial else "内置下载器"
    proxy_failed = False
    youtube_auth_with_cookies = False
    force_browser_cookies = False
    youtube_tv_client = False
    rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=use_aria_initial, extra_args=extra_download_args,
                                     force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                     timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                          f"[speed] 使用{downloader_desc} (并发={init_conc}, 块={init_chunk}, IPv4)")

    stripped_impersonate_args = _strip_impersonate_args(extra_download_args)
    if rc != 0 and len(stripped_impersonate_args) != len(extra_download_args) and _has_impersonate_unavailable(recent):
        task.log.append('[fallback] 当前 yt-dlp 不支持 --impersonate，移除后重试…')
        logger.warning(f"Task {task.id} 当前 yt-dlp 不支持 impersonate，移除参数后重试")
        extra_download_args = stripped_impersonate_args
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=use_aria_initial, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] 移除 impersonate 后重试')

    # 调试：记录首次下载结果
    logger.info(f"Task {task.id} 首次下载结果: rc={rc}, output_lines={len(recent)}")
    if rc != 0:
        task.log.append(f"[debug] 首次下载失败 (exit={rc}), skip_probe={task.skip_probe}")
        if recent:
            task.log.append("[debug] 首次下载最后20行输出:")
            for line in recent[-20:]:
                task.log.append(f"  > {line}")
                logger.error(f"Task {task.id} yt-dlp output: {line}")

    if rc != 0 and _has_proxy_error(recent):
        task.log.append('[net] 检测到代理连接错误，回退直连重试…')
        proxy_failed = True
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] 代理失败后直连重试')

    if rc != 0 and is_youtube and _is_youtube_signin_error(recent):
        youtube_auth_with_cookies = True
        task.log.append('[fallback] YouTube 要求登录验证，切换 cookies 鉴权重试…')
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] YouTube cookies 鉴权重试')

    if rc != 0 and task.skip_probe:
        joined_tail = '\n'.join(recent[-40:]).lower()
        if any(k in joined_tail for k in ['requested format not available','no such format','unable to download video data','404']):
            info = _probe_info(manager, task)
            format_selector = build_adaptive_selector()
            rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                             force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                             timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                                  '[fallback] 补 probe 后重试')

    if rc != 0 and direct_selector is not None and adaptive_selector:
        format_selector = adaptive_selector
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] 自适应格式首次尝试')

    # Format not available fallback - 直接使用 best
    if rc != 0:
        joined_tail = '\n'.join(recent[-40:]).lower()
        if 'requested format is not available' in joined_tail or 'no such format' in joined_tail:
            task.log.append('[fallback] 请求的格式不可用，回退到 best 格式')
            logger.warning(f"Task {task.id} 格式不可用，使用 best 回退")
            format_selector = 'best'
            rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                             force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                             timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                                  '[fallback] 使用 best 格式重试')

    if rc != 0 and is_youtube and youtube_auth_with_cookies and not force_browser_cookies and _is_format_unavailable(recent):
        force_browser_cookies = True
        task.log.append('[fallback] YouTube 格式不可用，尝试浏览器 cookies 重试…')
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] 浏览器 cookies 重试')

    if rc != 0 and is_youtube and force_browser_cookies and _is_browser_cookie_copy_error(recent):
        force_browser_cookies = False
        youtube_tv_client = True
        task.log.append('[fallback] 浏览器 cookies 读取失败，回退 cookies.txt + tv client 重试…')
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] cookies.txt + tv client 重试')

    if rc != 0 and is_youtube and youtube_auth_with_cookies and _is_format_unavailable(recent) and not youtube_tv_client:
        youtube_tv_client = True
        task.log.append('[fallback] YouTube 格式仍不可用，尝试 tv client 重试…')
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] tv client 重试')

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
                                             force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                             timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                                  '[retry] 回退格式重试 (mp4/m4a 优先)')
        except Exception as _fb_e:
            task.log.append(f"[retry] 回退格式构建异常: {_fb_e}")

    # SSL EOF fallback
    if rc != 0 and _has_ssl_eof(recent):
        task.log.append('[net] 检测到 SSLEOF/连接被对端提前关闭，降低并发与增大分块后重试…')
        rc, recent = run_once(build_args(2, '8M', use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout), '[speed] 内置下载器降级重试 (并发=2, 块=8M, IPv4)')

    if rc != 0 and _has_ssl_eof(recent):
        if manager.aria2c_path:
            task.log.append('[net] 仍失败，切换 aria2c 兜底重试…')
            rc, recent = run_once(build_args(2, '8M', use_aria=True, extra_args=extra_download_args,
                                             force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                             timeout=to_timeout), '[speed] 使用 aria2c 兜底 (-x16 -s16 -k1M)')

    if rc != 0 and is_youtube and youtube_auth_with_cookies and _is_format_unavailable(recent) and not youtube_tv_client:
        youtube_tv_client = True
        task.log.append('[fallback] 后期重试后仍格式不可用，切换 tv client 再试一次…')
        rc, recent = run_once(build_args(init_conc, init_chunk, use_aria=False, extra_args=extra_download_args,
                                         force_no_proxy=proxy_failed, youtube_auth_with_cookies=youtube_auth_with_cookies, force_browser_cookies=force_browser_cookies, youtube_tv_client=youtube_tv_client,
                                         timeout=to_timeout, retries=to_retries, fragment_retries=to_frag_retries),
                              '[fallback] tv client 终极重试')

    if rc != 0 and is_youtube and _is_format_unavailable(recent):
        task.log.append('[fallback] YouTube 仍提示格式不可用，尝试最小参数模式重试…')
        rc, recent = run_once(build_youtube_minimal_args(force_no_proxy=proxy_failed, use_browser_cookie=False),
                              '[fallback] YouTube 最小参数重试')

    if rc != 0 and is_youtube and _is_format_unavailable(recent) and not _is_browser_cookie_copy_error(recent):
        task.log.append('[fallback] 最小参数仍失败，尝试最小参数 + 浏览器 cookies…')
        rc, recent = run_once(build_youtube_minimal_args(force_no_proxy=proxy_failed, use_browser_cookie=True),
                              '[fallback] YouTube 最小参数 + 浏览器 cookies')

    if rc != 0 and is_youtube and _is_format_unavailable(recent):
        task.log.append('[fallback] 尝试兼容格式 18/best（360p）…')
        rc, recent = run_once(build_youtube_minimal_args(force_no_proxy=proxy_failed, use_browser_cookie=False, explicit_format='18/best'),
                              '[fallback] YouTube 兼容格式 18/best')

    if rc != 0:
        _check_partial_success(manager, task, base_template)
        # If rc became 0, skip re-raise
        if task.status == 'finished': rc = 0

    if rc != 0:
        # 记录 yt-dlp 输出的最后几行，帮助诊断问题
        if recent:
            task.log.append('[debug] yt-dlp 最后输出:')
            for line in recent[-30:]:
                task.log.append(f'  | {line}')
                logger.error(f"Task {task.id} yt-dlp error output: {line}")

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

def _is_proxy_error_text(text: str) -> bool:
    t = text.lower()
    markers = (
        'proxyerror',
        'proxy error',
        'proxy tunnel',
        'failed to connect to proxy',
        'cannot connect to proxy',
        'connection to proxy failed',
        'proxy authentication required',
        'winerror 10061',
    )
    return any(m in t for m in markers)

def _has_proxy_error(lines: list[str]) -> bool:
    return _is_proxy_error_text('\n'.join(lines))

def _is_format_unavailable(lines: list[str]) -> bool:
    t = '\n'.join(lines).lower()
    return ('requested format is not available' in t) or ('no such format' in t)

def _is_browser_cookie_copy_error(lines: list[str]) -> bool:
    return _is_browser_cookie_copy_error_text('\n'.join(lines))

def _is_youtube_signin_error(lines: list[str]) -> bool:
    t = '\n'.join(lines).lower()
    markers = (
        "sign in to confirm you're not a bot",
        'sign in to confirm youre not a bot',
        'use --cookies-from-browser or --cookies for the authentication',
        'youtube requires account age-verification',
        'this video is age-restricted',
    )
    return any(m in t for m in markers)

def _strip_youtube_extractor_args(args: list[str]) -> list[str]:
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        cur = args[i]
        if cur == '--extractor-args' and i + 1 < len(args):
            nxt = args[i + 1]
            if isinstance(nxt, str) and nxt.startswith('youtube:'):
                i += 2
                continue
        cleaned.append(cur)
        i += 1
    return cleaned

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
    merged_candidate: Optional[str] = None
    component_files: List[str] = []
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
            selected_component = component_files[0]
            task.file_path = selected_component
            task.log.append(f"[detect] 未发现合并文件，组件文件数: {len(component_files)}，暂用: {os.path.basename(selected_component)}")
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
        selected_cookie_file = _select_cookie_file(task.url, manager.cookies_file)
        effective_url = _normalize_missav_url_by_cookie(task.url, selected_cookie_file)
        if not task.file_path or not os.path.exists(task.file_path):
            task.log.append('[audio-fallback] 视频文件丢失，放弃补救')
            return False
        source_video = task.file_path

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
        audio_args = _with_plugin_dir_args(audio_args)

        if not selected_cookie_file and _should_try_browser_cookies(effective_url, manager.cookies_file):
            audio_args += ['--cookies-from-browser', _choose_browser_cookie_source(task)]
        elif selected_cookie_file:
            audio_args += ['--cookies', selected_cookie_file]

        import site_configs
        sc_args = site_configs.get_site_config(effective_url).get_download_args()
        if sc_args.get('impersonate'):
            audio_args += ['--impersonate', sc_args['impersonate']]
        if sc_args.get('args'):
            audio_args += sc_args['args']


        # Proxy
        try:
            import config
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY') or getattr(config, 'PROXY_URL', '')
        except ImportError:
            proxy_url = os.environ.get('LUMINA_PROXY') or os.environ.get('UMD_PROXY', '')
        if proxy_url:
            audio_args += ['--proxy', proxy_url]

        audio_args += ['--ffmpeg-location', ffmpeg_bin]
        audio_args.append(effective_url)

        task.log.append('[audio-fallback] 执行音频补抓: ' + ' '.join(audio_args))
        logger.info(f"Task {task.id} 补抓音频: {' '.join(audio_args)}")

        def _run_audio_once(cur_args: List[str]) -> tuple[int, List[str]]:
            recent_audio: List[str] = []
            manager.procs[task.id] = proc_a = subprocess.Popen(cur_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
                    line = l.rstrip()
                    recent_audio.append(line)
                    if len(recent_audio) > 200:
                        recent_audio = recent_audio[-200:]
                    task.log.append('[A] ' + line)
            proc_a.wait()
            try:
                manager.procs.pop(task.id, None)
            except Exception:
                pass
            return proc_a.returncode, recent_audio

        audio_rc, audio_recent = _run_audio_once(audio_args)
        stripped_audio_args = _strip_impersonate_args(audio_args)
        if audio_rc != 0 and len(stripped_audio_args) != len(audio_args) and _has_impersonate_unavailable(audio_recent):
            task.log.append('[audio-fallback] 当前 yt-dlp 不支持 --impersonate，移除后重试…')
            logger.warning(f"Task {task.id} 音频补抓不支持 impersonate，移除参数后重试")
            audio_args = stripped_audio_args
            audio_rc, audio_recent = _run_audio_once(audio_args)

        if audio_rc != 0:
            task.log.append(f'[audio-fallback] 音频下载失败(exit={audio_rc})')
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
        if os.path.abspath(merged_out) == os.path.abspath(source_video):
            merged_out = source_video + '.mkv'

        merge_cmd = [
            ffmpeg_bin, '-y',
            '-i', source_video,
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
