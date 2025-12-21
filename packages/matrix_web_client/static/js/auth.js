// Matrix Web Client - 认证模块
// 处理登录相关的功能

// 标签页切换
function switchTab(tabName) {
    // 更新标签
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    
    event.target.classList.add('active');
    document.getElementById(tabName + 'Tab').classList.add('active');
    
    // 如果切换到 AstrBot 配置标签，加载配置
    if (tabName === 'astrbot') {
        loadAstrBotConfigs();
    }
}

// 加载 AstrBot 配置
async function loadAstrBotConfigs() {
    const select = document.getElementById('astrbotConfigSelect');
    select.innerHTML = '<option value="">加载中...</option>';
    
    try {
        const response = await fetch('/api/astrbot-config');
        const data = await response.json();
        
        if (data.success) {
            select.innerHTML = '';
            
            if (data.matrix_configs.length === 0) {
                select.innerHTML = '<option value="">没有找到启用的 Matrix 配置</option>';
            } else {
                data.matrix_configs.forEach(config => {
                    const option = document.createElement('option');
                    option.value = config.id;
                    option.textContent = `${config.name} (${config.user_id})`;
                    option.dataset.homeserver = config.homeserver;
                    option.dataset.userId = config.user_id;
                    option.dataset.authMethod = config.auth_method;
                    option.dataset.e2eeEnabled = config.enable_e2ee;
                    select.appendChild(option);
                });
            }
        } else {
            select.innerHTML = '<option value="">加载失败: ' + data.error + '</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">加载失败: ' + e.message + '</option>';
    }
}

// 密码登录
async function loginWithPassword() {
    const homeserver = document.getElementById('homeserver1').value;
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    
    if (!homeserver || !username || !password) {
        showError('请填写所有字段');
        return;
    }
    
    try {
        const response = await fetch('/api/login/password', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({homeserver, username, password})
        });
        
        const data = await response.json();
        
        if (data.success) {
            sessionId = data.session_id;
            showSuccess('登录成功！');
            setTimeout(() => showClient(), 1000);
        } else {
            showError('登录失败: ' + data.error);
        }
    } catch (e) {
        showError('登录失败: ' + e.message);
    }
}

// Token 登录
async function loginWithToken() {
    const homeserver = document.getElementById('homeserver2').value;
    const accessToken = document.getElementById('accessToken').value;
    const userId = document.getElementById('userId').value;
    
    if (!homeserver || !accessToken) {
        showError('请填写 Homeserver 和 Access Token');
        return;
    }
    
    try {
        const response = await fetch('/api/login/token', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({homeserver, access_token: accessToken, user_id: userId})
        });
        
        const data = await response.json();
        
        if (data.success) {
            sessionId = data.session_id;
            showSuccess('登录成功！');
            setTimeout(() => showClient(), 1000);
        } else {
            showError('登录失败: ' + data.error);
        }
    } catch (e) {
        showError('登录失败: ' + e.message);
    }
}

// AstrBot 配置登录
async function loginWithAstrBotConfig() {
    const select = document.getElementById('astrbotConfigSelect');
    const configId = select.value;
    
    if (!configId) {
        showError('请选择一个配置');
        return;
    }
    
    try {
        const response = await fetch('/api/login/astrbot-config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({config_id: configId})
        });
        
        const data = await response.json();
        
        if (data.success) {
            sessionId = data.session_id;
            const selectedOption = select.options[select.selectedIndex];
            const configName = selectedOption.textContent;
            const e2eeEnabled = selectedOption.dataset.e2eeEnabled === 'true';
            
            let successMessage = `登录成功！使用配置: ${configName}`;
            if (e2eeEnabled) {
                successMessage += ' (已启用端到端加密)';
            }
            
            showSuccess(successMessage);
            setTimeout(() => showClient(), 1000);
        } else {
            showError('登录失败: ' + data.error);
        }
    } catch (e) {
        showError('登录失败: ' + e.message);
    }
}

// OAuth2 登录
async function loginWithOAuth2() {
    const homeserver = document.getElementById('homeserver3').value;
    
    if (!homeserver) {
        showError('请填写 Homeserver');
        return;
    }
    
    // 检查是否是 matrix.org，提醒用户
    if (homeserver === 'https://matrix.org' || homeserver === 'https://matrix-client.matrix.org') {
        showInfo('提示：您正在使用 matrix.org，它支持 OAuth2 登录。如果您想连接到其他服务器，请确保该服务器支持 OAuth2。');
    }
    
    try {
        const response = await fetch('/api/login/oauth2/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({homeserver})
        });
        
        const data = await response.json();
        
        if (data.success) {
            // 打开 OAuth2 授权窗口
            const popup = window.open(
                data.authorization_url,
                'oauth2_login',
                'width=500,height=600,scrollbars=yes,resizable=yes'
            );
            
            // 监听 OAuth2 完成
            window.addEventListener('message', function(event) {
                if (event.data.type === 'oauth2_success') {
                    popup.close();
                    sessionId = event.data.session_id;
                    showSuccess('OAuth2 登录成功！');
                    setTimeout(() => showClient(), 1000);
                }
            });
        } else {
            showError('OAuth2 启动失败: ' + data.error);
        }
    } catch (e) {
        showError('OAuth2 登录失败: ' + e.message);
    }
}

// 导出函数
window.AuthModule = {
    switchTab,
    loadAstrBotConfigs,
    loginWithPassword,
    loginWithToken,
    loginWithAstrBotConfig,
    loginWithOAuth2
};