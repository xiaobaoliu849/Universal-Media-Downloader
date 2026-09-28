# 🎬 Universal Media Downloader

[![下载最新版本](https://img.shields.io/github/v/release/xiaobaoliu849/Universal-Media-Downloader?label=下载最新版本&color=blue)](https://github.com/xiaobaoliu849/Universal-Media-Downloader/releases/latest)
[![GitHub stars](https://img.shields.io/github/stars/xiaobaoliu849/Universal-Media-Downloader)](https://github.com/xiaobaoliu849/Universal-Media-Downloader/stargazers)
[![License](https://img.shields.io/github/license/xiaobaoliu849/Universal-Media-Downloader)](LICENSE)

一个功能强大的跨平台多媒体下载工具，具备现代化精致 Web UI，支持多平台视频、图集、音频一键提取下载。

---

## ✨ 主要特性

- 🌐 **全平台支持**：支持 YouTube、X (Twitter)、抖音/TikTok (无水印视频及高清图集)、Bilibili、MissAV 等主流流媒体平台。
- 📺 **超清与全格式解析**：支持 1080p / 2K / 4K / 8K 原画画质自动嗅探与智能格式合并。
- 🛡️ **突破 YouTube 403 限制**：
  - 自动集成 Node.js JavaScript 挑战求解引擎（自动计算 `nsig` 与 PO Token）。
  - 智能 Cookie 梯度认证：支持根目录 `cookies.txt` 与主流浏览器（Chrome / Edge / Brave）Cookies 自动探测提取。
  - 彻底规避 YouTube 机器人风控封锁与 `HTTP 403: Forbidden` 访问限制。
- ⚡ **高速多线程与死代理自愈**：
  - 内置 Aria2 与多线程分块并发下载引擎。
  - 智能代理活性检测（Socket Pre-check），直连/TUN/VPN 模式下无缝自动切换，避免无效代理挂死。
- 🔄 **内核在线一键更新**：前端界面内置 `yt-dlp` 内核更新管理，支持 `Stable` 稳定版与 `Nightly` 尝鲜版一键升级。
- 🎨 **现代化精致 Web 界面**：实时下载速率仪表盘、平滑任务进度条、卡片式任务列表与原生目录选择器。
- 🎯 **开箱即用免安装**：提供 Windows 绿色单包版，解压双击即可直接运行，无需配置 Python 环境。

---

## 📥 快速下载

**🚀 一键下载免安装版（推荐）**

[⬇️ 点击前往 Releases 下载 Windows 最新版压缩包](https://github.com/xiaobaoliu849/Universal-Media-Downloader/releases/latest)

> 下载后解压 `Universal Media Downloader_v3.5.8_Windows.zip`，双击运行 `Universal Media Downloader.exe` 即可自动启动并在浏览器中打开控制台！

---

## 🛠️ 从源码运行

### 前提条件
- **Python 3.10+**
- **Node.js**（推荐安装，用于执行 YouTube 签名与 PO Token 求解器）
- **FFmpeg**（放置于 `ffmpeg/bin/` 目录或配置于系统 `PATH` 环境变量）

### 安装与启动
```bash
# 1. 克隆仓库
git clone https://github.com/xiaobaoliu849/Universal-Media-Downloader.git
cd Universal-Media-Downloader

# 2. 创建并激活虚拟环境
python -m venv .venv
.\.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux / macOS

# 3. 安装依赖包
pip install -r requirements.txt

# 4. 启动服务
python app.py
```
启动成功后，浏览器自动打开或访问 `http://localhost:5001` 即可体验。

---

## 💡 进阶使用 & 常见问题

### 1. YouTube 下载 403 Forbidden 或需要登录认证
- 本程序现已内置浏览器 Cookies 自动提取功能（优先读取系统中已登录 YouTube 的 Chrome / Edge）。
- 若需要使用指定账号，可使用浏览器扩展（如 *Get cookies.txt LOCALLY*）导出 `cookies.txt`，直接放入应用根目录，程序会自动加载并优先使用。

### 2. 更改默认下载目录
- 打包版默认保存在电脑桌面 `流光视频下载` 文件夹。
- 在 Web 界面右上角点击 **设置下载目录**，即可调用系统原生文件夹选择器动态更改保存路径。

### 3. 网络与代理设置
- 若您的网络环境需要配置 HTTP/SOCKS 代理，可在项目根目录新建 `.env` 文件并填入：
  ```ini
  LUMINA_PROXY=http://127.0.0.1:7890
  ```
  *(注：若使用 Clash / FlClash 等 TUN 模式，程序会自动检测并直连系统虚拟网卡，无需繁琐设置)*。

---

## 💝 支持开发

如果这个项目对您有所帮助，欢迎 Star 关注或扫码打赏支持开发与维护！

<div align="center">
<img src="donate_qr.png" alt="打赏二维码" width="280">
<br>
<em>感谢您的支持与鼓励 ❤️</em>
</div>

---

## ⚖️ 免责声明
本工具仅供学习交流与个人研究使用，请严格遵守相关媒体网站的服务条款及版权规定。下载的媒体内容严禁用于任何商业用途！
