#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试网络连接和 YouTube 访问"""

import subprocess
import sys
import time

def test_youtube_access():
    """测试是否能访问 YouTube"""
    print("=" * 60)
    print("测试 YouTube 网络连接")
    print("=" * 60)
    
    # 测试 1: 简单的 ping 测试（可能被墙）
    print("\n1. 测试 DNS 解析...")
    try:
        import socket
        ip = socket.gethostbyname('www.youtube.com')
        print(f"   ✓ YouTube DNS 解析成功: {ip}")
    except Exception as e:
        print(f"   ✗ YouTube DNS 解析失败: {e}")
        print("   → 可能需要配置 DNS 或使用代理")
    
    # 测试 2: 使用 yt-dlp 测试（最准确）
    print("\n2. 测试 yt-dlp 访问 YouTube...")
    print("   尝试获取视频标题（15秒超时）...")
    
    cmd = [
        sys.executable, '-m', 'yt_dlp',
        '--skip-download',
        '--print', 'title',
        '--socket-timeout', '10',
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode == 0 and result.stdout.strip():
            print(f"   ✓ 成功获取视频: {result.stdout.strip()}")
            print("\n✅ YouTube 访问正常，无需代理")
            return True
        else:
            print(f"   ✗ 访问失败")
            if result.stderr:
                print(f"   错误: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print("   ✗ 请求超时（15秒）")
    except Exception as e:
        print(f"   ✗ 测试失败: {e}")
    
    print("\n❌ YouTube 访问受阻")
    print("\n可能的原因:")
    print("  1. 网络防火墙阻止访问")
    print("  2. 需要配置代理（VPN/梯子）")
    print("  3. DNS 污染")
    
    print("\n解决方案:")
    print("  1. 如果你有代理，编辑 .env 文件添加:")
    print("     LUMINA_PROXY=http://127.0.0.1:7890")
    print("     （将端口改为你的代理端口）")
    print("\n  2. 或者使用系统代理，然后重启应用")
    print("\n  3. 测试代理是否工作:")
    print("     python -m yt_dlp --proxy http://127.0.0.1:7890 --print title \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"")
    
    return False

def test_with_proxy():
    """测试常见代理端口"""
    print("\n" + "=" * 60)
    print("测试常见代理端口")
    print("=" * 60)
    
    common_ports = [7890, 7891, 1080, 10808, 10809]
    
    for port in common_ports:
        print(f"\n测试代理端口 {port}...")
        cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--proxy', f'http://127.0.0.1:{port}',
            '--skip-download',
            '--print', 'title',
            '--socket-timeout', '5',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                encoding='utf-8',
                errors='ignore'
            )
            
            if result.returncode == 0 and result.stdout.strip():
                print(f"   ✓ 端口 {port} 可用！")
                print(f"   视频标题: {result.stdout.strip()}")
                print(f"\n✅ 找到可用代理！请在 .env 中添加:")
                print(f"   LUMINA_PROXY=http://127.0.0.1:{port}")
                return port
            else:
                print(f"   ✗ 端口 {port} 不可用")
        except subprocess.TimeoutExpired:
            print(f"   ✗ 端口 {port} 超时")
        except Exception as e:
            print(f"   ✗ 端口 {port} 错误: {e}")
    
    print("\n❌ 未找到可用的代理端口")
    return None

if __name__ == "__main__":
    print("\n🔍 YouTube 下载器网络诊断工具\n")
    
    # 先测试直连
    if test_youtube_access():
        print("\n✅ 网络正常，可以直接使用")
        sys.exit(0)
    
    # 如果直连失败，测试代理
    print("\n" + "-" * 60)
    input("按 Enter 键测试常见代理端口（或 Ctrl+C 退出）...")
    
    proxy_port = test_with_proxy()
    
    if proxy_port:
        sys.exit(0)
    else:
        print("\n⚠️  请手动配置代理后重试")
        sys.exit(1)
