#!/usr/bin/env python3
"""
使用 yt-dlp 导出浏览器 Cookies
"""

import os
import sys
import subprocess
from pathlib import Path

def export_cookies():
    """使用 yt-dlp 从浏览器导出 cookies"""
    browsers = [
        ('chrome', 'Chrome'),
        ('edge', 'Edge'),
        ('firefox', 'Firefox')
    ]
    
    for browser_name, browser_desc in browsers:
        try:
            print(f"[INFO] 尝试从 {browser_desc} 导出 cookies...")
            
            # 构建 cookies 文件路径
            cookies_file = Path(__file__).parent / 'cookies.txt'
            
            # 使用 yt-dlp 导出 cookies
            cmd = [
                sys.executable, '-m', 'yt_dlp',
                '--cookies-from-browser', browser_name,
                '--no-download',
                'https://www.youtube.com/'
            ]
            
            # 运行命令导出 cookies
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                print(f"[OK] 成功从 {browser_desc} 导出 cookies")
                return True
            else:
                print(f"[ERROR] 从 {browser_desc} 导出失败: {result.stderr}")
                
        except Exception as e:
            print(f"[ERROR] 从 {browser_desc} 导出异常: {e}")
            continue
    
    print("[ERROR] 无法从任何浏览器导出 cookies")
    return False

if __name__ == '__main__':
    export_cookies()