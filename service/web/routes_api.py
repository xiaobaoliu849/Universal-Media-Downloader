import os
import logging
import json
import traceback
from flask import Blueprint, request, jsonify, Response
from ..tasks.manager import get_task_manager
from ..utils.common import validate_url, _safe_get_json

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api')

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
    from ..tasks.manager import cancel_task as tm_cancel
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

    from ..tasks.downloader import _probe_info
    from ..tasks.models import Task

    # 临时创建一个 Task 对象用于探测
    temp_task = Task(id='temp-probe', url=url)
    try:
        info = _probe_info(tm, temp_task)
        return jsonify(info)
    except Exception as e:
        logger.error(f"Probe failed: {e}")
        return jsonify({'error': str(e)}), 500

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
    from ..utils.dependencies import get_ytdlp_version
    version = get_ytdlp_version()
    return jsonify({'version': version})

@api_bp.route('/open_download_dir', methods=['POST'])
def open_download_dir():
    import subprocess
    from ..tasks.manager import get_task_manager
    tm = get_task_manager()
    if not tm: return jsonify({'success': False, 'error': 'not initialized'})
    try:
        os.makedirs(tm.download_dir, exist_ok=True)
        os.startfile(tm.download_dir)
        return jsonify({'success': True, 'path': tm.download_dir})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/last_finished_file', methods=['GET'])
def last_finished_file():
    from ..tasks.manager import get_task_manager
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
    from ..tasks.manager import get_task_manager
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
