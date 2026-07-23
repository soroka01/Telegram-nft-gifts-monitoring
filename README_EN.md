# 🎁 Telegram NFT Gift Monitor

> A Telegram bot that tracks specific NFT gifts through public t.me pages with optional MTProto enrichment for sale and owner data.

🌐 **Language:** [Русский](README.md) · [English](README_EN.md)

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![Data sources](https://img.shields.io/badge/Data-public_web_%2B_optional_MTProto-6F42C1)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## ✨ Overview

Telegram NFT Gift Monitor checks gifts such as `ExampleGift-12345`, stores their latest snapshots, and notifies administrators about changes. Its primary mode reads the public `https://t.me/nft/<slug>` page and does not require a Telegram user account.

The monitor can optionally enrich snapshots through MTProto with active resale prices and the owner's Telegram identity. This mode requires an `api_id`, an `api_hash`, and an already authorized Telethon session.

## 🧭 Operating Modes

| Mode | Requirements | Data |
| --- | --- | --- |
| HTTP-only | Bot token | Public NFT page, traits, owner, TON address, original details |
| HTTP + MTProto | Bot token, API credentials, authorized user session | All HTTP data plus sale price and owner Telegram identity |

If `telegram.api_id` or `telegram.api_hash` remain placeholders, the monitor continues in HTTP-only mode. Set `track_sale` to `false` to select that mode explicitly.

## 🚀 Features

- gift page availability checks;
- title, collection, and number;
- owner, public link, TON address, and avatar URL;
- model, backdrop, symbol, and their rarity values;
- issued quantity and original details;
- optional image URL tracking;
- optional sale status and Stars/TON pricing through MTProto;
- optional owner Telegram ID, peer type, username, and display name;
- ETag and Last-Modified conditional HTTP requests;
- independent backoff for each gift;
- delayed error alerts after a configurable period without a successful snapshot;
- shared state, global JSONL, and per-gift JSONL;
- administrator-only Telegram commands and an inline keyboard.

## 🏗️ How It Works

```text
config.json
    │
    ▼
main.py
    ├── t.me/nft/<slug> ───────── public HTML snapshot
    └── Telethon (optional) ───── sale + owner enrichment
    │
    ▼
normalized snapshot + diff
    ├── Telegram alerts and commands
    ├── state/nft_gift_state.json
    └── global and per-gift JSONL logs
```

The first successful snapshot becomes the baseline. Every later successful check updates state and sends only meaningful changes. A transient page without an NFT table is ignored when the previous snapshot was valid.

## 📋 Requirements

- Python 3.10 or newer;
- a Telegram bot from [@BotFather](https://t.me/BotFather);
- the Telegram user ID of each administrator;
- at least one NFT slug or full URL;
- for MTProto mode: Telegram `api_id`, `api_hash`, and an authorized Telethon session.

Main dependencies:

| Package | Purpose |
| --- | --- |
| `aiogram` | Bot API, commands, and inline keyboard |
| `httpx` | Asynchronous HTTP requests |
| `beautifulsoup4` | Public NFT page parsing |
| `telethon` | Optional MTProto enrichment |
| `tzdata` | IANA time zones on systems without a system database |

## ⚙️ Installation and Running

### 1. Clone the repository

```bash
git clone https://github.com/soroka01/Telegram-nft-gifts-monitoring.git
cd Telegram-nft-gifts-monitoring
```

### 2. Quick start on Windows

```bat
start.bat
```

On its first run, the launcher:

1. creates `.venv`;
2. copies `config.example.json` to `config.json`;
3. exits so you can fill in the configuration.

Run `start.bat` again after configuration. It installs dependencies and starts the monitor.

### 3. Manual start

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
python main.py
```

Linux or macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

## 🎯 Monitoring Targets

A simple list:

```json
{
  "monitor": {
    "targets": [
      "ExampleGift-12345",
      "https://t.me/nft/AnotherGift-67890"
    ]
  }
}
```

Supported forms:

- a slug such as `ExampleGift-12345`;
- a full URL such as `https://t.me/nft/ExampleGift-12345`;
- `tg://nft?slug=ExampleGift-12345`;
- an object with an enable flag:

```json
{"slug": "ExampleGift-12345", "enabled": true}
```

Invalid and duplicate slugs are discarded.

## ⚙️ Configuration

### Bot

```json
{
  "bot": {
    "token": "PUT_TELEGRAM_BOT_TOKEN_HERE",
    "admin_ids": [123456789]
  }
}
```

Replace both the token and the example ID. The monitor accepts commands from and sends notifications only to users in `admin_ids`.

### MTProto — Optional

```json
{
  "telegram": {
    "api_id": "PUT_API_ID_HERE",
    "api_hash": "PUT_API_HASH_HERE",
    "session_name": "state/nft_gift_account"
  },
  "monitor": {
    "track_sale": true,
    "mtproto_min_interval_seconds": 60
  }
}
```

`track_sale = true` enables MTProto only when both `api_id` and `api_hash` are filled in. The repository does not create or authorize a user session automatically: the file selected by `session_name` must already be authorized through Telethon. Without it, HTTP monitoring continues, but sale/owner enrichment is unavailable and the log contains a warning.

Do not use the same SQLite session from multiple processes at the same time.

### Monitor

| Field | Default | Purpose |
| --- | ---: | --- |
| `targets` | — | Gift list; required |
| `interval_seconds` | `30` | Delay between cycles; minimum 5 seconds |
| `request_timeout_seconds` | `10` | HTTP timeout; minimum 2 seconds |
| `request_delay_seconds` | `0.25` | Delay between gifts within one cycle |
| `jitter_seconds` | `3` | Random addition to the cycle delay |
| `error_backoff_seconds` | `120` | How long to skip a target after an error |
| `stale_error_notify_seconds` | `3600` | How long an error must persist before an alert |
| `notify_initial_snapshot` | `true` | Send the first baseline |
| `notify_errors` | `true` | Allow automatic error alerts |
| `track_image_url` | `false` | Treat image URL changes as significant |
| `track_sale` | `true` | Allow MTProto enrichment when credentials/session are ready |
| `mtproto_min_interval_seconds` | `60` | Minimum interval between MTProto lookups for one slug |
| `timezone` | `Europe/Moscow` | Display time zone |
| `state_path` | `state/nft_gift_state.json` | State path |
| `events_path` | `logs/nft_gift_events.jsonl` | JSONL event path |
| `user_agent` | browser-like | User-Agent for public HTTP requests |

### Environment Variables

Environment values take precedence over matching fields:

| Variable | Field |
| --- | --- |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, comma-separated |
| `NFT_GIFT_TARGETS` | `monitor.targets`, comma-separated |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_SESSION_NAME` | `telegram.session_name` |

## 🤖 Telegram Commands

| Command | Action |
| --- | --- |
| `/start` | Help and inline keyboard |
| `/help` | Help |
| `/status` | Cycle state, paths, and last result |
| `/gifts` | Configured gifts and latest snapshots |
| `/check` | Check every gift immediately |
| `/check ExampleGift-12345` | Check one slug |
| `/snapshot ExampleGift-12345` | Show a saved snapshot |

Users outside `admin_ids` receive an access-denied response.

## 💾 State, Events, and Errors

| Path | Contents |
| --- | --- |
| `state/nft_gift_state.json` | Latest snapshot for each slug |
| `logs/nft_gift_events.jsonl` | Baselines, meaningful changes, and errors |
| `logs/gifts/<slug>/nft_gift_events.jsonl` | The same stream for one gift |
| `logs/monitor.log` | Technical runtime log |
| `state/nft_gift_account.session` | Optional Telethon session |

Quantity/issued/total changes update state and appear in the technical log, but no separate JSONL event is written when only those fields change. Original details and avatar URLs do not trigger alerts: on their own they are written as `ignored_change`, and alongside a significant change they are included in the shared JSONL event. Image URL changes alert only when `track_image_url = true`.

After a `429` or `5xx`, the affected slug enters backoff. An automatic error message is sent only when the latest successful snapshot is older than `stale_error_notify_seconds`; a manual `/check` reports the error immediately.

## 🔐 Security

- Never commit `config.json`, `.env`, `*.session`, or `*.session-journal`.
- Replace the placeholder `admin_ids`; it is a syntactically valid ID.
- A Telethon session grants access to a user account and needs password-level protection.
- State and JSONL may contain owners, TON addresses, and change history.
- Revoke leaked bot tokens or API credentials immediately.

## ⚠️ Limitations

- HTML parsing depends on the current public t.me page structure.
- HTTP-only mode cannot provide private MTProto sale/owner fields.
- MTProto enrichment does not work without a pre-authorized user session.
- Telegram may rate-limit frequent HTTP and MTProto requests.
- A missing or transient public page may delay an event.
- Bot messages and runtime logs are primarily in Russian.

## 🧪 Testing and Troubleshooting

The repository currently has no automated tests or CI. End-to-end verification requires the Bot API, and MTProto mode additionally requires a user session.

If the monitor does not start:

1. Validate the JSON syntax in `config.json`.
2. Replace token, admin ID, and target placeholders.
3. Install dependencies with `python -m pip install -r requirements.txt`.
4. Set `track_sale` to `false` explicitly for HTTP-only mode.
5. For MTProto, verify the `api_id`, `api_hash`, session path, and authorization.
6. Read `logs/monitor.log`.

## 📄 License

This project is distributed under the [MIT License](LICENSE).

---

Built for transparent monitoring of public data without bypassing Telegram privacy.
