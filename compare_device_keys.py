#!/usr/bin/env python3
"""
Script to compare local Olm keys with server-registered device keys
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")


async def main():
    from astrbot.core.platform.sources.matrix.client import MatrixHTTPClient

    # Load auth
    with open("data/matrix_store/chatbot_neko.aaca.eu.org/auth.json") as f:
        auth = json.load(f)

    access_token = auth["access_token"]
    device_id = auth["device_id"]
    user_id = auth["user_id"]
    homeserver = auth["home_server"]

    print(f"User: {user_id}")
    print(f"Device ID (auth.json): {device_id}")
    print(f"Homeserver: {homeserver}")
    print()

    # Create client and set token
    client = MatrixHTTPClient(homeserver=homeserver)
    client.access_token = access_token

    # Query device keys from server
    print("=== Querying server for device keys ===")
    try:
        response = await client._request(
            "POST", "/_matrix/client/v3/keys/query", data={"device_keys": {user_id: []}}
        )

        device_keys = response.get("device_keys", {}).get(user_id, {})

        print(f"Found {len(device_keys)} devices on server:")
        for dev_id, keys in device_keys.items():
            print(f"\n  Device: {dev_id}")
            print(f"    algorithms: {keys.get('algorithms', [])}")
            print(f"    keys: {list(keys.get('keys', {}).keys())}")
            if keys.get("keys"):
                for key_id, key_value in keys.get("keys", {}).items():
                    print(f"      {key_id}: {key_value[:20]}...")

    except Exception as e:
        print(f"Error querying keys: {e}")

    # Load local Olm keys
    print("\n=== Loading local Olm account ===")
    try:
        with open(f"data/matrix_e2ee/@chatbot_neko.aaca.eu.org/olm_account.json") as f:
            olm_data = json.load(f)
        print(f"Local Olm account pickle exists: {len(olm_data.get('pickle', '')) > 0}")
        print(f"Local device_id: {olm_data.get('device_id', 'N/A')}")

        # Try to get identity keys from the account
        from astrbot.core.platform.sources.matrix.e2ee.crypto_store import CryptoStore
        from astrbot.core.platform.sources.matrix.e2ee.olm_machine import OlmMachine

        store = CryptoStore(
            "data/matrix_e2ee/@chatbot_neko.aaca.eu.org", user_id, device_id
        )
        olm = OlmMachine(store, user_id, device_id)

        # Get keys directly from account with proper base64 conversion
        curve25519_key = olm._account.curve25519_key
        ed25519_key = olm._account.ed25519_key

        # Convert to base64 string using .to_base64() method
        local_keys_str = {
            f"curve25519:{device_id}": curve25519_key.to_base64(),
            f"ed25519:{device_id}": ed25519_key.to_base64(),
        }

        print(f"\nLocal identity keys:")
        for key_id, key_value in local_keys_str.items():
            print(f"  {key_id}: {key_value}")

        # Compare with server
        print("\n=== Comparison ===")
        server_device = device_keys.get(device_id, {})
        if server_device:
            server_device_keys = server_device.get("keys", {})
            print(f"Server device keys: {list(server_device_keys.keys())}")

            for key_id, local_value in local_keys_str.items():
                server_value = server_device_keys.get(key_id, "NOT ON SERVER")
                # Convert server value to string if needed
                if hasattr(server_value, "to_base64"):
                    server_value_str = server_value.to_base64()
                elif isinstance(server_value, str):
                    server_value_str = server_value
                else:
                    server_value_str = str(server_value)
                match = "✅ MATCH" if local_value == server_value_str else "❌ MISMATCH"
                print(f"  {key_id}: {match}")
                if local_value != server_value_str:
                    print(f"    Local:  {local_value}")
                    print(f"    Server: {server_value_str}")
        else:
            print(f"  ❌ Device {device_id} has NO KEYS on server!")

    except Exception as e:
        print(f"Error loading local keys: {e}")
        import traceback

        traceback.print_exc()

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
