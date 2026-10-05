# 🎁 Telegram NFT Gift Monitor

> A Telegram bot that tracks specific NFT gifts through public t.me pages.

🌐 **Язык / Language:** [Русский](README.md) · [English](README_EN.md)

![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-26A5E4?logo=telegram&logoColor=white)
![httpx](https://img.shields.io/badge/httpx-async_HTTP-0A7BBB)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## 📌 Overview

Telegram NFT Gift Monitor checks gifts such as `ExampleGift-12345`, stores their latest snapshots, and notifies administrators about changes. It reads the public `https://t.me/nft/<slug>` page and does not require a Telegram user account — only a bot token.

> [!WARNING]
> Replace the placeholder `admin_ids` from the example config: it is a syntactically valid ID, not a dummy value.

## ✨ Features

- gift page availability checks;
- title, collection, and number;
- owner, public link, TON address, and avatar URL;
- model, backdrop, symbol, and their rarity values;
- issued quantity and original details;
- optional image URL tracking;
- ETag and Last-Modified conditional HTTP requests;
- independent backoff for each gift;
- delayed error alerts: only after a configurable period without a successful snapshot;
- shared state, global JSONL, and per-gift JSONL;
- administrator-only Telegram commands and inline keyboard.

## 🏗️ How it works

```text
config.json
    │
    ▼
main.py ── t.me/nft/<slug> (public HTML)
    │
    ▼
normalized snapshot + diff
    ├── Telegram: alerts and commands
    ├── state/nft_gift_state.json
    └── JSONL logs: global and per gift
```

The first successful snapshot becomes the baseline. Every later successful check updates state and sends alerts only for meaningful changes. A transient page without an NFT table is ignored when the previous snapshot was valid.

## 🚀 Quick start

### Requirements

- Python 3.14 or newer;
- a Telegram bot from [@BotFather](https://t.me/BotFather);
- the Telegram user ID of each administrator;
- at least one NFT slug or full URL.

### Installation

```bash
git clone https://github.com/soroka01/Telegram-nft-gifts-monitoring.git
cd Telegram-nft-gifts-monitoring
```

Windows: `start.bat` creates `.venv`, copies `config.example.json` to `config.json` on first run, and stops so you can fill in the configuration. On later runs it upgrades pip, setuptools, and wheel, installs dependencies, and starts the monitor.

Manually (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

Manually (Linux / macOS):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

### Configuration

Fill in `config.json`:

```json
{
  "bot": {
    "token": "PUT_TELEGRAM_BOT_TOKEN_HERE",
    "admin_ids": [123456789]
  },
  "monitor": {
    "targets": [
      "ExampleGift-12345",
      "https://t.me/nft/AnotherGift-67890"
    ]
  }
}
```

All other fields are optional; defaults are listed in the "Configuration" section below.

### Run

```bat
start.bat
```

or manually:

```bash
python main.py
```

## ⚙️ Configuration

The monitor accepts commands from and sends notifications only to users in `bot.admin_ids`.

### `bot` and `monitor` fields

| Field | Default | Description |
| --- | --- | --- |
| `bot.token` | — | Bot token; required |
| `bot.admin_ids` | — | Administrator IDs |
| `monitor.targets` | — | Gift list; required |
| `monitor.interval_seconds` | `30` | Delay between cycles; minimum 5 seconds |
| `monitor.request_timeout_seconds` | `10` | HTTP timeout; minimum 2 seconds |
| `monitor.request_delay_seconds` | `0.25` | Delay between gifts within one cycle |
| `monitor.jitter_seconds` | `3` | Random addition to the cycle delay |
| `monitor.error_backoff_seconds` | `120` | How long to skip a target after an error |
| `monitor.stale_error_notify_seconds` | `3600` | How long an error must persist before an alert |
| `monitor.notify_initial_snapshot` | `true` | Send the baseline after the first read |
| `monitor.notify_errors` | `true` | Allow automatic error alerts |
| `monitor.track_image_url` | `false` | Treat image URL changes as significant |
| `monitor.timezone` | `Europe/Moscow` | Display time zone |
| `monitor.state_path` | `state/nft_gift_state.json` | State path |
| `monitor.events_path` | `logs/nft_gift_events.jsonl` | JSONL event path |
| `monitor.user_agent` | browser-like | User-Agent for public HTTP requests |

### Target formats

`targets` accepts:

- a slug: `ExampleGift-12345`;
- a full URL: `https://t.me/nft/ExampleGift-12345`;
- `tg://nft?slug=ExampleGift-12345`;
- an object with an enable flag: `{"slug": "ExampleGift-12345", "enabled": true}`.

Invalid and duplicate slugs are discarded.

### Environment variables

They take precedence over the matching `config.json` fields.

| Variable | Default | Description |
| --- | --- | --- |
| `BOT_TOKEN` | — | Overrides `bot.token` |
| `ADMIN_IDS` | — | Overrides `bot.admin_ids`, comma-separated |
| `NFT_GIFT_TARGETS` | — | Overrides `monitor.targets`, comma-separated |

### Telegram commands

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

### State, events, and errors

| Path | Contents |
| --- | --- |
| `state/nft_gift_state.json` | Latest snapshot for each slug |
| `logs/nft_gift_events.jsonl` | Baselines, meaningful changes, and errors |
| `logs/gifts/<slug>/nft_gift_events.jsonl` | The same stream for one gift |
| `logs/monitor.log` | Technical runtime log |

- Quantity/issued/total changes update state and appear in the technical log, but no separate JSONL event is written when only those fields change.
- Original details and avatar URLs do not trigger alerts: on their own they are written as `ignored_change`, and alongside a significant change they are included in the shared JSONL event.
- Image URL changes alert only when `track_image_url = true`.
- After a `429` or `5xx`, the affected slug enters backoff. An automatic error message is sent only when the latest successful snapshot is older than `stale_error_notify_seconds`; a manual `/check` reports the error immediately.

## 🗂️ Project structure

```text
.
├── main.py                # entry point
├── nft_monitor/           # code: config, parser, diff, fetcher, monitor, bot, state
├── config.example.json    # configuration template
├── config.json            # your configuration (not committed)
├── requirements.txt       # dependencies: aiogram, httpx, beautifulsoup4, tzdata
├── start.bat              # Windows launcher
├── state/                 # state (created at runtime)
└── logs/                  # monitor.log and JSONL logs (created at runtime)
```

## 🔒 Security & privacy

- Never commit `config.json` or `.env`.
- State and JSONL may contain owners, TON addresses, and change history.
- Revoke a leaked bot token immediately via @BotFather.
- The monitor uses public data only and does not bypass Telegram privacy.

## ⚠️ Limitations

- HTML parsing depends on the current public t.me page structure.
- The monitor sees only data that Telegram publishes on the public NFT page.
- Telegram may rate-limit frequent HTTP requests.
- A missing or transient public page may delay an event.
- Bot messages and runtime logs are primarily in Russian.
- There are no automated tests or CI; end-to-end verification requires the Bot API.

If the monitor does not start: validate the JSON syntax in `config.json`, replace the placeholders (token, admin ID, targets), install dependencies, and read `logs/monitor.log`.

## 📄 License

This project is distributed under the [MIT License](LICENSE).

## 💬 Support

If you find the project useful, fork it or give it a star: [soroka01/Telegram-nft-gifts-monitoring](https://github.com/soroka01/Telegram-nft-gifts-monitoring).

---

with love ❤️
