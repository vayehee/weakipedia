# Weakipedia MTProto Service

Local MTProto client utilities for Telegram authentication and communication.

## Login Check

From the repository root:

```bash
npm run mtproto:login
```

The script reads Telegram app credentials from `telegram/TELEGRAM_APP.txt` by default and stores the Telegram session under `telegram/sessions/`. The `telegram/` folder is ignored by Git.

Do not commit `api_id`, `api_hash`, phone numbers, login codes, passwords, or saved session files.
