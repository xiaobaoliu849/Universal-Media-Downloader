// 下载队列面板：轮询 /api/tasks，按任务渲染一行，原地更新避免闪烁。
(function () {
    const ACTIVE = new Set(['queued', 'downloading', 'merging']);
    const listEl = () => document.getElementById('queueList');
    const knownStatus = new Map();   // id -> 上一次看到的状态，用来判断“刚完成”
    let pollTimer = null;
    let firstLoad = true;

    const MODE_LABEL = {
        merged: '视频 + 音频',
        video_only: '仅视频',
        audio_only: '仅音频',
        thumbnail_only: '仅封面',
    };
    const STATUS_LABEL = {
        queued: '排队中',
        downloading: '下载中',
        merging: '合并中',
        finished: '已完成',
        error: '失败',
        canceled: '已取消',
    };

    function formatSpeed(v) {
        if (v == null || v === '') return '';
        if (typeof v === 'string') return v.trim();
        if (typeof v !== 'number' || !isFinite(v) || v <= 0) return '';
        const units = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
        let i = 0;
        while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
        return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
    }

    function formatQuality(t) {
        if (t.mode === 'audio_only' || t.mode === 'thumbnail_only') return '';
        const q = String(t.quality || '');
        const m = q.match(/(\d{3,4})/);
        if (m) return `${m[1]}p`;
        if (q === 'best4k') return '4K';
        if (q === 'best8k') return '8K';
        if (t.height) return `${t.height}p`;
        return '';
    }

    function shortUrl(u) {
        try {
            const x = new URL(u);
            return x.hostname.replace(/^www\./, '') + x.pathname;
        } catch (e) { return u || ''; }
    }

    function baseName(p) {
        return (p || '').split(/[/\\]/).pop();
    }

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function buildRow(t) {
        const li = el('li', 'q-row');
        li.dataset.id = t.id;

        const fill = el('div', 'q-fill');
        fill.setAttribute('aria-hidden', 'true');
        li.appendChild(fill);

        const thumb = el('div', 'q-thumb');
        li.appendChild(thumb);

        const body = el('div', 'q-body');
        body.appendChild(el('div', 'q-title'));
        const meta = el('div', 'q-meta');
        meta.appendChild(el('span', 'q-status'));
        meta.appendChild(el('span', 'q-mode'));
        meta.appendChild(el('span', 'q-quality'));
        meta.appendChild(el('span', 'q-detail'));
        body.appendChild(meta);
        li.appendChild(body);

        const side = el('div', 'q-side');
        side.appendChild(el('span', 'q-percent'));
        const actions = el('div', 'q-actions');
        side.appendChild(actions);
        li.appendChild(side);
        return li;
    }

    function setThumb(row, t) {
        const thumb = row.querySelector('.q-thumb');
        const src = (typeof t.thumbnail === 'string' && /^https?:\/\//.test(t.thumbnail)) ? t.thumbnail : '';
        if (thumb.dataset.src === src) return;
        thumb.dataset.src = src;
        thumb.textContent = '';
        if (src) {
            const img = el('img');
            img.alt = '';
            img.loading = 'lazy';
            img.referrerPolicy = 'no-referrer';
            img.src = src;
            img.onerror = () => { img.remove(); };
            thumb.appendChild(img);
        }
    }

    function setActions(row, t) {
        const box = row.querySelector('.q-actions');
        const key = t.status + '|' + (t.file_path ? 1 : 0);
        if (box.dataset.key === key) return;
        box.dataset.key = key;
        box.textContent = '';

        if (ACTIVE.has(t.status)) {
            const b = el('button', 'link-btn q-cancel', '取消');
            b.type = 'button';
            b.addEventListener('click', () => cancelTask(t.id, b));
            box.appendChild(b);
        } else if (t.status === 'finished' && t.file_path) {
            const b = el('button', 'link-btn', '在文件夹中显示');
            b.type = 'button';
            b.addEventListener('click', () => revealFile(t.file_path, b));
            box.appendChild(b);
        }
    }

    function updateRow(row, t) {
        const status = t.status || 'queued';
        row.className = 'q-row is-' + status;

        const pct = Math.max(0, Math.min(100, Number(t.progress) || 0));
        const shownPct = status === 'finished' ? 100 : pct;
        row.querySelector('.q-fill').style.width = (ACTIVE.has(status) || status === 'finished' ? shownPct : 0) + '%';

        row.querySelector('.q-title').textContent = t.title || shortUrl(t.url);
        row.querySelector('.q-title').title = t.title || t.url || '';
        row.querySelector('.q-status').textContent = STATUS_LABEL[status] || status;
        row.querySelector('.q-mode').textContent = MODE_LABEL[t.mode] || '';
        row.querySelector('.q-quality').textContent = formatQuality(t);

        let detail = '';
        if (status === 'downloading') {
            const sp = formatSpeed(t.speed);
            const eta = (t.eta && t.eta !== 'Unknown') ? `剩余 ${String(t.eta).trim()}` : '';
            detail = [sp, eta].filter(Boolean).join('，');
        } else if (status === 'error') {
            detail = t.error_message || '下载失败，查看日志了解原因';
        } else if (status === 'finished' && t.file_path) {
            detail = baseName(t.file_path);
        } else if (status === 'finished' && t.warning_message) {
            detail = t.warning_message;
        }
        const d = row.querySelector('.q-detail');
        d.textContent = detail;
        d.title = detail;

        const pctEl = row.querySelector('.q-percent');
        pctEl.textContent = (status === 'downloading' || status === 'merging') ? `${pct.toFixed(pct >= 10 ? 0 : 1)}%` : '';

        setThumb(row, t);
        setActions(row, t);
    }

    function notifyTransitions(tasks) {
        tasks.forEach(t => {
            const prev = knownStatus.get(t.id);
            if (!firstLoad && prev && ACTIVE.has(prev)) {
                const name = t.title || shortUrl(t.url);
                if (t.status === 'finished') window.showToast && window.showToast(`下载完成：${name}`, 'success');
                if (t.status === 'error') window.showToast && window.showToast(`下载失败：${name}`, 'error');
            }
            knownStatus.set(t.id, t.status);
        });
        firstLoad = false;
    }

    function render(tasks) {
        const list = listEl();
        if (!list) return;
        tasks.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));

        const existing = new Map();
        list.querySelectorAll('.q-row').forEach(r => existing.set(r.dataset.id, r));

        let prev = null;
        tasks.forEach(t => {
            let row = existing.get(t.id);
            if (!row) row = buildRow(t);
            existing.delete(t.id);
            updateRow(row, t);
            const want = prev ? prev.nextSibling : list.firstChild;
            if (row !== want) list.insertBefore(row, want);
            prev = row;
        });
        existing.forEach(r => r.remove());

        const active = tasks.filter(t => ACTIVE.has(t.status)).length;
        const done = tasks.length - active;
        const count = document.getElementById('queueCount');
        if (count) {
            count.textContent = tasks.length
                ? (active ? `${active} 个进行中` : '') + (active && done ? '，' : '') + (done ? `${done} 个已结束` : '')
                : '';
        }
        const empty = document.getElementById('queueEmpty');
        if (empty) empty.style.display = tasks.length ? 'none' : '';
        const clearBtn = document.getElementById('queueClearBtn');
        if (clearBtn) clearBtn.disabled = done === 0;

        return active;
    }

    async function refreshQueue() {
        clearTimeout(pollTimer);
        let active = 0;
        try {
            const r = await fetch('/api/tasks', { cache: 'no-store' });
            if (r.ok) {
                const tasks = await r.json();
                if (Array.isArray(tasks)) {
                    notifyTransitions(tasks);
                    active = render(tasks) || 0;
                }
            }
        } catch (e) { /* 后端暂时不可达，下次再试 */ }
        pollTimer = setTimeout(refreshQueue, active ? 1000 : 4000);
    }

    async function cancelTask(id, btn) {
        if (btn) btn.disabled = true;
        try {
            await fetch(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
        } catch (e) {
            window.showToast && window.showToast('取消失败：' + e.message, 'error');
        }
        refreshQueue();
    }

    async function revealFile(path, btn) {
        if (btn) btn.disabled = true;
        try {
            const r = await fetch('/api/reveal_file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: baseName(path) }),
            });
            const d = await r.json();
            if (!d.success) window.showToast && window.showToast('找不到这个文件：' + (d.error || ''), 'error');
        } catch (e) {
            window.showToast && window.showToast('无法打开文件夹：' + e.message, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async function clearFinished() {
        try {
            await fetch('/api/tasks/cleanup', { method: 'POST' });
        } catch (e) { /* ignore */ }
        refreshQueue();
    }

    window.refreshQueue = refreshQueue;

    document.addEventListener('DOMContentLoaded', () => {
        const clearBtn = document.getElementById('queueClearBtn');
        if (clearBtn) clearBtn.addEventListener('click', clearFinished);
        refreshQueue();
    });
})();
