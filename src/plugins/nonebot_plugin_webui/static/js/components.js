/**
 * 可复用 Web 组件：Toast、Modal、重启流程
 */

// ── Toast 通知 ──

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}


// ── 重启流程 ──

function triggerRestart() {
    document.getElementById('restart-modal').style.display = 'flex';
}

function closeRestartModal() {
    document.getElementById('restart-modal').style.display = 'none';
}

async function confirmRestart() {
    const btn = document.getElementById('confirm-restart-btn');
    const statusEl = document.getElementById('restart-status');
    btn.disabled = true;
    btn.textContent = '重启中...';
    statusEl.style.display = 'block';
    statusEl.innerHTML = '<span class="spinner"></span> 正在发送重启信号...';

    try {
        const resp = await fetch('/webui/api/restart', { method: 'POST' });
        const data = await resp.json();
        if (data.ok) {
            statusEl.innerHTML = '<div class="alert alert-warning">🔄 Bot 正在重启，页面将在 5 秒后自动刷新...</div>';
            setTimeout(() => location.reload(), 5000);
        } else {
            statusEl.innerHTML = `<div class="alert alert-error">❌ ${data.error}</div>`;
            btn.disabled = false;
            btn.textContent = '确认重启';
        }
    } catch (e) {
        // 请求可能在重启过程中被中断，正常现象
        statusEl.innerHTML = '<div class="alert alert-warning">🔄 Bot 可能已开始重启，请等待几秒后手动刷新页面。</div>';
        setTimeout(() => location.reload(), 5000);
    }
}


// ── 确认弹窗 ──

function showConfirm(title, message, onConfirm) {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div class="modal-overlay"></div>
        <div class="modal-content">
            <h3>${title}</h3>
            <p>${message}</p>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="_cancel">取消</button>
                <button class="btn btn-danger" id="_confirm">确认</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);

    modal.querySelector('#_cancel').onclick = () => modal.remove();
    modal.querySelector('#_confirm').onclick = () => { onConfirm(); modal.remove(); };
    modal.querySelector('.modal-overlay').onclick = () => modal.remove();
}


// ── 工具函数 ──

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function formatDate(ts) {
    if (!ts) return '-';
    try {
        return new Date(ts).toLocaleString('zh-CN');
    } catch(e) {
        return ts;
    }
}
