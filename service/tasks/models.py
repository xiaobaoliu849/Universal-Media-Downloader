from dataclasses import dataclass, field, asdict
import time
from typing import Optional, List, Dict, Any

@dataclass
class Task:
    id: str
    url: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = 'queued'  # queued, downloading, merging, finished, error, canceled
    stage: Optional[str] = None
    progress: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: Optional[float] = None # Changed from str to float to match tasks.py
    eta: Optional[str] = None
    
    # 文件路径
    file_path: Optional[str] = None # Renamed from final_path to match tasks.py usage
    temp_dir: Optional[str] = None
    
    # 错误/日志信息
    error_code: Optional[str] = None
    error_message: Optional[str] = None # Added for compatibility
    log: List[str] = field(default_factory=list) # Added log
    
    # 下载配置
    mode: str = 'merged'
    quality: str = 'best'
    video_format: Optional[str] = None
    audio_format: Optional[str] = None
    prefer_container: str = 'mp4' # Added
    filename_template: str = '%(title)s' # Added
    
    # 重试与控制
    retry: int = 3 # Added
    attempts: int = 0 # Added
    geo_bypass: bool = False # Added
    canceled: bool = False # Added
    
    # 字幕
    subtitles_only: bool = False
    subtitles: List[str] = field(default_factory=list)
    auto_subtitles: bool = False # Added
    
    # 资源元数据 (Video Info)
    title: Optional[str] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    width: Optional[int] = None # Renamed from media_width for compatibility
    height: Optional[int] = None # Renamed from media_height for compatibility
    vcodec: Optional[str] = None # Renamed from media_vcodec for compatibility
    acodec: Optional[str] = None # Renamed from media_acodec for compatibility
    filesize: Optional[int] = None # Renamed from file_size (partial match)
    
    # 缩略图嵌入控制
    write_thumbnail: bool = False
    
    # 高级/内部字段
    info_cache: Optional[dict] = None
    skip_probe: bool = False # Added
    meta_mode: Optional[str] = None # Added
    partial_success: bool = False # Added
    warning_message: Optional[str] = None # Added
    
    # 进度平滑/合成相关
    _synthetic_phase: Optional[str] = None
    start_ts: float = field(default_factory=time.time)
    first_progress_ts: Optional[float] = None 

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 截断日志避免过大
        if len(d.get('log', [])) > 200:
            d['log'] = d['log'][-200:]
        return d
