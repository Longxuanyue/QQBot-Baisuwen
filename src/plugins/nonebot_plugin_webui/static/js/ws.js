/**
 * WebSocket 客户端 — 实时事件推送（二期扩展预留）
 *
 * 当前主要用于 token 登录验证推送，
 * 后续可扩展为仪表盘实时数据、插件状态变更通知等。
 */

class WSBus {
    constructor() {
        this.ws = null;
        this.handlers = {};
        this.reconnectTimer = null;
    }

    connect(url) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = url || `${protocol}//${location.host}/webui/ws`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('[WS] 已连接');
            this._dispatch('connected', {});
        };

        this.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                this._dispatch(msg.type, msg);
            } catch (e) {
                console.warn('[WS] 消息解析失败:', e);
            }
        };

        this.ws.onclose = () => {
            console.log('[WS] 已断开');
            this._dispatch('disconnected', {});
        };

        this.ws.onerror = () => {
            // 静默处理，onclose 会随后触发
        };
    }

    on(eventType, handler) {
        if (!this.handlers[eventType]) this.handlers[eventType] = [];
        this.handlers[eventType].push(handler);
    }

    _dispatch(eventType, data) {
        const handlers = this.handlers[eventType] || [];
        handlers.forEach(h => h(data));

        // 也发送到 '*' 通配符处理器
        const wildcard = this.handlers['*'] || [];
        wildcard.forEach(h => h(eventType, data));
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    close() {
        if (this.ws) this.ws.close();
    }
}

// 全局单例
const wsBus = new WSBus();
