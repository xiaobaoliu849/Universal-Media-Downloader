#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试修复后的X视频下载器
"""
import os
import sys
import subprocess

def test_cookies_file():
    """测试cookies文件是否存在且名称正确"""
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    if os.path.exists(cookies_path):
        print(f"[OK] cookies.txt 文件存在: {cookies_path}")
        # 检查大小
        size = os.path.getsize(cookies_path)
        print(f"   文件大小: {size} 字节")
        return True
    else:
        print(f"[ERROR] cookies.txt 文件不存在: {cookies_path}")
        # 检查是否有其他cookies文件
        for f in os.listdir(os.path.dirname(__file__)):
            if f.startswith("cookies") and f.endswith(".txt"):
                print(f"   发现cookies相关文件: {f}")
        return False

def test_dependencies():
    """测试依赖项是否正常"""
    try:
        import flask
        import requests
        import browser_cookie3
        print("[OK] Python依赖项正常")
    except ImportError as e:
        print(f"[ERROR] Python依赖项问题: {e}")
        return False

    # 检查yt-dlp可执行文件
    ytdlp_path = os.path.join(os.path.dirname(__file__), "yt-dlp.exe")
    if os.path.exists(ytdlp_path):
        print(f"[OK] yt-dlp可执行文件存在: {ytdlp_path}")
    else:
        print(f"[ERROR] yt-dlp可执行文件不存在: {ytdlp_path}")
        return False

    return True

def test_download_dir():
    """测试下载目录"""
    try:
        import config
        print(f"[OK] 配置文件加载成功")
        print(f"   下载目录: {config.DOWNLOAD_DIR}")
        print(f"   日志目录: {config.LOG_DIR}")

        # 检查下载目录是否存在，如果不存在则尝试创建
        if not os.path.exists(config.DOWNLOAD_DIR):
            print(f"   目录不存在，尝试创建: {config.DOWNLOAD_DIR}")
            try:
                os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)
                print("   [OK] 目录创建成功")
            except Exception as e:
                print(f"   [ERROR] 目录创建失败: {e}")
                return False
        else:
            print("   [OK] 下载目录存在")

        # 检查是否有写权限
        test_file = os.path.join(config.DOWNLOAD_DIR, ".test_write_permission")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            print("   [OK] 下载目录有写权限")
        except Exception as e:
            print(f"   [ERROR] 下载目录写权限问题: {e}")
            return False

        return True
    except Exception as e:
        print(f"[ERROR] 配置文件加载失败: {e}")
        return False

def main():
    print("开始测试X视频下载器修复...")
    print("=" * 50)

    all_passed = True

    print("\n1. 测试cookies文件...")
    if not test_cookies_file():
        all_passed = False

    print("\n2. 测试依赖项...")
    if not test_dependencies():
        all_passed = False

    print("\n3. 测试下载目录...")
    if not test_download_dir():
        all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("[OK] 所有测试通过！修复已完成。")
        print("\n下一步: 启动应用并测试视频信息获取功能")
    else:
        print("[ERROR] 有测试失败，需要进一步修复。")

    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)