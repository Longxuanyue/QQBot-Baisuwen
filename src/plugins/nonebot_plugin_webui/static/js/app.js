/**
 * WebUI 主入口：全局初始化、键盘快捷键、通用事件
 */

document.addEventListener('DOMContentLoaded', () => {
    // ESC 关闭所有 modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal').forEach(m => {
                if (m.style.display === 'flex') m.style.display = 'none';
            });
        }
    });

    // 点击 modal overlay 关闭
    document.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-overlay')) {
            e.target.parentElement.style.display = 'none';
        }
    });

    // 自动隐藏 toast（由 components.js 处理）
    console.log('WebUI 管理后台已就绪');
});
