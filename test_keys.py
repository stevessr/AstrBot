#!/usr/bin/env python3
import hashlib
import json
import requests
import vodozemac
from pickle_key_generator import generate_pickle_key

# ================= 配置区域 =================
# 设置代理地址
PROXY_URL = "http://127.0.0.1:7897"

# 构造标准 requests 代理字典
# 确保 http 和 https 请求都走此代理
PROXIES = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}
# ===========================================


def get_server_keys_as_str(auth):
    """从服务器获取设备 Keys，并强制转换为字符串以防止对象类型干扰"""
    print(f"Connecting to {auth['home_server']} via proxy...")

    try:
        resp = requests.post(
            f"{auth['home_server']}/_matrix/client/v3/keys/query",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {auth['access_token']}",
            },
            json={"device_keys": {auth["user_id"]: []}},
            proxies=PROXIES,  # 使用上方定义的全局代理配置
            timeout=10,  # 代理连接通常较慢，建议稍微增加超时时间
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Network Error: {e}")
        # 打印更多调试信息帮助排查代理问题
        if "ProxyError" in str(e):
            print(
                "Tip: Check if your proxy software (Clash/v2ray) is running and allows LAN connections."
            )
        exit(1)

    print(f"Status: {resp.status_code}")
    # === 关键步骤：直接打印服务器发回来的原始文本 ===
    print("\n=== RAW RESPONSE (Server Output) ===")
    print(resp.text)
    print("======================================\n")

    data = json.loads(resp.text)
    raw_keys = data.get("device_keys", {}).get(auth["user_id"], {}).get(auth["device_id"], {}).get("keys", {})

    clean_keys = {}
    print("=== Server Keys (Processed) ===")
    for k, v in raw_keys.items():
        if k.startswith("ed25519"):
            val_str = vodozemac.Ed25519PublicKey.from_base64(v).to_base64()
        elif k.startswith("curve25519"):
            val_str = vodozemac.Curve25519PublicKey.from_base64(v).to_base64()
        else:
            val_str = str(v)

        clean_keys[k] = val_str
        print(f"  {k}: {val_str}")

    return clean_keys


# ================= 主流程 =================

# 1. 读取 Auth
try:
    with open("data/matrix_store/chatbot_neko.aaca.eu.org/auth.json") as f:
        auth = json.load(f)
except FileNotFoundError:
    print("❌ Error: auth.json not found.")
    exit(1)

print(f"User: {auth['user_id']}")
print(f"Device: {auth['device_id']}")
print()

# 2. 获取服务器 Keys (带代理)
server_keys = get_server_keys_as_str(auth)

# 3. 读取本地 Olm 数据
try:
    with open("data/matrix_e2ee/@chatbot_neko.aaca.eu.org/olm_account.json") as f:
        olm_data = json.load(f)
except FileNotFoundError:
    print("❌ Error: olm_account.json not found.")
    exit(1)

pickle = olm_data.get("pickle", "")
pickle_key = generate_pickle_key(auth["user_id"], auth["device_id"])

# 4. 尝试解密
try:
    account = vodozemac.Account.from_pickle(pickle, pickle_key)
    print("\n🔓 Decryption Success!")
except Exception as e:
    print(f"\n❌ Decryption failed: {e}")
    account = None

if not account:
    print("\n❌ All decryption strategies failed.")
    print("Possibilities:")
    print("1. The pickle uses a different passphrase.")
    print("2. The pickle key derivation is custom (e.g. PBKDF2).")
    exit(1)

# 5. 比较 Keys
local_curve = account.curve25519_key.to_base64()
local_ed = account.ed25519_key.to_base64()

print("\n=== Local Keys ===")
print(f"  curve25519:{auth['device_id']}: {local_curve}")
print(f"  ed25519:{auth['device_id']}: {local_ed}")

print("\n=== Comparison ===")
s_curve = server_keys.get(f"curve25519:{auth['device_id']}", "MISSING")
s_ed = server_keys.get(f"ed25519:{auth['device_id']}", "MISSING")


def check(name, local, server):
    if local == server:
        print(f"  {name}: ✅ MATCH")
    else:
        print(f"  {name}: ❌ MISMATCH")
        print(f"    Local:  {local}")
        print(f"    Server: {server}")


check("curve25519", local_curve, s_curve)
check("ed25519", local_ed, s_ed)
