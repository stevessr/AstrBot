# Matrix Platform Adapter for AstrBot

This document provides instructions for setting up and configuring the Matrix platform adapter for AstrBot.

## Overview

The Matrix adapter allows AstrBot to connect to Matrix homeservers and participate in Matrix rooms (channels) and direct messages. It supports:

- Text messaging
- Image and file sharing
- Room and direct message conversations
- Auto-joining rooms when invited
- Matrix protocol authentication

## Dependencies

The Matrix adapter requires the `matrix-nio` library with encryption support:

```bash
pip install "matrix-nio[e2e]"
```

Or using UV:

```bash
uv add "matrix-nio[e2e]"
```

## Configuration

Add the following configuration to your AstrBot platform configuration:

### Example Configuration

```json
{
  "type": "matrix",
  "enable": true,
  "id": "my_matrix_bot",
  "matrix_homeserver": "https://matrix.org",
  "matrix_user_id": "@your_bot:matrix.org",
  "matrix_password": "your_bot_password",
  "matrix_access_token": "",
  "matrix_device_name": "AstrBot",
  "matrix_auto_join_rooms": true,
  "matrix_sync_timeout": 30000
}
```

### Configuration Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `type` | Yes | `"matrix"` | Platform adapter type |
| `enable` | Yes | `false` | Enable/disable the Matrix adapter |
| `id` | Yes | `"matrix"` | Unique identifier for this adapter instance |
| `matrix_homeserver` | Yes | `"https://matrix.org"` | Matrix homeserver URL |
| `matrix_user_id` | Yes | - | Full Matrix user ID (e.g., `@bot:matrix.org`) |
| `matrix_password` | No | - | Bot account password (required if no access token) |
| `matrix_access_token` | No | - | Matrix access token (alternative to password) |
| `matrix_device_name` | No | `"AstrBot"` | Device name for Matrix sessions |
| `matrix_auto_join_rooms` | No | `true` | Automatically join rooms when invited |
| `matrix_sync_timeout` | No | `30000` | Sync timeout in milliseconds |

## Authentication Methods

### Method 1: Password Authentication

Set `matrix_password` with your bot account's password:

```json
{
  "matrix_user_id": "@mybot:matrix.org",
  "matrix_password": "my_secure_password"
}
```

### Method 2: Access Token Authentication

If you have an existing access token, you can use it instead of a password:

```json
{
  "matrix_user_id": "@mybot:matrix.org",
  "matrix_access_token": "syt_bXlidXNlcm5hbWU_..."
}
```

## Setting Up a Matrix Bot Account

1. **Create a Matrix Account**: Register a new account on your chosen homeserver (e.g., matrix.org)

2. **Get User ID**: Note your full Matrix user ID (format: `@username:homeserver.tld`)

3. **Get Access Token** (optional):
   - Use a Matrix client to log in
   - Access developer tools to get the access token
   - Or use the password method for automatic token generation

## Usage

### Starting the Bot

Once configured, start AstrBot normally. The Matrix adapter will:

1. Connect to the specified homeserver
2. Authenticate using password or access token
3. Start syncing Matrix events
4. Automatically join rooms if `matrix_auto_join_rooms` is enabled

### Inviting the Bot to Rooms

1. Invite your bot to Matrix rooms: `/invite @your_bot:matrix.org`
2. If auto-join is enabled, the bot will automatically accept invitations
3. The bot will start responding to messages in joined rooms

### Direct Messages

Users can send direct messages to the bot by starting a private chat with the bot's Matrix user ID.

## Features Supported

### Message Types
- ✅ Plain text messages
- ✅ Images (uploaded to Matrix media repository)
- ✅ Files (uploaded to Matrix media repository)
- ✅ Message replies (converted from AstrBot format)
- ⚠️ Rich text (partial support with HTML formatting)

### Chat Types
- ✅ Room messages (group chat equivalent)
- ✅ Direct messages (private chat)
- ✅ Message history and context

### Matrix-Specific Features
- ✅ Automatic room joining
- ✅ Matrix media uploads
- ✅ Event synchronization
- ✅ Homeserver authentication
- ❌ End-to-end encryption (not implemented yet)
- ❌ Matrix reactions (not implemented yet)

## Troubleshooting

### Common Issues

1. **"matrix-nio is not installed" Error**
   ```bash
   pip install "matrix-nio[e2e]"
   ```

2. **Authentication Failed**
   - Check your user ID format (`@username:homeserver.tld`)
   - Verify password or access token
   - Ensure homeserver URL is correct

3. **Bot Not Responding**
   - Check if bot has joined the room
   - Verify Matrix adapter is enabled in configuration
   - Check AstrBot logs for error messages

4. **File/Image Upload Issues**
   - Ensure bot has appropriate permissions on homeserver
   - Check network connectivity to homeserver
   - Verify file size limits

### Logging

Enable debug logging to troubleshoot Matrix adapter issues:

```json
{
  "log_level": "DEBUG"
}
```

Look for log messages prefixed with `[Matrix]` for adapter-specific information.

## Security Considerations

- Store access tokens securely
- Use strong passwords for bot accounts
- Consider using dedicated bot accounts rather than personal accounts
- Be cautious with auto-join features in public homeservers
- Regularly rotate access tokens

## Advanced Configuration

### Multiple Matrix Instances

You can run multiple Matrix adapter instances by creating separate configurations with different `id` values:

```json
[
  {
    "type": "matrix",
    "enable": true,
    "id": "matrix_main",
    "matrix_homeserver": "https://matrix.org",
    "matrix_user_id": "@bot1:matrix.org"
  },
  {
    "type": "matrix", 
    "enable": true,
    "id": "matrix_backup",
    "matrix_homeserver": "https://my-homeserver.com",
    "matrix_user_id": "@bot2:my-homeserver.com"
  }
]
```

### Custom Sync Settings

Adjust sync timeout for different network conditions:

- Fast networks: `matrix_sync_timeout: 10000` (10 seconds)
- Slow/unreliable networks: `matrix_sync_timeout: 60000` (60 seconds)

## Contributing

To contribute improvements to the Matrix adapter:

1. Check the implementation in `astrbot/core/platform/sources/matrix/`
2. Follow the existing adapter patterns
3. Test with various Matrix homeservers
4. Submit pull requests with proper documentation

## References

- [Matrix Protocol Documentation](https://matrix.org/docs/)
- [matrix-nio Library Documentation](https://matrix-nio.readthedocs.io/)
- [Matrix Bot SDK Documentation](https://turt2live.github.io/matrix-bot-sdk/)
- [AstrBot Documentation](https://astrbot.soulter.top/)