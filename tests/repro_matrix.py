
import asyncio
from unittest.mock import MagicMock, AsyncMock
from astrbot.api.message_components import Plain, Reply, Image
from astrbot.api.event import MessageChain
# Import the class to test (assuming python path is set or we adjust imports)
# We will mock the minimal dependencies
import sys
import os

# Adjust path to find astrbot
sys.path.append(os.getcwd())

from astrbot.core.platform.sources.matrix.event import MatrixPlatformEvent

async def test_outgoing():
    print("--- Testing Outgoing Matrix Messages ---")
    
    # Mock Client
    client = AsyncMock()
    client.send_message.return_value = {"event_id": "$new_event"}
    client.upload_file.return_value = {"content_uri": "mxc://example.org/123"}
    
    # Test 1: Adjacent Text Components (Message Chain issue)
    print("\nTest 1: Adjacent Plain Text")
    chain = MessageChain()
    chain.chain = [Plain("Hello"), Plain(" World")]
    
    await MatrixPlatformEvent.send_with_client(
        client=client, 
        message_chain=chain, 
        room_id="!room:example.org"
    )
    
    print(f"send_message called {client.send_message.call_count} times")
    if client.send_message.call_count == 2:
        print("[FAIL] adjacent text sent as separate messages")
    else:
        print("[PASS] adjacent text merged")
        
    client.reset_mock()
    
    # Test 2: Threading Default (Reply to normal message)
    print("\nTest 2: Reply to normal message (Threading Default)")
    chain2 = MessageChain()
    chain2.chain = [Reply(id="$original:example.org"), Plain("Reply")]
    
    # Mock getting the original event (Normal message, no thread)
    client.get_event = AsyncMock(return_value={
        "sender": "@alice:example.org",
        "content": {
            "body": "Original Message",
            # No m.relates_to
        }
    })
    
    # Create event instance to use .send() logic (which does the thread detection)
    # We need to minimally instantiate MatrixPlatformEvent or copy the logic
    # Since .send() is an instance method and uses self.client, let's instantiate it.
    
    # But MatrixPlatformEvent.__init__ requires args.
    # Let's just use the static method logic which accepts 'use_thread'
    # Wait, the logic to *decide* use_thread is in send(), not send_with_client().
    
    # Let's look at event.py send() again.
    # We will reproduce the logic manually to confirm what we read:
    
    reply_to = "$original:example.org"
    resp = await client.get_event("!room", reply_to)
    
    use_thread = False
    thread_root = None
    
    relates_to = resp["content"].get("m.relates_to", {})
    if relates_to.get("rel_type") == "m.thread":
        thread_root = relates_to.get("event_id")
        use_thread = True
    else:
        # DEFAULT BEHAVIOR IN CODE (lines 296-298)
        use_thread = True 
        thread_root = reply_to
        
    print(f"Decision: use_thread={use_thread}")
    
    await MatrixPlatformEvent.send_with_client(
        client=client,
        message_chain=chain2,
        room_id="!room:example.org",
        reply_to=reply_to,
        thread_root=thread_root,
        use_thread=use_thread,
        original_message_info={"sender": "@alice", "body": "Original"}
    )
    
    call_args = client.send_message.call_args[1]
    content = call_args["content"]
    relates = content.get("m.relates_to", {})
    
    print(f"m.relates_to: {relates}")
    
    if relates.get("rel_type") == "m.thread" and relates.get("event_id") == "$original:example.org":
        print("[WARN] Created a new thread on a normal reply (Aggressive Threading)")
    elif "m.in_reply_to" in relates and "rel_type" not in relates:
        print("[PASS] Normal timeline reply")
        
if __name__ == "__main__":
    asyncio.run(test_outgoing())
