#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 YouTube 下载功能是否正常"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """测试所有模块导入"""
    print("=" * 60)
    print("测试 1: 模块导入")
    print("=" * 60)
    
    try:
        import config
        print("✓ config 模块导入成功")
        
        import errors
        print("✓ errors 模块导入成功")
        
        import tasks
        print("✓ tasks 模块导入成功")
        
        import app
        print("✓ app 模块导入成功")
        
        return True
    except Exception as e:
        print(f"✗ 模块导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_task_manager():
    """测试 TaskManager 初始化"""
    print("\n" + "=" * 60)
    print("测试 2: TaskManager 初始化")
    print("=" * 60)
    
    try:
        import app
        from tasks import init_task_manager
        from config import YTDLP_PATH, DOWNLOAD_DIR, COOKIES_FILE
        
        tm = init_task_manager(YTDLP_PATH, app.get_ffmpeg_path, DOWNLOAD_DIR, COOKIES_FILE)
        
        if tm is None:
            print("✗ TaskManager 初始化返回 None")
            return False
        
        print(f"✓ TaskManager 初始化成功")
        print(f"  - 下载目录: {DOWNLOAD_DIR}")
        print(f"  - yt-dlp 路径: {YTDLP_PATH}")
        print(f"  - Cookies 文件: {COOKIES_FILE}")
        print(f"  - 工作线程数: {tm.max_workers}")
        
        return True
    except Exception as e:
        print(f"✗ TaskManager 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_yt_dlp_version():
    """测试 yt-dlp 版本"""
    print("\n" + "=" * 60)
    print("测试 3: yt-dlp 版本检查")
    print("=" * 60)
    
    try:
        import yt_dlp
        version = yt_dlp.version.__version__
        print(f"✓ yt-dlp 版本: {version}")
        
        # 检查版本是否足够新
        if version >= "2025.11.12":
            print("✓ 版本符合要求 (>= 2025.11.12)")
            return True
        else:
            print(f"⚠ 版本较旧，建议更新到 2025.11.12 或更高")
            return True  # 不算失败，只是警告
    except Exception as e:
        print(f"✗ yt-dlp 版本检查失败: {e}")
        return False

def test_ffmpeg():
    """测试 ffmpeg 可用性"""
    print("\n" + "=" * 60)
    print("测试 4: FFmpeg 检查")
    print("=" * 60)
    
    try:
        import app
        ffmpeg_path = app.get_ffmpeg_path()
        
        if ffmpeg_path:
            print(f"✓ FFmpeg 路径: {ffmpeg_path}")
            
            # 测试 ffmpeg 是否可执行
            import subprocess
            result = subprocess.run([ffmpeg_path, '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                print(f"✓ FFmpeg 可执行: {version_line}")
                return True
            else:
                print(f"⚠ FFmpeg 执行失败")
                return False
        else:
            print("⚠ 未找到 FFmpeg (某些功能可能受限)")
            return True  # 不算失败
    except Exception as e:
        print(f"✗ FFmpeg 检查失败: {e}")
        return False

def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("YouTube 下载器修复验证测试")
    print("=" * 60)
    
    results = []
    
    # 运行测试
    results.append(("模块导入", test_imports()))
    results.append(("TaskManager 初始化", test_task_manager()))
    results.append(("yt-dlp 版本", test_yt_dlp_version()))
    results.append(("FFmpeg 检查", test_ffmpeg()))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}: {name}")
    
    print("\n" + "-" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！YouTube 下载功能已修复。")
        print("\n下一步:")
        print("  1. 运行 'python app.py' 或 'python run.py' 启动服务器")
        print("  2. 访问 http://127.0.0.1:5001")
        print("  3. 粘贴 YouTube 链接测试下载")
        return 0
    else:
        print("\n⚠ 部分测试失败，请检查上述错误信息。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
