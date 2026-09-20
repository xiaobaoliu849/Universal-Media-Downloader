import os
import logging
import json
import traceback
import urllib.parse
from flask import Blueprint, request, jsonify, Response
from service.tasks.manager import get_task_manager
from service.utils.common import validate_url, _safe_get_json
from service.utils.cache import LRUCache, _get_inflight, _create_inflight, _publish_and_cleanup_inflight, _force_cleanup_inflight

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')

# 全局 LRU 缓存实例：缓存容量为 100，生存周期 10 分钟 (600秒)
info_lru_cache = LRUCache(max_size=100, ttl=600)


def _is_storyboard_format(fmt: dict) -> bool:
    format_id = str(fmt.get('format_id') or '').lower()
    ext = str(fmt.get('ext') or '').lower()
    protocol = str(fmt.get('protocol') or '').lower()
    format_note = str(fmt.get('format_note') or '').lower()
    vcodec = str(fmt.get('vcodec') or '').lower()
    return (
        format_id.startswith('sb')
        or ext == 'mhtml'
        or protocol == 'mhtml'
        or 'storyboard' in format_note
        or vcodec == 'images'
    )


def _is_playable_video_format(fmt: dict) -> bool:
    if _is_storyboard_format(fmt):
        return False
    vcodec = str(fmt.get('vcodec') or '').lower()
    return bool(vcodec and vcodec != 'none')


def _video_format_score(fmt: dict) -> tuple:
    """Prefer higher-bitrate video-only streams for per-height pairing."""
    acodec = fmt.get('acodec')
    protocol = (fmt.get('protocol') or '').lower()
    ext = (fmt.get('ext') or '').lower()
    dynamic_range = (fmt.get('dynamic_range') or '').lower()
    return (
        1 if acodec == 'none' else 0,
        1 if protocol in ('https', 'http', 'dash', 'http_dash_segments') else 0,
        1 if dynamic_range not in ('hdr', 'dv') else 0,
        1 if ext == 'mp4' else 0,
        float(fmt.get('tbr') or fmt.get('vbr') or 0),
        int(fmt.get('fps') or 0),
    )


def _open_path_in_file_manager(path: str) -> None:
    startfile = getattr(os, 'startfile', None)
    if callable(startfile):
        startfile(path)
        return
    raise RuntimeError('open_download_dir is only supported on Windows')

@api_bp.route('/tasks', methods=['GET'])
def list_tasks():
    tm = get_task_manager()
    if not tm:
        return jsonify([])
    return jsonify(tm.list_tasks())

@api_bp.route('/tasks', methods=['POST'])
def add_task():
    tm = get_task_manager()
    if not tm:
        return jsonify({'error': 'Task manager not initialized'}), 500

    data = _safe_get_json(request)
    url = data.get('url')
    if not url or not validate_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    task = tm.add_task(**data)
    return jsonify(task.to_dict())

@api_bp.route('/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task_route(task_id):
    from service.tasks.manager import cancel_task as tm_cancel
    if tm_cancel(task_id):
        return jsonify({'message': 'Task canceled'})
    return jsonify({'error': 'Task not found or already finished'}), 404

@api_bp.route('/tasks/cleanup', methods=['POST'])
def cleanup_tasks():
    tm = get_task_manager()
    if not tm:
        return jsonify({'error': 'Task manager not initialized'}), 500
    count = tm.cleanup_finished_tasks()
    return jsonify({'message': f'Cleaned up {count} tasks'})

def _is_wechat_channels(url: str) -> bool:
    lower_url = (url or '').lower()
    return 'findermp.video.qq.com' in lower_url or 'decodekey=' in lower_url or 'decode_key=' in lower_url

@api_bp.route('/info', methods=['POST'])
def api_info():
    """获取视频详细信息 (用于前端解析格式)"""
    tm = get_task_manager()
    if not tm:
        return jsonify({'error': 'Task manager not initialized'}), 500

    data = _safe_get_json(request)
    url = data.get('url')
    if not url or not validate_url(url):
        return jsonify({'error': 'Invalid URL'}), 400

    if _is_wechat_channels(url):
        info = {
            'title': '微信视频号加密视频 (WeChat Channel Video)',
            'extractor': 'wechat_channels',
            'extractor_key': 'WechatChannels',
            'webpage_url': url,
            'formats': [
                {
                    'format_id': 'best',
                    'height': 1080,
                    'ext': 'mp4',
                    'vcodec': 'h264',
                    'acodec': 'aac',
                }
            ],
            'quality_pairs': {
                '1080': {
                    'video': 'best',
                    'audio': 'best'
                }
            },
            'max_height': 1080
        }
        return jsonify(info)


    # 1. 优先从 LRU 缓存获取已探测的视频信息
    cached_info = info_lru_cache.get(url)
    if cached_info:
        logger.info(f"[API_INFO] 命中 LRU 缓存: {url}")
        return jsonify(cached_info)

    # 2. 尝试从 In-flight 队列中获取正在并发探测的相同请求，合并请求
    inf = _get_inflight(url)
    if inf:
        logger.info(f"[API_INFO] 命中 In-flight 合并并发探测请求: {url}")
        inf.waiters += 1
        
        # 探测超时时间，根据 URL 选择
        from service.tasks.downloader import PROBE_TIMEOUT_DEFAULT, PROBE_TIMEOUT_TWITTER, PROBE_TIMEOUT_MISSAV
        lower_url = url.lower()
        is_missav = 'missav' in lower_url
        is_twitter = 'twitter.com' in lower_url or 'x.com' in lower_url
        timeout = PROBE_TIMEOUT_TWITTER if is_twitter else (PROBE_TIMEOUT_MISSAV if is_missav else PROBE_TIMEOUT_DEFAULT)
        
        # 阻塞等待前一个探测任务完成
        finished = inf.event.wait(timeout=timeout)
        if not finished:
            return jsonify({'error': 'Probe request timed out due to concurrent wait'}), 504
        if inf.error:
            return jsonify(inf.error), 500
        if inf.result:
            return jsonify(inf.result)
        return jsonify({'error': 'Concurrent request failed without details'}), 500

    # 3. 未命中缓存且无并发请求，创建新的 In-flight 探测任务
    inf = _create_inflight(url)
    from service.tasks.downloader import _probe_info
    from service.tasks.models import Task

    # 临时创建一个 Task 对象用于探测
    temp_task = Task(id='temp-probe', url=url)
    try:
        info = _probe_info(tm, temp_task)
        
        # 生成 quality_pairs 用于前端显示
        quality_pairs = {}
        if 'formats' in info and isinstance(info['formats'], list):
            # 收集视频和音频格式
            video_formats = {}  # height -> best format dict
            audio_formats = []  # 音频格式列表
            all_heights = []
            
            for fmt in info['formats']:
                # 视频格式
                if _is_playable_video_format(fmt):
                    height = fmt.get('height')
                    if height and isinstance(height, int) and height > 0:
                        all_heights.append(height)
                        best_existing = video_formats.get(height)
                        if best_existing is None or _video_format_score(fmt) > _video_format_score(best_existing):
                            video_formats[height] = fmt
                
                # 音频格式
                if fmt.get('acodec') and fmt.get('acodec') != 'none' and not _is_playable_video_format(fmt):
                    audio_formats.append(fmt)
            
            # 选择最佳音频格式
            best_audio = None
            if audio_formats:
                # 按 abr (audio bitrate) 排序，选择最高的
                audio_formats.sort(key=lambda f: f.get('abr', 0) or 0, reverse=True)
                best_audio = audio_formats[0]['format_id']
            
            # 生成 quality_pairs
            for height, video_fmt in video_formats.items():
                if best_audio:
                    quality_pairs[str(height)] = {
                        'video': video_fmt['format_id'],
                        'audio': best_audio
                    }
            if all_heights:
                info['max_height'] = max(all_heights)
                if info['max_height'] <= 360 and ('youtube.com' in url or 'youtu.be' in url):
                    info['quality_warning'] = 'YouTube 当前只返回到 360p；这通常不是界面限制，而是账号 cookies、IP 或 PO Token 限制导致。'
            logger.info(f"[API_INFO] playable_heights={sorted(set(all_heights), reverse=True)} quality_pairs={sorted(quality_pairs.keys(), key=int, reverse=True) if quality_pairs else []}")
        
        info['quality_pairs'] = quality_pairs
        
        # 缓存探测结果，并更新并发请求的状态，最后发布广播并自动清理
        info_lru_cache.set(url, info)
        inf.result = info
        _publish_and_cleanup_inflight(url, inf)
        return jsonify(info)
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Probe failed: {e}")
        
        # 并发请求的异常结果同样进行广播并自动清理
        err_payload = {'error': str(e)}
        inf.error = err_payload
        _publish_and_cleanup_inflight(url, inf)
        return jsonify(err_payload), 500

@api_bp.route('/stream_task')
def stream_task():
    """SSE 增量推送任务状态与日志 - 同时支持通过 URL 参数创建任务"""
    tm = get_task_manager()
    if not tm:
        return "Task manager not initialized", 500

    # 从 URL 参数解析任务配置
    url = request.args.get('url')
    if not url or not validate_url(url):
        def error_stream():
            yield f"data: {json.dumps({'error': 'Invalid URL'})}\n\n"
        return Response(error_stream(), mimetype="text/event-stream")

    # 解析任务参数
    mode = request.args.get('mode', 'merged')
    quality = request.args.get('quality', 'best')
    meta_mode = request.args.get('meta', None)
    skip_probe = request.args.get('skip_probe', '0') == '1'
    write_thumbnail = request.args.get('write_thumbnail', '0') == '1'
    video_format = request.args.get('video_format')
    audio_format = request.args.get('audio_format')
    geo_bypass = request.args.get('geo_bypass', '0') == '1'

    # 解析 info_cache
    info_cache = None
    info_cache_raw = request.args.get('info_cache')
    if info_cache_raw:
        try:
            import urllib.parse
            info_cache = json.loads(urllib.parse.unquote(info_cache_raw))
        except Exception:
            pass

    # 解析字幕参数
    subtitles_only = request.args.get('subtitles_only', '0') == '1'
    subtitles = []
    sub_langs = request.args.get('sub_langs')
    if sub_langs:
        subtitles = [s.strip() for s in sub_langs.split(',') if s.strip()]
    auto_subtitles = request.args.get('auto_subtitles', '0') == '1'

    # 构建任务参数
    task_kwargs = {
        'url': url,
        'mode': mode,
        'quality': quality,
        'skip_probe': skip_probe,
        'write_thumbnail': write_thumbnail,
        'geo_bypass': geo_bypass,
        'subtitles_only': subtitles_only,
        'subtitles': subtitles,
        'auto_subtitles': auto_subtitles,
    }
    if video_format:
        task_kwargs['video_format'] = video_format
    if audio_format:
        task_kwargs['audio_format'] = audio_format
    if info_cache:
        task_kwargs['info_cache'] = info_cache
    if meta_mode is not None:
        task_kwargs['meta_mode'] = 'off' if meta_mode == '0' else meta_mode

    # 创建任务
    task = tm.add_task(**task_kwargs)
    task_id = task.id
    logger.info(f"[SSE] 创建任务 {task_id} for {url}")

    def event_stream():
        import time
        last_log_idx = 0
        yield f"data: {json.dumps({'task_id': task_id, 'type': 'init'})}\n\n"

        while True:
            t = tm.get_task(task_id)
            if not t:
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                break

            # 发送新日志
            if len(t.log) > last_log_idx:
                for line in t.log[last_log_idx:]:
                    yield f"data: {json.dumps({'type': 'log', 'line': line})}\n\n"
                last_log_idx = len(t.log)

            # 发送状态更新
            status_data = {
                'type': 'status',
                'status': t.status,
                'stage': t.stage,
                'progress': t.progress,
                'title': t.title,
                'file_path': t.file_path,
                'error_message': t.error_message,
            }
            yield f"data: {json.dumps(status_data)}\n\n"

            # 终止条件
            if t.status in ('finished', 'error', 'canceled'):
                break

            time.sleep(0.5)

    return Response(event_stream(), mimetype="text/event-stream")

@api_bp.route('/diag/ytdlp_version')
def ytdlp_version():
    from service.utils.dependencies import get_ytdlp_version
    version = get_ytdlp_version()
    return jsonify({'version': version})

@api_bp.route('/open_download_dir', methods=['POST'])
def open_download_dir():
    from service.tasks.manager import get_task_manager
    tm = get_task_manager()
    if not tm: return jsonify({'success': False, 'error': 'not initialized'})
    try:
        os.makedirs(tm.download_dir, exist_ok=True)
        _open_path_in_file_manager(tm.download_dir)
        return jsonify({'success': True, 'path': tm.download_dir})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/last_finished_file', methods=['GET'])
def last_finished_file():
    from service.tasks.manager import get_task_manager
    tm = get_task_manager()
    if not tm: return jsonify({'found': False, 'error': 'not initialized'})
    
    # Search backwards through tasks by updated_at
    sorted_tasks = sorted(tm.tasks.values(), key=lambda t: t.updated_at, reverse=True)
    for task in sorted_tasks:
        if task.status == 'finished' and task.file_path and os.path.exists(task.file_path):
            return jsonify({'found': True, 'file': task.file_path})
            
    return jsonify({'found': False})

@api_bp.route('/reveal_file', methods=['POST'])
def reveal_file():
    data = _safe_get_json(request)
    name = data.get('name')
    if not name: return jsonify({'success': False, 'error': 'no name'})
    
    import subprocess
    from service.tasks.manager import get_task_manager
    tm = get_task_manager()
    if not tm: return jsonify({'success': False, 'error': 'not initialized'})
    
    target_path = os.path.join(tm.download_dir, name)
    if os.path.exists(target_path):
        import shlex
        try:
            subprocess.run(f'explorer /select,"{target_path}"', shell=True)
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})
    return jsonify({'success': False, 'error': 'file not found'})

@api_bp.route('/ytdlp/version', methods=['GET'])
def api_ytdlp_version():
    """获取当前 yt-dlp 内核版本"""
    from service.utils.dependencies import get_ytdlp_version
    ver = get_ytdlp_version()
    return jsonify({
        'version': ver,
        'success': bool(ver)
    })

@api_bp.route('/ytdlp/update', methods=['POST'])
def api_ytdlp_update():
    """触发 yt-dlp 内核更新到最新稳定版"""
    from service.utils.dependencies import update_ytdlp
    result = update_ytdlp()
    status_code = 200 if result.get('success') else 400
    return jsonify(result), status_code

