#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试最终配置：代理 + cookies"""

import subprocess
import sys
import os

def test_with_proxy_and_cookies():
    """测试代理 + cookies 组合"""
    print("=" * 60)
    print("测试最终配置：代理 + Cookies")
    print("=" * 60)
    
    proxy = "http://127.0.0.1:33210"
    cookies = "D:\\Projects\\X_video_downloader\\cookies.txt"
    test_url = "https://www.youtube.com/watch?v=jrKTpQ41WSE"
    
    print(f"\n配置:")
    print(f"  代理: {proxy}")
    print(f"  Cookies: {cookies}")
    print(f"  测试视频: {test_url}")
    
    if not os.path.exists(cookies):
        print(f"\n✗ Cookies 文件不存在: {cookies}")
        return False
    
    print(f"\n正在测试（可能需要 10-15 秒）...")
    
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--proxy', proxy,
        '--cookies', cookies,
        '--skip-download',
        '--print', 'title',
        test_url
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=20,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"\n✅ 成功！")
            print(f"视频标题: {result.stdout.strip()}")
            print("\n配置正确，现在可以:")
            print("  1. 停止当前运行的服务器（Ctrl+C）")
            print("  2. 重新启动: python app.py")
            print("  3. 访问: http://127.0.0.1:5001")
            print("  4. 粘贴 YouTube 链接下载")
            return True
        else:
            print(f"\n✗ 失败")
            print(f"错误: {result.stderr[:300]}")
            
            if "Sign in to confirm your age" in result.stderr:
                print("\n可能的原因:")
                print("  1. cookies.txt 已过期")
                print("  2. cookies.txt 格式不正确")
                print("\n解决方案:")
                print("  1. 重新从浏览器导出 cookies.txt")
                print("  2. 确保登录了 YouTube 账号")
            
            return False
    except subprocess.TimeoutExpired:
        print("\n✗ 请求超时")
        return False
    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        return False

if __name__ == "__main__":
    success = test_with_proxy_and_cookies()
    sys.exit(0 if success else 1)
