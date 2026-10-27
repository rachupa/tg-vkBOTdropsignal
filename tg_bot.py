import asyncio
import html
import logging
import json
import os
import random
import sqlite3
import urllib.parse
from contextlib import contextmanager
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv
# Пути привязаны к папке проекта, а не к рабочей папке терминала.
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(PROJECT_DIR, ".env"))
def resolve_project_path(path: str) -> str:
    """Преобразует путь проекта в абсолютный; абсолютные пути не меняет."""
    if not path:
        return ""
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_DIR, path)
# Токен хранится только в переменной окружения BOT_TOKEN.
TOKEN = os.getenv("BOT_TOKEN")
MAIN_MENU_PHOTO_PATH = "images/1_mes.png"
DEVELOPER_URL = "https://t.me/grinyagera"
DEVELOPER_MESSAGE_TEMPLATE = (
    "Здравствуйте! Я из бота «Дроп-Сигнал».\n\nМой вопрос по проекту: "
)
PDF_PATH = "documents/p_72.pdf"
# Видеораздел. Ссылки задаются в .env, чтобы их можно было менять без правки кода.
VIDEO_MAIN_URL = os.getenv("VIDEO_MAIN_URL", "https://youtu.be/DD94Hkeodlc").strip()
VIDEO_SHORT_1_URL = os.getenv("VIDEO_SHORT_1_URL", "https://youtube.com/shorts/tlZ1j-yC3tE?feature=share").strip()
VIDEO_SHORT_2_URL = os.getenv("VIDEO_SHORT_2_URL", "https://youtube.com/shorts/BMCvTGrwSiY?feature=share").strip()
VIDEO_SHORT_3_URL = os.getenv("VIDEO_SHORT_3_URL", "https://youtube.com/shorts/7OAKXIL2GEA?feature=share").strip()
VIDEO_SHORT_4_URL = os.getenv("VIDEO_SHORT_4_URL", "https://youtube.com/shorts/18rc6ymUk6I?feature=share").strip()
# Изображения разделов. Добавьте файлы с этими именами в папку images.
SECTION_PHOTO_PATHS = {
    "useful_links": "images/useful_links.png",
    "parents_memo": "images/parents_memo.png",
    "about_creators": "images/about_creators.png",
    "videos": "images/questions/video.png",
    # Иллюстрации обратной связи после ответа на каждый вопрос.
    "answer_true": "images/true.png",
    "answer_false": "images/false.png",
    # Подтверждение сброса остаётся текстовым экраном без изображения.
    "restart_confirm": "",
    # Картинка итогового экрана (файл images/results.png).
    "results": "images/results.png",
    # Экран PDF остаётся текстовым экраном без изображения.
    "download_pdf": "",
}
# ID уже загруженных фото сохраняются локально, чтобы не отправлять тяжёлые PNG
# в Telegram заново при каждом открытии раздела.
PHOTO_CACHE_FILE = resolve_project_path(os.getenv("PHOTO_CACHE_FILE", "telegram_photo_cache.json"))
def _load_photo_cache() -> dict:
    try:
        with open(PHOTO_CACHE_FILE, "r", encoding="utf-8") as cache_file:
            data = json.load(cache_file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
PHOTO_FILE_ID_CACHE = _load_photo_cache()
_MEDIA_LOCKS: dict[str, asyncio.Lock] = {}
def _media_lock(cache_key: str) -> asyncio.Lock:
    # Один и тот же ещё не закешированный файл не должен параллельно загружаться
    # несколькими пользователями: первый запрос загрузит его, остальные возьмут file_id.
    lock = _MEDIA_LOCKS.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _MEDIA_LOCKS[cache_key] = lock
    return lock
def _save_photo_cache_sync() -> None:
    temp_path = f"{PHOTO_CACHE_FILE}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as cache_file:
            json.dump(PHOTO_FILE_ID_CACHE, cache_file, ensure_ascii=False, separators=(",", ":"))
        os.replace(temp_path, PHOTO_CACHE_FILE)
    except OSError:
        logging.getLogger(__name__).warning(
            "Не удалось сохранить кеш Telegram-медиа в %s", PHOTO_CACHE_FILE, exc_info=True
        )
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
async def _save_photo_cache() -> None:
    # Файловый I/O не блокирует event loop Telegram.
    await asyncio.to_thread(_save_photo_cache_sync)
def _file_signature(path: str) -> tuple[int, int]:
    stat = os.stat(path)
    return stat.st_size, stat.st_mtime_ns
def _cached_file_id(cache_key: str, size: int, mtime_ns: int) -> str | None:
    entry = PHOTO_FILE_ID_CACHE.get(cache_key)
    if (
        isinstance(entry, dict)
        and entry.get("size") == size
        and entry.get("mtime_ns") == mtime_ns
        and isinstance(entry.get("file_id"), str)
    ):
        return entry["file_id"]
    return None
def get_scenario_photo_path(scenario: dict) -> str:
    return scenario.get("image_path", "")
async def answer_photo_cached(
    message: Message,
    *,
    photo_path: str,
    caption: str | None = None,
    reply_markup=None,
    parse_mode: str = "HTML",
):
    """Загружает локальное фото только один раз, затем использует Telegram file_id."""
    photo_path = resolve_project_path(photo_path)
    size, mtime_ns = _file_signature(photo_path)
    cache_key = os.path.normcase(os.path.abspath(photo_path))
    async with _media_lock(cache_key):
        cached_file_id = _cached_file_id(cache_key, size, mtime_ns)
        if cached_file_id:
            try:
                return await message.answer_photo(
                    photo=cached_file_id,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except TelegramBadRequest as exc:
                error_text = str(exc).lower()
                if not any(
                    fragment in error_text
                    for fragment in ("wrong file identifier", "file identifier", "file_id", "invalid file")
                ):
                    raise
                PHOTO_FILE_ID_CACHE.pop(cache_key, None)
        sent_message = await message.answer_photo(
            photo=FSInputFile(photo_path),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        if sent_message.photo:
            PHOTO_FILE_ID_CACHE[cache_key] = {
                "file_id": sent_message.photo[-1].file_id,
                "size": size,
                "mtime_ns": mtime_ns,
            }
            await _save_photo_cache()
        return sent_message
async def answer_document_cached(
    message: Message,
    *,
    document_path: str,
    filename: str,
    caption: str | None = None,
):
    """Кеширует file_id PDF/документа, чтобы повторные скачивания не грузили файл с диска."""
    document_path = resolve_project_path(document_path)
    size, mtime_ns = _file_signature(document_path)
    cache_key = f"document:{os.path.normcase(os.path.abspath(document_path))}"
    async with _media_lock(cache_key):
        cached_file_id = _cached_file_id(cache_key, size, mtime_ns)
        if cached_file_id:
            try:
                return await message.answer_document(document=cached_file_id, caption=caption)
            except TelegramBadRequest as exc:
                error_text = str(exc).lower()
                if not any(
                    fragment in error_text
                    for fragment in ("wrong file identifier", "file identifier", "file_id", "invalid file")
                ):
                    raise
                PHOTO_FILE_ID_CACHE.pop(cache_key, None)
        sent_message = await message.answer_document(
            document=FSInputFile(document_path, filename=filename),
            caption=caption,
        )
        if sent_message.document:
            PHOTO_FILE_ID_CACHE[cache_key] = {
                "file_id": sent_message.document.file_id,
                "size": size,
                "mtime_ns": mtime_ns,
            }
            await _save_photo_cache()
        return sent_message
async def answer_with_optional_photo(
    message: Message,
    *,
    text: str,
    reply_markup=None,
    photo_path: str = "",
    parse_mode: str = "HTML",
    **kwargs,
):
    """Отправляет фото с подписью, если ресурс доступен; иначе не ломает экран."""
    resolved_photo_path = resolve_project_path(photo_path) if photo_path else ""
    has_photo = bool(resolved_photo_path) and os.path.isfile(resolved_photo_path)
    if has_photo:
        if len(text) <= 1000:
            return await answer_photo_cached(
                message,
                photo_path=resolved_photo_path,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        await answer_photo_cached(message, photo_path=resolved_photo_path, parse_mode=parse_mode)
    return await message.answer(
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        **kwargs,
    )
async def delete_message_safely(message: Message) -> None:
    try:
        await message.delete()
    except TelegramBadRequest:
        logging.getLogger(__name__).debug("Старое сообщение уже удалено или недоступно")
    except Exception:
        logging.getLogger(__name__).warning("Не удалось удалить старое сообщение", exc_info=True)
# ==========================================
# === БАЗА ДАННЫХ (SQLITE) =================
# ==========================================
DB_FILE = resolve_project_path(os.getenv("DB_FILE", "bot_data.db"))
def _connect_db():
    """Открывает соединение с таймаутом ожидания блокировки SQLite."""
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn
@contextmanager
def _db_connection():
    """Гарантирует commit/rollback и закрытие соединения."""
    conn = _connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
def init_db():
    """Инициализирует БД. Выполняется в отдельном потоке при запуске."""
    with _db_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id INTEGER PRIMARY KEY,
                index_num INTEGER NOT NULL DEFAULT 0,
                score INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0
            )
        """)
def _get_user_session_sync(user_id: int) -> dict:
    with _db_connection() as conn:
        row = conn.execute(
            "SELECT index_num, score, completed FROM user_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row:
        return {"index": row["index_num"], "score": row["score"], "completed": bool(row["completed"])}
    return {"index": 0, "score": 0, "completed": False}
async def get_user_session(user_id: int) -> dict:
    """Читает прогресс вне event loop, чтобы SQLite не блокировал обработчики."""
    return await asyncio.to_thread(_get_user_session_sync, user_id)
def _save_user_session_sync(user_id: int, index: int, score: int, completed: bool):
    with _db_connection() as conn:
        conn.execute("""
            INSERT INTO user_sessions (user_id, index_num, score, completed)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                index_num = excluded.index_num,
                score = excluded.score,
                completed = excluded.completed
        """, (user_id, index, score, int(completed)))
async def save_user_session(user_id: int, index: int, score: int, completed: bool):
    await asyncio.to_thread(_save_user_session_sync, user_id, index, score, completed)
def _reset_user_session_sync(user_id: int):
    with _db_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
async def reset_user_session(user_id: int):
    await asyncio.to_thread(_reset_user_session_sync, user_id)
def _record_answer_sync(user_id: int, expected_index: int, is_correct: bool, total: int):
    """Атомарно фиксирует ответ. Повторный callback не начислит очко дважды."""
    conn = _connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT index_num, score, completed FROM user_sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            current_index, current_score, completed = 0, 0, False
            conn.execute(
                "INSERT INTO user_sessions (user_id, index_num, score, completed) VALUES (?, 0, 0, 0)",
                (user_id,),
            )
        else:
            current_index = row["index_num"]
            current_score = row["score"]
            completed = bool(row["completed"])
        if completed or current_index != expected_index or current_index < 0 or current_index >= total:
            conn.rollback()
            return None
        new_index = current_index + 1
        new_score = current_score + int(is_correct)
        is_completed = new_index >= total
        conn.execute(
            "UPDATE user_sessions SET index_num = ?, score = ?, completed = ? WHERE user_id = ?",
            (new_index, new_score, int(is_completed), user_id),
        )
        conn.commit()
        return {"index": new_index, "score": new_score, "completed": is_completed}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
async def record_answer(user_id: int, expected_index: int, is_correct: bool, total: int):
    return await asyncio.to_thread(_record_answer_sync, user_id, expected_index, is_correct, total)
SCENARIOS = [
    {
        "id": 1,
        "image_path": "images/questions/q1.png",
        "text": (
            "📱 <b>Сообщение в Telegram-чате подработки:</b>\n\n"
            "<i>👤 «Привет! Есть лёгкая подработка на 15 минут. Нужно забрать карту в банке и скинуть фото реквизитов. Плачу 5 000 руб. Интересно?»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Согласиться — деньги нужны срочно",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ловушка.</b> Передача карты или данных онлайн-банка третьим лицам — классическая вербовка дропа.\n\n"
                    "⚖️ <b>Последствия:</b> ст. 187 УК РФ, блокировка счетов по 161-ФЗ, иск по ст. 1102 ГК РФ."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Заблокировать — продажа реквизитов (ст. 187 УК РФ)",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Вы заметили главный красный флаг — передачу личных банковских реквизитов."
                ),
            },
        ],
    },
    {
        "id": 2,
        "image_path": "images/questions/q2.png",
        "text": (
            "📱 <b>Сообщение от одноклассника:</b>\n\n"
            "<i>👤 «Привет! Я перевёл тебе 350 рублей за вчерашнюю пиццу в кафе по номеру телефона через СБП. Проверишь?»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Принять — обычная бытовая ситуация",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Правильно.</b> Это безопасный перевод между друзьями за совместную покупку. Человек знаком лично, чужих денег в цепочке нет."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться и заблокировать",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Слишком подозрительно.</b> Возврат долга или расчёт за обед между знакомыми через СБП — легальная операция."
                ),
            },
        ],
    },
    {
        "id": 3,
        "image_path": "images/questions/q3.png",
        "text": (
            "📱 <b>Сообщение от «куратора обменника»:</b>\n\n"
            "<i>👤 «Слушай, у меня лимиты кончились. Прими перевод от незнакомца на свою карту (50 000 руб), а мне перекинь дальше. Себе оставь 3к за помощь!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Помочь — это же просто перевод",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ошибка.</b> Принимать переводы от незнакомцев и переправлять их дальше за процент — это транзит похищенных денег.\n\n"
                    "⚖️ <b>Последствия:</b> соучастие в мошенничестве (ст. 159 УК РФ)."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказать — транзит чужих средств (соучастие)",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Отлично.</b> Вы не дали использовать свою карту как транзитный шлюз."
                ),
            },
        ],
    },
    {
        "id": 4,
        "image_path": "images/questions/q4.png",
        "text": (
            "📱 <b>Уведомление от интернет-магазина:</b>\n\n"
            "<i>📦 «Возврат средств за отменённый заказ №4820 оформлен на карту, с которой производилась оплата. Поступление — до 3 рабочих дней.»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Всё в порядке — ожидать возврат",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Официальный возврат денег за отменённый заказ обратно на вашу карту — стандартная процедура."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Заявить о мошенничестве в банк",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ошибка.</b> Это легальный возврат ваших же средств за некупленный товар."
                ),
            },
        ],
    },
    {
        "id": 5,
        "image_path": "images/questions/q5.png",
        "text": (
            "📱 <b>Сообщение от вербовщика:</b>\n\n"
            "<i>👤 «Оформи карту по моей ссылке. Если в банке будут вопросы — говори, что для родственника или что потерял карту. Решай прямо сейчас!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Сделать, как сказал куратор",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ловушка.</b> Указание врать сотрудникам банка и искусственная спешка — признаки преступной схемы.\n\n"
                    "⚖️ <b>Последствия:</b> уголовная ответственность по ст. 187 УК РФ."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Прекратить общение — манипуляция и обман банка",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Правильно.</b> Просьба врать банку — стопроцентный индикатор вербовки."
                ),
            },
        ],
    },
    {
        "id": 6,
        "image_path": "images/questions/q6.png",
        "text": (
            "📱 <b>Предложение в соцсетях:</b>\n\n"
            "<i>💬 «Сдавай в аренду доступ к своему онлайн-банкингу на пару дней в месяц. Платим 10 000 руб пассивного дохода — ничего делать не нужно!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Звучит выгодно — почему бы и нет",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ошибка.</b> Передача логина и пароля от онлайн-банка — это передача контроля над вашими средствами.\n\n"
                    "⚖️ <b>Последствия:</b> ст. 187 УК РФ и ответственность за все транзакции."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Заблокировать и пожаловаться — аренда онлайн-банка",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Ни один легальный бизнес не арендует чужие банковские кабинеты."
                ),
            },
        ],
    },
    {
        "id": 7,
        "image_path": "images/questions/q7.png",
        "text": (
            "📱 <b>Сообщение от мамы или папы:</b>\n\n"
            "<i>👪 «Перевела тебе 1 000 рублей на карманные. Купи продукты по списку, когда пойдёшь домой.»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Принять и выполнить просьбу",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Обычный семейный перевод без рисков и подозрительных условий."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться — перевод от другого человека",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ложная тревога.</b> Переводы от родителей на личные нужды безопасны."
                ),
            },
        ],
    },
    {
        "id": 8,
        "image_path": "images/questions/q8.png",
        "text": (
            "📱 <b>Сообщение от «скупщика симок»:</b>\n\n"
            "<i>👤 «Куплю б/у SIM-карты, оформленные на ваш паспорт, или помогу оформить новые — штук 5–10. Плачу 1 000 руб за штуку!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Оформить и продать — симки же копейки стоят",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ловушка.</b> Сим-карты на продажу используют для анонимных аккаунтов и криптокошельков."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться — продажа SIM-карт",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Отлично.</b> Оформление SIM-карт на продажу — прямой путь к соучастию в киберпреступлениях."
                ),
            },
        ],
    },
    {
        "id": 9,
        "image_path": "images/questions/q9.png",
        "text": (
            "📱 <b>Объявление о «вакансии курьера»:</b>\n\n"
            "<i>💼 «Нужно ездить по адресам, забирать наличные у пожилых людей и класть их на указанные криптокошельки через банкомат. Зарплата — 15% от суммы!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Согласиться — отличная курьерская работа",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Это тяжкое преступление.</b> Вы становитесь физическим соучастником («бегунком») мошенников, которые обманывают пенсионеров.\n\n"
                    "⚖️ <b>Последствия:</b> тюремный срок по ст. 159 УК РФ и ответственность по ст. 1102 ГК РФ."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Срочно отказаться — работа «денежным курьером»",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Сбор наличных у граждан по чужим инструкциям — прямая уголовная статья."
                ),
            },
        ],
    },
    {
        "id": 10,
        "image_path": "images/questions/q10.png",
        "text": (
            "📱 <b>Запрос от сервиса безналичных чаевых в кафе:</b>\n\n"
            "<i>☕ «Вам поступили безналичные чаевые от посетителя столика №4 — 200 рублей через сервис НетМонет.»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Легальное зачисление чаевых",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Правильно.</b> Чаевые через официальные платформы — стандартная легальная практика в общепите."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Подозрение в обналичивании",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Неверно.</b> Официальные сервисы чаевых работают прозрачно и к дроппингу отношения не имеют."
                ),
            },
        ],
    },
    {
        "id": 11,
        "image_path": "images/questions/q11.png",
        "text": (
            "📱 <b>Запрос в крипточате:</b>\n\n"
            "<i>💬 «Пройдите верификацию (KYC) на бирже по моему шаблону — с вашим паспортом и лицом. Заплачу 3 000 рублей за готовый верифицированный аккаунт!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Пройти верификацию за деньги",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ловушка.</b> Верифицированные аккаунты бирж нужны злоумышленникам для отмывания преступных доходов."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Заблокировать — продажа верификации (KYC)",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Отлично.</b> Передавать персональные данные для чужих аккаунтов крайне опасно."
                ),
            },
        ],
    },
    {
        "id": 12,
        "image_path": "images/questions/q12.png",
        "text": (
            "📱 <b>Предложение «регистрации бизнеса»:</b>\n\n"
            "<i>🏢 «Стань учредителем и гендиректором ООО за 20 000 руб. Делать ничего не нужно — мы всё оформим, от тебя только подпись!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Согласиться стать директором",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Преступление.</b> Вас вербуют в «номинальные директора» для фирмы-однодневки.\n\n"
                    "⚖️ <b>Последствия:</b> ст. 173.2 УК РФ."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться — «номинальное директорство» (ст. 173.2 УК РФ)",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Быть «номиналом» в фирмах-однодневках — уголовная ответственность."
                ),
            },
        ],
    },
    {
        "id": 13,
        "image_path": "images/questions/q13.png",
        "text": (
            "📱 <b>Сообщение от друга, с которым сбрасывались на подарок:</b>\n\n"
            "<i>🎁 «Перевёл тебе свою часть (500 руб) за подарок учителю. Чек в приложении банка.»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Принять — это совместная покупка",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Верно.</b> Сбор средств на общие покупки или подарки среди знакомых — законная бытовая ситуация."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться и потребовать объяснений",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Необоснованно.</b> Обычные переводы между друзьями за подарки не несут юридических угроз."
                ),
            },
        ],
    },
    {
        "id": 14,
        "image_path": "images/questions/q14.png",
        "text": (
            "📱 <b>Сообщение от «благодетеля»:</b>\n\n"
            "<i>👤 «У меня зависли деньги на заблокированном счёте. Давай переведу их тебе — ты обналичишь в банкомате и вернёшь мне 80%, а 20% оставь себе за хлопоты!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Обналичить и забрать процент",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Ошибка.</b> Обналичивание средств с сомнительных счетов — это отмывание преступных доходов."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Отказаться — обнал сомнительных средств",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Отлично.</b> Вы не дали втянуть себя в цепочку обналичивания грязных денег."
                ),
            },
        ],
    },
    {
        "id": 15,
        "image_path": "images/questions/q15.png",
        "text": (
            "📱 <b>Финальный тест. Сообщение от незнакомца в сети:</b>\n\n"
            "<i>🚨 «Срочно дай данные своей банковской карты (номер, срок, CVC) и код из СМС — мне нужно перевести деньги за билет, а моя карта не работает!»</i>"
        ),
        "options": [
            {
                "id": "opt1",
                "text": "🟢 Скинуть данные карты и СМС-код",
                "is_correct": False,
                "feedback": (
                    "❌ <b>Фатальная ошибка.</b> Ни при каких обстоятельствах нельзя передавать CVC-коды и коды из СМС."
                ),
            },
            {
                "id": "opt2",
                "text": "🔴 Категорически отказать — передача реквизитов и СМС",
                "is_correct": True,
                "feedback": (
                    "✅ <b>Идеально.</b> Вы усвоили главное правило: CVC и СМС-коды — табу для всех."
                ),
            },
        ],
    },
]
SCENARIO_INDEX_BY_ID = {scenario["id"]: index for index, scenario in enumerate(SCENARIOS)}
if not TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Создайте переменную окружения BOT_TOKEN с токеном из @BotFather."
    )
bot = Bot(token=TOKEN)
dp = Dispatcher()
def build_main_menu_text(session: dict) -> str:
    """Формирует текст главного меню на основе уже загруженного прогресса."""
    base_text = (
        "🛡️ <b>Дроп-Сигнал</b>\n\n"
        "Бот, который учит распознавать вербовку дропперов — финансовых посредников мошенников. "
        "Здесь вы разберёте 15 ситуаций: где опасная схема, а где обычный перевод от друга.\n\n"
        "Защитите свою карту и узнайте, что грозит за участие: ст. 187 УК РФ, 161-ФЗ, ст. 1102 ГК РФ.\n\n"
        "👨‍💻 Авторы: команда «Финансисты 72»\n"
    )
    if session.get("completed"):
        progress_text = f"\n📊 Прошлый результат: {session['score']} из {len(SCENARIOS)}\n"
    elif session.get("index", 0) > 0:
        progress_text = (
            f"\n📊 Прогресс: {session['score']} очков • "
            f"Кейс {session['index']} из {len(SCENARIOS)}\n"
        )
    else:
        progress_text = ""
    return base_text + progress_text + "\n👇 Выберите действие:"
def build_main_menu_keyboard(session: dict) -> InlineKeyboardMarkup:
    """Формирует клавиатуру главного меню по текущему прогрессу."""
    if session.get("completed"):
        start_button_text = "🔄 Пройти тест заново"
    elif session.get("index", 0) > 0:
        start_button_text = "▶️ Продолжить тренировку"
    else:
        start_button_text = "🚀 Начать тренировку"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=start_button_text, callback_data="start_training")],
        [InlineKeyboardButton(text="🎬 Видео о дроппинге", callback_data="videos")],
        [InlineKeyboardButton(text="📄 Памятка для родителей", callback_data="parents_memo")],
        [InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data="useful_links")],
        [InlineKeyboardButton(text="👥 О создателях", callback_data="about_creators")],
    ])
def get_scenario_keyboard(scenario):
    """Интерактивные кнопки + кнопка 'Начать сначала' прямо в тесте"""
    opts = list(scenario["options"])
    random.shuffle(opts)
    keyboard = []
    for opt in opts:
        callback_data = f"ans_{scenario['id']}_{opt['id']}"
        keyboard.append([InlineKeyboardButton(text=opt["text"], callback_data=callback_data)])
    keyboard.append([InlineKeyboardButton(text="🔄 Начать сначала", callback_data="confirm_restart")])
    keyboard.append([InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
# ==========================================
def build_developer_url() -> str:
    """Открывает чат с разработчиком с заранее заполненным сообщением."""
    encoded_text = urllib.parse.urlencode(
        {"text": DEVELOPER_MESSAGE_TEMPLATE},
        quote_via=urllib.parse.quote,
    )
    return f"{DEVELOPER_URL}?{encoded_text}"
def get_result_evaluation(score: int) -> str:
    """Возвращает оценку по числу правильных ответов."""
    if score >= 13:
        return (
            "🛡️ <b>Отлично!</b> Вы отлично распознаёте уловки мошенников. "
            "Вас практически невозможно втянуть в дроппинг."
        )
    if score >= 8:
        return (
            "⚠️ <b>Хорошо, но будьте бдительнее.</b> Вы знаете базовые правила, "
            "но иногда пропускаете хитрые схемы вербовщиков."
        )
    return (
        "🚨 <b>Вы в зоне риска!</b> Повторите правила безопасности и не соглашайтесь "
        "на предложения «лёгких денег»."
    )
def build_result_text(score: int) -> str:
    """Собирает единый текст итогового экрана."""
    return (
        "🎉 <b>Тренировка завершена!</b>\n\n"
        f"Ваш результат: <b>{score} из {len(SCENARIOS)}</b>\n\n"
        f"📊 <b>Оценка:</b>\n{get_result_evaluation(score)}\n\n"
        "🛡️ <b>Памятка безопасности:</b>\n"
        "• Не переводите чужие деньги через свою карту.\n"
        "• Никогда не передавайте CVC-коды, СМС-пароли и логин от банка.\n"
        "• Сообщите взрослым, если вам предлагают подозрительный заработок.\n\n"
        "📞 <b>Куда обращаться:</b>\n"
        "• <b>102 / 112</b> — полиция.\n"
        "• <b>мвд.рф</b> — Управление «К» МВД РФ.\n"
        "• <b>Горячая линия банка</b> — номер на обороте карты."
    )
def build_result_keyboard() -> InlineKeyboardMarkup:
    """Единая клавиатура итогового экрана."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Пройти заново", callback_data="confirm_restart")],
        [InlineKeyboardButton(text="📄 Памятка для родителей", callback_data="parents_memo")],
        [InlineKeyboardButton(text="🔗 Полезные ссылки", callback_data="useful_links")],
        [InlineKeyboardButton(text="💬 Написать разработчику", url=build_developer_url())],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_menu")],
    ])
# === ХЭНДЛЕРЫ МЕНЮ И КОМАНД ===============
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    session = await get_user_session(user_id)
    text = build_main_menu_text(session)
    kb = build_main_menu_keyboard(session)
    if os.path.isfile(resolve_project_path(MAIN_MENU_PHOTO_PATH)):
        await answer_photo_cached(
            message,
            photo_path=MAIN_MENU_PHOTO_PATH,
            caption=text,
            reply_markup=kb,
            parse_mode="HTML",
        )
    else:
        await message.answer(
            text=text,
            reply_markup=kb,
            parse_mode="HTML"
        )
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    """Выход в главное меню с сохранением прогресса."""
    await callback.answer()  # Сразу убираем индикатор ожидания у кнопки.
    session = await get_user_session(callback.from_user.id)
    text = build_main_menu_text(session)
    keyboard = build_main_menu_keyboard(session)
    if os.path.isfile(resolve_project_path(MAIN_MENU_PHOTO_PATH)):
        await answer_photo_cached(
            callback.message,
            photo_path=MAIN_MENU_PHOTO_PATH,
            caption=text,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(text=text, reply_markup=keyboard, parse_mode="HTML")
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "videos")
async def show_videos(callback: CallbackQuery):
    """Раздел с основным роликом и четырьмя короткими версиями."""
    await callback.answer()
    video_items = [
        ("🎬 Твоя карта — твоё будущее | полный ролик", VIDEO_MAIN_URL),
        ("1️⃣ Два школьника — два решения", VIDEO_SHORT_1_URL),
        ("2️⃣ Как происходит вербовка", VIDEO_SHORT_2_URL),
        ("3️⃣ Цена ошибки: долг и юридические последствия", VIDEO_SHORT_3_URL),
        ("4️⃣ Главный вывод: как не стать дроппером", VIDEO_SHORT_4_URL),
    ]
    links = []
    for title, url in video_items:
        if url.startswith(("https://", "http://")):
            safe_url = html.escape(url, quote=True)
            links.append(f'<a href="{safe_url}">{title}</a>')
        else:
            links.append(f"{title} — <i>ссылка скоро появится</i>")
    videos_text = (
        "🎥 <b>ТВОЯ КАРТА — ТВОЁ БУДУЩЕЕ</b>\n\n"
        "Как одно решение может превратить обычную банковскую карту в серьёзную проблему — и что делать, чтобы не попасть в схему мошенников.\n\n"
        "В полном ролике разбираем историю двух школьников, схему вербовки, реальные финансовые и юридические последствия и правила безопасного поведения. Ниже — полный ролик и четыре короткие версии по ключевым темам.\n\n"
        + "\n\n".join(links)
        + "\n\n🛡 <i>Не передавай карту, её данные и доступ к банковскому приложению другим людям. Твоя карта — твоё будущее.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
    ])
    await answer_with_optional_photo(
        callback.message,
        text=videos_text,
        reply_markup=keyboard,
        photo_path=SECTION_PHOTO_PATHS["videos"],
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "useful_links")
async def show_useful_links(callback: CallbackQuery):
    """Раздел полезных ссылок."""
    await callback.answer()
    links_text = (
        "🔗 <b>ПОЛЕЗНЫЕ РЕСУРСЫ И ССЫЛКИ</b>\n\n"
        "Чтобы глубже разобраться в финансовой безопасности и законодательстве РФ, используйте проверенные официальные источники:\n\n"
        "📌 <a href='https://fincult.info/grabli/'>Финкульт.инфо — Раздел «Грабли»</a>\n\n"
        "🏛️ <a href='https://cbr.ru/protection_rights/finfraud/'>Сайт Банка России (ЦБ РФ)</a>\n\n"
        "🚨 <a href='https://мвд.рф/mvd/structure1/Upravlenija/Управление_К_МВД_России'>Управление «К» МВД России</a>\n\n"
        "💡 <i>Сохраните эти ресурсы, чтобы всегда проверять подозрительные предложения подработки!</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Памятка для родителей", callback_data="parents_memo")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
    ])
    # Сначала отправляем новый экран, чтобы чат не пустел при загрузке первого фото.
    await answer_with_optional_photo(
        callback.message,
        text=links_text,
        reply_markup=keyboard,
        photo_path=SECTION_PHOTO_PATHS["useful_links"],
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "parents_memo")
async def show_parents_memo(callback: CallbackQuery):
    await callback.answer()
    memo_text = (
        "📄 <b>ПАМЯТКА ДЛЯ РОДИТЕЛЕЙ</b>\n"
        "<b>Как защитить подростка от вербовки в «дропперы»</b>\n\n"
        "🚨 <b>Кто такие дропперы?</b>\n"
        "Это подставные лица, через счета которых мошенники выводят и обналичивают похищенные деньги. Подростки часто попадаются на обещания «легких денег» в соцсетях.\n\n"
        "⚠️ <b>Главные опасности и законы:</b>\n"
        "• <b>Ст. 187 УК РФ</b> — незаконный оборот средств платежей (передача карты/доступа третьим лицам).\n"
        "• <b>Ст. 159 УК РФ</b> — соучастие в мошенничестве.\n"
        "• <b>ФЗ-161</b> — блокировка счетов и карт.\n\n"
        "🛡️ <b>На что обратить внимание родителям:</b>\n"
        "1. Появление у ребенка денег неизвестного происхождения или дорогих покупок.\n"
        "2. Оформление на свое имя нескольких банковских карт или сим-карт.\n"
        "3. Просьбы незнакомцев в сети «принять перевод и перекинуть дальше за процент».\n\n"
        "📞 <b>Экстренные контакты:</b>\n"
        "• Полиция: <b>102 / 112</b>\n"
        "• Горячая линия банка (блокировка счета)\n\n"
        "💡 <i>Материал подготовлен школьной командой «Финансисты 72» в рамках проекта «Дроп-Сигнал».</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать памятку (PDF)", callback_data="download_pdf_stub")],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
    ])
    await answer_with_optional_photo(
        callback.message,
        text=memo_text,
        reply_markup=keyboard,
        photo_path=SECTION_PHOTO_PATHS["parents_memo"],
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "download_pdf_stub")
async def download_pdf_stub(callback: CallbackQuery):
    """Отправляет PDF, если он установлен; не удаляет экран памятки."""
    pdf_path = resolve_project_path(PDF_PATH)
    if not os.path.isfile(pdf_path):
        await callback.answer(
            "PDF пока не добавлен. Когда файл появится, его можно будет скачать здесь.",
            show_alert=True,
        )
        return
    await callback.answer("Отправляю памятку PDF…")
    try:
        await answer_document_cached(
            callback.message,
            document_path=pdf_path,
            filename="p_72.pdf",
            caption="📄 Памятка для родителей — Дроп-Сигнал",
        )
    except Exception:
        logging.getLogger(__name__).exception("Не удалось отправить PDF-файл: %s", pdf_path)
        await callback.message.answer(
            "Не получилось отправить PDF. Попробуйте ещё раз чуть позже."
        )
@dp.callback_query(F.data == "about_creators")
async def show_creators(callback: CallbackQuery):
    await callback.answer()
    creators_text = (
        "👥 <b>О команде</b>\n\n"
        "Проект сделала школьная команда «Финансисты 72». "
        "Мы хотим, чтобы подростки разбирались в финансах и праве и не попадались на удочку мошенников. "
        "Бот показывает, как работает вербовка дропов, и учит отличать её от безопасных бытовых переводов.\n\n"
        "📌 В симуляторе 15 кейсов с правовым разбором."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать разработчику", url=build_developer_url())],
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")],
    ])
    await answer_with_optional_photo(
        callback.message,
        text=creators_text,
        reply_markup=keyboard,
        photo_path=SECTION_PHOTO_PATHS["about_creators"],
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "confirm_restart")
async def confirm_restart(callback: CallbackQuery):
    """Показывает подтверждение сброса прогресса."""
    await callback.answer()
    confirm_text = (
        "⚠️ <b>Сброс прогресса</b>\n\n"
        "Вы уверены, что хотите начать тренировку сначала? Весь текущий прогресс будет сброшен."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, начать сначала", callback_data="do_restart")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_restart")],
    ])
    await callback.message.answer(text=confirm_text, reply_markup=keyboard, parse_mode="HTML")
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "cancel_restart")
async def cancel_restart(callback: CallbackQuery):
    """Возвращает к результатам или текущему кейсу после отмены сброса."""
    await callback.answer()
    session = await get_user_session(callback.from_user.id)
    if session.get("completed"):
        await answer_with_optional_photo(
            callback.message,
            text=build_result_text(session["score"]),
            reply_markup=build_result_keyboard(),
            photo_path=SECTION_PHOTO_PATHS["results"],
            parse_mode="HTML",
        )
        await delete_message_safely(callback.message)
        return
    index = session.get("index", 0)
    if not isinstance(index, int) or index < 0 or index >= len(SCENARIOS):
        index = 0
        await save_user_session(callback.from_user.id, 0, 0, False)
    scenario = SCENARIOS[index]
    text = f"<b>Кейс {index + 1}/{len(SCENARIOS)}</b>\n\n{scenario['text']}"
    await answer_with_optional_photo(
        callback.message,
        text=text,
        reply_markup=get_scenario_keyboard(scenario),
        photo_path=get_scenario_photo_path(scenario),
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "do_restart")
async def do_restart(callback: CallbackQuery):
    """Сбрасывает прогресс и запускает первый кейс."""
    await callback.answer()
    user_id = callback.from_user.id
    await save_user_session(user_id, 0, 0, False)
    scenario = SCENARIOS[0]
    text = (
        f"🚀 <b>Тренировка началась сначала!</b>\n\n"
        f"<b>Кейс 1/{len(SCENARIOS)}</b>\n\n{scenario['text']}"
    )
    await answer_with_optional_photo(
        callback.message,
        text=text,
        reply_markup=get_scenario_keyboard(scenario),
        photo_path=get_scenario_photo_path(scenario),
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data == "start_training")
async def start_training(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    session = await get_user_session(user_id)
    index = session.get("index", 0)
    must_reset = bool(session.get("completed")) or not isinstance(index, int) or index < 0 or index >= len(SCENARIOS)
    if must_reset:
        session = {"index": 0, "score": 0, "completed": False}
        index = 0
        await save_user_session(user_id, 0, 0, False)
    scenario = SCENARIOS[index]
    label = "Тренировка началась!" if index == 0 else "Продолжаем тренировку!"
    text = f"🚀 <b>{label}</b>\n\n<b>Кейс {index + 1}/{len(SCENARIOS)}</b>\n\n{scenario['text']}"
    await answer_with_optional_photo(
        callback.message,
        text=text,
        reply_markup=get_scenario_keyboard(scenario),
        photo_path=get_scenario_photo_path(scenario),
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data.startswith("ans_"))
async def process_answer(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        _, scen_id_str, opt_id = callback.data.split("_", 2)
        scen_id = int(scen_id_str)
    except (ValueError, AttributeError):
        await callback.answer("Некорректный ответ. Откройте актуальный кейс.", show_alert=True)
        return
    current_index = SCENARIO_INDEX_BY_ID.get(scen_id)
    if current_index is None:
        await callback.answer("Этот кейс уже пройден или устарел.", show_alert=True)
        return
    scenario = SCENARIOS[current_index]
    selected_option = next((option for option in scenario["options"] if option["id"] == opt_id), None)
    if selected_option is None:
        await callback.answer("Ошибка: вариант ответа не найден.", show_alert=True)
        return
    # Атомарная запись защищает от повторного начисления очка при двойном нажатии.
    updated_session = await record_answer(
        user_id=user_id,
        expected_index=current_index,
        is_correct=selected_option["is_correct"],
        total=len(SCENARIOS),
    )
    if updated_session is None:
        await callback.answer("Этот ответ уже обработан. Откройте актуальный экран.", show_alert=True)
        return
    # Подтверждаем нажатие до отправки сообщения или фотографии.
    await callback.answer()
    score = updated_session["score"]
    next_index = updated_session["index"]
    if next_index >= len(SCENARIOS):
        # Подпись результата специально компактная, поэтому фото и текст идут вместе.
        await answer_with_optional_photo(
            callback.message,
            text=build_result_text(score),
            reply_markup=build_result_keyboard(),
            photo_path=SECTION_PHOTO_PATHS["results"],
            parse_mode="HTML",
        )
        await delete_message_safely(callback.message)
        return
    feedback_text = (
        f"{selected_option['feedback']}\n\n"
        f"📊 Прогресс: {score}/{next_index}"
    )
    next_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Следующий кейс", callback_data=f"next_{next_index}")],
        [InlineKeyboardButton(text="🔄 Начать сначала", callback_data="confirm_restart")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")],
    ])
    # Показываем отдельную иллюстрацию в зависимости от правильности ответа.
    # Если файл ещё не добавлен, helper автоматически отправит только текст.
    feedback_photo = SECTION_PHOTO_PATHS[
        "answer_true" if selected_option["is_correct"] else "answer_false"
    ]
    await answer_with_optional_photo(
        callback.message,
        text=feedback_text,
        reply_markup=next_keyboard,
        photo_path=feedback_photo,
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
@dp.callback_query(F.data.startswith("next_"))
async def next_scenario(callback: CallbackQuery):
    user_id = callback.from_user.id
    session = await get_user_session(user_id)
    index = session["index"]
    try:
        requested_index = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError, AttributeError):
        await callback.answer("Некорректная кнопка. Откройте меню заново.", show_alert=True)
        return
    if requested_index != index:
        await callback.answer("Эта кнопка устарела. Используйте актуальное сообщение.", show_alert=True)
        return
    if index < 0 or index >= len(SCENARIOS):
        await callback.answer("Тренировка уже завершена.")
        return
    await callback.answer()
    scenario = SCENARIOS[index]
    text = f"<b>Кейс {index + 1}/{len(SCENARIOS)}</b>\n\n{scenario['text']}"
    await answer_with_optional_photo(
        callback.message,
        text=text,
        reply_markup=get_scenario_keyboard(scenario),
        photo_path=get_scenario_photo_path(scenario),
        parse_mode="HTML",
    )
    await delete_message_safely(callback.message)
def validate_scenarios() -> None:
    """Проверяет целостность локальной базы кейсов перед запуском polling."""
    if not SCENARIOS:
        raise RuntimeError("SCENARIOS не должен быть пустым")
    seen_ids = set()
    for scenario in SCENARIOS:
        scenario_id = scenario.get("id")
        if scenario_id in seen_ids:
            raise RuntimeError(f"Повторяется ID кейса: {scenario_id}")
        seen_ids.add(scenario_id)
        if not scenario.get("text"):
            raise RuntimeError(f"У кейса {scenario_id} отсутствует текст")
        options = scenario.get("options", [])
        if len(options) < 2:
            raise RuntimeError(f"У кейса {scenario_id} должно быть не менее двух вариантов")
        option_ids = [option.get("id") for option in options]
        if len(option_ids) != len(set(option_ids)):
            raise RuntimeError(f"У кейса {scenario_id} повторяются ID вариантов ответа")
        if sum(bool(option.get("is_correct")) for option in options) != 1:
            raise RuntimeError(f"У кейса {scenario_id} должен быть ровно один правильный ответ")
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    validate_scenarios()
    await asyncio.to_thread(init_db)
    logging.getLogger(__name__).info(
        "Бот «Дроп-Сигнал» запускается; кейсов: %s; база: %s",
        len(SCENARIOS), DB_FILE,
    )
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
if __name__ == "__main__":
    asyncio.run(main())
