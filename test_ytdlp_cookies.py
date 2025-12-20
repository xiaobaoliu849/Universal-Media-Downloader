#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试yt-dlp使用cookies文件的脚本
"""
import subprocess
import os
import sys

def test_cookies_file():
    """测试yt-dlp能否使用cookies文件"""
    # 获取项目路径
    project_dir = os.path.dirname(__file__)
    ytdlp_path = os.path.join(project_dir, "yt-dlp.exe")
    cookies_path = os.path.join(project_dir, "cookies.txt")
    
    print(f"yt-dlp路径: {ytdlp_path}")
    print(f"cookies路径: {cookies_path}")
    print(f"yt-dlp存在: {os.path.exists(ytdlp_path)}")
    print(f"cookies存在: {os.path.exists(cookies_path)}")
    
    if not os.path.exists(ytdlp_path):
        print("❌ yt-dlp.exe 不存在")
        return False
        
    if not os.path.exists(cookies_path):
        print("❌ cookies.txt 不存在")
        return False
    
    # 测试使用cookies文件获取信息
    test_url = "https://x.com/elonmusk/status/1858011430879248719"  # 一个公开的推文作为测试
    cmd = [ytdlp_path, '--no-warnings', '--dump-single-json', '--no-check-certificate', '--cookies', cookies_path, test_url]
    
    print(f"\n执行命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)
        print(f"Return code: {result.returncode}")
        if result.returncode == 0:
            print("[OK] Using cookies.txt successfully retrieved video info")
            # Parse partial result
            import json
            try:
                info = json.loads(result.stdout.split('\n')[0])
                print(f"Title: {info.get('title', 'N/A')}")
                print(f"Uploader: {info.get('uploader', 'N/A')}")
            except:
                print("Cannot parse JSON response")
        else:
            print(f"[ERROR] Using cookies.txt failed")
            print(f"stderr: {result.stderr}")

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("[ERROR] Command timeout")
        return False
    except Exception as e:
        print(f"[ERROR] Execution error: {e}")
        return False

def test_without_cookies():
    """测试不使用cookies获取信息"""
    project_dir = os.path.dirname(__file__)
    ytdlp_path = os.path.join(project_dir, "yt-dlp.exe")

    test_url = "https://x.com/elonmusk/status/1858011430879248719"  # 一个公开的推文作为测试
    cmd = [ytdlp_path, '--no-warnings', '--dump-single-json', '--no-check-certificate', test_url]

    print(f"\nCommand without cookies: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=30)
        print(f"Return code: {result.returncode}")
        if result.returncode == 0:
            print("[OK] Can retrieve info without cookies")
        else:
            print(f"[ERROR] Cannot retrieve info without cookies")
            print(f"stderr: {result.stderr}")

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("[ERROR] Command timeout")
        return False
    except Exception as e:
        print(f"[ERROR] Execution error: {e}")
        return False

if __name__ == "__main__":
    print("Testing yt-dlp and cookies file functionality...")
    print("="*50)

    success_with_cookies = test_cookies_file()
    success_without_cookies = test_without_cookies()

    print("\n" + "="*50)
    print("Test Summary:")
    print(f"  With cookies.txt: {'Success' if success_with_cookies else 'Failed'}")
    print(f"  Without cookies: {'Success' if success_without_cookies else 'Failed'}")

    if success_with_cookies:
        print("\n[OK] cookies.txt file works properly")
    elif success_without_cookies:
        print("\n[WARN] cookies.txt file may have issues, but works without cookies")
    else:
        print("\n[ERROR] Both methods failed, may need to update yt-dlp or check network")