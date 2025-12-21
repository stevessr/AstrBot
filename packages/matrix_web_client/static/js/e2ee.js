// Matrix Web Client - E2EE 和设备管理模块
// 处理端到端加密和设备验证功能

// 密钥管理
async function showKeyManagement() {
    if (!sessionId) {
        showError('请先登录');
        return;
    }
    
    try {
        // 获取设备列表
        const devicesResponse = await fetch(`/api/devices?session_id=${sessionId}`);
        const devicesData = await devicesResponse.json();
        
        let devicesHtml = '';
        if (devicesData.success) {
            // 获取当前用户ID
            const userInfo = document.getElementById('userInfo').textContent;
            const match = userInfo.match(/@[^:]+:[^)]+/);
            const currentUserId = match ? match[0] : null;
            
            devicesData.devices.forEach(device => {
                const status = device.verified ? 'verified' : 'unverified';
                const statusText = device.verified ? '已验证' : '未验证';
                
                // 判断是否是当前用户的设备
                const isOwnDevice = device.device_id && device.device_id.startsWith(currentUserId?.split(':')[0]?.substring(1));
                
                devicesHtml += `
                    <div class="device-item">
                        <div class="device-name">${device.display_name || device.device_id}</div>
                        <div class="device-info">ID: ${device.device_id}</div>
                        <div class="device-info">最后显示: ${device.last_seen ? new Date(device.last_seen_ts).toLocaleString() : '未知'}</div>
                        <span class="device-status ${status}">${statusText}</span>
                        ${!device.verified ? `<button class="verify-btn" onclick="verifyDevice('${device.device_id.replace(/'/g, "\\'"})', ${isOwnDevice ? 'null' : `'${currentUserId}'`})">验证设备</button>` : ''}
                    </div>
                `;
            });
        }
        
        // 获取 E2EE 状态
        let e2eeStatusHtml = '';
        try {
            const e2eeResponse = await fetch(`/api/e2ee/status?session_id=${sessionId}`);
            const e2eeData = await e2eeResponse.json();
            
            if (e2eeData.success) {
                const status = e2eeData.e2ee_enabled ? 'enabled' : 'disabled';
                const statusText = e2eeData.e2ee_enabled ? '已启用' : '未启用';
                
                e2eeStatusHtml = `
                    <div class="e2ee-status ${status}">
                        端到端加密: ${statusText}
                    </div>
                `;
                
                if (!e2eeData.e2ee_enabled) {
                    e2eeStatusHtml += `
                        <button class="btn" onclick="initializeE2EE()" style="margin-top: 10px;">
                            初始化端到端加密
                        </button>
                    `;
                }
            }
        } catch (e) {
            e2eeStatusHtml = '<div class="error">获取 E2EE 状态失败</div>';
        }
        
        // 显示模态框
        document.getElementById('keyManagementModal').style.display = 'block';
        document.getElementById('deviceList').innerHTML = devicesHtml || '<div class="loading">没有找到设备</div>';
        document.getElementById('e2eeStatusContainer').innerHTML = e2eeStatusHtml;
        
    } catch (e) {
        showError('获取密钥信息失败: ' + e.message);
    }
}

// 关闭模态框
function closeModal() {
    document.getElementById('keyManagementModal').style.display = 'none';
}

// 初始化 E2EE
async function initializeE2EE() {
    try {
        const response = await fetch(`/api/e2ee/initialize?session_id=${sessionId}`, {
            method: 'POST'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showSuccess('E2EE 初始化成功！');
            // 刷新密钥管理界面
            showKeyManagement();
        } else {
            showError('E2EE 初始化失败: ' + data.error);
        }
    } catch (e) {
        showError('E2EE 初始化失败: ' + e.message);
    }
}

// 验证设备
async function verifyDevice(deviceId, userId = null) {
    console.log('verifyDevice called with deviceId:', deviceId, 'userId:', userId);

    if (!sessionId) {
        console.error('No session ID');
        showError('请先登录');
        return;
    }

    try {
        console.log('Sending verify request for device:', deviceId);
        const requestBody = {};
        if (userId) {
            requestBody.user_id = userId;
        }

        const response = await fetch(`/api/devices/${deviceId}/verify?session_id=${sessionId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });

        console.log('Verify response status:', response.status);
        const data = await response.json();
        console.log('Verify response data:', data);

        if (data.success) {
            if (data.requires_interaction) {
                // 需要交互式验证（如 SAS）
                showInfo(data.message);
                currentSasTransactionId = data.transaction_id;
                startSasPolling(data.transaction_id);
            } else {
                showSuccess(data.message);
            }
            // 刷新设备列表
            showKeyManagement();
        } else {
            showError('验证设备失败: ' + data.error);
        }
    } catch (e) {
        console.error('Verify device error:', e);
        showError('验证设备失败: ' + e.message);
    }
}

let currentSasTransactionId = null;
let sasPollInterval = null;

function startSasPolling(transactionId) {
    if (sasPollInterval) clearInterval(sasPollInterval);

    // 打开模态框显示加载状态
    const modal = document.getElementById('sasVerificationModal');
    if (modal) {
        modal.style.display = 'block';
        document.getElementById('sasEmojis').innerHTML = '<div class="loading">等待密钥交换...</div>';
    }

    let attempts = 0;
    sasPollInterval = setInterval(async () => {
        attempts++;
        if (attempts > 60) { // 60 seconds timeout
            clearInterval(sasPollInterval);
            if (document.getElementById('sasVerificationModal').style.display === 'block') {
                showError('验证超时');
                closeSasModal();
            }
            return;
        }

        try {
            const response = await fetch(`/api/devices/verification/${transactionId}/info?session_id=${sessionId}`);
            const data = await response.json();

            if (data.success && data.info && data.info.sas) {
                clearInterval(sasPollInterval);
                displaySas(data.info.sas);
            }
        } catch (e) {
            console.error('Polling error:', e);
        }
    }, 1000);
}

function displaySas(sasData) {
    const emojisDiv = document.getElementById('sasEmojis');
    const decimalsDiv = document.getElementById('sasDecimals');

    if (sasData.emojis) {
        let html = '';
        sasData.emojis.forEach(item => {
            html += `
                <div style="display: flex; flex-direction: column; align-items: center; width: 60px;">
                    <span style="font-size: 32px;">${item.emoji}</span>
                    <span style="font-size: 12px; margin-top: 5px;">${item.name}</span>
                </div>
            `;
        });
        emojisDiv.innerHTML = html;
        emojisDiv.style.display = 'flex';
        decimalsDiv.style.display = 'none';
    } else if (sasData.decimal) {
        decimalsDiv.textContent = sasData.decimal.join(' ');
        decimalsDiv.style.display = 'block';
        emojisDiv.style.display = 'none';
    }
}

async function confirmSas() {
    if (!currentSasTransactionId) return;

    try {
        const response = await fetch(`/api/devices/verification/${currentSasTransactionId}/confirm?session_id=${sessionId}`, {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            showSuccess('设备验证成功！');
            closeSasModal();
            showKeyManagement(); // Refresh device list
        } else {
            showError('验证确认失败: ' + data.error);
        }
    } catch (e) {
        showError('验证确认失败: ' + e.message);
    }
}

function cancelSas() {
    // TODO: implement cancel endpoint
    closeSasModal();
}

function closeSasModal() {
    const modal = document.getElementById('sasVerificationModal');
    if (modal) modal.style.display = 'none';

    if (sasPollInterval) clearInterval(sasPollInterval);
    currentSasTransactionId = null;
}

// 点击模态框外部关闭
window.onclick = function(event) {
    const modal = document.getElementById('keyManagementModal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }

    const sasModal = document.getElementById('sasVerificationModal');
    if (event.target === sasModal) {
        // SAS 验证过程中不建议点击外部关闭，但为了用户体验允许
        // closeSasModal();
    }
}

// 导出函数
window.E2EEModule = {
    showKeyManagement,
    closeModal,
    closeSasModal,
    initializeE2EE,
    verifyDevice,
    confirmSas,
    cancelSas
};