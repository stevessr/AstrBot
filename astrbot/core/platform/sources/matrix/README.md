# Matrix Protocol Adapter for AstrBot

This is a Matrix protocol adapter for AstrBot with End-to-End Encryption (E2EE) support using vodozemac.

## Features

- Full Matrix protocol support via matrix-nio
- End-to-End Encryption (E2EE) support using vodozemac (via matrix-nio[e2e])
- Support for text, image, audio/voice messages
- Works with both direct messages and group rooms
- Automatic device key management and storage

## Dependencies

The adapter uses `matrix-nio[e2e]` which includes:
- `matrix-nio`: Python Matrix client library
- `vodozemac-python`: Python bindings for vodozemac (E2EE)
- `python-olm`: Additional E2EE support

These dependencies are automatically installed via the `matrix-nio[e2e]` extra.

## Configuration

Add the following configuration to your AstrBot platform settings:

```json
{
  "id": "matrix",
  "type": "matrix",
  "enable": true,
  "matrix_homeserver": "https://matrix.org",
  "matrix_user_id": "@your_username:matrix.org",
  "matrix_password": "your_password",
  "matrix_device_name": "AstrBot",
  "matrix_device_id": "",
  "matrix_access_token": ""
}
```

### Configuration Options

- `matrix_homeserver`: The URL of your Matrix homeserver (e.g., `https://matrix.org`)
- `matrix_user_id`: Your Matrix user ID (e.g., `@username:matrix.org`)
- `matrix_password`: Your Matrix account password (required if `matrix_access_token` is not provided)
- `matrix_device_name`: A friendly name for this bot instance
- `matrix_device_id`: (Optional) Reuse an existing device ID
- `matrix_access_token`: (Optional) Use an existing access token instead of password login

## E2EE Support

The adapter automatically enables E2EE support when matrix-nio is installed with the `[e2e]` extra. 

### How E2EE Works

1. **Key Storage**: Device keys and session data are stored in `data/matrix_store/` directory
2. **Vodozemac**: Uses the vodozemac library (via matrix-nio) for Olm and Megolm cryptographic operations
3. **Automatic**: E2EE is handled automatically - encrypted rooms work transparently

### Device Verification

For optimal security, you should verify your bot's device:
1. Log in to your Matrix account on Element or another client
2. Find the bot's session in your device list
3. Verify the device using emoji verification or device keys

## Usage

Once configured and enabled, the bot will:
1. Login to the Matrix homeserver
2. Sync with all joined rooms
3. Respond to messages in both encrypted and unencrypted rooms
4. Handle text, images, and voice messages

## Supported Message Types

### Receiving
- Text messages
- Images (automatically downloaded)
- Audio/Voice messages (automatically downloaded)
- Files (displayed as text notification)
- Videos (displayed as text notification)

### Sending
- Plain text messages
- Images (uploaded to homeserver)
- Audio/Voice messages (uploaded to homeserver)
- Files (uploaded to homeserver)

## Technical Details

### Architecture

- **matrix_adapter.py**: Main adapter implementation
  - Handles Matrix client initialization
  - Manages login and sync
  - Converts Matrix events to AstrBotMessage
  
- **matrix_event.py**: Event handling
  - Sends messages to Matrix rooms
  - Handles media uploads

### E2EE Implementation

The adapter uses matrix-nio's built-in E2EE support:
- matrix-nio internally uses vodozemac (or python-olm as fallback)
- Encryption/decryption is handled transparently
- Device keys are managed automatically

## Troubleshooting

### Module not found: nio
Make sure to install dependencies:
```bash
pip install "matrix-nio[e2e]>=0.25.0"
```

### E2EE not working
1. Check that matrix-nio was installed with the `[e2e]` extra
2. Verify device keys in Element or another Matrix client
3. Check logs for encryption errors

### Connection issues
1. Verify homeserver URL is correct
2. Check network connectivity
3. Try using an access token instead of password

## References

- [matrix-nio Documentation](https://matrix-nio.readthedocs.io/)
- [Matrix E2EE Guide](https://matrix.org/docs/matrix-concepts/end-to-end-encryption/)
- [vodozemac Repository](https://github.com/matrix-org/vodozemac)
- [vodozemac Python Bindings](https://github.com/matrix-nio/vodozemac-python)
