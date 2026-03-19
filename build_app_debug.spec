# Debug spec variant: console enabled, no UPX/strip to diagnose _ctypes import
import os, sys
block_cipher = None  # debug spec无需依赖主 build 脚本

# Fallback simple dynamic collection (reuse logic inline to keep file independent)
python_dlls = os.path.join(sys.base_prefix, 'DLLs')
_dyn_bins = []
for name in ('_ctypes.pyd','libffi-8.dll','libffi-7.dll','libffi.dll'):
    p = os.path.join(python_dlls, name)
    if os.path.exists(p):
        _dyn_bins.append((p,'.'))

def _add_if_exists(items, src: str, dest: str):
    if os.path.exists(src):
        items.append((src, dest))

def _collect_ffmpeg_runtime():
    items = []
    for src, dest in [
        ('ffmpeg/bin/ffmpeg.exe', 'ffmpeg/bin'),
        ('ffmpeg/bin/ffprobe.exe', 'ffmpeg/bin'),
        ('ffmpeg/bin/avcodec-62.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/avdevice-62.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/avfilter-11.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/avformat-62.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/avutil-60.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/swresample-6.dll', 'ffmpeg/bin'),
        ('ffmpeg/bin/swscale-9.dll', 'ffmpeg/bin'),
        ('ffmpeg/LICENSE.txt', 'ffmpeg'),
    ]:
        _add_if_exists(items, src, dest)
    return items

def _collect_aria2_runtime():
    items = []
    _add_if_exists(items, 'aria2/aria2-1.36.0-win-64bit-build1/aria2c.exe', 'aria2/aria2-1.36.0-win-64bit-build1')
    return items


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_dyn_bins,
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('yt-dlp.exe', '.'),
    ] + _collect_ffmpeg_runtime() + _collect_aria2_runtime(),
    hiddenimports=[
        'flask','flask_cors','werkzeug','jinja2','markupsafe','itsdangerous','click','blinker',
        'tasks','errors'
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter','matplotlib','numpy','pandas','scipy','sklearn','torch','tensorflow','cv2'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='流光下载器_debug',
    debug=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='流光下载器_debug',
)
