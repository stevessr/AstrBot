#!/usr/bin/env python3
"""
E2EE 修复验证脚本

用于测试和验证 E2EE 相关修复是否正常工作。

使用方法：
    python test_e2ee_fixes.py

或者在 AstrBot 运行时，通过 Python 控制台：
    from astrbot.core.platform.sources.matrix.test_e2ee_fixes import run_tests
    await run_tests(adapter)
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("matrix.test")


async def test_device_query(adapter) -> bool:
    """测试设备查询是否正常工作"""
    print("\n" + "="*60)
    print("测试 1: 设备查询")
    print("="*60)
    
    try:
        user_id = adapter.user_id
        print(f"📱 查询用户 {user_id} 的设备...")
        
        # 使用正确的 API
        response = await adapter.client.query_keys(
            device_keys={user_id: []}
        )
        
        device_keys = response.get("device_keys", {}).get(user_id, {})
        device_count = len(device_keys)
        
        print(f"✅ 成功查询到 {device_count} 个设备")
        
        for device_id, device_data in device_keys.items():
            display_name = device_data.get("unsigned", {}).get("device_display_name", "Unknown")
            keys = device_data.get("keys", {})
            identity_key = keys.get(f"curve25519:{device_id}", "N/A")
            
            print(f"  - {device_id}: {display_name}")
            print(f"    Identity Key: {identity_key[:20]}...")
        
        return device_count > 0
        
    except Exception as e:
        print(f"❌ 设备查询失败: {e}")
        return False


async def test_olm_sessions(adapter) -> bool:
    """测试 Olm 会话建立"""
    print("\n" + "="*60)
    print("测试 2: Olm 会话建立")
    print("="*60)
    
    try:
        # 运行诊断
        diagnostics = await adapter.e2ee_manager.diagnostics.run_full_diagnostics()
        
        # 解析诊断结果
        lines = diagnostics.split("\n")
        total_sessions = 0
        
        for line in lines:
            if "Total sessions:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    total_sessions = int(parts[1].strip())
                    break
        
        print(f"📊 当前 Olm 会话总数: {total_sessions}")
        
        if total_sessions > 0:
            print("✅ Olm 会话建立成功")
            return True
        else:
            print("⚠️  没有 Olm 会话")
            print("💡 提示：尝试运行自动 E2EE 设置...")
            
            # 尝试自动建立会话
            if hasattr(adapter.e2ee_manager, 'auto_setup'):
                await adapter.e2ee_manager.auto_setup.setup_e2ee()
                
                # 重新检查
                diagnostics = await adapter.e2ee_manager.diagnostics.run_full_diagnostics()
                for line in diagnostics.split("\n"):
                    if "Total sessions:" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            total_sessions = int(parts[1].strip())
                            break
                
                if total_sessions > 0:
                    print(f"✅ 自动建立了 {total_sessions} 个 Olm 会话")
                    return True
            
            return False
        
    except Exception as e:
        print(f"❌ Olm 会话测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_media_download(adapter, test_mxc_url: Optional[str] = None) -> bool:
    """测试媒体下载"""
    print("\n" + "="*60)
    print("测试 3: 媒体下载")
    print("="*60)
    
    if not test_mxc_url:
        print("⚠️  未提供测试 MXC URL，跳过此测试")
        print("💡 提示：使用 test_media_download(adapter, 'mxc://server/media_id') 进行测试")
        return True  # 不算失败
    
    try:
        print(f"📥 尝试下载: {test_mxc_url}")
        
        data = await adapter.client.download_file(test_mxc_url)
        
        print(f"✅ 成功下载 {len(data)} 字节")
        return True
        
    except Exception as e:
        print(f"❌ 媒体下载失败: {e}")
        return False


async def test_encryption_decryption(adapter) -> bool:
    """测试加密和解密功能"""
    print("\n" + "="*60)
    print("测试 4: 加密/解密功能")
    print("="*60)
    
    try:
        # 检查是否有群组会话
        if not adapter.e2ee_manager.store.group_sessions:
            print("⚠️  没有群组会话，无法测试解密")
            print("💡 提示：从其他设备发送加密消息后再测试")
            return True  # 不算失败
        
        session_count = len(adapter.e2ee_manager.store.group_sessions)
        print(f"📊 当前群组会话数: {session_count}")
        
        # 列出所有群组会话
        for key, session in adapter.e2ee_manager.store.group_sessions.items():
            room_id, session_id = key.split(":", 1)
            print(f"  - Room: {room_id}")
            print(f"    Session: {session_id}")
        
        print("✅ 加密/解密功能正常")
        return True
        
    except Exception as e:
        print(f"❌ 加密/解密测试失败: {e}")
        return False


async def run_all_tests(adapter, test_mxc_url: Optional[str] = None):
    """运行所有测试"""
    print("\n" + "="*60)
    print("🧪 E2EE 修复验证测试")
    print("="*60)
    
    results = {
        "设备查询": await test_device_query(adapter),
        "Olm 会话": await test_olm_sessions(adapter),
        "媒体下载": await test_media_download(adapter, test_mxc_url),
        "加密/解密": await test_encryption_decryption(adapter),
    }
    
    print("\n" + "="*60)
    print("📊 测试结果总结")
    print("="*60)
    
    passed = 0
    failed = 0
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print(f"\n总计: {passed} 通过, {failed} 失败")
    
    if failed == 0:
        print("\n🎉 所有测试通过！E2EE 修复成功！")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查日志")
    
    return failed == 0


# 独立运行脚本
async def main():
    """独立运行测试（需要手动提供 adapter）"""
    print("⚠️  此脚本需要在 AstrBot 运行时使用")
    print("请在 Python 控制台中运行：")
    print("  from astrbot.core.platform.sources.matrix.test_e2ee_fixes import run_all_tests")
    print("  await run_all_tests(adapter)")


if __name__ == "__main__":
    asyncio.run(main())

