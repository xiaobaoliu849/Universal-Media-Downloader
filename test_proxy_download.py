#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试代理配置后的完整下载流程"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_full_download():
    """测试完整的下载流程"""
    print("=" * 60)
    print("测试代理配置后的下载功能")
    print("=" * 60)
    
    # 重新加载环境变量
    import importlib
    import config
    importlib.reload(config)
    
    print(f"\n✓ 代理配置: {config.PROXY_URL or '未配置'}")
    
    if not config.PROXY_URL:
        print("\n⚠️  警告: 未检测到代理配置")
        print("请确保 .env 文件中有: LUMINA_PROXY=http://127.0.0.1:33210")
        return False
    
    # 测试 yt-dlp 能否通过代理访问
    print("\n测试 YouTube 访问...")
    import subprocess
    
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--proxy', config.PROXY_URL,
        '--skip-download',
        '--print', 'title',
        'https://www.youtube.com/watch?v=jrKTpQ41WSE'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, encoding='utf-8', errors='ignore')
        if result.returncode == 0 and result.stdout.strip():
            print(f"✓ 成功获取视频: {result.stdout.strip()}")
            print("\n✅ 代理配置正确，YouTube 访问正常")
            print("\n现在可以:")
            print("  1. 重启应用: python app.py")
            print("  2. 访问: http://127.0.0.1:5001")
            print("  3. 粘贴 YouTube 链接开始下载")
            return True
        else:
            print(f"✗ 访问失败: {result.stderr[:200]}")
            return False
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False

if __name__ == "__main__":
    success = test_full_download()
    sys.exit(0 if success else 1)
