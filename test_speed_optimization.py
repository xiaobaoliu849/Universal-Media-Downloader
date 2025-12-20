#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试视频信息获取速度优化效果"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_info_speed():
    """测试信息获取速度"""
    print("=" * 60)
    print("视频信息获取速度测试")
    print("=" * 60)
    
    # 重新加载配置
    import importlib
    import config
    importlib.reload(config)
    
    # 检查快速模式
    fast_mode = os.environ.get('LUMINA_FAST_INFO','').lower() in ('1','true','yes')
    print(f"\n快速模式: {'✓ 已启用' if fast_mode else '✗ 未启用'}")
    print(f"代理配置: {config.PROXY_URL or '未配置'}")
    
    if not fast_mode:
        print("\n⚠️  快速模式未启用")
        print("要启用快速模式，请在 .env 中添加:")
        print("  LUMINA_FAST_INFO=1")
        print("\n继续测试（使用默认模式）...")
    
    # 测试 URL
    test_urls = [
        ("YouTube 公开视频", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
        ("YouTube 年龄限制", "https://www.youtube.com/watch?v=jrKTpQ41WSE"),
    ]
    
    print("\n" + "=" * 60)
    print("开始测试...")
    print("=" * 60)
    
    results = []
    
    for name, url in test_urls:
        print(f"\n测试: {name}")
        print(f"URL: {url}")
        print("正在获取信息...")
        
        start_time = time.time()
        
        # 使用 yt-dlp 命令行测试
        import subprocess
        
        cmd = [
            sys.executable, '-m', 'yt_dlp',
            '--proxy', config.PROXY_URL,
            '--skip-download',
            '--print', 'title',
            '--socket-timeout', '15' if fast_mode else '30',
            '--extractor-retries', '2' if fast_mode else '5',
        ]
        
        if os.path.exists(config.COOKIES_FILE):
            cmd += ['--cookies', config.COOKIES_FILE]
        
        cmd.append(url)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=25 if fast_mode else 60,
                encoding='utf-8',
                errors='ignore'
            )
            
            elapsed = time.time() - start_time
            
            if result.returncode == 0 and result.stdout.strip():
                status = "✓ 成功"
                title = result.stdout.strip()
                print(f"{status} ({elapsed:.1f}秒)")
                print(f"标题: {title}")
            else:
                status = "✗ 失败"
                error = result.stderr[:150] if result.stderr else "未知错误"
                print(f"{status} ({elapsed:.1f}秒)")
                print(f"错误: {error}")
            
            results.append({
                'name': name,
                'status': status,
                'time': elapsed,
                'success': result.returncode == 0
            })
            
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start_time
            print(f"✗ 超时 ({elapsed:.1f}秒)")
            results.append({
                'name': name,
                'status': '✗ 超时',
                'time': elapsed,
                'success': False
            })
        except Exception as e:
            elapsed = time.time() - start_time
            print(f"✗ 异常: {e}")
            results.append({
                'name': name,
                'status': '✗ 异常',
                'time': elapsed,
                'success': False
            })
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    for r in results:
        print(f"{r['status']}: {r['name']} - {r['time']:.1f}秒")
    
    avg_time = sum(r['time'] for r in results) / len(results) if results else 0
    success_rate = sum(1 for r in results if r['success']) / len(results) * 100 if results else 0
    
    print(f"\n平均耗时: {avg_time:.1f}秒")
    print(f"成功率: {success_rate:.0f}%")
    
    if fast_mode:
        print("\n✅ 快速模式已启用")
        if avg_time < 10:
            print("✓ 速度优化效果明显！")
        else:
            print("⚠️  速度仍然较慢，可能是:")
            print("  1. 代理速度慢")
            print("  2. 网络不稳定")
            print("  3. 视频需要更多验证")
    else:
        print("\n💡 建议启用快速模式以提升速度")
        print("在 .env 中添加: LUMINA_FAST_INFO=1")
    
    return success_rate > 50

if __name__ == "__main__":
    try:
        success = test_info_speed()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n测试已取消")
        sys.exit(1)
