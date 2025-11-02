#!/usr/bin/env python3
"""
快速测试脚本 - 诊断 E2EE 和图片下载问题

使用方法：
    在 AstrBot 启动后，在 Python 控制台运行：
    
    from astrbot.core.platform.sources.matrix.quick_test import diagnose
    await diagnose()
"""

import asyncio
import logging

logger = logging.getLogger("matrix.quick_test")


async def diagnose():
    """快速诊断 E2EE 和图片下载问题"""
    print("\n" + "="*70)
    print("🔍 Matrix E2EE & 图片下载快速诊断")
    print("="*70)
    
    # 获取 adapter 实例
    try:
        from astrbot.core import AstrBotCore
        core = AstrBotCore.get_instance()
        
        # 查找 Matrix adapter
        adapter = None
        for platform_adapter in core.platform_mgr.platform_adapters:
            if hasattr(platform_adapter, 'client') and hasattr(platform_adapter, 'e2ee_manager'):
                adapter = platform_adapter
                break
        
        if not adapter:
            print("❌ 未找到 Matrix adapter")
            return
        
        print(f"✅ 找到 Matrix adapter: {adapter.user_id}")
        
    except Exception as e:
        print(f"❌ 无法获取 adapter: {e}")
        print("\n💡 请确保 AstrBot 已启动并且 Matrix 适配器已加载")
        return
    
    # 1. 检查 vodozemac
    print("\n" + "-"*70)
    print("1️⃣  检查 vodozemac 库")
    print("-"*70)
    
    try:
        import vodozemac
        print(f"✅ vodozemac 已安装: {vodozemac.__version__ if hasattr(vodozemac, '__version__') else 'unknown'}")
    except ImportError:
        print("❌ vodozemac 未安装")
        print("💡 运行: pip install vodozemac")
        return
    
    # 2. 检查 account 状态
    print("\n" + "-"*70)
    print("2️⃣  检查 E2EE Account 状态")
    print("-"*70)
    
    if not adapter.e2ee_manager:
        print("❌ E2EE manager 未初始化")
        return
    
    if not adapter.e2ee_manager.store:
        print("❌ E2EE store 未初始化")
        return
    
    store_account = adapter.e2ee_manager.store.account
    crypto_account = adapter.e2ee_manager.crypto.account
    
    print(f"Store account: {type(store_account)} - {'✅ OK' if store_account else '❌ None'}")
    print(f"Crypto account: {type(crypto_account)} - {'✅ OK' if crypto_account else '❌ None'}")
    
    if not store_account:
        print("\n❌ 严重错误：store.account 是 None！")
        print("💡 这会导致无法创建 Olm 会话")
        print("💡 尝试重新初始化 E2EE manager")
        return
    
    if not crypto_account:
        print("\n❌ 严重错误：crypto.account 是 None！")
        print("💡 这会导致无法创建 Olm 会话")
        print("💡 检查 e2ee_manager.initialize() 是否正确执行")
        
        # 尝试修复
        print("\n🔧 尝试修复...")
        adapter.e2ee_manager.crypto.account = store_account
        print("✅ 已将 store.account 赋值给 crypto.account")
        
        # 验证修复
        if adapter.e2ee_manager.crypto.account:
            print("✅ 修复成功！")
        else:
            print("❌ 修复失败")
            return
    
    # 3. 获取身份密钥
    print("\n" + "-"*70)
    print("3️⃣  检查身份密钥")
    print("-"*70)
    
    try:
        identity_keys = adapter.e2ee_manager.get_identity_keys()
        if identity_keys:
            print(f"✅ Curve25519: {identity_keys.get('curve25519', 'N/A')[:30]}...")
            print(f"✅ Ed25519: {identity_keys.get('ed25519', 'N/A')[:30]}...")
        else:
            print("❌ 无法获取身份密钥")
    except Exception as e:
        print(f"❌ 获取身份密钥失败: {e}")
    
    # 4. 查询设备
    print("\n" + "-"*70)
    print("4️⃣  查询设备列表")
    print("-"*70)
    
    try:
        response = await adapter.client.query_keys(
            device_keys={adapter.user_id: []}
        )
        device_keys = response.get("device_keys", {}).get(adapter.user_id, {})
        
        print(f"✅ 查询到 {len(device_keys)} 个设备")
        
        for device_id, device_data in device_keys.items():
            keys = device_data.get("keys", {})
            identity_key = keys.get(f"curve25519:{device_id}")
            is_current = device_id == adapter.device_id
            
            print(f"  {'🟢' if is_current else '⚪'} {device_id}")
            print(f"     Identity key: {identity_key[:30] if identity_key else 'N/A'}...")
            
    except Exception as e:
        print(f"❌ 查询设备失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 5. 检查 Olm 会话
    print("\n" + "-"*70)
    print("5️⃣  检查 Olm 会话")
    print("-"*70)
    
    session_count = len(adapter.e2ee_manager.crypto.sessions)
    print(f"当前 Olm 会话数: {session_count}")
    
    if session_count == 0:
        print("⚠️  没有 Olm 会话")
        print("💡 尝试建立会话...")
        
        try:
            created = await adapter.e2ee_manager.auto_setup.get_missing_sessions([adapter.user_id])
            print(f"✅ 建立了 {created} 个 Olm 会话")
        except Exception as e:
            print(f"❌ 建立会话失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("✅ 已有 Olm 会话:")
        for session_key in adapter.e2ee_manager.crypto.sessions.keys():
            print(f"  - {session_key}")
    
    # 6. 测试图片下载
    print("\n" + "-"*70)
    print("6️⃣  测试图片下载")
    print("-"*70)
    
    # 使用一个测试 MXC URL（如果用户提供）
    test_mxc = input("请输入要测试的 MXC URL (或按回车跳过): ").strip()
    
    if test_mxc:
        try:
            print(f"📥 下载: {test_mxc}")
            data = await adapter.client.download_file(test_mxc)
            print(f"✅ 成功下载 {len(data)} 字节")
        except Exception as e:
            print(f"❌ 下载失败: {e}")
    else:
        print("⏭️  跳过图片下载测试")
    
    # 7. 总结
    print("\n" + "="*70)
    print("📊 诊断总结")
    print("="*70)
    
    issues = []
    
    if not store_account:
        issues.append("❌ store.account 是 None")
    if not crypto_account:
        issues.append("❌ crypto.account 是 None")
    if session_count == 0:
        issues.append("⚠️  没有 Olm 会话")
    
    if issues:
        print("发现以下问题：")
        for issue in issues:
            print(f"  {issue}")
        print("\n💡 建议：")
        print("  1. 重启 AstrBot")
        print("  2. 检查日志中的错误信息")
        print("  3. 确保其他设备已上传 E2EE 密钥")
    else:
        print("✅ 所有检查通过！")
    
    print("\n" + "="*70)


if __name__ == "__main__":
    asyncio.run(diagnose())

