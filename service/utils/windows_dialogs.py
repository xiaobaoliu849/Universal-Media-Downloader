"""
Windows 原生文件夹选择器模块
使用 Windows 现代 Shell COM 接口 (IFileOpenDialog + FOS_PICKFOLDERS)
彻底杜绝 CMD / PowerShell 黑色控制台弹窗，展现现代 Windows 资源管理器风格的文件夹选择界面。
"""

import os
import sys
import platform
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Windows COM / Win32 常量定义
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1

# Options for IFileDialog::SetOptions
FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_NOCHANGEDIR = 0x00000008
FOS_PATHMUSTEXIST = 0x00000800
FOS_FILEMUSTEXIST = 0x00001000

# SIGDN (Shell Item Get Display Name)
SIGDN_FILESYSPATH = 0x80058000

# HRESULT 用户取消: HRESULT_FROM_WIN32(ERROR_CANCELLED) = 0x800704C7 (-2147023673)
HRESULT_CANCELLED = -2147023673


def _show_com_folder_dialog(initial_dir: Optional[str] = None, title: str = "请选择视频下载保存目录") -> Optional[str]:
    """
    在当前线程（须为 STA 套间）中直接通过 COM 调起 IFileOpenDialog
    纯进程内调用，无任何子进程，零控制台黑框，毫秒级弹出。
    """
    import ctypes
    from ctypes import wintypes, POINTER, c_void_p, c_wchar_p, byref, Structure, WINFUNCTYPE, cast, c_ulong, c_long

    class GUID(Structure):
        _fields_ = [
            ('Data1', wintypes.DWORD),
            ('Data2', wintypes.WORD),
            ('Data3', wintypes.WORD),
            ('Data4', wintypes.BYTE * 8)
        ]

        def __init__(self, l, w1, w2, b1, b2, b3, b4, b5, b6, b7, b8):
            super().__init__()
            self.Data1 = l
            self.Data2 = w1
            self.Data3 = w2
            self.Data4 = (wintypes.BYTE * 8)(b1, b2, b3, b4, b5, b6, b7, b8)

    CLSID_FileOpenDialog = GUID(0xDC1C5A9C, 0xE88A, 0x4DDE, 0xA5, 0xA1, 0x60, 0xF8, 0x2A, 0x20, 0xAE, 0xF7)
    IID_IFileOpenDialog = GUID(0xD57C7288, 0xD4AD, 0x4768, 0xBE, 0x02, 0x9D, 0x96, 0x95, 0x32, 0xD9, 0x60)
    IID_IShellItem = GUID(0x43826D1E, 0xE718, 0x42EE, 0xBC, 0x55, 0xA1, 0xE2, 0x61, 0xC3, 0x7B, 0xFE)

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    user32 = ctypes.windll.user32

    # 初始化 COM 为 STA
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    need_uninit = True
    if hr < 0 and hr != -2147417850:  # RPC_E_CHANGED_MODE = 0x80010106
        # 初始化返回错误且非已有模式
        need_uninit = False
        logger.warning(f"[COM Dialog] CoInitializeEx returned hr={hex(hr & 0xFFFFFFFF)}")

    dialog = c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            byref(CLSID_FileOpenDialog),
            None,
            CLSCTX_INPROC_SERVER,
            byref(IID_IFileOpenDialog),
            byref(dialog)
        )
        if hr != 0 or not dialog.value:
            raise RuntimeError(f"CoCreateInstance(CLSID_FileOpenDialog) failed with hr={hex(hr & 0xFFFFFFFF)}")

        vtbl = cast(dialog, POINTER(POINTER(c_void_p))).contents

        # 映射 IFileDialog / IModalWindow 虚函数表
        Show = WINFUNCTYPE(c_long, c_void_p, wintypes.HWND)(vtbl[3])
        SetOptions = WINFUNCTYPE(c_long, c_void_p, wintypes.DWORD)(vtbl[9])
        GetOptions = WINFUNCTYPE(c_long, c_void_p, POINTER(wintypes.DWORD))(vtbl[10])
        SetFolder = WINFUNCTYPE(c_long, c_void_p, c_void_p)(vtbl[12])
        SetTitle = WINFUNCTYPE(c_long, c_void_p, wintypes.LPCWSTR)(vtbl[17])
        GetResult = WINFUNCTYPE(c_long, c_void_p, POINTER(c_void_p))(vtbl[20])

        # 启用文件夹选择模式以及路径存在校验
        opts = wintypes.DWORD()
        GetOptions(dialog, byref(opts))
        SetOptions(dialog, opts.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST)

        # 设置标题
        if title:
            SetTitle(dialog, title)

        # 设置初始选择目录
        if initial_dir and os.path.exists(initial_dir):
            try:
                norm_init = os.path.normpath(os.path.abspath(initial_dir))
                folder_item = c_void_p()
                SHCreateItemFromParsingName = shell32.SHCreateItemFromParsingName
                SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(GUID), POINTER(c_void_p)]
                SHCreateItemFromParsingName.restype = c_long
                if SHCreateItemFromParsingName(norm_init, None, byref(IID_IShellItem), byref(folder_item)) == 0 and folder_item.value:
                    try:
                        SetFolder(dialog, folder_item)
                    finally:
                        f_vtbl = cast(folder_item, POINTER(POINTER(c_void_p))).contents
                        WINFUNCTYPE(c_ulong, c_void_p)(f_vtbl[2])(folder_item)
            except Exception as set_err:
                logger.debug(f"[COM Dialog] 设定初始目录失败 (忽略): {set_err}")

        # 获取前台窗口句柄，让弹窗聚焦并置于前端
        hwnd_owner = user32.GetForegroundWindow()

        # 显示模态对话框
        show_hr = Show(dialog, hwnd_owner)
        if show_hr == HRESULT_CANCELLED or (show_hr & 0xFFFFFFFF) == 0x800704C7:
            logger.info("[COM Dialog] 用户取消选择文件夹")
            return None
        if show_hr != 0:
            logger.warning(f"[COM Dialog] Show failed with hr={hex(show_hr & 0xFFFFFFFF)}")
            return None

        # 获取选中的 IShellItem
        selected_item = c_void_p()
        if GetResult(dialog, byref(selected_item)) != 0 or not selected_item.value:
            return None

        psz_path = c_wchar_p()
        chosen_path = None
        try:
            sel_vtbl = cast(selected_item, POINTER(POINTER(c_void_p))).contents
            GetDisplayName = WINFUNCTYPE(c_long, c_void_p, wintypes.DWORD, POINTER(c_wchar_p))(sel_vtbl[5])
            path_hr = GetDisplayName(selected_item, SIGDN_FILESYSPATH, byref(psz_path))
            if path_hr == 0 and psz_path.value:
                chosen_path = str(psz_path.value)
        except Exception as parse_err:
            logger.error(f"[COM Dialog] 解析选中结果异常: {parse_err}")
        finally:
            if psz_path and psz_path.value:
                try:
                    ole32.CoTaskMemFree(psz_path)
                except Exception:
                    pass
            try:
                sel_vtbl = cast(selected_item, POINTER(POINTER(c_void_p))).contents
                WINFUNCTYPE(c_ulong, c_void_p)(sel_vtbl[2])(selected_item)
            except Exception:
                pass

        return chosen_path

    finally:
        if dialog and dialog.value:
            try:
                d_vtbl = cast(dialog, POINTER(POINTER(c_void_p))).contents
                WINFUNCTYPE(c_ulong, c_void_p)(d_vtbl[2])(dialog)
            except Exception:
                pass
        if need_uninit:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def _show_powershell_dialog_silent(initial_dir: Optional[str] = None, title: str = "请选择视频下载保存目录") -> Optional[str]:
    """
    兜底方案 1: 带 CREATE_NO_WINDOW 与 SW_HIDE 的 PowerShell 弹窗
    确保绝对不会产生黑框 CMD / PowerShell 窗口！
    """
    import subprocess

    safe_title = (title or "请选择视频下载保存目录").replace("'", "''")
    ps_code = (
        "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;\n"
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;\n"
        f"$dialog.Description = '{safe_title}';\n"
        "$dialog.ShowNewFolderButton = $true;\n"
    )
    if initial_dir and os.path.exists(initial_dir):
        safe_init = os.path.normpath(initial_dir).replace("'", "''")
        ps_code += f"$dialog.SelectedPath = '{safe_init}';\n"
    ps_code += (
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {\n"
        "    [Console]::Out.Write($dialog.SelectedPath)\n"
        "}\n"
    )

    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE

    p = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", ps_code],
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=creationflags,
        startupinfo=startupinfo
    )
    chosen = (p.stdout or '').strip()
    return chosen if chosen else None


def _show_tkinter_dialog_silent(initial_dir: Optional[str] = None, title: str = "请选择视频下载保存目录") -> Optional[str]:
    """
    兜底方案 2: Tkinter askdirectory (若环境已包含)
    """
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        norm_init = os.path.normpath(initial_dir) if (initial_dir and os.path.exists(initial_dir)) else None
        chosen = filedialog.askdirectory(parent=root, initialdir=norm_init, title=title)
        root.destroy()
        return chosen.strip() if (chosen and chosen.strip()) else None
    except Exception as e:
        logger.debug(f"[Tkinter Dialog] Tkinter不可用: {e}")
        return None


def choose_folder_native(initial_dir: Optional[str] = None, title: str = "请选择视频下载保存目录") -> Optional[str]:
    """
    跨层级的无黑框、现代化 Windows 文件夹选择入口
    优先级：
    1. COM IFileOpenDialog (现代 Windows 资源管理器界面，零控制台黑框，速度极快)
    2. PowerShell 脚本调用 (显式配置 CREATE_NO_WINDOW 与 SW_HIDE，杜绝黑框)
    3. Tkinter askdirectory
    """
    if platform.system().lower() != 'windows':
        logger.warning("choose_folder_native 仅支持 Windows 系统")
        return None

    result = [None]
    err_holder = [None]

    # 在独立的 STA 线程中运行 COM 对话框，避免与 Flask 多线程套间上下文冲突
    def _worker():
        try:
            result[0] = _show_com_folder_dialog(initial_dir=initial_dir, title=title)
        except Exception as e:
            err_holder[0] = e

    t = threading.Thread(target=_worker, name="UMD-FolderPicker-Thread")
    t.start()
    t.join(timeout=300)

    if err_holder[0] is not None:
        logger.warning(f"[FolderPicker] 原生 COM 对话框失败 ({err_holder[0]})，尝试无黑框 PowerShell 兜底...")
        try:
            return _show_powershell_dialog_silent(initial_dir=initial_dir, title=title)
        except Exception as ps_err:
            logger.warning(f"[FolderPicker] PowerShell 兜底失败 ({ps_err})，尝试 Tkinter 兜底...")
            return _show_tkinter_dialog_silent(initial_dir=initial_dir, title=title)

    return result[0]
