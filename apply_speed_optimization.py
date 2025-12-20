#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用视频信息获取速度优化补丁"""

import os
import sys

def apply_optimization():
    """应用优化补丁"""
    print("=" * 60)
    print("视频信息获取速度优化工具")
    print("=" * 60)
    
    # 读取当前 .env
    env_path = ".env"
    if not os.path.exists(env_path):
        print(f"\n✗ 未找到 {env_path} 文件")
        return False
    
    with open(env_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 检查是否已经有快速模式配置
    has_fast_info = any('LUMINA_FAST_INFO' in line for line in lines)
    
    if has_fast_info:
        print("\n✓ 已经配置了快速模式")
        # 检查是否启用
        for line in lines:
            if 'LUMINA_FAST_INFO' in line and not line.strip().startswith('#'):
                if '=1' in line or '=true' in line.lower():
                    print("✓ 快速模式已启用")
                else:
                    print("⚠ 快速模式已配置但未启用")
                    print("\n要启用快速模式，请修改 .env 文件:")
                    print("  LUMINA_FAST_INFO=1")
        return True
    
    # 添加快速模式配置
    print("\n正在添加快速模式配置...")
    
    # 找到合适的插入位置（在代理配置之后）
    insert_pos = len(lines)
    for i, line in enumerate(lines):
        if 'LUMINA_PROXY' in line:
            # 找到代理配置后的第一个空行或文件末尾
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == '' or j == len(lines) - 1:
                    insert_pos = j + 1
                    break
            break
    
    # 插入快速模式配置
    fast_config = [
        "\n",
        "# 快速信息获取模式（优化视频信息加载速度）\n",
        "LUMINA_FAST_INFO=1\n",
        "\n",
        "# 可选：手动微调参数（不设置则使用快速模式默认值）\n",
        "# INFO_SOCKET_TIMEOUT=15  # 单次请求超时（秒）\n",
        "# INFO_EXTRACTOR_RETRIES=2  # 提取器重试次数\n",
        "# INFO_MAX_STAGES=2  # 最大尝试阶段数\n",
    ]
    
    lines[insert_pos:insert_pos] = fast_config
    
    # 写回文件
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print("✓ 快速模式配置已添加到 .env 文件")
    print("\n配置内容:")
    print("  LUMINA_FAST_INFO=1")
    print("\n预期效果:")
    print("  - 视频信息获取时间: 2-5 秒（原来 5-30 秒）")
    print("  - 失败情况返回时间: 5-10 秒（原来 30-180 秒）")
    
    return True

def show_current_config():
    """显示当前配置"""
    print("\n" + "=" * 60)
    print("当前 .env 配置")
    print("=" * 60)
    
    env_path = ".env"
    if not os.path.exists(env_path):
        print(f"\n✗ 未找到 {env_path} 文件")
        return
    
    with open(env_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(content)

def main():
    print("\n🚀 视频信息获取速度优化\n")
    
    # 应用优化
    success = apply_optimization()
    
    if success:
        print("\n" + "=" * 60)
        print("✅ 优化完成！")
        print("=" * 60)
        print("\n下一步:")
        print("  1. 重启应用: python app.py")
        print("  2. 测试速度: 粘贴 YouTube 链接")
        print("\n如果遇到问题:")
        print("  - 查看 '优化视频信息获取速度.md' 了解详情")
        print("  - 如果经常失败，可以关闭快速模式:")
        print("    在 .env 中设置 LUMINA_FAST_INFO=0")
        
        # 显示当前配置
        show_current_config()
        
        return 0
    else:
        print("\n⚠️ 优化失败，请手动检查配置")
        return 1

if __name__ == "__main__":
    sys.exit(main())
