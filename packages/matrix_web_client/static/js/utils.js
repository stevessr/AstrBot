// Matrix Web Client - 工具函数模块
// 通用工具和辅助函数

// 全局变量
let sessionId = null;
let currentRoomId = null;
let homeserverUrl = null;

// Markdown 渲染器
let md = window.markdownit({
    html: true,
    linkify: true,
    breaks: true
});

// 转换 mxc:// 链接为 https 链接
function convertMxcToHttp(mxcUrl) {
    if (!mxcUrl.startsWith('mxc://')) {
        return mxcUrl;
    }
    
    const parts = mxcUrl.substring(6).split('/');
    const serverName = parts[0];
    const mediaId = parts[1];
    
    // 使用本地代理路由，避免跨域问题
    return `/_matrix/media/r0/download/${serverName}/${mediaId}`;
}

// 显示客户端界面
function showClient() {
    document.getElementById('loginContainer').classList.add('hidden');
    document.getElementById('clientContainer').classList.remove('hidden');
    loadUserInfo();
    RoomModule.loadRooms();
}

// 加载用户信息
async function loadUserInfo() {
    try {
        const response = await fetch(`/api/profile?session_id=${sessionId}`);
        const data = await response.json();
        
        if (data.success) {
            // 存储 homeserver URL
            if (data.homeserver) {
                homeserverUrl = data.homeserver;
            }
            
            document.getElementById('userInfo').innerHTML = `
                <div>${data.displayname || data.user_id}</div>
                <div style="font-size: 12px; margin-top: 5px;">${data.user_id}</div>
            `;
        } else {
            showError('获取用户信息失败: ' + data.error);
        }
    } catch (e) {
        showError('获取用户信息失败: ' + e.message);
    }
}

// 显示错误信息
function showError(message) {
    const errorDiv = document.getElementById('loginError');
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
    
    setTimeout(() => {
        errorDiv.classList.add('hidden');
    }, 5000);
}

// 显示成功信息
function showSuccess(message) {
    const successDiv = document.getElementById('loginSuccess');
    successDiv.textContent = message;
    successDiv.classList.remove('hidden');
    
    setTimeout(() => {
        successDiv.classList.add('hidden');
    }, 5000);
}

// 显示信息提示
function showInfo(message) {
    const errorDiv = document.getElementById('loginError');
    errorDiv.textContent = message;
    errorDiv.classList.remove('hidden');
    errorDiv.style.background = '#2196F3'; // 蓝色背景表示信息
    
    setTimeout(() => {
        errorDiv.classList.add('hidden');
        // 恢复原来的红色背景
        errorDiv.style.background = '';
    }, 5000);
}

// 导出变量和函数
window.Utils = {
    sessionId,
    currentRoomId,
    homeserverUrl,
    md,
    convertMxcToHttp,
    showClient,
    loadUserInfo,
    showError,
    showSuccess,
    showInfo
};