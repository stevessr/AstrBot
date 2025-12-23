"""
Tests for Matrix E2EE events handling and auto-reply-to functionality
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from astrbot.core.platform.sources.matrix.sync.sync_manager import MatrixSyncManager


class TestE2EEEventsHandling(unittest.TestCase):
    """Test E2EE events handling in sync manager"""

    def setUp(self):
        """Set up test fixtures"""
        self.client = MagicMock()
        self.sync_manager = MatrixSyncManager(
            client=self.client, sync_timeout=30000, auto_join_rooms=True
        )

    def test_device_lists_callback_registration(self):
        """Test that device_lists callback can be registered"""
        callback = AsyncMock()
        self.sync_manager.set_device_lists_callback(callback)
        self.assertEqual(self.sync_manager.on_device_lists_changed, callback)

    def test_device_one_time_keys_callback_registration(self):
        """Test that device_one_time_keys callback can be registered"""
        callback = AsyncMock()
        self.sync_manager.set_device_one_time_keys_callback(callback)
        self.assertEqual(self.sync_manager.on_device_one_time_keys_count, callback)

    def test_sync_response_with_device_lists(self):
        """Test that device_lists from sync response trigger callback"""

        async def run_test():
            # Set up callback
            callback = AsyncMock()
            self.sync_manager.set_device_lists_callback(callback)

            # Mock sync response with device_lists
            self.client.sync = AsyncMock(
                return_value={
                    "next_batch": "s123",
                    "device_lists": {
                        "changed": ["@user1:example.com", "@user2:example.com"],
                        "left": ["@user3:example.com"],
                    },
                    "rooms": {"join": {}},
                    "to_device": {"events": []},
                }
            )

            # Run one sync iteration
            self.sync_manager._running = True
            task = asyncio.create_task(self.sync_manager.sync_forever())

            # Give it time to process
            await asyncio.sleep(0.1)

            # Stop sync
            self.sync_manager.stop()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()

            # Verify callback was called with correct arguments
            callback.assert_called_once()
            args = callback.call_args[0]
            self.assertEqual(
                args[0], ["@user1:example.com", "@user2:example.com"]
            )  # changed
            self.assertEqual(args[1], ["@user3:example.com"])  # left

        asyncio.run(run_test())

    def test_sync_response_with_key_counts(self):
        """Test that key counts from sync response trigger callback"""

        async def run_test():
            # Set up callback
            callback = AsyncMock()
            self.sync_manager.set_device_one_time_keys_callback(callback)

            # Mock sync response with key counts
            self.client.sync = AsyncMock(
                return_value={
                    "next_batch": "s124",
                    "device_one_time_keys_count": {"signed_curve25519": 25},
                    "device_unused_fallback_key_types": ["signed_curve25519"],
                    "rooms": {"join": {}},
                    "to_device": {"events": []},
                }
            )

            # Run one sync iteration
            self.sync_manager._running = True
            task = asyncio.create_task(self.sync_manager.sync_forever())

            # Give it time to process
            await asyncio.sleep(0.1)

            # Stop sync
            self.sync_manager.stop()
            try:
                await asyncio.wait_for(task, timeout=1.0)
            except asyncio.TimeoutError:
                task.cancel()

            # Verify callback was called
            callback.assert_called_once()
            args = callback.call_args[0]
            self.assertEqual(args[0], {"signed_curve25519": 25})
            self.assertEqual(args[1], ["signed_curve25519"])

        asyncio.run(run_test())


class TestAutoReplyToTracking(unittest.TestCase):
    """Test auto-reply-to functionality in adapter"""

    def test_last_sent_message_tracking_initialization(self):
        """Test that last_sent_message_ids dict is initialized"""
        with (
            patch("astrbot.core.platform.sources.matrix.adapter.MatrixHTTPClient"),
            patch("astrbot.core.platform.sources.matrix.adapter.MatrixAuth"),
            patch("astrbot.core.platform.sources.matrix.adapter.MatrixSyncManager"),
            patch("astrbot.core.platform.sources.matrix.adapter.MatrixEventProcessor"),
        ):
            from astrbot.core.platform.sources.matrix.adapter import (
                MatrixPlatformAdapter,
            )

            platform_config = {
                "matrix_homeserver": "https://matrix.example.com",
                "matrix_user_id": "@bot:example.com",
                "matrix_password": "password",
                "matrix_device_id": "DEVICEID",
                "matrix_store_path": "/tmp/matrix_store",
            }
            event_queue = asyncio.Queue()

            adapter = MatrixPlatformAdapter(platform_config, {}, event_queue)

            # Verify the tracking dict exists
            self.assertIsInstance(adapter._last_sent_message_ids, dict)
            self.assertEqual(len(adapter._last_sent_message_ids), 0)


class TestE2EEEventTypes(unittest.TestCase):
    """Test that all E2EE event types are recognized"""

    def test_e2ee_constants_exist(self):
        """Test that E2EE event type constants are defined"""
        from astrbot.core.platform.sources.matrix.constants import (
            M_DUMMY,
            M_FORWARDED_ROOM_KEY,
            M_ROOM_ENCRYPTED,
            M_ROOM_KEY,
            M_ROOM_KEY_REQUEST,
            M_SECRET_REQUEST,
            M_SECRET_SEND,
        )

        # Verify constants are defined with correct values
        self.assertEqual(M_ROOM_ENCRYPTED, "m.room.encrypted")
        self.assertEqual(M_ROOM_KEY, "m.room_key")
        self.assertEqual(M_ROOM_KEY_REQUEST, "m.room_key_request")
        self.assertEqual(M_FORWARDED_ROOM_KEY, "m.forwarded_room_key")
        self.assertEqual(M_SECRET_REQUEST, "m.secret.request")
        self.assertEqual(M_SECRET_SEND, "m.secret.send")
        self.assertEqual(M_DUMMY, "m.dummy")


if __name__ == "__main__":
    unittest.main()
