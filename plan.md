# 集成规划与追踪计划 (plan.md)

本文件用于规划和追踪“抖音无水印下载”与“微信视频号视频解密下载”深度集成的各项任务。

## 📅 进度追踪表

| 任务模块 | 具体内容 | 状态 | 责任人 | 备注 |
| :--- | :--- | :--- | :--- | :--- |
| **0. 方案规划** | 建立 `plan.md` 并获得用户审批 | 🟢 已完成 | AI | 本次任务启动 |
| **1. 抖音下载优化** | 在 `site_configs.py` 增加抖音的专属配置，提高 API 成功率 | 🟢 已完成 | AI | 增加 UA, Referer |
| **2. 微信视频号拦截** | 在 `service/web/routes_api.py` 的 `/api/info` 拦截视频号链接并返回模拟信息 | 🟢 已完成 | AI | 避免 yt-dlp 报错 |
| **3. 视频号下载分发** | 在 `service/tasks/downloader.py` 中分发视频号任务，不走常规流程 | 🟢 已完成 | AI | 拦截并单独执行下载与解密 |
| **4. Isaac64 纯Python算法** | 在 `service/utils/isaac64.py` 中实现标准 ISAAC-64 解密算法 | 🟢 已完成 | AI | 无 native 库依赖 |
| **5. 自动化测试与集成验证** | 编写单元测试验证解密流是否正确，用测试链接验证抖音和视频号的下载 | 🟢 已完成 | AI | 确保合并后正常运作 |

---

## 🛠️ 文件修改清单

### 新增文件 (NEW)
*   [`service/utils/isaac64.py`](file:///d:/Projects/X_video_downloader/service/utils/isaac64.py): 包含纯 Python 实现的 `Isaac64` 解密算法。

### 修改文件 (MODIFY)
*   [`site_configs.py`](file:///d:/Projects/X_video_downloader/site_configs.py): 为抖音链接配置专门的 Impersonate、UA、Referer。
*   [`service/web/routes_api.py`](file:///d:/Projects/X_video_downloader/service/web/routes_api.py): 在 `api_info` (和相关 API) 中劫持并处理微信视频号的连接（以 `findermp.video.qq.com` 或者是带 `decodekey` 参数为特征）。
*   [`service/tasks/downloader.py`](file:///d:/Projects/X_video_downloader/service/tasks/downloader.py): 在任务执行中判断若为 `wechat_channels`，跳过 `yt-dlp` 的探测和下载，采用直接下载并进行 `Isaac64` 解密。

---

## 📈 追踪与验证

完成各个模块的开发后，我们将使用单元测试以及真实的视频号（包含 `decodekey`）和抖音分享 URL 进行验证，记录最终的 walkthrough。
