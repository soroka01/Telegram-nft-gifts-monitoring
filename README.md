# 🎁 Telegram NFT Gift Monitor

> Telegram-бот для отслеживания конкретных NFT-подарков по публичным страницам t.me с опциональным MTProto-обогащением данных о продаже и владельце.

🌐 **Язык:** [Русский](README.md) · [English](README_EN.md)

![Python 3.14+](https://img.shields.io/badge/Python-3.14%2B-3776AB?logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram-Telegram_bot-26A5E4?logo=telegram&logoColor=white)
![Data sources](https://img.shields.io/badge/Data-public_web_%2B_optional_MTProto-6F42C1)
![MIT License](https://img.shields.io/badge/License-MIT-2EA44F.svg)

## ✨ Обзор

Telegram NFT Gift Monitor проверяет подарки вида `ExampleGift-12345`, сохраняет их последние снимки и уведомляет администраторов об изменениях. Основной режим читает публичную страницу `https://t.me/nft/<slug>` и не требует пользовательского Telegram-аккаунта.

Дополнительно монитор умеет обогащать снимок через MTProto: получать активную цену перепродажи и Telegram identity владельца. Этот режим требует `api_id`, `api_hash` и уже авторизованную Telethon session.

## 🧭 Режимы работы

| Режим | Что требуется | Данные |
| --- | --- | --- |
| HTTP-only | Bot token | Публичная NFT-страница, traits, владелец, TON address, original details |
| HTTP + MTProto | Bot token, API credentials, авторизованная user session | Всё из HTTP и дополнительно sale price и Telegram identity владельца |

Если `telegram.api_id` или `telegram.api_hash` остаются placeholder, монитор продолжает работать в HTTP-only режиме. Чтобы выбрать этот режим явно, установите `track_sale` в `false`.

## 🚀 Возможности

- проверка доступности страницы подарка;
- название, коллекция и номер;
- владелец, публичная ссылка, TON address и avatar URL;
- модель, фон, символ и их rarity;
- количество выпущенных подарков и исходные сведения;
- опциональное отслеживание image URL;
- опциональные sale status и цена в Stars/TON через MTProto;
- опциональные Telegram ID, peer type, username и display name владельца;
- ETag и Last-Modified для условных HTTP-запросов;
- отдельный backoff для каждого подарка;
- отложенные error alerts только после заданного периода без успешного снимка;
- общий state, глобальный JSONL и отдельный JSONL каждого подарка;
- Telegram-команды и inline keyboard только для администраторов.

## 🏗️ Как это работает

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

Первый успешный снимок становится baseline. Дальше монитор обновляет state при каждой успешной проверке и отправляет только значимые изменения. Временная страница без NFT-таблицы игнорируется, если предыдущий снимок был корректным.

## 📋 Требования

- Python 3.14 или новее (рекомендуется актуальный патч 3.14.6);
- pip 26.1.2, setuptools 84.0.0 и wheel 0.48.0 (launcher обновляет их автоматически);
- Telegram-бот от [@BotFather](https://t.me/BotFather);
- Telegram user ID каждого администратора;
- хотя бы один NFT slug или полная ссылка;
- для MTProto-режима: Telegram `api_id`, `api_hash` и авторизованная Telethon session.

Основные зависимости:

| Пакет | Назначение |
| --- | --- |
| `aiogram` | Bot API, команды и inline keyboard |
| `httpx` | Асинхронные HTTP-запросы |
| `beautifulsoup4` | Разбор публичной NFT-страницы |
| `telethon` | Опциональное MTProto enrichment |
| `tzdata` | IANA timezones на системах без системной базы |

## ⚙️ Установка и запуск

### 1. Клонируйте репозиторий

```bash
git clone https://github.com/soroka01/Telegram-nft-gifts-monitoring.git
cd Telegram-nft-gifts-monitoring
```

### 2. Быстрый старт на Windows

```bat
start.bat
```

При первом запуске файл:

1. создаст `.venv`;
2. скопирует `config.example.json` в `config.json`;
3. остановится, чтобы вы заполнили конфигурацию.

После настройки повторно запустите `start.bat`. Он установит зависимости и запустит монитор.

### 3. Ручной запуск

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

Linux или macOS:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.json config.json
python main.py
```

## 🎯 Цели мониторинга

Простой список:

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

Поддерживаются:

- slug `ExampleGift-12345`;
- полная ссылка `https://t.me/nft/ExampleGift-12345`;
- `tg://nft?slug=ExampleGift-12345`;
- объект с флагом включения:

```json
{"slug": "ExampleGift-12345", "enabled": true}
```

Невалидные и повторяющиеся slug отбрасываются.

## ⚙️ Конфигурация

### Bot

```json
{
  "bot": {
    "token": "PUT_TELEGRAM_BOT_TOKEN_HERE",
    "admin_ids": [123456789]
  }
}
```

Замените и token, и пример ID. Монитор принимает команды и отправляет уведомления только пользователям из `admin_ids`.

### MTProto — опционально

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

`track_sale = true` включает MTProto только когда `api_id` и `api_hash` заполнены. Репозиторий не создаёт и не авторизует user session автоматически: файл, указанный в `session_name`, должен быть заранее авторизован через Telethon. Без него HTTP monitoring продолжит работу, но sale/owner enrichment будет недоступен и появится warning в log.

Не используйте одну SQLite session одновременно в нескольких процессах.

### Monitor

| Поле | По умолчанию | Назначение |
| --- | ---: | --- |
| `targets` | — | Список подарков; обязателен |
| `interval_seconds` | `30` | Пауза между циклами; минимум 5 секунд |
| `request_timeout_seconds` | `10` | HTTP timeout; минимум 2 секунды |
| `request_delay_seconds` | `0.25` | Пауза между подарками внутри цикла |
| `jitter_seconds` | `3` | Случайная добавка к паузе между циклами |
| `error_backoff_seconds` | `120` | Сколько пропускать цель после ошибки |
| `stale_error_notify_seconds` | `3600` | Когда ошибка становится достаточно долгой для alert |
| `notify_initial_snapshot` | `true` | Отправить baseline после первого чтения |
| `notify_errors` | `true` | Разрешить автоматические error alerts |
| `track_image_url` | `false` | Считать image URL значимым изменением |
| `track_sale` | `true` | Разрешить MTProto enrichment при готовых credentials/session |
| `mtproto_min_interval_seconds` | `60` | Минимальный интервал MTProto lookup одного slug |
| `timezone` | `Europe/Moscow` | Timezone для отображения |
| `state_path` | `state/nft_gift_state.json` | Путь к state |
| `events_path` | `logs/nft_gift_events.jsonl` | Путь к JSONL events |
| `user_agent` | browser-like | User-Agent публичного HTTP-запроса |

### Переменные окружения

Значения окружения имеют приоритет над соответствующими полями:

| Переменная | Поле |
| --- | --- |
| `BOT_TOKEN` | `bot.token` |
| `ADMIN_IDS` | `bot.admin_ids`, comma-separated |
| `NFT_GIFT_TARGETS` | `monitor.targets`, comma-separated |
| `TG_API_ID` | `telegram.api_id` |
| `TG_API_HASH` | `telegram.api_hash` |
| `TG_SESSION_NAME` | `telegram.session_name` |

## 🤖 Команды Telegram

| Команда | Действие |
| --- | --- |
| `/start` | Справка и inline keyboard |
| `/help` | Справка |
| `/status` | Состояние цикла, paths и последний результат |
| `/gifts` | Настроенные подарки и последние snapshots |
| `/check` | Немедленно проверить все подарки |
| `/check ExampleGift-12345` | Проверить один slug |
| `/snapshot ExampleGift-12345` | Показать сохранённый snapshot |

Запросы пользователей вне `admin_ids` получают отказ в доступе.

## 💾 State, события и ошибки

| Путь | Содержимое |
| --- | --- |
| `state/nft_gift_state.json` | Последний snapshot каждого slug |
| `logs/nft_gift_events.jsonl` | Baseline, meaningful changes и errors |
| `logs/gifts/<slug>/nft_gift_events.jsonl` | Та же лента для одного подарка |
| `logs/monitor.log` | Технический runtime log |
| `state/nft_gift_account.session` | Опциональная Telethon session |

Изменения quantity/issued/total обновляют state и видны в техническом log, но если изменились только эти поля, отдельный JSONL event не создаётся. Original details и avatar URL сами не вызывают Telegram alert: при отдельном изменении они пишутся как `ignored_change`, а при одновременном значимом изменении входят в общий JSONL event. Image URL вызывает alert только при `track_image_url = true`.

После `429` или `5xx` конкретный slug переходит в backoff. Автоматическое сообщение об ошибке отправляется только когда последнего успешного снимка нет дольше `stale_error_notify_seconds`; ручной `/check` сообщает ошибку сразу.

## 🔐 Безопасность

- Никогда не коммитьте `config.json`, `.env`, `*.session` или `*.session-journal`.
- Замените placeholder `admin_ids`; он является синтаксически допустимым ID.
- Telethon session даёт доступ пользовательского аккаунта и требует той же защиты, что пароль.
- State и JSONL могут содержать владельцев, TON addresses и историю изменений.
- После утечки bot token или API credentials немедленно отзовите их.

## ⚠️ Ограничения

- HTML-разбор зависит от текущей структуры публичной страницы t.me.
- HTTP-only режим не знает приватные MTProto sale/owner fields.
- MTProto enrichment не работает без заранее авторизованной user session.
- Telegram может ограничивать частые HTTP и MTProto запросы.
- Пустая или временно изменённая публичная страница может задержать фиксацию события.
- Тексты бота и runtime logs преимущественно русскоязычные.

## 🧪 Проверка и диагностика

В репозитории пока нет автоматических тестов и CI. Полноценная проверка требует Bot API, а MTProto-режим дополнительно требует user session.

Если монитор не запускается:

1. Проверьте JSON-синтаксис `config.json`.
2. Замените token, admin ID и targets placeholders.
3. Установите зависимости: `python -m pip install -r requirements.txt`.
4. Для HTTP-only явно установите `track_sale` в `false`.
5. Для MTProto проверьте `api_id`, `api_hash`, путь и авторизацию session.
6. Изучите `logs/monitor.log`.

## 📄 Лицензия

Проект распространяется по лицензии [MIT](LICENSE).

---

Сделано для прозрачного мониторинга публичных данных без обхода приватности Telegram.
