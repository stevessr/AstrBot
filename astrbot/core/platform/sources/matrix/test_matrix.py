#!/usr/bin/env python3
"""
Simple test script for Matrix adapter
This script helps verify that Matrix connection and E2EE are working correctly.

Usage:
    python test_matrix.py
"""
import asyncio
import sys
from pathlib import Path

try:
    from nio import AsyncClient, LoginResponse, SyncResponse
except ImportError:
    print("Error: matrix-nio is not installed.")
    print("Please install it with: pip install 'matrix-nio[e2e]'")
    sys.exit(1)


async def test_matrix_connection():
    """Test basic Matrix connection and E2EE setup"""
    
    # Configuration
    homeserver = input("Matrix Homeserver URL (e.g., https://matrix.org): ").strip()
    user_id = input("Matrix User ID (e.g., @username:matrix.org): ").strip()
    password = input("Matrix Password: ").strip()
    
    # Create store directory
    store_path = Path("./test_matrix_store")
    store_path.mkdir(parents=True, exist_ok=True)
    
    print("\n=== Testing Matrix Connection ===")
    
    # Create client
    client = AsyncClient(
        homeserver,
        user_id,
        store_path=str(store_path),
    )
    
    print(f"✓ Client created")
    print(f"  Homeserver: {homeserver}")
    print(f"  User ID: {user_id}")
    print(f"  Store path: {store_path}")
    
    # Test login
    print("\n=== Testing Login ===")
    try:
        response = await client.login(password=password, device_name="AstrBot-Test")
        
        if isinstance(response, LoginResponse):
            print(f"✓ Login successful!")
            print(f"  Device ID: {response.device_id}")
            print(f"  Access Token: {response.access_token[:20]}...")
        else:
            print(f"✗ Login failed: {response}")
            await client.close()
            return
    except Exception as e:
        print(f"✗ Login error: {e}")
        await client.close()
        return
    
    # Test E2EE
    print("\n=== Testing E2EE Support ===")
    if client.store:
        print(f"✓ E2EE store available")
        print(f"  Store type: {type(client.store).__name__}")
    else:
        print(f"⚠ Warning: E2EE store not available")
        print(f"  Make sure matrix-nio[e2e] is installed")
    
    # Test sync
    print("\n=== Testing Sync ===")
    try:
        response = await client.sync(timeout=10000, full_state=True)
        
        if isinstance(response, SyncResponse):
            print(f"✓ Sync successful!")
            print(f"  Joined rooms: {len(response.rooms.join)}")
            
            if response.rooms.join:
                print(f"\n  Rooms:")
                for room_id, room_info in list(response.rooms.join.items())[:5]:
                    room = client.rooms.get(room_id)
                    if room:
                        print(f"    - {room.display_name or room.room_id}")
        else:
            print(f"✗ Sync failed: {response}")
    except Exception as e:
        print(f"✗ Sync error: {e}")
    
    # Cleanup
    print("\n=== Cleaning Up ===")
    await client.close()
    print("✓ Client closed")
    
    print("\n=== Test Complete ===")
    print("If all tests passed, your Matrix configuration is working correctly!")
    print(f"\nYou can now use these credentials in AstrBot:")
    print(f"  matrix_homeserver: {homeserver}")
    print(f"  matrix_user_id: {user_id}")
    print(f"  matrix_device_id: {response.device_id}")
    print(f"  matrix_access_token: {response.access_token}")


if __name__ == "__main__":
    try:
        asyncio.run(test_matrix_connection())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
