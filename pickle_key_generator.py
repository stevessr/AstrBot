import hashlib
import json


def generate_pickle_key(user_id, device_id):
    key_material = f"{user_id}:{device_id}:astrbot_e2ee".encode()
    return hashlib.sha256(key_material).digest()


if __name__ == "__main__":
    with open("data/matrix_store/chatbot_neko.aaca.eu.org/auth.json") as f:
        auth = json.load(f)

    user_id = auth["user_id"]
    device_id = auth["device_id"]

    pickle_key = generate_pickle_key(user_id, device_id)

    print(f"User ID: {user_id}")
    print(f"Device ID: {device_id}")
    print(f"Pickle Key (hex): {pickle_key.hex()}")
