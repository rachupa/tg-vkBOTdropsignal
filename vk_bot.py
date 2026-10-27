"""VK-версия бота «Дроп-Сигнал».
Установка: py -m pip install vk-api python-dotenv
Запуск: py vk_bot.py
В .env задайте VK_TOKEN и VK_GROUP_ID. Не публикуйте токен.
Для встроенной анонимной поддержки укажите VK_SUPPORT_ADMIN_ID — числовой ID администратора VK.
"""
import json
import logging
import os
import random
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.upload import VkUpload
from dotenv import load_dotenv
PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")
TOKEN = os.getenv("VK_TOKEN")
GROUP_ID = os.getenv("VK_GROUP_ID")
if not TOKEN or not GROUP_ID:
    raise RuntimeError("Заполните VK_TOKEN и VK_GROUP_ID в .env (токен не публикуйте).")
GROUP_ID = int(GROUP_ID)
SUPPORT_ADMIN_ID = int(os.getenv("VK_SUPPORT_ADMIN_ID", "0") or 0)
DB_FILE = PROJECT_DIR / os.getenv("DB_FILE", "bot_data.db")
MAIN_MENU_PHOTO_PATH = "images/1_mes.png"
PDF_PATH = "documents/p_72.pdf"
# Видеораздел. Использует те же переменные .env, что и Telegram-бот.
VIDEO_MAIN_URL = os.getenv("VIDEO_MAIN_URL", "https://vkvideo.ru/video-242376028_456239017").strip()
VIDEO_SHORT_1_URL = os.getenv("VIDEO_SHORT_1_URL", "https://vkvideo.ru/clip-242376028_456239022").strip()
VIDEO_SHORT_2_URL = os.getenv("VIDEO_SHORT_2_URL", "https://vkvideo.ru/clip-242376028_456239018").strip()
VIDEO_SHORT_3_URL = os.getenv("VIDEO_SHORT_3_URL", "https://vkvideo.ru/clip-242376028_456239020").strip()
VIDEO_SHORT_4_URL = os.getenv("VIDEO_SHORT_4_URL", "https://vkvideo.ru/clip-242376028_456239019").strip()
PHOTO_CACHE_FILE = PROJECT_DIR / os.getenv("PHOTO_CACHE_FILE", "vk_photo_cache.json")
SECTION_PHOTO_PATHS = {
    "useful_links": "images/useful_links.png", "parents_memo": "images/parents_memo.png",
    "videos": "images/questions/video.png",
    "about_creators": "images/about_creators.png", "answer_true": "images/true.png",
    "answer_false": "images/false.png", "results": "images/results.png"
}
vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
upload = VkUpload(vk_session)
longpoll = VkBotLongPoll(vk_session, GROUP_ID)
SCENARIOS = [{'id': 1,
  'image_path': 'images/questions/q1.png',
  'text': '📱 <b>Сообщение в Telegram-чате подработки:</b>\n'
          '\n'
          '<i>👤 «Привет! Есть лёгкая подработка на 15 минут. Нужно забрать карту в банке и скинуть фото '
          'реквизитов. Плачу 5 000 руб. Интересно?»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Согласиться — деньги нужны срочно',
               'is_correct': False,
               'feedback': '❌ <b>Ловушка.</b> Передача карты или данных онлайн-банка третьим лицам — '
                           'классическая вербовка дропа.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> ст. 187 УК РФ, блокировка счетов по 161-ФЗ, иск по ст. '
                           '1102 ГК РФ.'},
              {'id': 'opt2',
               'text': '🔴 Заблокировать — продажа реквизитов (ст. 187 УК РФ)',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Вы заметили главный красный флаг — передачу личных банковских '
                           'реквизитов.'}]},
 {'id': 2,
  'image_path': 'images/questions/q2.png',
  'text': '📱 <b>Сообщение от одноклассника:</b>\n'
          '\n'
          '<i>👤 «Привет! Я перевёл тебе 350 рублей за вчерашнюю пиццу в кафе по номеру телефона через СБП. '
          'Проверишь?»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Принять — обычная бытовая ситуация',
               'is_correct': True,
               'feedback': '✅ <b>Правильно.</b> Это безопасный перевод между друзьями за совместную '
                           'покупку. Человек знаком лично, чужих денег в цепочке нет.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться и заблокировать',
               'is_correct': False,
               'feedback': '❌ <b>Слишком подозрительно.</b> Возврат долга или расчёт за обед между '
                           'знакомыми через СБП — легальная операция.'}]},
 {'id': 3,
  'image_path': 'images/questions/q3.png',
  'text': '📱 <b>Сообщение от «куратора обменника»:</b>\n'
          '\n'
          '<i>👤 «Слушай, у меня лимиты кончились. Прими перевод от незнакомца на свою карту (50 000 руб), '
          'а мне перекинь дальше. Себе оставь 3к за помощь!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Помочь — это же просто перевод',
               'is_correct': False,
               'feedback': '❌ <b>Ошибка.</b> Принимать переводы от незнакомцев и переправлять их дальше за '
                           'процент — это транзит похищенных денег.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> соучастие в мошенничестве (ст. 159 УК РФ).'},
              {'id': 'opt2',
               'text': '🔴 Отказать — транзит чужих средств (соучастие)',
               'is_correct': True,
               'feedback': '✅ <b>Отлично.</b> Вы не дали использовать свою карту как транзитный шлюз.'}]},
 {'id': 4,
  'image_path': 'images/questions/q4.png',
  'text': '📱 <b>Уведомление от интернет-магазина:</b>\n'
          '\n'
          '<i>📦 «Возврат средств за отменённый заказ №4820 оформлен на карту, с которой производилась '
          'оплата. Поступление — до 3 рабочих дней.»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Всё в порядке — ожидать возврат',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Официальный возврат денег за отменённый заказ обратно на вашу '
                           'карту — стандартная процедура.'},
              {'id': 'opt2',
               'text': '🔴 Заявить о мошенничестве в банк',
               'is_correct': False,
               'feedback': '❌ <b>Ошибка.</b> Это легальный возврат ваших же средств за некупленный '
                           'товар.'}]},
 {'id': 5,
  'image_path': 'images/questions/q5.png',
  'text': '📱 <b>Сообщение от вербовщика:</b>\n'
          '\n'
          '<i>👤 «Оформи карту по моей ссылке. Если в банке будут вопросы — говори, что для родственника '
          'или что потерял карту. Решай прямо сейчас!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Сделать, как сказал куратор',
               'is_correct': False,
               'feedback': '❌ <b>Ловушка.</b> Указание врать сотрудникам банка и искусственная спешка — '
                           'признаки преступной схемы.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> уголовная ответственность по ст. 187 УК РФ.'},
              {'id': 'opt2',
               'text': '🔴 Прекратить общение — манипуляция и обман банка',
               'is_correct': True,
               'feedback': '✅ <b>Правильно.</b> Просьба врать банку — стопроцентный индикатор вербовки.'}]},
 {'id': 6,
  'image_path': 'images/questions/q6.png',
  'text': '📱 <b>Предложение в соцсетях:</b>\n'
          '\n'
          '<i>💬 «Сдавай в аренду доступ к своему онлайн-банкингу на пару дней в месяц. Платим 10 000 руб '
          'пассивного дохода — ничего делать не нужно!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Звучит выгодно — почему бы и нет',
               'is_correct': False,
               'feedback': '❌ <b>Ошибка.</b> Передача логина и пароля от онлайн-банка — это передача '
                           'контроля над вашими средствами.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> ст. 187 УК РФ и ответственность за все транзакции.'},
              {'id': 'opt2',
               'text': '🔴 Заблокировать и пожаловаться — аренда онлайн-банка',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Ни один легальный бизнес не арендует чужие банковские '
                           'кабинеты.'}]},
 {'id': 7,
  'image_path': 'images/questions/q7.png',
  'text': '📱 <b>Сообщение от мамы или папы:</b>\n'
          '\n'
          '<i>👪 «Перевела тебе 1 000 рублей на карманные. Купи продукты по списку, когда пойдёшь '
          'домой.»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Принять и выполнить просьбу',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Обычный семейный перевод без рисков и подозрительных условий.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться — перевод от другого человека',
               'is_correct': False,
               'feedback': '❌ <b>Ложная тревога.</b> Переводы от родителей на личные нужды безопасны.'}]},
 {'id': 8,
  'image_path': 'images/questions/q8.png',
  'text': '📱 <b>Сообщение от «скупщика симок»:</b>\n'
          '\n'
          '<i>👤 «Куплю б/у SIM-карты, оформленные на ваш паспорт, или помогу оформить новые — штук 5–10. '
          'Плачу 1 000 руб за штуку!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Оформить и продать — симки же копейки стоят',
               'is_correct': False,
               'feedback': '❌ <b>Ловушка.</b> Сим-карты на продажу используют для анонимных аккаунтов и '
                           'криптокошельков.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться — продажа SIM-карт',
               'is_correct': True,
               'feedback': '✅ <b>Отлично.</b> Оформление SIM-карт на продажу — прямой путь к соучастию в '
                           'киберпреступлениях.'}]},
 {'id': 9,
  'image_path': 'images/questions/q9.png',
  'text': '📱 <b>Объявление о «вакансии курьера»:</b>\n'
          '\n'
          '<i>💼 «Нужно ездить по адресам, забирать наличные у пожилых людей и класть их на указанные '
          'криптокошельки через банкомат. Зарплата — 15% от суммы!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Согласиться — отличная курьерская работа',
               'is_correct': False,
               'feedback': '❌ <b>Это тяжкое преступление.</b> Вы становитесь физическим соучастником '
                           '(«бегунком») мошенников, которые обманывают пенсионеров.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> тюремный срок по ст. 159 УК РФ и ответственность по ст. '
                           '1102 ГК РФ.'},
              {'id': 'opt2',
               'text': '🔴 Срочно отказаться — работа «денежным курьером»',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Сбор наличных у граждан по чужим инструкциям — прямая '
                           'уголовная статья.'}]},
 {'id': 10,
  'image_path': 'images/questions/q10.png',
  'text': '📱 <b>Запрос от сервиса безналичных чаевых в кафе:</b>\n'
          '\n'
          '<i>☕ «Вам поступили безналичные чаевые от посетителя столика №4 — 200 рублей через сервис '
          'НетМонет.»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Легальное зачисление чаевых',
               'is_correct': True,
               'feedback': '✅ <b>Правильно.</b> Чаевые через официальные платформы — стандартная легальная '
                           'практика в общепите.'},
              {'id': 'opt2',
               'text': '🔴 Подозрение в обналичивании',
               'is_correct': False,
               'feedback': '❌ <b>Неверно.</b> Официальные сервисы чаевых работают прозрачно и к дроппингу '
                           'отношения не имеют.'}]},
 {'id': 11,
  'image_path': 'images/questions/q11.png',
  'text': '📱 <b>Запрос в крипточате:</b>\n'
          '\n'
          '<i>💬 «Пройдите верификацию (KYC) на бирже по моему шаблону — с вашим паспортом и лицом. Заплачу '
          '3 000 рублей за готовый верифицированный аккаунт!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Пройти верификацию за деньги',
               'is_correct': False,
               'feedback': '❌ <b>Ловушка.</b> Верифицированные аккаунты бирж нужны злоумышленникам для '
                           'отмывания преступных доходов.'},
              {'id': 'opt2',
               'text': '🔴 Заблокировать — продажа верификации (KYC)',
               'is_correct': True,
               'feedback': '✅ <b>Отлично.</b> Передавать персональные данные для чужих аккаунтов крайне '
                           'опасно.'}]},
 {'id': 12,
  'image_path': 'images/questions/q12.png',
  'text': '📱 <b>Предложение «регистрации бизнеса»:</b>\n'
          '\n'
          '<i>🏢 «Стань учредителем и гендиректором ООО за 20 000 руб. Делать ничего не нужно — мы всё '
          'оформим, от тебя только подпись!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Согласиться стать директором',
               'is_correct': False,
               'feedback': '❌ <b>Преступление.</b> Вас вербуют в «номинальные директора» для '
                           'фирмы-однодневки.\n'
                           '\n'
                           '⚖️ <b>Последствия:</b> ст. 173.2 УК РФ.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться — «номинальное директорство» (ст. 173.2 УК РФ)',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Быть «номиналом» в фирмах-однодневках — уголовная '
                           'ответственность.'}]},
 {'id': 13,
  'image_path': 'images/questions/q13.png',
  'text': '📱 <b>Сообщение от друга, с которым сбрасывались на подарок:</b>\n'
          '\n'
          '<i>🎁 «Перевёл тебе свою часть (500 руб) за подарок учителю. Чек в приложении банка.»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Принять — это совместная покупка',
               'is_correct': True,
               'feedback': '✅ <b>Верно.</b> Сбор средств на общие покупки или подарки среди знакомых — '
                           'законная бытовая ситуация.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться и потребовать объяснений',
               'is_correct': False,
               'feedback': '❌ <b>Необоснованно.</b> Обычные переводы между друзьями за подарки не несут '
                           'юридических угроз.'}]},
 {'id': 14,
  'image_path': 'images/questions/q14.png',
  'text': '📱 <b>Сообщение от «благодетеля»:</b>\n'
          '\n'
          '<i>👤 «У меня зависли деньги на заблокированном счёте. Давай переведу их тебе — ты обналичишь в '
          'банкомате и вернёшь мне 80%, а 20% оставь себе за хлопоты!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Обналичить и забрать процент',
               'is_correct': False,
               'feedback': '❌ <b>Ошибка.</b> Обналичивание средств с сомнительных счетов — это отмывание '
                           'преступных доходов.'},
              {'id': 'opt2',
               'text': '🔴 Отказаться — обнал сомнительных средств',
               'is_correct': True,
               'feedback': '✅ <b>Отлично.</b> Вы не дали втянуть себя в цепочку обналичивания грязных '
                           'денег.'}]},
 {'id': 15,
  'image_path': 'images/questions/q15.png',
  'text': '📱 <b>Финальный тест. Сообщение от незнакомца в сети:</b>\n'
          '\n'
          '<i>🚨 «Срочно дай данные своей банковской карты (номер, срок, CVC) и код из СМС — мне нужно '
          'перевести деньги за билет, а моя карта не работает!»</i>',
  'options': [{'id': 'opt1',
               'text': '🟢 Скинуть данные карты и СМС-код',
               'is_correct': False,
               'feedback': '❌ <b>Фатальная ошибка.</b> Ни при каких обстоятельствах нельзя передавать '
                           'CVC-коды и коды из СМС.'},
              {'id': 'opt2',
               'text': '🔴 Категорически отказать — передача реквизитов и СМС',
               'is_correct': True,
               'feedback': '✅ <b>Идеально.</b> Вы усвоили главное правило: CVC и СМС-коды — табу для '
                           'всех.'}]}]
@contextmanager
def db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
def init_db():
    with db_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS user_sessions (user_id INTEGER PRIMARY KEY, index_num INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS support_state (user_id INTEGER PRIMARY KEY, awaiting_message INTEGER NOT NULL DEFAULT 0)")
        conn.execute("CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, peer_id INTEGER NOT NULL, message TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
def get_session(user_id):
    """Read progress and repair out-of-range state left by interrupted/old runs."""
    with db_connection() as conn:
        row = conn.execute(
            "SELECT index_num, score, completed FROM user_sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {"index": 0, "score": 0, "completed": False}
    index = int(row["index_num"])
    score = int(row["score"])
    completed = bool(row["completed"])
    total = len(SCENARIOS)
    valid = 0 <= index <= total and 0 <= score <= index
    valid = valid and ((completed and index == total) or (not completed and index < total))
    if not valid:
        logging.warning("Повреждённый прогресс пользователя %s сброшен", user_id)
        save_session(user_id, 0, 0, False)
        return {"index": 0, "score": 0, "completed": False}
    return {"index": index, "score": score, "completed": completed}
def save_session(user_id, index, score, completed=False):
    total = len(SCENARIOS)
    if not (0 <= int(index) <= total and 0 <= int(score) <= int(index)):
        raise ValueError("Индекс или результат выходят за допустимые границы")
    if completed and int(index) != total:
        raise ValueError("Завершённая тренировка должна иметь индекс конца списка кейсов")
    with db_connection() as conn:
        conn.execute(
            """INSERT INTO user_sessions(user_id,index_num,score,completed)
               VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 index_num=excluded.index_num,
                 score=excluded.score,
                 completed=excluded.completed""",
            (int(user_id), int(index), int(score), int(bool(completed))),
        )
def record_answer(user_id, expected_index, is_correct):
    """Atomically records one answer; stale/repeated button clicks score nothing."""
    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT index_num, score, completed FROM user_sessions WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if row is None:
            current_index, current_score, completed = 0, 0, False
            conn.execute(
                "INSERT INTO user_sessions(user_id,index_num,score,completed) VALUES(?,0,0,0)",
                (user_id,),
            )
        else:
            current_index = int(row["index_num"])
            current_score = int(row["score"])
            completed = bool(row["completed"])
        total = len(SCENARIOS)
        if (
            completed
            or current_index != expected_index
            or current_index < 0
            or current_index >= total
            or current_score < 0
            or current_score > current_index
        ):
            return None
        new_index = current_index + 1
        new_score = current_score + int(bool(is_correct))
        is_completed = new_index >= total
        conn.execute(
            "UPDATE user_sessions SET index_num=?, score=?, completed=? WHERE user_id=?",
            (new_index, new_score, int(is_completed), user_id),
        )
        return {"index": new_index, "score": new_score, "completed": is_completed}
def keyboard(rows, inline=False):
    """Build a VK keyboard, keeping each supplied row on one actual row."""
    kb = VkKeyboard(one_time=False, inline=inline)
    for row_index, row in enumerate(rows):
        if row_index > 0:
            kb.add_line()
        for item in row:
            if isinstance(item, dict) and item.get("link"):
                kb.add_openlink_button(item["label"], item["link"])
                continue
            label, payload = item[0], item[1]
            color = item[2] if len(item) > 2 else VkKeyboardColor.PRIMARY
            kb.add_button(label, payload={"action": payload}, color=color)
    return kb.get_keyboard()
def main_menu_keyboard(session):
    start = "🔄 Пройти тест заново" if session["completed"] else ("▶️ Продолжить тренировку" if session["index"] else "🚀 Начать тренировку")
    return keyboard([[(start, "start_training")], [("🎬 Видео о дроппинге", "videos")], [("📄 Памятка для родителей", "parents_memo")], [("🔗 Полезные ссылки", "useful_links")], [("👥 О создателях", "about_creators")], [("🛡️ Анонимная поддержка", "support")]])
def scenario_keyboard(scenario):
    opts = list(scenario["options"]); random.shuffle(opts)
    rows = [[((o["text"][:37] + "…") if len(o["text"]) > 40 else o["text"], f"ans:{scenario['id']}:{o['id']}")] for o in opts]
    rows += [[("🔄 Начать сначала","confirm_restart")],[("🔙 В главное меню","back_to_menu")]]
    return keyboard(rows)
def result_keyboard():
    rows = [
        [("🔄 Пройти заново", "confirm_restart")],
        [("📄 Памятка для родителей", "parents_memo")],
        [("🔗 Полезные ссылки", "useful_links")],
        [("🛡️ Анонимная поддержка", "support")],
        [("🔙 Главное меню", "back_to_menu")],
    ]
    return keyboard(rows)
def clean_text(text):
    """VK messages do not render Telegram HTML; convert basic tags to readable text."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(b|strong)>", "", text, flags=re.I)
    text = re.sub(r"</?(i|em)>", "", text, flags=re.I)
    text = re.sub(r'<a\s+href=["\']([^"\']+)["\']>(.*?)</a>', r"\2 (\1)", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return text
def _load_photo_cache():
    try:
        with PHOTO_CACHE_FILE.open("r", encoding="utf-8") as cache_file:
            data = json.load(cache_file)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}
PHOTO_ATTACHMENT_CACHE = _load_photo_cache()
def _save_photo_cache():
    """Persist uploaded VK photo attachments so repeat visits do not re-upload PNGs."""
    temporary_path = PHOTO_CACHE_FILE.with_suffix(PHOTO_CACHE_FILE.suffix + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as cache_file:
            json.dump(PHOTO_ATTACHMENT_CACHE, cache_file, ensure_ascii=False, indent=2)
        temporary_path.replace(PHOTO_CACHE_FILE)
    except OSError:
        logging.warning("Не удалось сохранить кеш фотографий VK", exc_info=True)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
def _photo_attachment(path, peer_id):
    """Return the saved VK attachment ID, uploading the image for this conversation when needed."""
    try:
        stat = path.stat()
    except OSError:
        logging.warning("Файл изображения не найден: %s", path)
        return ""
    cache_key = f"{GROUP_ID}:{path.resolve()}"
    cached = PHOTO_ATTACHMENT_CACHE.get(cache_key)
    if (
        isinstance(cached, dict)
        and cached.get("size") == stat.st_size
        and cached.get("mtime_ns") == stat.st_mtime_ns
        and isinstance(cached.get("attachment"), str)
    ):
        return cached["attachment"]
    try:
        uploaded = upload.photo_messages(str(path), peer_id=int(peer_id))
        if not uploaded:
            logging.warning("VK не вернул attachment для изображения %s", path)
            return ""
        photo = uploaded[0]
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        PHOTO_ATTACHMENT_CACHE[cache_key] = {
            "attachment": attachment,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
        _save_photo_cache()
        return attachment
    except Exception as exc:
        error_text = str(exc).lower()
        if "current scopes" in error_text or "access denied" in error_text or "[15]" in error_text:
            logging.error("VK отказал в загрузке картинки %s из-за прав ключа сообщества (ошибка %s). Проверьте доступ к фотографиям.", path, exc)
        else:
            logging.exception("Не удалось загрузить фото %s", path)
        return ""
def send(peer_id, text, kb=None, photo_path="", attachment=""):
    """Send a message; a missing/unuploadable image never blocks the text itself."""
    text = clean_text(str(text or ""))
    params = {
        "peer_id": int(peer_id),
        "message": text,
        "random_id": int(time.time_ns() % 2_147_483_647),
    }
    if kb:
        params["keyboard"] = kb
    if photo_path:
        path = PROJECT_DIR / photo_path
        uploaded_attachment = _photo_attachment(path, peer_id)
        if uploaded_attachment:
            attachment = uploaded_attachment
    if attachment:
        params["attachment"] = attachment
    try:
        return vk.messages.send(**params)
    except Exception:
        if photo_path and params.get("attachment"):
            path = PROJECT_DIR / photo_path
            cache_key = f"{GROUP_ID}:{path.resolve()}"
            PHOTO_ATTACHMENT_CACHE.pop(cache_key, None)
            _save_photo_cache()
            logging.exception("VK отклонил вложение %s; повторяю отправку текста без картинки", path)
            params.pop("attachment", None)
            return vk.messages.send(**params)
        raise
def build_main_text(session):
    text = ("🛡️ <b>Дроп-Сигнал</b>\n\nБот, который учит распознавать вербовку дропперов — финансовых посредников мошенников. Здесь вы разберёте 15 ситуаций: где опасная схема, а где обычный перевод от друга.\n\nЗащитите свою карту и узнайте, что грозит за участие: ст. 187 УК РФ, 161-ФЗ, ст. 1102 ГК РФ.\n\n👨‍💻 Авторы: команда «Финансисты 72»")
    if session["completed"]: text += f"\n\n📊 Прошлый результат: {session['score']} из {len(SCENARIOS)}"
    elif session["index"]: text += f"\n\n📊 Пройдено кейсов: {session['index']} из {len(SCENARIOS)} • Баллы: {session['score']}"
    return text + "\n\n👇 Выберите действие:"
def result_text(score):
    if score >= 13:
        evaluation = (
            "🛡️ Отлично! Вы отлично распознаёте уловки мошенников. "
            "Вы хорошо понимаете, как защититься от дроппинга."
        )
    elif score >= 8:
        evaluation = (
            "⚠️ Хорошо, но будьте бдительнее. Вы знаете базовые правила, "
            "но иногда можете пропустить хитрые схемы вербовщиков."
        )
    else:
        evaluation = (
            "🚨 Вы в зоне риска! Повторите правила безопасности и не соглашайтесь "
            "на предложения «лёгких денег»."
        )
    return (
        f"🎉 <b>Тренировка завершена!</b>\n\n"
        f"Ваш результат: <b>{score} из {len(SCENARIOS)}</b>\n\n"
        f"📊 <b>Оценка:</b>\n{evaluation}\n\n"
        "🛡️ <b>Памятка безопасности:</b>\n"
        "• Не переводите чужие деньги через свою карту.\n"
        "• Никогда не передавайте CVC-коды, СМС-пароли и логин от банка.\n"
        "• Сообщите взрослым, если вам предлагают подозрительный заработок.\n\n"
        "📞 <b>Куда обращаться:</b>\n"
        "• 102 / 112 — полиция.\n"
        "• мвд.рф — Управление «К» МВД РФ.\n"
        "• Горячая линия банка — номер на обороте карты."
    )
def show_scenario(peer_id, index, prefix=""):
    if not isinstance(index, int) or index < 0 or index >= len(SCENARIOS):
        send(
            peer_id,
            "Не удалось открыть кейс. Возвращаю в главное меню.",
            keyboard([[("🔙 В главное меню", "back_to_menu")]]),
        )
        return
    scenario = SCENARIOS[index]
    text = f"{prefix}<b>Кейс {index+1}/{len(SCENARIOS)}</b>\n\n{scenario['text']}"
    send(peer_id, text, scenario_keyboard(scenario), scenario.get("image_path", ""))
def extract_action(payload):
    """Extract the button action from dict, JSON-string or nested VK payloads."""
    if isinstance(payload, str):
        try:
            decoded = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return payload.strip()
        return extract_action(decoded)
    if isinstance(payload, dict):
        for key in ("action", "command", "payload"):
            value = payload.get(key)
            if isinstance(value, dict):
                action = extract_action(value)
                if action:
                    return action
            elif isinstance(value, str) and value:
                if key == "payload":
                    action = extract_action(value)
                    if action:
                        return action
                else:
                    return value.strip()
    return ""
TEXT_ACTIONS = {
    "🚀 начать тренировку": "start_training",
    "начать тренировку": "start_training",
    "▶️ продолжить тренировку": "start_training",
    "продолжить тренировку": "start_training",
    "🔄 пройти тест заново": "start_training",
    "пройти тест заново": "start_training",
    "🔄 пройти заново": "confirm_restart",
    "🛡️ анонимная поддержка": "support",
    "анонимная поддержка": "support",
    "💬 написать разработчику": "support",
    "написать разработчику": "support",
    "❌ отменить обращение": "cancel_support",
    "отменить обращение": "cancel_support",
    "пройти заново": "confirm_restart",
    "🎬 видео о дроппинге": "videos",
    "видео о дроппинге": "videos",
    "видео": "videos",
    "📄 памятка для родителей": "parents_memo",
    "памятка для родителей": "parents_memo",
    "🔗 полезные ссылки": "useful_links",
    "полезные ссылки": "useful_links",
    "👥 о создателях": "about_creators",
    "о создателях": "about_creators",
    "🔙 в главное меню": "back_to_menu",
    "в главное меню": "back_to_menu",
    "🔙 назад в меню": "back_to_menu",
    "назад в меню": "back_to_menu",
    "🔙 главное меню": "back_to_menu",
    "главное меню": "back_to_menu",
    "📥 скачать памятку (pdf)": "download_pdf",
    "скачать памятку (pdf)": "download_pdf",
    "✅ да, начать сначала": "do_restart",
    "да, начать сначала": "do_restart",
    "❌ отмена": "cancel_restart",
    "отмена": "cancel_restart",
    "🔄 начать сначала": "confirm_restart",
    "начать сначала": "confirm_restart",
}
VALID_ACTIONS = {
    "start_training", "back_to_menu", "confirm_restart", "do_restart",
    "cancel_restart", "videos", "useful_links", "parents_memo", "download_pdf",
    "about_creators", "support", "cancel_support",
}
def resolve_text_action(message_text):
    normalized = " ".join((message_text or "").strip().lower().split())
    if normalized in ("начать", "/start", "старт", "меню", "/menu"):
        return "__main_menu__"
    return TEXT_ACTIONS.get(normalized, "")
def validate_scenarios():
    """Fail fast if the embedded 15-case quiz data is inconsistent."""
    if not SCENARIOS:
        raise RuntimeError("SCENARIOS не должен быть пустым")
    seen_scenario_ids = set()
    for scenario in SCENARIOS:
        scenario_id = scenario.get("id")
        if scenario_id in seen_scenario_ids:
            raise RuntimeError(f"Повторяется ID кейса: {scenario_id}")
        seen_scenario_ids.add(scenario_id)
        if not scenario.get("text"):
            raise RuntimeError(f"У кейса {scenario_id} отсутствует текст")
        options = scenario.get("options", [])
        if len(options) < 2:
            raise RuntimeError(f"У кейса {scenario_id} должно быть не менее двух ответов")
        option_ids = [option.get("id") for option in options]
        if len(option_ids) != len(set(option_ids)):
            raise RuntimeError(f"У кейса {scenario_id} повторяются ID вариантов")
        if sum(bool(option.get("is_correct")) for option in options) != 1:
            raise RuntimeError(f"У кейса {scenario_id} должен быть ровно один правильный ответ")
        if any(not option.get("feedback") or not option.get("text") for option in options):
            raise RuntimeError(f"У кейса {scenario_id} у каждого ответа должны быть текст и разбор")
def support_start(user_id):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO support_state(user_id, awaiting_message) VALUES(?,1) "
            "ON CONFLICT(user_id) DO UPDATE SET awaiting_message=1",
            (int(user_id),),
        )
def support_cancel(user_id):
    with db_connection() as conn:
        conn.execute(
            "INSERT INTO support_state(user_id, awaiting_message) VALUES(?,0) "
            "ON CONFLICT(user_id) DO UPDATE SET awaiting_message=0",
            (int(user_id),),
        )
def support_is_waiting(user_id):
    with db_connection() as conn:
        row = conn.execute("SELECT awaiting_message FROM support_state WHERE user_id=?", (int(user_id),)).fetchone()
    return bool(row and row["awaiting_message"])
def create_support_ticket(user_id, peer_id, message):
    with db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO support_tickets(user_id, peer_id, message) VALUES(?,?,?)",
            (int(user_id), int(peer_id), message[:4000]),
        )
        ticket_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO support_state(user_id, awaiting_message) VALUES(?,0) "
            "ON CONFLICT(user_id) DO UPDATE SET awaiting_message=0",
            (int(user_id),),
        )
    return ticket_id
def handle_admin_reply(admin_user_id, message_text):
    match = re.match(r"^!ответ\s+(\d+)\s+([\s\S]+)$", message_text.strip(), re.I)
    if not match:
        send(admin_user_id, "Формат ответа: !ответ НОМЕР текст ответа")
        return
    ticket_id, reply_text = int(match.group(1)), match.group(2).strip()
    with db_connection() as conn:
        ticket = conn.execute("SELECT peer_id, status FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
    if ticket is None:
        send(admin_user_id, f"Заявка №{ticket_id} не найдена.")
        return
    if ticket["status"] != "open":
        send(admin_user_id, f"Заявка №{ticket_id} закрыта или не была доставлена.")
        return
    try:
        send(int(ticket["peer_id"]), f"💬 Ответ поддержки по заявке №{ticket_id}\n\n{reply_text[:3500]}",
             keyboard([[ ("🛡️ Написать ещё", "support") ], [ ("🔙 В меню", "back_to_menu") ]]))
    except Exception:
        logging.exception("Не удалось доставить ответ по заявке №%s", ticket_id)
        send(admin_user_id, f"Не удалось отправить ответ по заявке №{ticket_id}. Проверьте журнал бота.")
        return
    with db_connection() as conn:
        conn.execute("UPDATE support_tickets SET status='answered' WHERE id=?", (ticket_id,))
    send(admin_user_id, f"✅ Ответ по заявке №{ticket_id} отправлен.")
def deliver_support_ticket(peer_id, user_id, message_text):
    if not SUPPORT_ADMIN_ID:
        support_cancel(user_id)
        send(peer_id, "⚠️ Анонимная поддержка пока не настроена. Попробуйте позже.", main_menu_keyboard(get_session(user_id)))
        logging.error("VK_SUPPORT_ADMIN_ID не задан: обращение не отправлено")
        return
    ticket_id = create_support_ticket(user_id, peer_id, message_text)
    # The operator gets only ticket number and message, not the sender's VK ID.
    try:
        send(SUPPORT_ADMIN_ID, f"💬 Анонимное обращение №{ticket_id}\n\n{message_text[:4000]}\n\nОтветить: !ответ {ticket_id} ваш текст")
    except Exception:
        logging.exception("Не удалось передать обращение №%s в поддержку", ticket_id)
        with db_connection() as conn:
            conn.execute("UPDATE support_tickets SET status='delivery_failed' WHERE id=?", (ticket_id,))
        send(peer_id, "⚠️ Не получилось доставить обращение. Проверьте позже или попробуйте ещё раз.", main_menu_keyboard(get_session(user_id)))
        return
    send(peer_id, f"✅ Обращение №{ticket_id} отправлено в поддержку. Ответ придёт сюда, в VK.\n\nНе отправляйте пароли, коды из СМС и данные банковской карты.", main_menu_keyboard(get_session(user_id)))
def handle(peer_id, user_id, payload, message_text):
    """Route both callback payloads and plain-text button labels."""
    message_text = str(message_text or "").strip()
    if SUPPORT_ADMIN_ID and int(user_id) == SUPPORT_ADMIN_ID and message_text.lower().startswith("!ответ"):
        handle_admin_reply(int(user_id), message_text)
        return
    if support_is_waiting(user_id) and not payload and message_text:
        if message_text.lower() in {"отмена", "cancel", "отменить обращение", "❌ отменить обращение"}:
            support_cancel(user_id)
            send(peer_id, "Отправка обращения отменена.", main_menu_keyboard(get_session(user_id)))
        else:
            deliver_support_ticket(peer_id, user_id, message_text)
        return
    action = extract_action(payload)
    known_action = (
        action in VALID_ACTIONS
        or action.startswith("ans:")
        or action.startswith("next:")
    )
    # Some VK clients/events deliver a wrapped or unfamiliar payload. In that
    # case use the visible button label before falling back to the main menu.
    if not known_action:
        action = resolve_text_action(message_text)
        if action == "__main_menu__":
            session = get_session(user_id)
            send(peer_id, build_main_text(session), main_menu_keyboard(session), MAIN_MENU_PHOTO_PATH)
            return
        if not action:
            logging.warning(
                "Неизвестное действие VK: user_id=%s payload_type=%s",
                user_id, type(payload).__name__,
            )
            send(peer_id, "Нажмите кнопку меню ниже, чтобы продолжить.", main_menu_keyboard(get_session(user_id)))
            return
    logging.debug("VK action user_id=%s action=%s", user_id, action[:80])
    if action == "start_training":
        session = get_session(user_id)
        if session["completed"]:
            session = {"index": 0, "score": 0, "completed": False}
        index = session["index"]
        if not 0 <= index < len(SCENARIOS):
            index, session = 0, {"index": 0, "score": 0, "completed": False}
        save_session(user_id, index, session["score"], False)
        prefix = "🚀 Тренировка началась!\n\n" if index == 0 else "▶️ Продолжаем тренировку!\n\n"
        show_scenario(peer_id, index, prefix)
    elif action == "back_to_menu":
        if support_is_waiting(user_id):
            support_cancel(user_id)
        session = get_session(user_id); send(peer_id, build_main_text(session), main_menu_keyboard(session), MAIN_MENU_PHOTO_PATH)
    elif action == "confirm_restart":
        send(peer_id, "⚠️ <b>Сброс прогресса</b>\n\nВы уверены, что хотите начать тренировку сначала? Весь текущий прогресс будет сброшен.", keyboard([[("✅ Да, начать сначала","do_restart",VkKeyboardColor.POSITIVE)],[("❌ Отмена","cancel_restart",VkKeyboardColor.NEGATIVE)]]))
    elif action == "do_restart":
        save_session(user_id,0,0,False); show_scenario(peer_id,0,"🚀 Тренировка началась сначала!\n\n")
    elif action == "cancel_restart":
        session=get_session(user_id)
        if session["completed"]: send(peer_id,result_text(session["score"]),result_keyboard(),SECTION_PHOTO_PATHS["results"])
        elif session["index"] < len(SCENARIOS): show_scenario(peer_id,session["index"])
        else: send(peer_id,build_main_text(session),main_menu_keyboard(session))
    elif action.startswith("ans:"):
        try: _, sid, oid = action.split(":",2); sid=int(sid)
        except ValueError: send(peer_id,"Не удалось распознать ответ."); return
        session=get_session(user_id); idx=session["index"]
        if idx < 0 or idx >= len(SCENARIOS) or SCENARIOS[idx]["id"] != sid:
            send(peer_id,"Этот кейс уже пройден или устарел.",main_menu_keyboard(session)); return
        option=next((o for o in SCENARIOS[idx]["options"] if o["id"]==oid),None)
        if option is None: send(peer_id,"Вариант ответа не найден."); return
        updated=record_answer(user_id,idx,option["is_correct"])
        if updated is None: send(peer_id,"Этот ответ уже обработан.",main_menu_keyboard(get_session(user_id))); return
        if updated["index"] >= len(SCENARIOS): send(peer_id,result_text(updated["score"]),result_keyboard(),SECTION_PHOTO_PATHS["results"]); return
        rows=[[("➡️ Следующий кейс",f"next:{updated['index']}")],[("🔄 Начать сначала","confirm_restart")],[("🔙 В главное меню","back_to_menu")]]
        photo=SECTION_PHOTO_PATHS["answer_true" if option["is_correct"] else "answer_false"]
        send(peer_id,option["feedback"]+f"\n\n📊 Прогресс: {updated['score']}/{updated['index']}",keyboard(rows),photo)
    elif action.startswith("next:"):
        try: requested=int(action.split(":",1)[1])
        except ValueError: send(peer_id,"Некорректная кнопка."); return
        session=get_session(user_id)
        if requested < 0 or requested != session["index"] or requested >= len(SCENARIOS):
            send(peer_id, "Эта кнопка устарела.", main_menu_keyboard(session))
            return
        show_scenario(peer_id,requested)
    elif action == "videos":
        video_items = [
            ("🎬 Твоя карта — твоё будущее | полный ролик", VIDEO_MAIN_URL),
            ("1️⃣ Два школьника — два решения", VIDEO_SHORT_1_URL),
            ("2️⃣ Как происходит вербовка", VIDEO_SHORT_2_URL),
            ("3️⃣ Цена ошибки: долг и юридические последствия", VIDEO_SHORT_3_URL),
            ("4️⃣ Главный вывод: как не стать дроппером", VIDEO_SHORT_4_URL),
        ]
        links=[]
        for title,url in video_items:
            links.append(f"{title}\n{url}" if url.startswith(("https://","http://")) else f"{title} — ссылка скоро появится")
        text=(
            "🎥 ТВОЯ КАРТА — ТВОЁ БУДУЩЕЕ\n\n"
            "Как одно решение может превратить обычную банковскую карту в серьёзную проблему — и что делать, чтобы не попасть в схему мошенников.\n\n"
            "В полном ролике разбираем историю двух школьников, схему вербовки, реальные финансовые и юридические последствия и правила безопасного поведения. Ниже — полный ролик и четыре короткие версии по ключевым темам.\n\n"
            + "\n\n".join(links)
            + "\n\n🛡 Не передавай карту, её данные и доступ к банковскому приложению другим людям. Твоя карта — твоё будущее."
        )
        send(
            peer_id,
            text,
            keyboard([[("🔙 Назад в меню", "back_to_menu")]]),
            SECTION_PHOTO_PATHS["videos"],
        )
    elif action == "useful_links":
        text=("🔗 <b>ПОЛЕЗНЫЕ РЕСУРСЫ И ССЫЛКИ</b>\n\nЧтобы глубже разобраться в финансовой безопасности и законодательстве РФ, используйте проверенные официальные источники:\n\n📌 <a href='https://fincult.info/grabli/'>Финкульт.инфо — раздел «Грабли»</a>\n\n🏛️ <a href='https://cbr.ru/protection_rights/finfraud/'>Сайт Банка России (ЦБ РФ)</a>\n\n🚨 <a href='https://мвд.рф/mvd/structure1/Upravlenija/Управление_К_МВД_России'>Управление «К» МВД России</a>\n\n💡 Сохраните эти ресурсы, чтобы проверять подозрительные предложения подработки!")
        send(peer_id,text,keyboard([[("📄 Памятка для родителей","parents_memo")],[("🔙 Назад в меню","back_to_menu")]]),SECTION_PHOTO_PATHS["useful_links"])
    elif action == "parents_memo":
        text=("📄 <b>ПАМЯТКА ДЛЯ РОДИТЕЛЕЙ</b>\n<b>Как защитить подростка от вербовки в «дропперы»</b>\n\n🚨 <b>Кто такие дропперы?</b>\nЭто подставные лица, через счета которых мошенники выводят и обналичивают похищенные деньги. Подростки часто попадаются на обещания «лёгких денег» в соцсетях.\n\n⚠️ <b>Главные опасности и законы:</b>\n• Ст. 187 УК РФ — незаконный оборот средств платежей (передача карты или доступа третьим лицам).\n• Ст. 159 УК РФ — мошенничество и возможное соучастие в нём.\n• ФЗ-161 — блокировка счетов и карт.\n\n🛡️ <b>На что обратить внимание родителям:</b>\n1. У ребёнка появляются деньги неизвестного происхождения или дорогие покупки.\n2. Его просят оформить несколько банковских карт или SIM-карт на своё имя.\n3. Незнакомцы предлагают «принять перевод и перекинуть дальше за процент».\n\n📞 <b>Экстренные контакты:</b>\n• Полиция: 102 / 112.\n• Горячая линия банка — для срочной блокировки карты и счёта.\n\n💡 Материал команды «Финансисты 72» в рамках проекта «Дроп-Сигнал».")
        send(peer_id,text,keyboard([[("📥 Скачать памятку (PDF)","download_pdf")],[("🔙 Назад в меню","back_to_menu")]]),SECTION_PHOTO_PATHS["parents_memo"])
    elif action == "download_pdf":
        path=PROJECT_DIR/PDF_PATH
        if not path.is_file(): send(peer_id,"PDF пока не добавлен. Проверьте файл documents/p_72.pdf."); return
        try:
            doc=upload.document_message(str(path),peer_id=peer_id,title="Памятка для родителей — Дроп-Сигнал")
            attach=f"doc{doc['doc']['owner_id']}_{doc['doc']['id']}"
            send(peer_id,"📄 Памятка для родителей — Дроп-Сигнал",attachment=attach)
        except Exception:
            logging.exception("Не удалось загрузить/отправить PDF: path=%s size=%s", path, path.stat().st_size if path.is_file() else "missing")
            send(peer_id, "Не получилось отправить PDF. Попробуйте позже или обратитесь через раздел «Анонимная поддержка».", keyboard([[ ("🔙 Назад в меню", "back_to_menu") ]]))
    elif action == "about_creators":
        text=("👥 <b>О команде</b>\n\nПроект сделала школьная команда «Финансисты 72». Мы хотим, чтобы подростки разбирались в финансах и праве и не попадались на удочку мошенников. Бот показывает, как работает вербовка дропов, и учит отличать её от безопасных бытовых переводов.\n\n📌 В симуляторе 15 кейсов с разбором ответов.\n\n💬 Есть вопрос или нашли ошибку? Напишите через раздел «Анонимная поддержка».")
        send(peer_id, text, keyboard([[ ("🛡️ Анонимная поддержка", "support") ], [ ("🔙 Назад в меню", "back_to_menu") ]]), SECTION_PHOTO_PATHS["about_creators"])
    elif action == "support":
        if not SUPPORT_ADMIN_ID:
            send(peer_id, "⚠️ Анонимная поддержка пока не настроена. Администратору нужно указать VK_SUPPORT_ADMIN_ID в .env.", main_menu_keyboard(get_session(user_id)))
            return
        support_start(user_id)
        send(peer_id, "🛡️ <b>Анонимная поддержка</b>\n\nНапишите одним сообщением, чем помочь или что исправить. Оператор получит номер обращения и текст, без вашего VK ID в тексте сообщения.\n\nНе отправляйте пароли, коды из СМС и данные банковской карты. Для отмены напишите «Отмена».", keyboard([[ ("❌ Отменить обращение", "cancel_support") ], [ ("🔙 В меню", "back_to_menu") ]]))
    elif action == "cancel_support":
        support_cancel(user_id)
        send(peer_id, "Отправка обращения отменена.", main_menu_keyboard(get_session(user_id)))
    else:
        send(peer_id,"Не понял действие. Вернитесь в главное меню.",main_menu_keyboard(get_session(user_id)))
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    validate_scenarios()
    init_db()
    logging.info("VK-бот «Дроп-Сигнал» запущен; сценариев: %s; база: %s; поддержка: %s", len(SCENARIOS), DB_FILE, "настроена" if SUPPORT_ADMIN_ID else "не настроена")
    for relative_path in [MAIN_MENU_PHOTO_PATH, *[item.get("image_path", "") for item in SCENARIOS], *SECTION_PHOTO_PATHS.values()]:
        if relative_path and not (PROJECT_DIR / relative_path).is_file():
            logging.warning("Файл ресурса не найден (бот продолжит без него): %s", relative_path)
    for event in longpoll.listen():
        try:
            if event.type == VkBotEventType.MESSAGE_NEW:
                obj = event.object.message if hasattr(event.object,"message") else event.object.get("message", event.object)
                peer_id = obj.peer_id if hasattr(obj,"peer_id") else obj.get("peer_id")
                user_id = obj.from_id if hasattr(obj,"from_id") else obj.get("from_id")
                text = obj.text if hasattr(obj,"text") else obj.get("text","")
                raw_payload = obj.payload if hasattr(obj,"payload") else obj.get("payload")
                try:
                    payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                except (json.JSONDecodeError, TypeError):
                    payload = raw_payload
                if peer_id and user_id:
                    logging.debug(
                        "VK message received: user_id=%s payload_type=%s",
                        user_id, type(payload).__name__,
                    )
                    handle(int(peer_id), int(user_id), payload, text or "")
        except Exception:
            logging.exception("Ошибка при обработке события VK")
if __name__ == "__main__":
    main()
