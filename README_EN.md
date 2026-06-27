# NFT Gift Monitor

Monitor specific Telegram NFT gifts such as `ExampleGift-12345`.

No Telegram user account or Telethon session is required. The monitor reads the public page at `https://t.me/nft/<slug>`, while a Telegram bot is used for notifications and commands.

## What It Tracks

- gift page availability;
- owner name, owner link, TON owner address;
- model and model rarity;
- backdrop and backdrop rarity;
- symbol and symbol rarity;
- title, collection, and number;
- gift image URL, if `track_image_url` is enabled.

Changes to quantity, issued count, original sender, and original recipient are not sent as bot alerts. They are still saved to state and JSONL logs as quiet changes.

## Setup

1. Create a dedicated Telegram bot with BotFather.
2. Run `start.bat` once. It will create `config.json`.
3. Fill in `bot.token`, `bot.admin_ids`, and the gift list.

Example:

```json
{
  "bot": {
    "token": "PUT_TELEGRAM_BOT_TOKEN_HERE",
    "admin_ids": [123456789]
  },
  "monitor": {
    "targets": [
      "ExampleGift-12345",
      "AnotherGift-67890"
    ],
    "interval_seconds": 30
  }
}
```

You can also paste a full URL such as `https://t.me/nft/ExampleGift-12345`; the script will extract the slug.

## Polling Interval

The default `interval_seconds` is `30`. For a small list of gifts, you can lower it, for example to `10`. If Telegram starts returning `429` or `5xx`, the monitor applies `error_backoff_seconds`.

`request_delay_seconds` adds a small pause between gifts within one check cycle. `jitter_seconds` adds a random delay between cycles so requests are not perfectly mechanical.

## Bot Commands

- `/status` - monitor status;
- `/gifts` - configured gifts and latest snapshots;
- `/check` - check all gifts now;
- `/check ExampleGift-12345` - check one gift;
- `/snapshot ExampleGift-12345` - show the latest saved snapshot.

## Files

- `state/nft_gift_state.json` - latest snapshot for each gift;
- `logs/nft_gift_events.jsonl` - global event stream;
- `logs/gifts/<slug>/nft_gift_events.jsonl` - per-gift event stream;
- `logs/monitor.log` - technical log.

## Notes

Telegram Bot API does not provide a method to fetch an NFT gift by slug. This monitor therefore reads the public web page instead of querying Telegram as a user account. It does not need a user session and does not spam a user account.

## License

MIT. See [LICENSE](LICENSE).
