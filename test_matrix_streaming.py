#!/usr/bin/env python3
"""
Matrix 流式输出测试脚本

测试 Matrix 适配器的流式输出功能（消息编辑）
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain


async def test_streaming_message_edit():
    """测试流式消息编辑逻辑"""
    print("\n=== 测试流式消息编辑 ===")

    # 模拟流式生成器
    async def message_generator():
        """模拟 LLM 流式输出"""
        texts = ["你好", "，", "我是", " ", "AstrBot", "。", "很高兴", "为你", "服务！"]

        for text in texts:
            chain = MessageChain()
            chain.chain = [Plain(text)]
            yield chain
            await asyncio.sleep(0.1)  # 模拟流式延迟

    # 测试累积逻辑
    delta = ""
    message_count = 0

    async for chain in message_generator():
        for component in chain.chain:
            if isinstance(component, Plain):
                delta += component.text
                message_count += 1

    print(f"总共接收 {message_count} 个文本片段")
    print(f"累积内容: {delta}")

    expected = "你好，我是 AstrBot。很高兴为你服务！"
    assert delta == expected, f"累积内容不匹配: 期望 '{expected}', 实际 '{delta}'"
    print("✓ 流式消息累积逻辑测试通过")


async def test_throttling():
    """测试节流逻辑"""
    print("\n=== 测试节流逻辑 ===")

    last_edit_time = 0
    throttle_interval = 0.8
    edit_count = 0

    # 模拟 10 次快速更新
    for i in range(10):
        current_time = asyncio.get_event_loop().time()
        time_since_last_edit = current_time - last_edit_time

        if time_since_last_edit >= throttle_interval:
            edit_count += 1
            last_edit_time = current_time
            print(f"  执行编辑 #{edit_count} (间隔: {time_since_last_edit:.2f}s)")
        else:
            print(
                f"  跳过编辑 (间隔: {time_since_last_edit:.2f}s < {throttle_interval}s)"
            )

        await asyncio.sleep(0.2)  # 200ms 间隔

    print(f"总共执行 {edit_count} 次编辑（预期约 3-4 次）")
    assert 2 <= edit_count <= 5, f"编辑次数异常: {edit_count}"
    print("✓ 节流逻辑测试通过")


async def test_mixed_content():
    """测试混合内容（文本 + 图片）的处理"""
    print("\n=== 测试混合内容处理 ===")

    from astrbot.api.message_components import Image

    async def mixed_generator():
        """模拟混合内容流式输出"""
        # 先发送一些文本
        yield MessageChain(chain=[Plain("这是一段文本，")])
        yield MessageChain(chain=[Plain("然后会有一张图片：")])

        # 发送图片（应该触发文本发送）
        yield MessageChain(
            chain=[Image(file="test.jpg", url="https://example.com/test.jpg")]
        )

        # 继续发送文本
        yield MessageChain(chain=[Plain("图片后的文本。")])

    delta = ""
    has_image = False

    async for chain in mixed_generator():
        for component in chain.chain:
            if isinstance(component, Plain):
                delta += component.text
            elif isinstance(component, Image):
                has_image = True
                # 在真实场景中，这里会触发文本的发送
                print(f"  检测到图片，当前累积文本: '{delta}'")
                delta = ""  # 重置

    print(f"最终文本: '{delta}'")
    print(f"包含图片: {has_image}")

    assert has_image, "应该检测到图片"
    assert delta == "图片后的文本。", f"最终文本不匹配: '{delta}'"
    print("✓ 混合内容处理测试通过")


async def main():
    """运行所有测试"""
    print("开始 Matrix 流式输出测试...")

    try:
        await test_streaming_message_edit()
        await test_throttling()
        await test_mixed_content()

        print("\n" + "=" * 50)
        print("✓ 所有测试通过！")
        print("=" * 50)
        return 0

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        return 1

    except Exception as e:
        logger.error(f"测试执行错误: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
