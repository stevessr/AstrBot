import asyncio
import json
import unittest
from unittest.mock import MagicMock, AsyncMock

from astrbot.core.platform.sources.matrix.components.event_processor import MatrixEventProcessor
from astrbot.core.platform.sources.matrix.client.event_types import MatrixRoom, RoomMessageText

class TestMatrixEventProcessor(unittest.IsolatedAsyncioTestCase):
    async def test_encrypted_message_processing(self):
        # Setup
        client = MagicMock()
        user_id = "@bot:example.com"
        startup_ts = 0
        e2ee_manager = MagicMock()
        
        # Mock decrypt_room_event to return a decrypted text message
        decrypted_content = {
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "Hello World"
            }
        }
        e2ee_manager.decrypt_room_event = AsyncMock(return_value=json.dumps(decrypted_content))
        
        processor = MatrixEventProcessor(client, user_id, startup_ts, e2ee_manager)
        
        # Callback to verify the result
        received_events = []
        async def on_message(room, event):
            received_events.append((room, event))
        
        processor.set_message_callback(on_message)
        
        # Simulate an encrypted event
        room_id = "!room:example.com"
        encrypted_event_data = {
            "type": "m.room.encrypted",
            "event_id": "$event123",
            "sender": "@user:example.com",
            "origin_server_ts": 1000,
            "content": {
                "algorithm": "m.megolm.v1.aes-sha2",
                "ciphertext": "encrypted_payload",
                "sender_key": "key",
                "session_id": "session",
                "device_id": "device"
            }
        }
        
        room_data = {
            "timeline": {
                "events": [encrypted_event_data]
            }
        }
        
        # Act
        await processor.process_room_events(room_id, room_data)
        
        # Assert
        self.assertEqual(len(received_events), 1)
        room, event = received_events[0]
        
        self.assertEqual(room.room_id, room_id)
        self.assertIsInstance(event, RoomMessageText)
        self.assertEqual(event.body, "Hello World")
        self.assertEqual(event.sender, "@user:example.com")
        self.assertEqual(event.event_id, "$event123")
        
        # Verify decrypt was called with correct data
        # The processor reconstructs the dict from MatrixEvent object, so we check if it matches expectations
        call_args = e2ee_manager.decrypt_room_event.call_args[0][0]
        self.assertEqual(call_args["type"], "m.room.encrypted")
        self.assertEqual(call_args["content"]["ciphertext"], "encrypted_payload")
        self.assertEqual(call_args["room_id"], room_id)

    async def test_e2ee_initialization_flow(self):
        # Setup
        client = MagicMock()
        user_id = "@bot:example.com"
        startup_ts = 0
        
        # Initialize processor without E2EE manager (simulating __init__)
        processor = MatrixEventProcessor(client, user_id, startup_ts, e2ee_manager=None)
        
        # Verify initial state
        self.assertIsNone(processor.e2ee_manager)
        
        # Simulate late initialization (simulating run())
        e2ee_manager = MagicMock()
        processor.e2ee_manager = e2ee_manager
        
        # Verify updated state
        self.assertEqual(processor.e2ee_manager, e2ee_manager)
        
        # Test that processing now uses the E2EE manager
        # Mock decrypt_room_event
        decrypted_content = {
            "type": "m.room.message",
            "content": {
                "msgtype": "m.text",
                "body": "Decrypted"
            }
        }
        e2ee_manager.decrypt_room_event = AsyncMock(return_value=json.dumps(decrypted_content))
        
        room_id = "!room:example.com"
        encrypted_event_data = {
            "type": "m.room.encrypted",
            "content": {"algorithm": "m.megolm.v1.aes-sha2"}
        }
        room_data = {"timeline": {"events": [encrypted_event_data]}}
        
        # Use a list to capture callback args
        received_events = []
        async def on_message(room, event):
            received_events.append(event)
        processor.set_message_callback(on_message)
        
        await processor.process_room_events(room_id, room_data)
        
        # Assertions
        self.assertEqual(len(received_events), 1)
        self.assertEqual(received_events[0].body, "Decrypted")

if __name__ == "__main__":
    unittest.main()