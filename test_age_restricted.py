#!/usr/bin/env python3
"""
测试年龄限制视频下载
"""

import subprocess
import sys

def test_age_restricted():
    """测试年龄限制视频"""
    
    # 视频 URL
    url = "https://www.youtube.com/watch?v=jrKTpQ41WSE"
    
    print("正在测试年龄限制视频...")
    print(f"URL: {url}")
    
    # 构建测试命令
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--skip-download',
        '--dump-single-json',
        '--no-warnings',
        '--cookies-from-browser', 'chrome',  # 尝试从 Chrome 获取
        '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        url
    ]
    
    print(f"命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print("[OK] 成功获取视频信息！")
            print("Cookies 验证通过，可以下载年龄限制视频")
            return True
        else:
            print(f"[ERROR] 失败: {result.stderr}")
            
            # 检查具体错误
            if 'Sign in to confirm your age' in result.stderr:
                print("\n[AGE] 这个视频需要年龄验证")
                print("请按照 manual_cookies_guide.txt 中的步骤手动导出 cookies")
            elif 'cookies' in result.stderr.lower():
                print("\n[COOKIES] Cookies 问题，需要手动导出")
                print("请按照 manual_cookies_guide.txt 中的步骤操作")
            
            return False
            
    except subprocess.TimeoutExpired:
        print("[ERROR] 超时")
        return False
    except Exception as e:
        print(f"[ERROR] 异常: {e}")
        return False

if __name__ == '__main__':
    test_age_restricted()