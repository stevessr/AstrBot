import unittest
from astrbot.core.platform.sources.matrix.matrix_crypto.key_manager import DeviceKeys, DeviceVerificationStatus

class TestDeviceKeys(unittest.TestCase):
    def test_serialization(self):
        # Create a DeviceKeys object
        original_keys = DeviceKeys(
            user_id="@user:example.com",
            device_id="DEVICEID",
            ed25519_key="ed25519_key_value",
            curve25519_key="curve25519_key_value",
            algorithms=["algo1", "algo2"],
            display_name="Test Device",
            verification_status=DeviceVerificationStatus.VERIFIED
        )
        
        # Serialize to dict
        data = original_keys.to_dict()
        
        # Check that the key in dict is 'curve25519' (as per current implementation of to_dict)
        self.assertIn("curve25519", data)
        self.assertEqual(data["curve25519"], "curve25519_key_value")
        
        # Deserialize from dict
        restored_keys = DeviceKeys.from_dict(data)
        
        # Verify correctness
        self.assertEqual(restored_keys.user_id, original_keys.user_id)
        self.assertEqual(restored_keys.device_id, original_keys.device_id)
        self.assertEqual(restored_keys.ed25519_key, original_keys.ed25519_key)
        self.assertEqual(restored_keys.curve25519_key, original_keys.curve25519_key)
        self.assertEqual(restored_keys.verification_status, original_keys.verification_status)

    def test_legacy_serialization(self):
        # Test backward compatibility if 'curve25519_key' was used in dict
        data = {
            "user_id": "@user:example.com",
            "device_id": "DEVICEID",
            "ed25519": "ed25519_key_value",
            "curve25519_key": "curve25519_key_value", # Legacy/Alternative key
            "algorithms": [],
            "verification_status": "unverified"
        }
        
        restored_keys = DeviceKeys.from_dict(data)
        self.assertEqual(restored_keys.curve25519_key, "curve25519_key_value")

if __name__ == "__main__":
    unittest.main()