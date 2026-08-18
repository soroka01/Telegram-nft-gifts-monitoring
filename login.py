from __future__ import annotations

import asyncio
import getpass
import sqlite3
from datetime import datetime
from pathlib import Path

import qrcode
from telethon import TelegramClient
from telethon.errors import AuthKeyDuplicatedError, SessionPasswordNeededError

from main import AppConfig, ConfigError, load_config


def session_file_path(session_name: Path) -> Path:
    return session_name if session_name.suffix == ".session" else Path(f"{session_name}.session")


def remove_empty_session(session_name: Path) -> bool:
    session_path = session_file_path(session_name)
    if not session_path.exists() or session_path.stat().st_size != 0:
        return False
    session_path.unlink()
    return True


def archive_invalid_session(session_name: Path) -> Path:
    session_path = session_file_path(session_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = session_path.with_name(f"{session_path.name}.invalid-{timestamp}.bak")
    session_path.replace(backup_path)

    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = Path(f"{session_path}{suffix}")
        if sidecar.exists():
            sidecar.replace(Path(f"{backup_path}{suffix}"))
    return backup_path


def print_qr(url: str) -> None:
    print()
    print("Telegram на телефоне: Настройки -> Устройства -> Подключить устройство")
    print("Отсканируй QR-код:")
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    print()
    qr.print_ascii(invert=True)
    print()


async def authorize(config: AppConfig, attempts: int = 10, timeout_seconds: int = 55) -> None:
    telegram = config.telegram
    if telegram is None:
        raise ConfigError("Для MTProto-входа заполни telegram.api_id и telegram.api_hash в config.json.")

    if remove_empty_session(telegram.session_name):
        print("[SESSION] Удалён пустой session-файл после предыдущего неудачного восстановления.")

    for recovery_attempt in range(2):
        client = TelegramClient(str(telegram.session_name), telegram.api_id, telegram.api_hash)
        try:
            await client.connect()
            if await client.is_user_authorized():
                me = await client.get_me()
                print(f"[OK] Сессия уже авторизована: {getattr(me, 'id', 'unknown')}")
                return

            for qr_attempt in range(1, attempts + 1):
                qr_login = await client.qr_login()
                print(f"[QR] Попытка {qr_attempt}/{attempts}")
                print_qr(qr_login.url)
                try:
                    await qr_login.wait(timeout=timeout_seconds)
                    break
                except TimeoutError:
                    if qr_attempt == attempts:
                        raise ConfigError("Время QR-входа истекло. Запусти login.bat ещё раз.") from None
                    print("[QR] Код устарел, создаю новый...")
                except SessionPasswordNeededError:
                    password = getpass.getpass("Введи пароль 2FA Telegram: ")
                    await client.sign_in(password=password)
                    break

            if not await client.is_user_authorized():
                raise ConfigError("QR-вход не завершён.")
            me = await client.get_me()
            print(f"[OK] Новая NFT-сессия сохранена: {getattr(me, 'id', 'unknown')}")
            return
        except AuthKeyDuplicatedError:
            if recovery_attempt:
                raise ConfigError(
                    "Telegram повторно аннулировал новую NFT-сессию. Не копируй один session-файл "
                    "между компьютерами/VPS и не запускай его одновременно с разных IP."
                ) from None

            if client.is_connected():
                await client.disconnect()
            try:
                backup_path = archive_invalid_session(telegram.session_name)
            except FileNotFoundError as exc:
                raise ConfigError("Отозванный NFT session-файл не найден для пересоздания.") from exc
            print(f"[SESSION] Отозванная NFT-сессия сохранена в {backup_path}")
            print("[SESSION] Создаю отдельную новую сессию...")
        finally:
            if client.is_connected():
                await client.disconnect()


async def main() -> None:
    await authorize(load_config())
    print("[OK] Теперь можно запускать start.bat.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"[CONFIG] {exc}")
        raise SystemExit(1)
    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            print("[SESSION] Session-файл занят. Останови start.bat и повторно запусти login.bat.")
            raise SystemExit(1)
        raise
