import unittest
from unittest.mock import MagicMock
from astrbot.core.platform.sources.matrix.e2ee.verification import (
    SasVerification,
    KeyManager,
)
from astrbot.core.platform.sources.matrix.e2ee.device_store import DeviceKeys


class TestSasCrypto(unittest.TestCase):
    def test_sas_flow(self):
        # Setup mocks
        key_manager_alice = MagicMock()
        key_manager_alice.own_device_keys.device_id = "ALICE_DEVICE"
        key_manager_alice.own_device_keys.user_id = "@alice:example.com"
        # Valid base64
        key_manager_alice.own_device_keys.ed25519_key = "aliceed25519keyA"

        key_manager_bob = MagicMock()
        key_manager_bob.own_device_keys.device_id = "BOB_DEVICE"
        key_manager_bob.own_device_keys.user_id = "@bob:example.com"
        # Valid base64
        key_manager_bob.own_device_keys.ed25519_key = "bobed25519keyBBB"

        transaction_id = "txn1"

        # Alice initiates
        alice = SasVerification(
            key_manager_alice,
            transaction_id,
            "ALICE_DEVICE",
            "BOB_DEVICE",
            "@alice:example.com",
            "@bob:example.com",
        )
        alice._state = alice._state.STARTED  # Force state

        # Bob accepts
        bob = SasVerification(
            key_manager_bob,
            transaction_id,
            "ALICE_DEVICE",
            "BOB_DEVICE",
            "@alice:example.com",
            "@bob:example.com",
        )
        bob._state = bob._state.STARTED

        # 1. Generate keys
        alice_data = alice.generate_sas()
        bob_data = bob.generate_sas()

        # 2. Exchange keys
        alice.set_their_public_key(bob_data["public_key"])
        bob.set_their_public_key(alice_data["public_key"])

        # 3. Check SAS matches
        self.assertIsNotNone(alice.decimal_sas)
        self.assertIsNotNone(bob.decimal_sas)
        self.assertEqual(alice.decimal_sas, bob.decimal_sas)

        self.assertIsNotNone(alice.emoji_sas)
        self.assertIsNotNone(bob.emoji_sas)
        # Check first emoji matches
        self.assertEqual(alice.emoji_sas[0].name, bob.emoji_sas[0].name)

        # 4. Calculate MAC
        alice_mac = alice.calculate_mac({"ed25519:ALICE_DEVICE": "aliceed25519keyA"})
        bob_mac = bob.calculate_mac({"ed25519:BOB_DEVICE": "bobed25519keyBBB"})

        self.assertIn("keys", alice_mac)
        self.assertIn("mac", alice_mac)

        # 5. Verify MAC
        # Alice verifies Bob's MAC
        # Mock Alice's key manager to return Bob's device keys
        bob_device_keys = DeviceKeys(
            user_id="@bob:example.com",
            device_id="BOB_DEVICE",
            ed25519_key="bobed25519keyBBB",
            curve25519_key="bobcurve25519key",
        )
        key_manager_alice.get_device_keys.return_value = bob_device_keys

        verify_success = alice.verify_mac(bob_mac)
        self.assertTrue(verify_success, "Alice failed to verify Bob's MAC")

        # Bob verifies Alice's MAC
        alice_device_keys = DeviceKeys(
            user_id="@alice:example.com",
            device_id="ALICE_DEVICE",
            ed25519_key="aliceed25519keyA",
            curve25519_key="alicecurve25519key",
        )
        key_manager_bob.get_device_keys.return_value = alice_device_keys

        verify_success_bob = bob.verify_mac(alice_mac)
        self.assertTrue(verify_success_bob, "Bob failed to verify Alice's MAC")


if __name__ == "__main__":
    unittest.main()
