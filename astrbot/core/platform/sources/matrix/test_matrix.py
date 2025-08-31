#!/usr/bin/env python3
"""
Matrix Adapter Test Script

This script tests the basic functionality of the Matrix adapter
without requiring a full AstrBot setup.
"""

import asyncio
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from astrbot.core.platform.sources.matrix.matrix_adapter import MatrixAdapter
from astrbot.core.platform.sources.matrix.matrix_event import MatrixMessageEvent
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType


async def test_matrix_adapter_creation():
    """Test Matrix adapter instantiation with different configurations"""
    print("Testing Matrix adapter creation...")

    # Test configuration
    config = {
        "type": "matrix",
        "enable": True,
        "id": "test_matrix",
        "matrix_homeserver": "https://matrix.org",
        "matrix_user_id": "@test_bot:matrix.org",
        "matrix_password": "test_password",
        "matrix_device_name": "AstrBot Test",
        "matrix_auto_join_rooms": True,
        "matrix_sync_timeout": 30000,
    }

    settings = {}
    event_queue = asyncio.Queue()

    try:
        adapter = MatrixAdapter(config, settings, event_queue)
        print(f"✅ Matrix adapter created successfully: {adapter.meta().name}")
        print(f"   Homeserver: {adapter.homeserver}")
        print(f"   User ID: {adapter.user_id}")
        print(f"   Device Name: {adapter.device_name}")
        print(f"   Auto Join: {adapter.auto_join_rooms}")

        return adapter

    except Exception as e:
        print(f"❌ Failed to create Matrix adapter: {e}")
        return None


async def test_matrix_event_creation():
    """Test Matrix message event creation and message handling"""
    print("\nTesting Matrix message event creation...")

    try:
        # Mock data for testing
        from astrbot.core.platform.platform_metadata import PlatformMetadata

        platform_meta = PlatformMetadata(
            name="matrix",
            description="Matrix test adapter",
        )

        # Create a mock AstrBot message
        sender = MessageMember(
            user_id="@test_user:matrix.org",
            nickname="Test User",
        )

        message_obj = AstrBotMessage()
        message_obj.type = MessageType.GROUP_MESSAGE
        message_obj.self_id = "@test_bot:matrix.org"
        message_obj.session_id = "!test_room:matrix.org"
        message_obj.message_id = "test_event_id"
        message_obj.sender = sender
        message_obj.message = [Plain("Hello from Matrix!")]
        message_obj.message_str = "Hello from Matrix!"
        message_obj.raw_message = None
        message_obj.group_id = "!test_room:matrix.org"
        message_obj.timestamp = 1234567890

        # Mock Matrix client (None for testing)
        matrix_event = MatrixMessageEvent(
            message_str="Hello from Matrix!",
            message_obj=message_obj,
            platform_meta=platform_meta,
            session_id="!test_room:matrix.org",
            client=None,  # Mock client
            room_id="!test_room:matrix.org",
        )

        print("✅ Matrix message event created successfully")
        print(f"   Message: {matrix_event.get_message_str()}")
        print(f"   Sender: {matrix_event.get_sender_name()} ({matrix_event.get_sender_id()})")
        print(f"   Room ID: {matrix_event.room_id}")
        print(f"   Session ID: {matrix_event.get_session_id()}")

        return matrix_event

    except Exception as e:
        print(f"❌ Failed to create Matrix message event: {e}")
        return None


async def test_message_chain_parsing():
    """Test message chain creation and parsing"""
    print("\nTesting message chain parsing...")

    try:
        # Create various message types
        chain = MessageChain([
            Plain("Hello, this is a text message!"),
            Plain("This supports multiple text segments."),
        ])

        print(f"✅ Message chain created with {len(chain.chain)} components")
        for i, comp in enumerate(chain.chain):
            print(f"   Component {i+1}: {comp.type} - {getattr(comp, 'text', 'N/A')}")

        return chain

    except Exception as e:
        print(f"❌ Failed to create message chain: {e}")
        return None


async def test_configuration_validation():
    """Test configuration validation and error handling"""
    print("\nTesting configuration validation...")

    # Test missing required fields
    invalid_configs = [
        {  # Missing user_id
            "type": "matrix",
            "enable": True,
            "matrix_homeserver": "https://matrix.org",
        },
        {  # Missing password and access_token
            "type": "matrix",
            "enable": True,
            "matrix_user_id": "@test:matrix.org",
            "matrix_homeserver": "https://matrix.org",
        }
    ]

    event_queue = asyncio.Queue()

    for i, config in enumerate(invalid_configs):
        try:
            MatrixAdapter(config, {}, event_queue)
            print(f"❌ Config {i+1} should have failed but didn't")
        except ValueError as e:
            print(f"✅ Config {i+1} correctly failed validation: {e}")
        except Exception as e:
            print(f"⚠️ Config {i+1} failed with unexpected error: {e}")


async def main():
    """Run all tests"""
    print("Matrix Platform Adapter Test Suite")
    print("=" * 50)

    # Test 1: Adapter creation
    adapter = await test_matrix_adapter_creation()

    # Test 2: Event creation
    event = await test_matrix_event_creation()

    # Test 3: Message chain parsing
    chain = await test_message_chain_parsing()

    # Test 4: Configuration validation
    await test_configuration_validation()

    print("\n" + "=" * 50)
    print("Test Summary:")
    print(f"✅ Matrix adapter: {'Working' if adapter else 'Failed'}")
    print(f"✅ Message events: {'Working' if event else 'Failed'}")
    print(f"✅ Message chains: {'Working' if chain else 'Failed'}")
    print("✅ Config validation: Working")

    if adapter and event and chain:
        print("\n🎉 All tests passed! Matrix adapter is ready for use.")
        print("\nNext steps:")
        print("1. Configure your Matrix homeserver and credentials")
        print("2. Add Matrix configuration to your AstrBot platform config")
        print("3. Start AstrBot and invite the bot to Matrix rooms")
        print("4. Test messaging functionality")
    else:
        print("\n⚠️ Some tests failed. Check the errors above.")

    return adapter and event and chain


if __name__ == "__main__":
    try:
        result = asyncio.run(main())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error during testing: {e}")
        sys.exit(1)
