#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试yt-dlp使用cookies文件的脚本 - 使用已知包含视频的链接
"""
import subprocess
import os
import sys
import json

def test_cookies_with_video_tweet():
    """测试yt-dlp与cookies获取包含视频的推文信息"""
    project_dir = os.path.dirname(__file__)
    ytdlp_path = os.path.join(project_dir, "yt-dlp.exe")
    cookies_path = os.path.join(project_dir, "cookies.txt")
    
    print(f"yt-dlp路径: {ytdlp_path}")
    print(f"cookies路径: {cookies_path}")
    print(f"yt-dlp存在: {os.path.exists(ytdlp_path)}")
    print(f"cookies存在: {os.path.exists(cookies_path)}")
    
    if not os.path.exists(ytdlp_path):
        print("[ERROR] yt-dlp.exe 不存在")
        return False
        
    if not os.path.exists(cookies_path):
        print("[ERROR] cookies.txt 不存在")
        return False
    
    # 使用一个已知包含视频的推文链接
    test_url = "https://x.com/elonmusk/status/1788579843751260202"  # 这是一个已知包含视频的推文
    print(f"\n测试URL: {test_url}")
    
    # 首先尝试使用cookies文件
    print("\n--- 测试使用cookies文件 ---")
    cmd_with_cookies = [ytdlp_path, '--no-warnings', '--dump-single-json', '--no-check-certificate', '--cookies', cookies_path, test_url]
    
    print(f"命令: {' '.join(cmd_with_cookies)}")
    
    try:
        result = subprocess.run(cmd_with_cookies, capture_output=True, text=True, encoding='utf-8', timeout=40)
        print(f"返回码: {result.returncode}")
        if result.returncode == 0:
            print("[OK] 使用cookies.txt成功")
            try:
                info = json.loads(result.stdout.split('\n')[0])
                print(f"标题: {info.get('title', 'N/A')}")
                print(f"上传者: {info.get('uploader', 'N/A')}")
                print(f"可用格式数: {len(info.get('formats', []))}")
            except:
                print("无法解析JSON响应")
            return True
        else:
            print(f"[ERROR] 使用cookies.txt失败")
            print(f"错误信息: {result.stderr}")
            
            # 检查是否是cookies数据库锁定问题
            if 'Could not copy Chrome cookie database' in result.stderr:
                print("[HINT] 这是Chrome cookies数据库锁定问题，浏览器可能正在运行")
            elif 'You must provide authentication cookies' in result.stderr:
                print("[HINT] 这可能需要有效的认证cookies")
            
    except subprocess.TimeoutExpired:
        print("[ERROR] 命令超时")
    except Exception as e:
        print(f"[ERROR] 执行出错: {e}")
    
    # 尝试不使用cookies
    print("\n--- 测试不使用cookies ---")
    cmd_without_cookies = [ytdlp_path, '--no-warnings', '--dump-single-json', '--no-check-certificate', test_url]
    
    print(f"命令: {' '.join(cmd_without_cookies)}")
    
    try:
        result = subprocess.run(cmd_without_cookies, capture_output=True, text=True, encoding='utf-8', timeout=40)
        print(f"返回码: {result.returncode}")
        if result.returncode == 0:
            print("[OK] 不使用cookies也能成功")
            try:
                info = json.loads(result.stdout.split('\n')[0])
                print(f"标题: {info.get('title', 'N/A')}")
                print(f"上传者: {info.get('uploader', 'N/A')}")
                print(f"可用格式数: {len(info.get('formats', []))}")
            except:
                print("无法解析JSON响应")
            return True
        else:
            print(f"[ERROR] 不使用cookies失败")
            print(f"错误信息: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        print("[ERROR] 命令超时")
    except Exception as e:
        print(f"[ERROR] 执行出错: {e}")
    
    return False

def validate_cookies_format():
    """验证cookies.txt格式是否正确"""
    cookies_path = os.path.join(os.path.dirname(__file__), "cookies.txt")
    
    print(f"\n--- 验证cookies.txt格式 ---")
    if not os.path.exists(cookies_path):
        print("[ERROR] cookies.txt 不存在")
        return False
        
    try:
        with open(cookies_path, 'r', encoding='utf-8') as f:
            content = f.read(1000)  # 读取前1000个字符
            print(f"文件前缀: {content[:200]}...")
            
        # 检查是否是 Netscape cookie 格式
        lines = content.split('\n')[:10]  # 检查前10行
        valid_format = True
        for i, line in enumerate(lines):
            if line.strip() and not line.startswith('#'):
                parts = line.split('\t')
                if len(parts) < 7:  # Netscape cookie 格式应至少有7个字段
                    print(f"[WARN] 第{i+1}行格式可能不正确: {line[:50]}...")
                    valid_format = False
                    break
                    
        if valid_format:
            print("[OK] cookies.txt 格式看起来是正确的 Netscape 格式")
        else:
            print("[ERROR] cookies.txt 格式可能有问题")
            
        return valid_format
    except Exception as e:
        print(f"[ERROR] 读取cookies.txt失败: {e}")
        return False

if __name__ == "__main__":
    print("测试yt-dlp cookies功能...")
    print("="*60)
    
    # 首先验证cookies格式
    format_valid = validate_cookies_format()
    
    # 然后测试功能
    success = test_cookies_with_video_tweet()
    
    print("\n" + "="*60)
    print("最终结果:")
    if format_valid and success:
        print("[OK] Cookies格式正确且功能正常")
    elif format_valid:
        print("[WARN] Cookies格式正确但功能可能受限（可能需要更新的认证信息）")
    else:
        print("[ERROR] Cookies格式有问题，需要重新导出")