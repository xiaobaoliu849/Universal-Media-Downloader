# 🎬 Universal Media Downloader

[![下载最新版本](https://img.shields.io/github/v/release/xiaobaoliu849/Universal-Media-Downloader?label=下载最新版本&color=blue)](https://github.com/xiaobaoliu849/Universal-Media-Downloader/releases/latest)
[![GitHub stars](https://img.shields.io/github/stars/xiaobaoliu849/Universal-Media-Downloader)](https://github.com/xiaobaoliu849/Universal-Media-Downloader/stargazers)
[![License](https://img.shields.io/github/license/xiaobaoliu849/Universal-Media-Downloader)](LICENSE)

一个功能强大的跨平台视频下载工具，具备现代化 Web UI，支持多平台视频一键提取下载。

## ✨ 主要特性
- � **全面支持**：支持 X/Twitter、YouTube、MissAV 等主流平台的解析。
- � **高度解析**：支持 1080p / 4K / 8K / 最佳画质自动嗅探。
- 🎵 **独立音轨与字幕**：支持单独提取音频、下载多语言字幕并自动转换为 SRT。
- ⚡ **高速多线程**：内置 Aria2 与多线程分块下载引擎。
- 🎯 **一键直达**：提供 Windows 可执行打包版本，双击使用，无需配置繁杂的命令行。

## 📥 快速下载

**🚀 一键下载免安装版（推荐）**

[⬇️ 下载 Windows 可执行文件](https://github.com/xiaobaoliu849/Universal-Media-Downloader/releases/latest) - 无需配置 Python 环境，开箱即用！

## �️ 从源码运行

### 前提条件
- Python 3.10+
- FFmpeg (请放置于 `ffmpeg/bin/` 目录下，或配置在系统 PATH 环境变量中)
- [可选] 浏览器导出的 `cookies.txt` (用于下载需要登录或年龄限制的视频)

### 安装与启动
```bash
git clone https://github.com/xiaobaoliu849/Universal-Media-Downloader.git
cd Universal-Media-Downloader
python -m venv venv
.\venv\Scripts\activate  # Windows
pip install -r requirements.txt
python app.py
```
启动成功后，浏览器访问 `http://localhost:5001` 即可使用。

## 🤝 常见问题 & 提示
- **需要登录验证**：若遇到 YouTube 等视频提示“Age-restricted”或者需要登录，请通过浏览器插件导出 `cookies.txt` 并放置在程序根目录。
- **默认下载目录**：一键打包版的下载内容默认保存在您的电脑桌面 `流光视频下载` 文件夹内。
- **网络/代理问题**：如果您的网络需要使用科学上网代理，请在根目录新建 `.env` 文件，输入 `UMD_PROXY=http://127.0.0.1:xxxx`。

## 💝 支持开发

如果这个项目对您有帮助，欢迎打赏支持开发者！

<div align="center">
<img src="donate_qr.png" alt="支付宝/微信打赏" width="300">
<br>
<em>扫码打赏 ❤️</em>
</div>

## ⚖️ 免责声明
本工具仅供学习和个人研究使用，请遵守相关媒体网站的服务条款及版权规定。下载的媒体内容请勿用于任何商业用途！欢迎提交 Issue 和 Pull Request 参与贡献。
