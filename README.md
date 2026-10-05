# 🎁 Telegram NFT Gift Monitor

> Telegram-бот для отслеживания конкретных NFT-подарков по публичным страницам t.me.

🌐 **Язык / Language:** [Русский](README.md) · [English](README_EN.md)

![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-3.x-26A5E4?logo=telegram&logoColor=white)
![httpx](https://img.shields.io/badge/httpx-async_HTTP-0A7BBB)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## 📌 Overview

Telegram NFT Gift Monitor проверяет подарки вида `ExampleGift-12345`, сохраняет их последние снимки и уведомляет администраторов об изменениях. Монитор читает публичную страницу `https://t.me/nft/<slug>` и не требует пользовательского Telegram-аккаунта — нужен только токен бота.

> [!WARNING]
> Замените placeholder `admin_ids` из примера конфигурации: это синтаксически допустимый ID, а не заглушка.

## ✨ Features

- проверка доступности страницы подарка;
- название, коллекция и номер;
- владелец, публичная ссылка, TON address и avatar URL;
- модель, фон, символ и их rarity;
- количество выпущенных подарков и исходные сведения (original details);
- опциональное отслеживание image URL;
- ETag и Last-Modified для условных HTTP-запросов;
- отдельный backoff для каждого подарка;
- отложенные error alerts: только после заданного периода без успешного снимка;
- общий state, глобальный JSONL и отдельный JSONL каждого подарка;
- Telegram-команды и inline keyboard только для администраторов.

## 🏗️ How it works

```text
config.json
    │
    ▼
main.py ── t.me/nft/<slug> (публичный HTML)
    │
    ▼
нормализованный снимок + diff
    ├── Telegram: уведомления и команды
    ├── state/nft_gift_state.json
    └── JSONL-журналы: общий и по каждому подарку
```

Первый успешный снимок становится baseline. Затем при каждой успешной проверке обновляется state, а уведомления уходят только о значимых изменениях. Временная страница без NFT-таблицы игнорируется, если предыдущий снимок был корректным.

## 🚀 Quick start

### Requirements

- Python 3.14 или новее;
- Telegram-бот от [@BotFather](https://t.me/BotFather);
- Telegram user ID каждого администратора;
- хотя бы один NFT slug или полная ссылка.

### Installation

```bash
git clone https://github.com/soroka01/Telegram-nft-gifts-monitoring.git
cd Telegram-nft-gifts-monitoring
```

Windows: `start.bat` сам создаёт `.venv`, при первом запуске копирует `config.example.json` в `config.json` и останавливается, чтобы вы заполнили конфигурацию. При следующих запусках он обновляет pip, setuptools и wheel, ставит зависимости и запускает монитор.

Вручную (Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item config.example.json config.json
```

Вручную (Linux / macOS):

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
```

### Configuration

Заполните `config.json`:

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

Остальные поля необязательны, значения по умолчанию — в разделе «Configuration» ниже.

### Run

```bat
start.bat
```

или вручную:

```bash
python main.py
```

## ⚙️ Configuration

Монитор принимает команды и отправляет уведомления только пользователям из `bot.admin_ids`.

### Параметры `bot` и `monitor`

| Поле | Default | Описание |
| --- | --- | --- |
| `bot.token` | — | Токен бота; обязателен |
| `bot.admin_ids` | — | ID администраторов |
| `monitor.targets` | — | Список подарков; обязателен |
| `monitor.interval_seconds` | `30` | Пауза между циклами; минимум 5 секунд |
| `monitor.request_timeout_seconds` | `10` | HTTP timeout; минимум 2 секунды |
| `monitor.request_delay_seconds` | `0.25` | Пауза между подарками внутри цикла |
| `monitor.jitter_seconds` | `3` | Случайная добавка к паузе между циклами |
| `monitor.error_backoff_seconds` | `120` | Сколько пропускать цель после ошибки |
| `monitor.stale_error_notify_seconds` | `3600` | Сколько ошибка должна длиться до alert |
| `monitor.notify_initial_snapshot` | `true` | Отправить baseline после первого чтения |
| `monitor.notify_errors` | `true` | Разрешить автоматические error alerts |
| `monitor.track_image_url` | `false` | Считать изменение image URL значимым |
| `monitor.timezone` | `Europe/Moscow` | Часовой пояс для отображения |
| `monitor.state_path` | `state/nft_gift_state.json` | Путь к state |
| `monitor.events_path` | `logs/nft_gift_events.jsonl` | Путь к JSONL events |
| `monitor.user_agent` | browser-like | User-Agent публичных HTTP-запросов |

### Формат целей

В `targets` поддерживаются:

- slug: `ExampleGift-12345`;
- полная ссылка: `https://t.me/nft/ExampleGift-12345`;
- `tg://nft?slug=ExampleGift-12345`;
- объект с флагом включения: `{"slug": "ExampleGift-12345", "enabled": true}`.

Невалидные и повторяющиеся slug отбрасываются.

### Переменные окружения

Имеют приоритет над соответствующими полями `config.json`.

| Переменная | Default | Описание |
| --- | --- | --- |
| `BOT_TOKEN` | — | Заменяет `bot.token` |
| `ADMIN_IDS` | — | Заменяет `bot.admin_ids`, через запятую |
| `NFT_GIFT_TARGETS` | — | Заменяет `monitor.targets`, через запятую |

### Команды Telegram

| Команда | Действие |
| --- | --- |
| `/start` | Справка и inline keyboard |
| `/help` | Справка |
| `/status` | Состояние цикла, пути и последний результат |
| `/gifts` | Настроенные подарки и последние снимки |
| `/check` | Немедленно проверить все подарки |
| `/check ExampleGift-12345` | Проверить один slug |
| `/snapshot ExampleGift-12345` | Показать сохранённый снимок |

Пользователи вне `admin_ids` получают отказ в доступе.

### State, события и ошибки

| Путь | Содержимое |
| --- | --- |
| `state/nft_gift_state.json` | Последний снимок каждого slug |
| `logs/nft_gift_events.jsonl` | Baseline, значимые изменения и ошибки |
| `logs/gifts/<slug>/nft_gift_events.jsonl` | Та же лента для одного подарка |
| `logs/monitor.log` | Технический runtime log |

- Изменения quantity/issued/total обновляют state и видны в техническом логе, но если изменились только они, отдельный JSONL event не создаётся.
- Original details и avatar URL сами не вызывают alert: отдельно они пишутся как `ignored_change`, а при значимом изменении входят в общий JSONL event.
- Image URL вызывает alert только при `track_image_url = true`.
- После `429` или `5xx` конкретный slug переходит в backoff. Автоматическое сообщение об ошибке уходит, только если последнему успешному снимку больше `stale_error_notify_seconds`; ручной `/check` сообщает об ошибке сразу.

## 🗂️ Project structure

```text
.
├── main.py                # точка входа
├── nft_monitor/           # код: config, parser, diff, fetcher, monitor, bot, state
├── config.example.json    # шаблон конфигурации
├── config.json            # ваша конфигурация (не коммитится)
├── requirements.txt       # зависимости: aiogram, httpx, beautifulsoup4, tzdata
├── start.bat              # launcher для Windows
├── state/                 # state (создаётся при работе)
└── logs/                  # monitor.log и JSONL-журналы (создаётся при работе)
```

## 🔒 Security & privacy

- Никогда не коммитьте `config.json` или `.env`.
- State и JSONL могут содержать владельцев, TON addresses и историю изменений.
- После утечки bot token немедленно отзовите его через @BotFather.
- Монитор использует только публичные данные и не обходит приватность Telegram.

## ⚠️ Limitations

- HTML-разбор зависит от текущей структуры публичной страницы t.me.
- Монитор видит только то, что Telegram публикует на публичной NFT-странице.
- Telegram может ограничивать частые HTTP-запросы.
- Пустая или временно изменённая страница может задержать фиксацию события.
- Тексты бота и runtime logs преимущественно русскоязычные.
- Автоматических тестов и CI нет; полная проверка требует Bot API.

Если монитор не запускается: проверьте JSON-синтаксис `config.json`, замените placeholders (token, admin ID, targets), установите зависимости и изучите `logs/monitor.log`.

## 📄 License

Проект распространяется по лицензии [MIT](LICENSE).

## 💬 Support

Если проект оказался полезным, сделайте fork или поставьте звезду: [soroka01/Telegram-nft-gifts-monitoring](https://github.com/soroka01/Telegram-nft-gifts-monitoring).

---

with love ❤️
