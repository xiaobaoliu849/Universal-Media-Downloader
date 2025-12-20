let currentVideoInfo = null;
let currentEventSource = null;
let currentTaskId = null;
let downloadStartTime = null;
const MAX_LOG_LINES = 500;

        // 当URL输入框失去焦点时，获取视频信息
        document.getElementById('videoUrl').addEventListener('blur', function() {
            const url = this.value.trim();
            if (url) {
                fetchVideoInfo(url);
            }    });

        // 当输入框内容变化时，也尝试获取信息（可选）
        document.getElementById('videoUrl').addEventListener('input', function() {
            const url = this.value.trim();
            // 如果URL看起来是完整的（包含http/https），立即获取信息
            if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
                // 延迟一点时间，避免输入过程中频繁请求
                clearTimeout(this.inputTimeout);
                this.inputTimeout = setTimeout(() => {
                    fetchVideoInfo(url);
                }, 800);
            }
        });

        // 当下载模式改变时，更新质量选项
        document.querySelectorAll('input[name="downloadMode"]').forEach(radio => {
            radio.addEventListener('change', function() {
                const mode = this.value;
                const qualitySection = document.getElementById('qualitySection');
                const thumbnailToggle = document.getElementById('thumbnailToggle');
                const thumbnailLabel = thumbnailToggle ? thumbnailToggle.closest('label') : null;
                
                // 仅封面模式时隐藏质量选择和封面复选框
                if (mode === 'thumbnail') {
                    if (qualitySection) qualitySection.style.display = 'none';
                    if (thumbnailLabel) thumbnailLabel.style.display = 'none';
                } else {
                    if (qualitySection) qualitySection.style.display = '';
                    if (thumbnailLabel) thumbnailLabel.style.display = '';
                }
                
                if (currentVideoInfo) {
                    updateQualityOptions(currentVideoInfo.formats || [], currentVideoInfo.quality_pairs || {});
                }
            });
        });

        async function fetchVideoInfo(url) {
            if (!url) {
                return;
            }

            // 显示加载状态 & 清理旧错误
            const inputField = document.getElementById('videoUrl');
            const originalPlaceholder = inputField.placeholder;
            const errorMessage = document.getElementById('error-message');
            inputField.placeholder = '正在获取视频信息...';
            errorMessage.style.display = 'none';
            errorMessage.textContent = '';

            try {
                const response = await fetch('/api/info', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ url: url })
                });
                const data = await response.json();

                if (data.error) {
                    console.error('获取视频信息失败:', data.error);
                    errorMessage.textContent = '获取视频信息失败: ' + data.error;
                    errorMessage.style.display = 'block';
                    hideVideoSections();
                    return;
                }

                currentVideoInfo = data;

                // 显示视频信息
                displayVideoInfo(data);

                // 更新质量选项
                updateQualityOptions(data.formats || [], data.quality_pairs || {});

                // 更新字幕选项
                updateSubtitleOptions(data.subtitles || [], data.auto_subtitles || []);

                // 显示质量和字幕部分
                showVideoSections();
            } catch (error) {
                console.error('获取视频信息出错:', error);
                errorMessage.textContent = '获取视频信息出错，请检查网络或链接。';
                errorMessage.style.display = 'block';
                hideVideoSections();
            } finally {
                inputField.placeholder = originalPlaceholder;
            }
        }

        function displayVideoInfo(data) {
            const videoInfo = document.getElementById('videoInfo');
            const title = document.getElementById('videoTitle');
            const details = document.getElementById('videoDetails');

            title.textContent = data.title || '未知标题';
            details.textContent = `上传者: ${data.uploader || '未知'} | 时长: ${formatDuration(data.duration)} | 最高质量: ${data.max_height || '未知'}p`;

            videoInfo.style.display = 'block';
        }

        function formatDuration(seconds) {
            if (!seconds) return '未知';
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            if (hours > 0) {
                return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
            }
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        }

        function updateQualityOptions(formats, qualityPairs) {
            const qualityContainer = document.querySelector('#qualitySection .radio-group');
            const downloadMode = document.querySelector('input[name="downloadMode"]:checked').value;

            // 记录之前的选择 (若尚未记录则读取当前已选或默认 best)
            const prevSelection = window._lastQualitySelection || document.querySelector('#qualitySection input[name="quality"]:checked')?.value || 'best';

            // 清空现有选项
            qualityContainer.innerHTML = '';

            // 总是添加自动推荐选项
            const bestOption = document.createElement('div');
            bestOption.className = 'radio-option';
            bestOption.innerHTML = `
                <input type="radio" id="best" name="quality" value="best" checked>
                <label for="best">🧠 自动推荐</label>
            `;
            qualityContainer.appendChild(bestOption);

            let usedPairs = false;
            if (qualityPairs && Object.keys(qualityPairs).length > 0 && downloadMode !== 'audio') {
                const heights = Object.keys(qualityPairs).filter(k => k !== 'default_best').map(h => parseInt(h)).filter(h => !isNaN(h));
                if (heights.length > 0) {
                    heights.sort((a,b)=>b-a);
                    heights.forEach(h => {
                        const pair = qualityPairs[h];
                        if (!pair || !pair.video || !pair.audio) return;
                        const option = document.createElement('div');
                        option.className = 'radio-option';
                        let labelTxt = `${h}p`;
                        if (h >= 4320) labelTxt = '8K';
                        else if (h >= 2160) labelTxt = '4K';
                        else if (h >= 1080) labelTxt = '1080P';
                        else if (h >= 720) labelTxt = '720P';
                        else if (h >= 480) labelTxt = '480P';
                        else if (h >= 360) labelTxt = '360P';
                        else labelTxt = `${h}p (低清)`;
                        option.innerHTML = `
                            <input type="radio" id="q${h}" name="quality" value="${h}" data-vfmt="${pair.video}" data-afmt="${pair.audio}">
                            <label for="q${h}">${labelTxt}</label>
                        `;
                        qualityContainer.appendChild(option);
                    });
                    usedPairs = true;
                }
            }

            if (!usedPairs && downloadMode === 'audio') {
                // 收集音频格式，使用Map来确保唯一性
                const audioFormats = new Map();
                formats.forEach(format => {
                    if (format.acodec && format.acodec !== 'none') {
                        const quality = format.abr || format.audio_quality || '未知';
                        if (quality !== '未知' && !audioFormats.has(quality)) {
                            audioFormats.set(quality, quality);
                        }
                    }
                });

                // 如果没有找到音频格式，添加默认选项
                if (audioFormats.size === 0) {
                    ['320k', '256k', '192k', '128k', '96k', '64k'].forEach(quality => {
                        const option = document.createElement('div');
                        option.className = 'radio-option';
                        option.innerHTML = `
                            <input type="radio" id="audio_${quality}" name="quality" value="${quality}">
                            <label for="audio_${quality}">${quality}</label>
                        `;
                        qualityContainer.appendChild(option);
                    });
                } else {
                    // 排序并添加音频质量选项
                    Array.from(audioFormats.keys()).sort((a, b) => {
                        const aNum = parseInt(a);
                        const bNum = parseInt(b);
                        return bNum - aNum;
                    }).forEach(quality => {
                        const option = document.createElement('div');
                        option.className = 'radio-option';
                        option.innerHTML = `
                            <input type="radio" id="audio_${quality}" name="quality" value="${quality}">
                            <label for="audio_${quality}">${quality}</label>
                        `;
                        qualityContainer.appendChild(option);
                    });
                }
            } else if (!usedPairs && downloadMode !== 'audio') {
                // 视频模式：收集所有可用的有效高度，使用Map确保唯一性
                const heights = new Map();
                formats.forEach(format => {
                    const height = format.effective_height || format.height;
                    if (height && height > 0) {  // 显示所有可用质量
                        if (!heights.has(height)) {
                            heights.set(height, height);
                        }
                    }
                });

                // 排序并添加选项（不再添加默认选项）
                Array.from(heights.keys()).sort((a, b) => b - a).forEach(height => {
                    const option = document.createElement('div');
                    option.className = 'radio-option';
                    let label = `${height}p`;
                    if (height >= 4320) label = '8K';
                    else if (height >= 2160) label = '4K';
                    else if (height >= 1080) label = '1080P';
                    else if (height >= 720) label = '720P';
                    else if (height >= 480) label = '480P';
                    else if (height >= 360) label = '360P';
                    else label = `${height}p (低清)`;  // 对于240p等低质量

                    option.innerHTML = `
                        <input type="radio" id="q${height}" name="quality" value="${height}">
                        <label for="q${height}">${label}</label>
                    `;
                    qualityContainer.appendChild(option);
                });

                // 如果没有找到任何质量选项，添加提示
                if (heights.size === 0) {
                    const noQualityOption = document.createElement('div');
                    noQualityOption.className = 'radio-option';
                    noQualityOption.innerHTML = `
                        <input type="radio" id="no_quality" name="quality" value="best" checked disabled>
                        <label for="no_quality">无可用质量选项 (使用最佳)</label>
                    `;
                    qualityContainer.appendChild(noQualityOption);
                }
            }

            // 恢复之前的选择
            const radios = qualityContainer.querySelectorAll('input[name="quality"]');
            let restored = false;
            radios.forEach(r => {
                if (r.value === prevSelection) {
                    r.checked = true;
                    restored = true;
                }
            });
            if (!restored) {
                // 如果之前的选项不存在，保留 best
                const bestRadio = qualityContainer.querySelector('input[value="best"]');
                if (bestRadio) bestRadio.checked = true;
            }

            // 添加监听保存新的选择
            radios.forEach(r => {
                r.addEventListener('change', () => {
                    if (r.checked) {
                        window._lastQualitySelection = r.value;
                    }
                });
            });
            // 初次生成立即保存当前有效选择
            window._lastQualitySelection = qualityContainer.querySelector('input[name="quality"]:checked')?.value || 'best';
        }

        function addLog(message, type = 'info') {
            const logContainer = document.getElementById('logContainer');
            const logStats = document.getElementById('logStats');
            const timestamp = new Date().toLocaleTimeString();

            // 创建日志条目
            const logEntry = document.createElement('div');
            logEntry.className = `log-entry log-${type}`;
            logEntry.innerHTML = `<span class="log-time">[${timestamp}]</span> <span class="log-message">${message}</span>`;

            // 添加到日志容器
            logContainer.appendChild(logEntry);
            // 截断过长日志
            while (logContainer.children.length > MAX_LOG_LINES) {
                logContainer.removeChild(logContainer.firstChild);
            }
            logContainer.scrollTop = logContainer.scrollHeight;

            // 更新日志统计
            const entryCount = logContainer.children.length;
            const errorCount = logContainer.querySelectorAll('.log-error').length;
            const warningCount = logContainer.querySelectorAll('.log-warning').length;

            let statsText = `共 ${entryCount} 条`;
            if (errorCount > 0) statsText += `, 错误 ${errorCount}`;
            if (warningCount > 0) statsText += `, 警告 ${warningCount}`;

            logStats.textContent = statsText;
        }

        function clearLogs() {
            // 清理日志内容
            document.getElementById('logContainer').textContent = '';

            // 清理下载状态显示
            const statusText = document.getElementById('statusText');
            const progressPercent = document.getElementById('progressPercent');
            const remainingTime = document.getElementById('remainingTime');

            // 重置为初始状态
            statusText.textContent = '等待下载...';
            progressPercent.textContent = '0.0%';
            remainingTime.textContent = '--:--';

            // 隐藏进度条
            const progressContainer = document.getElementById('progress');
            progressContainer.style.display = 'none';

            // 重置进度条
            const progressBar = document.querySelector('.progress-fill');
            progressBar.style.width = '0%';

            // 重置下载按钮状态
            const downloadButton = document.querySelector('.download-btn');
            downloadButton.disabled = false;
            downloadButton.innerHTML = '📥 下载媒体';

            // 清理字幕按钮状态
            const subtitleButton = document.querySelector('.subtitle-btn');
            if (subtitleButton) {
                subtitleButton.disabled = false;
                subtitleButton.innerHTML = '字幕下载';
            }

            // 清理视频信息显示
            const videoInfo = document.getElementById('videoInfo');
            const videoTitle = document.getElementById('videoTitle');
            const videoDetails = document.getElementById('videoDetails');

            if (videoInfo) {
                videoInfo.style.display = 'none';
                videoTitle.textContent = '视频标题';
                videoDetails.textContent = '详细信息';
            }

            // 清理字幕选择器
            const subtitleSelect = document.getElementById('subtitles');
            if (subtitleSelect) {
                subtitleSelect.innerHTML = '<option value="">无字幕</option>';
            }

            // 清理URL输入框
            const videoUrlInput = document.getElementById('videoUrl');
            if (videoUrlInput) {
                videoUrlInput.value = '';
                videoUrlInput.placeholder = '粘贴视频或播放列表链接...';
            }

            // 清理日志统计
            const logStats = document.getElementById('logStats');
            if (logStats) {
                logStats.textContent = '等待下载...';
            }

            // 关闭可能存在的下载连接
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }

            // 重置下载统计
            downloadStartTime = null;
            downloadStats = {
                speed: 0,
                downloaded: 0,
                total: 0,
                remainingTime: 0
            };

            addLog('已清理所有下载记录和状态');
        }

        function toggleLogVisibility() {
            const logContainer = document.getElementById('logContainer');
            const toggleBtn = document.getElementById('toggleLogBtn');
            if (logContainer.style.display === 'none') {
                logContainer.style.display = 'block';
                toggleBtn.textContent = '隐藏日志';
            } else {
                logContainer.style.display = 'none';
                toggleBtn.textContent = '显示日志';
            }
        }

        function updateSubtitleOptions(subtitles, autoSubtitles) {
            const subtitleSelect = document.getElementById('subtitles');
            const subtitlesLabel = document.getElementById('subtitlesLabel');
            const hasSubtitles = (subtitles && subtitles.length > 0) || (autoSubtitles && autoSubtitles.length > 0);

            // 重置UI状态
            subtitleSelect.innerHTML = '';
            subtitlesLabel.style.color = ''; // 恢复默认颜色

            if (hasSubtitles) {
                // 有可用字幕，高亮标签并更新默认文本
                subtitlesLabel.style.color = '#1d9bf0';
                subtitleSelect.innerHTML = '<option value="">有可用字幕</option>';
            } else {
                // 没有字幕
                subtitleSelect.innerHTML = '<option value="">无字幕</option>';
            }

            // 填充人工字幕
            (subtitles || []).forEach(sub => {
                const opt = document.createElement('option');
                opt.value = sub.lang;
                opt.textContent = `${sub.lang} (人工)`;
                subtitleSelect.appendChild(opt);
            });

            // 填充自动字幕
            (autoSubtitles || []).forEach(sub => {
                const opt = document.createElement('option');
                opt.value = sub.lang;
                opt.textContent = `${sub.lang} (自动)`;
                subtitleSelect.appendChild(opt);
            });
        }

        function showVideoSections() {
            document.getElementById('videoInfo').style.display = 'block';
            document.getElementById('qualitySection').style.display = 'flex';
        }

        function hideVideoSections() {
            document.getElementById('videoInfo').style.display = 'none';
            // 质量选择区域始终显示，不隐藏
            // document.getElementById('qualitySection').style.display = 'none';
        }

        // 删除旧统计对象：后端暂未提供速度/ETA 直接字段

        function mapQualityForBackend(raw) {
            if (!raw) return 'best';
            // 数字表示高度
            if (/^\d+$/.test(raw)) return `height<=${raw}`;
            const val = raw.toLowerCase();
            if (val === '4k') return 'best4k';
            if (val === '8k') return 'best8k';
            return val; // best / fast / best4k / best8k / height<=X 等
        }

        function closeCurrentEventSource() {
            if (currentEventSource) {
                try { currentEventSource.close(); } catch(e) {}
                currentEventSource = null;
            }
        }

        function resetProgressUI() {
            document.querySelector('.progress-fill').style.width = '0%';
            document.getElementById('progressPercent').textContent = '0.0%';
            document.getElementById('statusText').textContent = '准备中...';
            document.getElementById('remainingTime').textContent = '--:--';
        }

        function updateStageStatus(stage, status) {
            const statusText = document.getElementById('statusText');
            let label = stage || status || '';
            switch(label){
                case 'queued': label = '队列中'; break;
                case 'downloading': label = '下载中'; break;
                case 'merging': label = '合并处理中'; break;
                case 'finished': label = '完成'; break;
                case 'error': label = '出错'; break;
                default: break;
            }
            statusText.textContent = label;
        }

        function downloadMedia() {
            const videoUrl = document.getElementById('videoUrl').value.trim();
            if (!videoUrl) {
                const errorMessage = document.getElementById('error-message');
                errorMessage.textContent = '请输入视频链接';
                errorMessage.style.display = 'block';
                return;
            }
            const modeRaw = document.querySelector('input[name="downloadMode"]:checked').value;
            let mode;
            if (modeRaw === 'video') mode = 'video_only';
            else if (modeRaw === 'audio') mode = 'audio_only';
            else if (modeRaw === 'thumbnail') mode = 'thumbnail_only';
            else mode = 'merged';
            const qualityEl = document.querySelector('input[name="quality"]:checked');
            const qualityRaw = qualityEl.value;
            const quality = mapQualityForBackend(qualityRaw);
            const vfmt = qualityEl.getAttribute('data-vfmt');
            const afmt = qualityEl.getAttribute('data-afmt');
            const subtitles = document.getElementById('subtitles').value;
            const progressContainer = document.getElementById('progress');
            const progressBar = document.querySelector('.progress-fill');
            const progressPercent = document.getElementById('progressPercent');
            const remainingTime = document.getElementById('remainingTime');
            const statusText = document.getElementById('statusText');
            const downloadButton = document.querySelector('.download-btn');
            const progressTitle = document.getElementById('progressTitle');
            const progressUrl = document.getElementById('progressUrl');

            closeCurrentEventSource();
            resetProgressUI();
            progressContainer.style.display = 'block';
            downloadButton.disabled = true;
            downloadButton.textContent = '初始化...';
            progressTitle.textContent = '下载任务';
            progressUrl.textContent = videoUrl;
            addLog(`创建任务: mode=${mode} quality=${quality}`);

            const params = new URLSearchParams();
            params.set('url', videoUrl);
            params.set('mode', mode);
            params.set('quality', quality);
            if (subtitles) params.set('subtitles', subtitles);
            const metaToggle = document.getElementById('metaToggle');
            if (metaToggle) {
                params.set('meta', metaToggle.checked ? '1' : '0');
            }
            const fastStart = document.getElementById('fastStartToggle');
            // 条件：勾选快速启动 + 已经有 currentVideoInfo（即前面获取过 /api/info）
            if (fastStart && fastStart.checked) {
                if (currentVideoInfo && currentVideoInfo.title) {
                    try {
                        const minimalInfo = {
                            title: currentVideoInfo.title,
                            id: currentVideoInfo.id || currentVideoInfo.video_id || undefined,
                            duration: currentVideoInfo.duration || undefined,
                            max_height: currentVideoInfo.max_height || undefined
                        };
                        // 清理 undefined 字段
                        Object.keys(minimalInfo).forEach(k=> minimalInfo[k] === undefined && delete minimalInfo[k]);
                        params.set('skip_probe', '1');
                        params.set('info_cache', encodeURIComponent(JSON.stringify(minimalInfo)));
                        addLog('启用快速启动 fast-path: ' + JSON.stringify(minimalInfo));
                    } catch(e) {
                        addLog('快速启动 JSON 序列化失败: ' + e, 'error');
                    }
                } else {
                    addLog('未获取视频信息，无法启用快速启动（将执行正常探测）', 'warning');
                }
            }
            // 封面图下载
            const thumbnailToggle = document.getElementById('thumbnailToggle');
            if (thumbnailToggle && thumbnailToggle.checked) {
                params.set('thumbnail', '1');
                addLog('启用封面图下载');
            }
            if (vfmt && afmt && qualityRaw !== 'best') {
                params.set('video_format', vfmt);
                params.set('audio_format', afmt);
                addLog(`使用直选格式: v=${vfmt} a=${afmt}`);
            }
            if (mode === 'audio_only' || mode === 'video_only') {
                // no special flag
            }

            const sseUrl = `/api/stream_task?${params.toString()}`;
            downloadStartTime = Date.now();
            currentEventSource = new EventSource(sseUrl);

            currentEventSource.onmessage = (ev) => {
                if (!ev.data) return;
                let data;
                try { data = JSON.parse(ev.data); } catch(e){ return; }
                if (data.error){
                    addLog('任务出错: ' + data.error, 'error');
                    const errorMessage = document.getElementById('error-message');
                    errorMessage.textContent = '任务出错: ' + data.error;
                    errorMessage.style.display = 'block';
                    updateStageStatus('error');
                    downloadButton.disabled = false;
                    downloadButton.textContent = '📥 下载媒体';
                    closeCurrentEventSource();
                    return;
                }
                if (data.task_id && !currentTaskId) {
                    currentTaskId = data.task_id;
                    addLog(`任务ID: ${currentTaskId}`);
                }
                if (data.type === 'log') {
                    addLog(data.line);
                } else if (data.type === 'status') {
                    // 进度 & 阶段
                    updateStageStatus(data.stage, data.status);
                    if (typeof data.progress === 'number') {
                        const pct = Math.min(100, Math.max(0, data.progress));
                        progressBar.style.width = pct + '%';
                        progressPercent.textContent = pct.toFixed(1) + '%';
                        // 简单 ETA 估算
                        const elapsed = (Date.now() - downloadStartTime)/1000;
                        if (pct > 0 && pct < 100) {
                            const remaining = elapsed * (100 - pct) / pct;
                            const m = Math.floor(remaining / 60);
                            const s = Math.floor(remaining % 60);
                            remainingTime.textContent = `${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
                        } else if (pct >= 100) {
                            remainingTime.textContent = '00:00';
                        }
                    }
                    if (data.status === 'finished') {
                        addLog('任务完成: ' + (data.file_path || '')); 
                        progressBar.style.width = '100%';
                        progressPercent.textContent = '100%';
                        updateStageStatus('finished');
                        remainingTime.textContent = '00:00';
                        downloadButton.disabled = false;
                        downloadButton.textContent = '📥 下载媒体';
                        closeCurrentEventSource();
                    } else if (data.status === 'error') {
                        addLog('任务失败', 'error');
                        downloadButton.disabled = false;
                        downloadButton.textContent = '📥 下载媒体';
                        closeCurrentEventSource();
                    }
                } else if (data.event === 'end') {
                    // SSE结束
                    closeCurrentEventSource();
                    if (downloadButton.disabled) {
                        downloadButton.disabled = false;
                        downloadButton.textContent = '📥 下载媒体';
                    }
                }
            };

            currentEventSource.onerror = () => {
                addLog('SSE 连接出错或中断', 'error');
                const errorMessage = document.getElementById('error-message');
                errorMessage.textContent = '与服务器的连接中断，请检查后端服务是否仍在运行。';
                errorMessage.style.display = 'block';
                downloadButton.disabled = false;
                downloadButton.textContent = '📥 下载媒体';
                updateStageStatus('error');
                closeCurrentEventSource();
            };
        }

        async function cancelDownload() {
            if (currentTaskId) {
                try {
                    const resp = await fetch(`/api/tasks/${currentTaskId}/cancel`, {method:'POST'});
                    const d = await resp.json();
                    addLog('取消请求: ' + JSON.stringify(d));
                } catch(e) {
                    addLog('取消请求失败: ' + e, 'error');
                }
            }
            closeCurrentEventSource();
            const downloadButton = document.querySelector('.download-btn');
            downloadButton.disabled = false;
            downloadButton.textContent = '📥 下载媒体';
            document.getElementById('statusText').textContent = '已取消';
            document.getElementById('progressPercent').textContent = '已取消';
            document.getElementById('remainingTime').textContent = '--:--';
        }

        function downloadSubtitles() {
            const videoUrl = document.getElementById('videoUrl').value.trim();
            const subtitles = document.getElementById('subtitles').value;
            const btn = document.querySelector('.subtitle-btn');
            const errorMessage = document.getElementById('error-message');

            if (!videoUrl) {
                errorMessage.textContent = '请输入视频链接';
                errorMessage.style.display = 'block';
                return;
            }
            if (!subtitles) {
                errorMessage.textContent = '请选择字幕语言';
                errorMessage.style.display = 'block';
                return;
            }
            errorMessage.style.display = 'none';
            closeCurrentEventSource();
            resetProgressUI();
            document.getElementById('progress').style.display = 'block';
            btn.disabled = true; btn.textContent = '字幕任务中...';
            const params = new URLSearchParams();
            params.set('url', videoUrl); params.set('mode','merged'); params.set('subtitles', subtitles); params.set('subtitles_only','true'); params.set('quality','best');
            const sseUrl = `/api/stream_task?${params.toString()}`;
            downloadStartTime = Date.now();
            currentEventSource = new EventSource(sseUrl);
            addLog('创建字幕任务: ' + subtitles);
            currentEventSource.onmessage = (ev)=>{
                if (!ev.data) return; let data; try { data = JSON.parse(ev.data);} catch(e){return;}
                if (data.error){
                    addLog('字幕任务出错: '+data.error,'error');
                    errorMessage.textContent = '字幕任务出错: ' + data.error;
                    errorMessage.style.display = 'block';
                    btn.disabled=false;
                    btn.textContent='字幕下载';
                    closeCurrentEventSource();
                    return;
                }
                if (data.type==='log'){ addLog(data.line); return; }
                if (data.type==='status'){
                    updateStageStatus(data.stage,data.status);
                    if (typeof data.progress==='number') {
                        const pct=Math.min(100,Math.max(0,data.progress));
                        document.querySelector('.progress-fill').style.width=pct+'%';
                        document.getElementById('progressPercent').textContent=pct.toFixed(1)+'%';
                        if (pct>=100){ btn.disabled=false; btn.textContent='字幕下载'; closeCurrentEventSource(); }
                    }
                } else if (data.event==='end') {
                    btn.disabled=false; btn.textContent='字幕下载'; closeCurrentEventSource();
                }
            };
            currentEventSource.onerror = ()=>{
                addLog('字幕 SSE 连接出错','error');
                errorMessage.textContent = '与服务器的连接中断，请检查后端服务是否仍在运行。';
                errorMessage.style.display = 'block';
                btn.disabled=false;
                btn.textContent='字幕下载';
                closeCurrentEventSource();
            };
        }

        // 移除 startDownload 旧实现（已废弃）

        async function openDownloadDir(){
            try {
                const r = await fetch('/api/open_download_dir',{method:'POST'});
                const d = await r.json();
                if(!d.success){ addLog('打开目录失败: '+(d.error||'未知')); }
                else { addLog('已请求打开目录: '+d.path); }
            } catch(e){ addLog('打开目录异常: '+e,'error'); }
        }

        async function revealLastFile(){
            const btn = document.getElementById('revealLastBtn');
            btn.disabled = true;
            try {
                const r = await fetch('/api/last_finished_file');
                const d = await r.json();
                if(!d.found){ addLog('没有已完成的任务文件'); btn.disabled=false; return; }
                const name = d.file.split(/[/\\]/).pop();
                // 调用选中文件
                const post = await fetch('/api/reveal_file',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name: name})});
                const pr = await post.json();
                if(!pr.success){ addLog('显示文件失败: '+(pr.error||'未知'),'error'); }
                else { addLog('已请求在资源管理器中显示: '+ name); }
            } catch(e){ addLog('显示最近文件异常: '+e,'error'); }
            finally { btn.disabled=false; }
        }
    
