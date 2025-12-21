// Matrix Web Client - 主入口文件
// 初始化和事件处理

// 页面加载完成后的初始化
document.addEventListener('DOMContentLoaded', function() {
    // 检查是否有保存的会话
    // 这里可以添加自动登录逻辑
    
    // 添加文件选择事件监听器
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', RoomModule.handleFileSelect);
    }
    
    // 初始化工具函数
    Utils.sessionId = sessionId;
    Utils.currentRoomId = currentRoomId;
    Utils.homeserverUrl = homeserverUrl;
});

// 监听 OAuth2 完成
window.addEventListener('message', function(event) {
    if (event.data.type === 'oauth2_success') {
        // 关闭弹出窗口
        if (window.popup) {
            window.popup.close();
        }
        
        sessionId = event.data.session_id;
        Utils.sessionId = sessionId;
        Utils.showSuccess('OAuth2 登录成功！');
        setTimeout(() => Utils.showClient(), 1000);
    }
});

// 监听会话变化
Object.defineProperty(window, 'sessionId', {
    get: function() { return Utils.sessionId; },
    set: function(value) { 
        Utils.sessionId = value;
        // 通知所有模块会话已更改
        console.log('Session ID updated:', value);
    }
});

Object.defineProperty(window, 'currentRoomId', {
    get: function() { return Utils.currentRoomId; },
    set: function(value) { 
        Utils.currentRoomId = value;
        // 通知房间模块房间已更改
        console.log('Current room ID updated:', value);
    }
});