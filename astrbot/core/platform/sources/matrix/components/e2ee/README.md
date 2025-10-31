# Matrix End-to-End Encryption (E2EE) Implementation

This directory contains the complete implementation of Matrix E2EE support for AstrBot, including Olm (1-to-1) and Megolm (group) encryption.

## Architecture

The E2EE implementation is modular and consists of several components:

### Core Components

1. **`e2ee_manager.py`** - Main coordinator
   - Orchestrates all E2EE operations
   - Manages lifecycle and initialization
   - Handles event routing

2. **`e2ee_crypto.py`** - Encryption/Decryption
   - Olm session management (1-to-1 encryption)
   - Megolm session management (group encryption)
   - Message encryption and decryption

3. **`e2ee_store.py`** - Key Storage
   - Persistent storage for keys and sessions
   - Account management
   - Session import/export

4. **`e2ee_verification.py`** - Device Verification
   - SAS (Short Authentication String) verification
   - Device trust management
   - Verification flow handling

5. **`e2ee_recovery.py`** - Key Recovery
   - Cross-device key sharing
   - Recovery code generation
   - Key backup/restore

6. **`e2ee_auto_setup.py`** - 🆕 Automatic E2EE Setup
   - Automatic device discovery
   - Automatic key exchange
   - Automatic Olm session establishment
   - Automatic device verification

## Features

### ✅ Implemented

- **Olm Encryption (1-to-1)**
  - Outbound session creation
  - Inbound session creation from PreKey messages
  - Message encryption/decryption
  - Session persistence

- **Megolm Encryption (Group)**
  - Outbound group session creation
  - Inbound group session import
  - Group message encryption/decryption
  - Session key sharing

- **Device Verification**
  - SAS verification flow
  - Automatic verification event handling
  - Device trust tracking

- **Key Management**
  - Device key upload
  - One-time key upload and rotation
  - Identity key management
  - Session storage and retrieval

- **To-Device Message Handling**
  - Encrypted to-device message decryption
  - Room key distribution
  - Verification event processing

- **🆕 Automatic E2EE Setup**
  - Automatic device list retrieval via `/devices` API
  - Automatic device key query via `/keys/query` API
  - Automatic one-time key claiming via `/keys/claim` API
  - Automatic Olm session establishment
  - Optional automatic device verification

### 🚧 Partial Implementation

- **Key Recovery**
  - Basic recovery flow implemented
  - Needs integration with key backup API

- **Cross-Signing**
  - Framework in place
  - Needs full implementation

## Usage

### Initialization

```python
from astrbot.core.platform.sources.matrix.components.e2ee import MatrixE2EEManager

# Create E2EE manager
e2ee_manager = MatrixE2EEManager(
    store_path="./data/matrix_store",
    user_id="@user:matrix.org",
    device_id="DEVICE_ID",
    homeserver="https://matrix.org",
    client=http_client
)

# Initialize (creates account, uploads keys)
await e2ee_manager.initialize()
```

### Encrypting Messages

```python
# For 1-to-1 (Olm)
encrypted = e2ee_manager.crypto.encrypt_message(
    user_id="@other:matrix.org",
    device_id="OTHER_DEVICE",
    plaintext='{"type": "m.room.message", "content": {...}}'
)

# For groups (Megolm)
encrypted = e2ee_manager.crypto.encrypt_group_message(
    room_id="!room:matrix.org",
    plaintext='{"type": "m.room.message", "content": {...}}'
)
```

### Decrypting Messages

```python
# For 1-to-1 (Olm)
plaintext = e2ee_manager.crypto.decrypt_message(
    user_id="@sender:matrix.org",
    device_id="SENDER_DEVICE",
    message_type=0,  # 0=PreKey, 1=Message
    ciphertext="..."
)

# For groups (Megolm)
plaintext = e2ee_manager.crypto.decrypt_group_message(
    session_id="SESSION_ID",
    ciphertext="..."
)
```

### Device Verification

```python
# Start verification
success, verification_id = await e2ee_manager.start_verification(
    other_user_id="@other:matrix.org",
    other_device_id="OTHER_DEVICE"
)

# Generate SAS code
sas_code = e2ee_manager.generate_sas_code(verification_id)
print(f"Verify this code matches: {sas_code}")

# Confirm SAS
if e2ee_manager.confirm_sas(verification_id, user_input_code):
    e2ee_manager.complete_verification(verification_id)
```

## Protocol Details

### Olm (1-to-1 Encryption)

Olm is a Double Ratchet implementation for 1-to-1 encryption:

1. **Session Creation**
   - Outbound: Uses recipient's identity key and one-time key
   - Inbound: Created from PreKey message (type 0)

2. **Message Types**
   - Type 0: PreKey message (establishes new session)
   - Type 1: Regular message (uses existing session)

3. **Key Exchange**
   - Uses Curve25519 for key agreement
   - Ed25519 for signatures

### Megolm (Group Encryption)

Megolm is a ratchet-based group encryption protocol:

1. **Session Management**
   - One outbound session per room (sender)
   - Multiple inbound sessions (receivers)

2. **Key Sharing**
   - Session keys shared via encrypted to-device messages
   - Uses Olm to encrypt the Megolm session key

3. **Message Format**
   - Algorithm: `m.megolm.v1.aes-sha2`
   - Includes session ID and message index

### Device Verification (SAS)

Short Authentication String verification flow:

1. **Request** (`m.key.verification.request`)
2. **Ready** (`m.key.verification.ready`)
3. **Start** (`m.key.verification.start`)
4. **Accept** (`m.key.verification.accept`)
5. **Key Exchange** (`m.key.verification.key`)
6. **MAC Exchange** (`m.key.verification.mac`)
7. **Done** (`m.key.verification.done`)

## Dependencies

- **vodozemac**: Rust-based cryptography library
  - Provides Olm and Megolm implementations
  - High-performance, memory-safe
  - Install: `pip install vodozemac`

## Error Handling

The implementation includes comprehensive error handling:

- **Missing Sessions**: Automatically requests room keys
- **Decryption Failures**: Logs detailed error information
- **Key Upload Failures**: Retries with exponential backoff
- **Verification Errors**: Graceful cancellation with reason codes

## Security Considerations

1. **Key Storage**
   - Keys stored in encrypted format
   - File permissions restricted to owner only
   - Separate storage per user/device

2. **Session Management**
   - Sessions rotated periodically
   - Old sessions cleaned up
   - One-time keys replenished automatically

3. **Verification**
   - SAS codes must be verified out-of-band
   - Unverified devices can still communicate
   - Trust-on-first-use (TOFU) model

## Troubleshooting

### "Unable to decrypt" errors

1. Check if E2EE is enabled: `matrix_enable_e2ee: true`
2. Verify vodozemac is installed: `pip install vodozemac`
3. Check logs for key request messages
4. Ensure device keys are uploaded

### Verification not working

1. Check both devices are online
2. Verify network connectivity
3. Check logs for verification events
4. Ensure client supports SAS verification

### Missing room keys

1. The adapter automatically requests missing keys
2. Check if sender's device is verified
3. Verify sender is still in the room
4. Check for key sharing events in logs

## Future Enhancements

- [ ] Cross-signing support
- [ ] Server-side key backup (SSSS)
- [ ] QR code verification
- [ ] Key forwarding between own devices
- [ ] Automatic key rotation
- [ ] Key export/import for backup

## References

- [Matrix E2EE Specification](https://spec.matrix.org/latest/client-server-api/#end-to-end-encryption)
- [Olm Specification](https://gitlab.matrix.org/matrix-org/olm/-/blob/master/docs/olm.md)
- [Megolm Specification](https://gitlab.matrix.org/matrix-org/olm/-/blob/master/docs/megolm.md)
- [vodozemac Documentation](https://docs.rs/vodozemac/)

