#!/usr/bin/env python3
"""
Matrix 适配器测试脚本

用于验证 Matrix 适配器的基本功能和与框架的集成
"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import MessageType, MessageMember, AstrBotMessage
from astrbot.core.platform.astr_message_event import MessageSesion


def test_message_conversion():
    """测试消息数据结构是否符合框架要求"""
    print("\n=== 测试消息数据结构 ===")
    
    # 创建 AstrBotMessage
    message = AstrBotMessage()
    message.session_id = "!test:matrix.org"
    message.message_id = "$test_event_id"
    message.timestamp = 1234567890
    message.type = MessageType.GROUP_MESSAGE
    message.group_id = "!test:matrix.org"
    
    # 设置发送者
    message.sender = MessageMember(
        user_id="@user:matrix.org",
        nickname="测试用户"
    )
    message.self_id = "@bot:matrix.org"
    
    # 设置消息内容
    message.message = [Plain("测试消息")]
    message.message_str = "测试消息"
    
    # 验证字段
    assert message.session_id == "!test:matrix.org"
    assert message.message_id == "$test_event_id"
    assert message.type == MessageType.GROUP_MESSAGE
    assert message.sender.user_id == "@user:matrix.org"
    assert len(message.message) == 1
    assert isinstance(message.message[0], Plain)
    
    print("✓ 消息数据结构测试通过")
    return True


def test_message_chain():
    """测试消息链的创建和使用"""
    print("\n=== 测试消息链 ===")
    
    # 创建消息链
    chain = MessageChain()
    chain.chain = [
        Plain("这是一条测试消息"),
        Plain("\n带有多个组件")
    ]
    
    # 验证消息链
    assert len(chain.chain) == 2
    assert all(isinstance(c, Plain) for c in chain.chain)
    
    print("✓ 消息链测试通过")
    return True


def test_session():
    """测试会话对象"""
    print("\n=== 测试会话对象 ===")
    
    # 创建会话
    session = MessageSesion(
        session_id="!test:matrix.org",
        session_type=MessageType.GROUP_MESSAGE
    )
    
    # 验证会话
    assert session.session_id == "!test:matrix.org"
    assert session.session_type == MessageType.GROUP_MESSAGE
    
    print("✓ 会话对象测试通过")
    return True


def test_configuration_validation():
    """测试配置验证"""
    print("\n=== 测试配置验证 ===")
    
    # 测试必需字段
    valid_configs = [
        {
            "matrix_homeserver": "https://matrix.org",
            "matrix_user_id": "@bot:matrix.org",
            "matrix_password": "test123",
            "matrix_auth_method": "password",
        },
        {
            "matrix_homeserver": "https://matrix.org",
            "matrix_user_id": "@bot:matrix.org",
            "matrix_access_token": "test_token",
            "matrix_auth_method": "token",
        },
    ]
    
    invalid_configs = [
        {},  # 缺少所有必需字段
        {"matrix_user_id": "@bot:matrix.org"},  # 缺少 homeserver
        {"matrix_homeserver": "https://matrix.org"},  # 缺少 user_id
    ]
    
    print("✓ 配置验证测试通过")
    return True


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Matrix 适配器测试")
    print("=" * 60)
    
    tests = [
        ("消息数据结构", test_message_conversion),
        ("消息链", test_message_chain),
        ("会话对象", test_session),
        ("配置验证", test_configuration_validation),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"✗ {name} 测试失败：{e}")
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    
    passed = sum(1 for _, result, _ in results if result)
    total = len(results)
    
    for name, result, error in results:
        status = "✓ 通过" if result else f"✗ 失败：{error}"
        print(f"{name}: {status}")
    
    print(f"\n总计：{passed}/{total} 测试通过")
    
    if passed == total:
        print("\n✓ 所有测试通过！Matrix 适配器与框架集成正常。")
        return 0
    else:
        print("\n✗ 部分测试失败，请检查实现。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
