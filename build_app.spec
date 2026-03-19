# -*- mode: python ; coding: utf-8 -*-
import os
import sys

block_cipher = None

"""PyInstaller spec for Universal Media Downloader
清理内容:
1. 移除硬编码绝对 DLL (防止跨机失败)
2. 不再强制打包 cookies.txt (避免泄露个人登录信息)
3. 精简 binaries: 绝大多数 Python 内置 .pyd 会自动收集
4. 增加自定义模块 hiddenimports: tasks, errors
如某些机器打包后启动缺少 OpenSSL (libcrypto/ssl) 可再手动添加 binaries 条目。
"""

# 获取 Python DLLs 目录路径（保留示例，如需手动添加可用）
python_dlls = os.path.join(sys.base_prefix, 'DLLs')

"""动态收集与平台绑定的底层 DLL（例如 _ctypes / libffi），避免写死绝对路径。
若后续运行期仍报告缺少 _ssl / libcrypto，可仿照这里追加。
"""
_dyn_bins = []
_ctypes_pyd = os.path.join(python_dlls, '_ctypes.pyd')
if os.path.exists(_ctypes_pyd):
    _dyn_bins.append((_ctypes_pyd, '.'))
for _ffi_name in ('libffi-8.dll','libffi-7.dll','libffi.dll','ffi.dll'):
    _ffi_path = os.path.join(python_dlls, _ffi_name)
    if os.path.exists(_ffi_path):
        _dyn_bins.append((_ffi_path, '.'))
        break  # 取到一个即可


"""为提高在部分精简 Python 安装 / 系统 PATH 异常情况下的可靠性，这里在动态收集的基础上
追加一次显式 fallback (若路径存在)。这样即使 PyInstaller 自身未能正确跟踪依赖，也能被打进包。
"""
_fallback_bins = []
try:
    # 常规 Windows 安装路径猜测，可按需扩展 / 修改
    _base = sys.base_prefix
    cand = [
        os.path.join(_base, 'DLLs', '_ctypes.pyd'),
        os.path.join(_base, 'DLLs', 'libffi-8.dll'),
        os.path.join(_base, 'DLLs', 'libffi-7.dll'),
        os.path.join(_base, 'DLLs', 'libffi.dll'),
    ]
    for _p in cand:
        if os.path.exists(_p):
            # 避免重复
            if not any(_p == b[0] for b in _dyn_bins):
                _fallback_bins.append((_p, '.'))
except Exception:
    pass

_all_bins = _dyn_bins + _fallback_bins
"""显式再次保证 _ctypes.pyd / libffi 至少被加入一次 (某些环境 PyInstaller 在 bootloader 下解析失败)。"""
try:
    _ctypes_file = os.path.join(sys.base_prefix, 'DLLs', '_ctypes.pyd')
    if os.path.exists(_ctypes_file) and not any(_ctypes_file == b[0] for b in _all_bins):
        _all_bins.append((_ctypes_file, '.'))
    for _ffi_alt in ('libffi-8.dll','libffi-7.dll','libffi.dll'):
        _ffi_file = os.path.join(sys.base_prefix, 'DLLs', _ffi_alt)
        if os.path.exists(_ffi_file) and not any(_ffi_file == b[0] for b in _all_bins):
            _all_bins.append((_ffi_file, '.'))
            break
except Exception:
    pass

def _add_if_exists(items, src: str, dest: str):
    if os.path.exists(src):
        items.append((src, dest))

def _collect_ffmpeg_runtime():
    items = []
    ffmpeg_files = [
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
    ]
    for src, dest in ffmpeg_files:
        _add_if_exists(items, src, dest)
    return items

def _collect_aria2_runtime():
    items = []
    aria2_files = [
        ('aria2/aria2-1.36.0-win-64bit-build1/aria2c.exe', 'aria2/aria2-1.36.0-win-64bit-build1'),
    ]
    for src, dest in aria2_files:
        _add_if_exists(items, src, dest)
    return items

"""构建 datas 列表: 仅打包运行所需资源，避免把开发文档/头文件一并带入发布包。"""
_datas = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('yt-dlp.exe', '.'),
]
_datas.extend(_collect_ffmpeg_runtime())
_datas.extend(_collect_aria2_runtime())
for extra in ('LICENSE','README.md','cookies.example.txt','build_meta.json'):
    if os.path.exists(extra):
        _datas.append((extra, '.'))

# 可选: 打包 certifi 证书 (保证在某些精简系统下 HTTPS 正常)。
# 之前使用 'certifi/cacert.pem' 作为目标路径在部分机器上触发过 COLLECT 阶段的重复复制/文件锁导致 PermissionError。
# 改为仅指定目标目录 'certifi'，让 PyInstaller 使用原文件名，并且提供环境变量 LUMINA_INCLUDE_CERTIFI=0 可禁用。
if os.environ.get('LUMINA_INCLUDE_CERTIFI', '1') == '1':
    try:
        import certifi  # type: ignore
        _datas.append((certifi.where(), 'certifi'))
    except Exception:
        pass

# 精简 hiddenimports，只保留可能被静态分析遗漏的项目自定义模块与扩展
_hidden = [
    'tasks',
    'errors',
    'flask_cors',  # 有时被遗漏
]

# runtime_fix_path.py 可选：若不存在则移除
_runtime_hooks = []
if os.path.exists('runtime_fix_path.py'):
    _runtime_hooks.append('runtime_fix_path.py')

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_all_bins,
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=_runtime_hooks,
    excludes=[
        'tkinter','matplotlib','numpy','PIL','IPython','jupyter','notebook','pandas','scipy','sklearn','tensorflow','torch','cv2','test','tests','unittest','doctest'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 清理 binaries 列表，移除 None 值
a.binaries = [b for b in a.binaries if b is not None]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Universal Media Downloader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # 暂时关闭剥离，便于调试 DLL loading
    upx=True,   # 若出现杀软误报可改为 False
    console=False,  # 设为 False 隐藏控制台窗口（发布版本）
    disable_windowed_traceback=False,
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
    upx=True,
    upx_exclude=['libffi-8.dll','libffi-7.dll','libffi.dll','ffi.dll','_ctypes.pyd'],  # 避免对 ffi / _ctypes 做 UPX 压缩
    name='Universal Media Downloader',
)
