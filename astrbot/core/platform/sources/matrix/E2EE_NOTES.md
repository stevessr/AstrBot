# Matrix E2EE Implementation Notes

## Overview

This document explains how End-to-End Encryption (E2EE) is implemented in the AstrBot Matrix adapter using matrix-nio and vodozemac.

## Key Components

### 1. Vodozemac Integration

Vodozemac is integrated automatically through matrix-nio when installed with the `[e2e]` extra:

```bash
pip install "matrix-nio[e2e]>=0.25.0"
```

This installs:
- `matrix-nio`: Core Matrix client
- `vodozemac-python`: Python bindings for vodozemac (Rust E2EE implementation)
- `python-olm`: Fallback E2EE support

### 2. Automatic E2EE Handling

matrix-nio handles most E2EE operations automatically:

- **Key Management**: Device keys are automatically generated and stored
- **Encryption**: Messages in encrypted rooms are automatically encrypted
- **Decryption**: Received encrypted messages are automatically decrypted during `sync()`
- **Key Upload**: Encryption keys are uploaded to the server after login

## Implementation Details

### Login and Key Upload

```python
async def _login(self):
    # Login to Matrix
    response = await self.client.login(password=self.password, device_name=self.device_name)
    
    # Upload encryption keys if E2EE is enabled
    if self.client.store:
        keys_response = await self.client.keys_upload()
        logger.info(f"Uploaded {keys_response.one_time_key_counts} encryption keys")
```

### Handling Encrypted Media

Encrypted media (images, audio, etc.) require special handling:

1. **Receiving Encrypted Media**:
   - `RoomEncryptedImage`, `RoomEncryptedAudio` events contain encrypted data
   - These events include decryption keys: `event.key`, `event.hashes`, `event.iv`
   - Download the encrypted file from the MXC URL
   - Decrypt using `nio.crypto.decrypt_attachment()`

```python
from nio.crypto import decrypt_attachment

# Download encrypted file
response = await client.download(server_name=server_name, media_id=media_id)

# Decrypt
decrypted_data = decrypt_attachment(
    response.body,
    event.key["k"],
    event.hashes["sha256"],
    event.iv,
)
```

2. **Sending Encrypted Media**:
   - Use `client.upload(..., encrypt=True)` to automatically encrypt files
   - Returns tuple: `(UploadResponse, encryption_info)`
   - Use `encryption_info` in the message content

```python
# Upload with encryption
upload_response, encrypted_info = await client.upload(
    data_provider=lambda: file_data,
    content_type=mimetype,
    filename=filename,
    encrypt=True,  # Enable encryption
)

# Build content with encryption info
content = {
    "msgtype": "m.image",
    "body": filename,
    "file": encrypted_info,  # Contains encrypted file info
    "info": {
        "mimetype": mimetype,
        "size": len(file_data),
    },
}
```

### Room Encryption Detection

```python
room = client.rooms.get(room_id)
is_encrypted = room.encrypted if room else False
```

### Auto-join Rooms

```python
async def _sync_callback(self, response: SyncResponse):
    # Auto-accept room invites
    for room_id, room_info in response.rooms.invite.items():
        await self.client.join(room_id)
        logger.info(f"Joined room {room_id}")
```

## E2EE Event Types

### Text Messages

- Unencrypted: `RoomMessageText`
- Encrypted: Automatically decrypted to `RoomMessageText` by matrix-nio

### Media Messages

- Unencrypted: `RoomMessageImage`, `RoomMessageAudio`, etc.
- Encrypted: `RoomEncryptedImage`, `RoomEncryptedAudio`, etc.

Both types are handled by checking `isinstance()`:

```python
if isinstance(event, (RoomMessageImage, RoomEncryptedImage)):
    # Handle both encrypted and unencrypted images
    if isinstance(event, RoomEncryptedImage):
        # Special decryption handling
    else:
        # Regular handling
```

## Key Storage

Device keys and session data are stored in:
```
data/matrix_store/
├── device_keys/
├── olm_sessions/
├── inbound_group_sessions/
└── ... (managed by matrix-nio)
```

**Important**: Keep this directory secure and backed up!

## Device Verification

For optimal security, devices should be verified:

1. **Via Element Web/Desktop**:
   - Log in with the same account
   - Go to Settings → Security & Privacy → Devices
   - Find "AstrBot" device
   - Click "Verify" → Emoji verification

2. **Programmatically** (future enhancement):
   - Implement automatic device verification
   - Handle verification requests

## Ignore Unverified Devices

When sending messages to encrypted rooms, we use:

```python
await client.room_send(
    room_id=room_id,
    message_type="m.room.message",
    content=content,
    ignore_unverified_devices=True,  # Don't block on unverified devices
)
```

This prevents messages from being blocked if not all devices are verified.

## Troubleshooting

### E2EE Not Working

1. **Check Installation**:
   ```bash
   pip show matrix-nio | grep "e2e"
   ```

2. **Check Logs**:
   Look for: `Matrix E2EE support enabled`

3. **Verify Store**:
   Check that `data/matrix_store/` directory exists and is writable

4. **Clear Keys** (last resort):
   ```bash
   rm -rf data/matrix_store/*
   ```
   Then restart AstrBot (generates new keys)

### Decryption Failures

- **Cause**: Missing session keys
- **Solution**: 
  1. Verify device in Element
  2. Request keys from other devices
  3. Check that `keys_upload()` succeeded

### Unable to Send to Encrypted Room

- **Cause**: Missing device keys or session
- **Solution**:
  1. Check that `client.store` exists
  2. Verify `keys_upload()` was successful
  3. Use `ignore_unverified_devices=True` in `room_send()`

## Security Considerations

### Trust Model

- **Default**: Trust on First Use (TOFU)
- Devices are trusted after first key exchange
- Manual verification recommended for high security

### Key Management

- Device keys: Long-term, identify the device
- Session keys: Short-term, encrypt messages
- One-time keys: Single-use for establishing sessions

### Best Practices

1. ✅ Verify devices in Element
2. ✅ Keep `data/matrix_store/` backed up
3. ✅ Use access tokens instead of passwords
4. ✅ Monitor logs for encryption errors
5. ✅ Regularly rotate device keys (future enhancement)

## Future Enhancements

Potential improvements for E2EE support:

- [ ] Automatic device verification
- [ ] Cross-signing support
- [ ] Key backup and recovery
- [ ] Session key forwarding
- [ ] Better unverified device handling
- [ ] Encryption status indicators
- [ ] Manual key verification UI

## References

### Documentation

- [matrix-nio E2EE docs](https://matrix-nio.readthedocs.io/en/latest/nio.html#module-nio.crypto)
- [Matrix E2EE Spec](https://spec.matrix.org/latest/client-server-api/#end-to-end-encryption)
- [Vodozemac GitHub](https://github.com/matrix-org/vodozemac)
- [Vodozemac Audit](https://matrix.org/blog/2022/05/16/independent-public-audit-of-vodozemac-a-native-rust-reference-implementation-of-matrix-end-to-end-encryption/)

### Key Algorithms

- **Olm**: Double Ratchet algorithm for 1-to-1 encryption
- **Megolm**: Group encryption for rooms
- **Vodozemac**: Rust implementation (5-6x faster than libolm)

## Testing E2EE

To test E2EE functionality:

1. Create two Matrix accounts (or use Element Web + Bot)
2. Create an encrypted room
3. Invite the bot
4. Send encrypted messages
5. Verify bot can receive and respond
6. Check logs for encryption status

### Test Script

```bash
cd astrbot/core/platform/sources/matrix
python test_matrix.py
```

This will test:
- Connection
- Login
- E2EE support detection
- Key upload
- Room sync

---

**Version**: 1.0.0  
**Last Updated**: 2025-10-18  
**Author**: AstrBot Team
