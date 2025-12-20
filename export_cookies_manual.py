#!/usr/bin/env python3
"""
手动导出浏览器 Cookies 到 Netscape 格式
支持 Chrome、Edge、Firefox
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

def export_cookies_from_browser():
    """尝试从浏览器导出 cookies"""
    browsers = [
        ('chrome', 'Chrome'),
        ('edge', 'Edge'),
        ('firefox', 'Firefox'),
        ('brave', 'Brave'),
        ('opera', 'Opera')
    ]
    
    for browser_name, browser_desc in browsers:
        try:
            print(f"[INFO] 尝试从 {browser_desc} 导出 cookies...")
            
            # 使用 yt-dlp 的 cookies-from-browser 功能
            cmd = [
                sys.executable, '-m', 'yt_dlp',
                '--cookies-from-browser', browser_name,
                '--no-download',
                '--dump-cookies',
                'https://www.youtube.com/'
            ]
            
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout:
                # 保存 cookies 到文件
                cookies_file = Path(__file__).parent / 'cookies.txt'
                with open(cookies_file, 'w', encoding='utf-8') as f:
                    f.write(result.stdout)
                
                print(f"[OK] 成功从 {browser_desc} 导出 cookies 到 {cookies_file}")
                return str(cookies_file)
            else:
                print(f"[ERROR] 从 {browser_desc} 导出失败: {result.stderr}")
                
        except Exception as e:
            print(f"[ERROR] 从 {browser_desc} 导出异常: {e}")
            continue
    
    print("[ERROR] 无法从任何浏览器导出 cookies")
    return None

if __name__ == '__main__':
    export_cookies_from_browser()