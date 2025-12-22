#!/usr/bin/env python3
import json

import requests

# Load auth token
with open("data/matrix_store/chatbot_neko.aaca.eu.org/auth.json") as f:
    auth = json.load(f)

token = auth["access_token"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# Query device keys
resp = requests.post(
    "https://neko.aaca.eu.org/_matrix/client/v3/keys/query",
    headers=headers,
    json={"device_keys": {"@chatbot:neko.aaca.eu.org": []}},
)

data = resp.json()
device_keys = data.get("device_keys", {}).get("@chatbot:neko.aaca.eu.org", {})

print(f"Found {len(device_keys)} devices:")
for device_id, keys in device_keys.items():
    print(f"\nDevice: {device_id}")
    print(f"  algorithms: {keys.get('algorithms', [])}")
    print(f"  keys: {list(keys.get('keys', {}).keys())}")
    print(f"  signatures: {list(keys.get('signatures', {}).keys())}")
