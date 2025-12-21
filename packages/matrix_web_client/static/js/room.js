// Matrix Web Client - 房间和消息模块
// 处理房间列表、消息显示和发送功能

// 加载房间列表
async function loadRooms() {
    try {
        const response = await fetch(`/api/rooms?session_id=${sessionId}`);
        const data = await response.json();
        
        if (data.success) {
            const roomList = document.getElementById('roomList');
            roomList.innerHTML = '';
            
            data.rooms.forEach(room => {
                const roomItem = document.createElement('div');
                roomItem.className = 'room-item';
                roomItem.onclick = () => selectRoom(room.room_id);
                
                roomItem.innerHTML = `
                    <div class="room-name">${room.name}</div>
                    <div class="room-last-message">${room.last_message || '暂无消息'}</div>
                `;
                
                roomList.appendChild(roomItem);
            });
        } else {
            showError('获取房间列表失败: ' + data.error);
        }
    } catch (e) {
        showError('获取房间列表失败: ' + e.message);
    }
}

// 选择房间
async function selectRoom(roomId) {
    currentRoomId = roomId;
    
    // 更新活动房间
    document.querySelectorAll('.room-item').forEach(item => {
        item.classList.remove('active');
    });
    event.currentTarget.classList.add('active');
    
    // 显示消息输入框
    document.getElementById('messageInput').classList.remove('hidden');
    
    // 加载房间消息
    loadMessages();
}

// 加载房间消息
async function loadMessages() {
    try {
        const response = await fetch(`/api/room/${currentRoomId}/messages?session_id=${sessionId}&limit=50`);
        const data = await response.json();
        
        if (data.success) {
            const messagesContainer = document.getElementById('messages');
            messagesContainer.innerHTML = '';
            
            // 反向显示消息（最新的在底部）
            data.messages.reverse().forEach(message => {
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${message.sender === getCurrentUserId() ? 'own' : ''}`;
                
                const content = message.content;
                let messageContent = '';
                
                if (content.msgtype === 'm.text') {
                    // 支持 Markdown 渲染
                    messageContent = md.render(content.body);
                } else if (content.msgtype === 'm.image') {
                    // 转换 mxc:// 链接为 https 链接
                    let imageUrl = content.url;
                    if (imageUrl.startsWith('mxc://')) {
                        imageUrl = convertMxcToHttp(imageUrl);
                    }
                    messageContent = `<img src="${imageUrl}" alt="${content.body}" />`;
                } else if (content.msgtype === 'm.file') {
                    // 转换 mxc:// 链接为 https 链接
                    let fileUrl = content.url;
                    if (fileUrl.startsWith('mxc://')) {
                        fileUrl = convertMxcToHttp(fileUrl);
                    }
                    messageContent = `<a href="${fileUrl}" class="file-attachment">📄 ${content.body}</a>`;
                } else {
                    messageContent = content.body;
                }
                
                messageDiv.innerHTML = `
                    <div class="message-sender">${message.sender}</div>
                    <div class="message-content">${messageContent}</div>
                    <div class="message-time">${new Date(message.timestamp).toLocaleString()}</div>
                `;
                
                messagesContainer.appendChild(messageDiv);
            });
            
            // 滚动到底部
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        } else {
            showError('获取消息失败: ' + data.error);
        }
    } catch (e) {
        showError('获取消息失败: ' + e.message);
    }
}

// 获取当前用户 ID
function getCurrentUserId() {
    // 从用户信息中获取
    const userInfo = document.getElementById('userInfo').textContent;
    const match = userInfo.match(/@[^:]+:[^)]+/);
    return match ? match[0] : null;
}

// 文件上传相关变量
let selectedFile = null;
let filePreview = null;

// 处理文件选择
function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    selectedFile = file;
    
    // 创建预览
    const reader = new FileReader();
    reader.onload = function(e) {
        const previewContainer = document.getElementById('filePreview') || createFilePreviewContainer();
        
        if (file.type.startsWith('image/')) {
            previewContainer.innerHTML = `
                <div class="file-preview">
                    <img src="${e.target.result}" alt="预览" style="max-width: 200px; max-height: 200px; border-radius: 8px;">
                    <div class="file-info">
                        <div>${file.name}</div>
                        <div>${formatFileSize(file.size)}</div>
                        <button onclick="clearFileSelection()" style="margin-top: 5px; padding: 4px 8px; background: #f44336; color: white; border: none; border-radius: 4px; cursor: pointer;">✕</button>
                    </div>
                </div>
            `;
        } else {
            previewContainer.innerHTML = `
                <div class="file-preview">
                    <div class="file-icon">📄</div>
                    <div class="file-info">
                        <div>${file.name}</div>
                        <div>${formatFileSize(file.size)}</div>
                        <button onclick="clearFileSelection()" style="margin-top: 5px; padding: 4px 8px; background: #f44336; color: white; border: none; border-radius: 4px; cursor: pointer;">✕</button>
                    </div>
                </div>
            `;
        }
    };
    
    reader.readAsDataURL(file);
}

// 创建文件预览容器
function createFilePreviewContainer() {
    const container = document.createElement('div');
    container.id = 'filePreview';
    container.style.cssText = 'margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 8px;';
    
    const messageInput = document.getElementById('messageInput');
    messageInput.insertBefore(container, messageInput.firstChild);
    
    return container;
}

// 清除文件选择
function clearFileSelection() {
    selectedFile = null;
    const previewContainer = document.getElementById('filePreview');
    if (previewContainer) {
        previewContainer.remove();
    }
    document.getElementById('fileInput').value = '';
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// 上传文件
async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);
    
    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            return data.content_uri;
        } else {
            throw new Error(data.error || '上传失败');
        }
    } catch (e) {
        throw new Error('上传文件失败: ' + e.message);
    }
}

// 发送消息
async function sendMessage() {
    const input = document.getElementById('messageText');
    const message = input.value.trim();
    
    // 如果有选择的文件，先上传
    if (selectedFile) {
        try {
            showSuccess('正在上传文件...');
            const contentUri = await uploadFile(selectedFile);
            
            // 确定消息类型
            let msgtype = 'm.file';
            let info = {};
            
            if (selectedFile.type.startsWith('image/')) {
                msgtype = 'm.image';
                info = {
                    mimetype: selectedFile.type,
                    size: selectedFile.size,
                    // 如果是图片，可以添加宽高信息
                };
            } else if (selectedFile.type.startsWith('video/')) {
                msgtype = 'm.video';
                info = {
                    mimetype: selectedFile.type,
                    size: selectedFile.size,
                };
            } else if (selectedFile.type.startsWith('audio/')) {
                msgtype = 'm.audio';
                info = {
                    mimetype: selectedFile.type,
                    size: selectedFile.size,
                };
            } else {
                info = {
                    mimetype: selectedFile.type || 'application/octet-stream',
                    size: selectedFile.size,
                };
            }
            
            // 发送文件消息
            const response = await fetch(`/api/room/${currentRoomId}/send?session_id=${sessionId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    message: selectedFile.name,
                    msgtype: msgtype,
                    url: contentUri,
                    info: info
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                clearFileSelection();
                input.value = '';
                // 重新加载消息
                loadMessages();
            } else {
                showError('发送文件失败: ' + data.error);
            }
        } catch (e) {
            showError(e.message);
        }
    } else if (message) {
        // 发送文本消息
        try {
            const response = await fetch(`/api/room/${currentRoomId}/send?session_id=${sessionId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    message: message,
                    msgtype: 'm.text'
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                input.value = '';
                // 重新加载消息
                loadMessages();
            } else {
                showError('发送消息失败: ' + data.error);
            }
        } catch (e) {
            showError('发送消息失败: ' + e.message);
        }
    }
}

// 处理消息输入框回车事件
function handleMessageKeyPress(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// 导出函数
window.RoomModule = {
    loadRooms,
    selectRoom,
    loadMessages,
    getCurrentUserId,
    handleFileSelect,
    clearFileSelection,
    formatFileSize,
    uploadFile,
    sendMessage,
    handleMessageKeyPress
};