"""Учебный Telegram-бот студии маникюра: Python 3.10+, aiogram 3, PostgreSQL."""
import asyncio
import os
import re
import psycopg
from psycopg.rows import dict_row
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, KeyboardButton, Message,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN", "")
TIME_ZONE = ZoneInfo(os.getenv("SALON_TIMEZONE", "Asia/Yekaterinburg"))
PG_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": int(os.getenv("PGPORT", "5432")),
    "dbname": os.getenv("PGDATABASE", "nail_studio"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", ""),
}
DAYS_AHEAD = 14

router = Router()


class Registration(StatesGroup):
    phone = State()
    confirm = State()


@contextmanager
def database(write=False):
    """Подключение к PostgreSQL. Изменения фиксируются только при успехе."""
    con = psycopg.connect(**PG_CONFIG, row_factory=dict_row)
    try:
        yield con
        if write:
            con.commit()
        else:
            con.rollback()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def check_database():
    """Таблицы должны быть созданы заранее файлом schema.sql."""
    expected = ("clients", "masters", "services", "master_services", "schedules", "bookings")
    with database() as con:
        found = {row["table_name"] for row in con.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """).fetchall()}
    missing = sorted(set(expected) - found)
    if missing:
        raise RuntimeError(
            "В базе PostgreSQL отсутствуют таблицы: " + ", ".join(missing) +
            ". Сначала выполните schema.sql в базе nail_studio через pgAdmin."
        )


def query_all(sql, args=()):
    with database() as con:
        return con.execute(sql, args).fetchall()


def query_one(sql, args=()):
    with database() as con:
        return con.execute(sql, args).fetchone()


def clock_minutes(hhmm):
    """Время может прийти как строка HH:MM или как datetime.time из PostgreSQL."""
    if isinstance(hhmm, time):
        return hhmm.hour * 60 + hhmm.minute
    h, m = map(int, str(hhmm)[:5].split(":"))
    return h * 60 + m


def formatted_time(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def valid_day(day):
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return False
    today = datetime.now(TIME_ZONE).date()
    return today <= d < today + timedelta(days=DAYS_AHEAD)


def available_times(con, master_id, service_id, day):
    if not valid_day(day):
        return []
    d = date.fromisoformat(day)
    service = con.execute("""
        SELECT s.duration_min AS duration FROM services s
        JOIN master_services ms ON ms.service_id = s.id
        JOIN masters m ON m.id = ms.master_id
        WHERE ms.master_id = %s AND ms.service_id = %s
          AND s.is_active AND m.is_active
    """, (master_id, service_id)).fetchone()
    shift = con.execute("""
        SELECT starts_at AS starts, ends_at AS ends FROM schedules
        WHERE master_id = %s AND weekday = %s
    """, (master_id, d.isoweekday())).fetchone()
    if service is None or shift is None:
        return []
    busy = con.execute("""
        SELECT starts_at AS starts, ends_at AS ends FROM bookings
        WHERE master_id = %s AND visit_date = %s
          AND status IN ('booked', 'completed')
    """, (master_id, d)).fetchall()
    result = []
    duration = service["duration"]
    now = datetime.now(TIME_ZONE) + timedelta(minutes=10)
    for begin in range(clock_minutes(shift["starts"]),
                       clock_minutes(shift["ends"]) - duration + 1, 30):
        finish = begin + duration
        begins_at = datetime.combine(d, time(begin // 60, begin % 60), TIME_ZONE)
        if begins_at <= now:
            continue
        if any(begin < clock_minutes(b["ends"]) and
               finish > clock_minutes(b["starts"]) for b in busy):
            continue
        result.append(formatted_time(begin))
    return result


def get_times(master_id, service_id, day):
    with database() as con:
        return available_times(con, master_id, service_id, day)


def save_booking(user, phone, master_id, service_id, day, start):
    """Запись в PostgreSQL. Исключающее ограничение БД защищает от двойной записи."""
    try:
        with database(write=True) as con:
            if start not in available_times(con, master_id, service_id, day):
                return None
            service = con.execute("""
                SELECT duration_min AS duration, price_rub AS price
                FROM services WHERE id = %s AND is_active
            """, (service_id,)).fetchone()
            if service is None:
                return None
            end = formatted_time(clock_minutes(start) + service["duration"])
            client = con.execute("""
                INSERT INTO clients (telegram_id, full_name, phone)
                VALUES (%s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone
                RETURNING id
            """, (user.id, user.full_name, phone)).fetchone()
            booking = con.execute("""
                INSERT INTO bookings
                    (client_id, master_id, service_id, visit_date,
                     starts_at, ends_at, duration_at_booking, price_at_booking)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (client["id"], master_id, service_id,
                  date.fromisoformat(day), time.fromisoformat(start),
                  time.fromisoformat(end), service["duration"], service["price"])).fetchone()
            return booking["id"]
    except (psycopg.errors.ExclusionViolation, psycopg.errors.CheckViolation,
            psycopg.errors.ForeignKeyViolation):
        return None
    except psycopg.errors.UniqueViolation:
        # Например, телефон уже принадлежит другому Telegram-пользователю.
        return None


def normalize_phone(raw):
    """Приводим российский номер к +7XXXXXXXXXX, как требует домен phone_number."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits[0] in "78":
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return "+7" + digits


def home_buttons():
    kb = InlineKeyboardBuilder()
    kb.button(text="💅 Записаться", callback_data="new")
    kb.button(text="📋 Мои записи", callback_data="mine")
    kb.adjust(1)
    return kb.as_markup()


async def show_masters(message):
    kb = InlineKeyboardBuilder()
    for master in query_all("SELECT id, full_name AS name FROM masters WHERE is_active ORDER BY id"):
        kb.button(text=master["name"], callback_data=f"master:{master['id']}")
    kb.adjust(1)
    await message.answer("Выберите мастера:", reply_markup=kb.as_markup())


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Добро пожаловать в студию маникюра! 💅\n"
                         "Здесь можно записаться на процедуру.",
                         reply_markup=home_buttons())


@router.message(Command("cancel"))
async def stop_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено. Чтобы начать заново, нажмите /start",
                         reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "new")
async def begin(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await show_masters(callback.message)


@router.callback_query(F.data.startswith("master:"))
async def choose_master(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    try:
        master_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return
    services = query_all("""
        SELECT s.id, s.title AS name, s.price_rub AS price,
               s.duration_min AS duration FROM services s
        JOIN master_services ms ON ms.service_id = s.id
        WHERE ms.master_id = %s AND s.is_active ORDER BY s.id
    """, (master_id,))
    if not services:
        await callback.message.answer("У этого мастера нет доступных процедур.")
        return
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(text=f"{s['name']} — {s['price']} ₽ ({s['duration']} мин)",
                  callback_data=f"service:{master_id}:{s['id']}")
    kb.adjust(1)
    await callback.message.answer("Выберите процедуру:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("service:"))
async def choose_service(callback: CallbackQuery):
    await callback.answer()
    try:
        _, master, service = callback.data.split(":")
        master_id, service_id = int(master), int(service)
    except (ValueError, IndexError):
        return
    kb = InlineKeyboardBuilder()
    today = datetime.now(TIME_ZONE).date()
    available_dates = 0
    for offset in range(DAYS_AHEAD):
        d = today + timedelta(days=offset)
        if get_times(master_id, service_id, d.isoformat()):
            available_dates += 1
            kb.button(text=d.strftime("%d.%m (%a)"),
                      callback_data=f"date:{master_id}:{service_id}:{d.isoformat()}")
    kb.adjust(2)
    if available_dates == 0:
        await callback.message.answer("На ближайшие две недели свободных дат нет.")
        return
    await callback.message.answer("Выберите день (время студии):",
                                  reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("date:"))
async def choose_day(callback: CallbackQuery):
    await callback.answer()
    try:
        _, master, service, day = callback.data.split(":")
        master_id, service_id = int(master), int(service)
    except (ValueError, IndexError):
        return
    times = get_times(master_id, service_id, day)
    if not times:
        await callback.message.answer("На эту дату свободного времени больше нет."
                                      " Выберите другую дату через /start")
        return
    kb = InlineKeyboardBuilder()
    for t in times:
        kb.button(text=t, callback_data=f"slot:{master_id}:{service_id}:{day}:{t}")
    kb.adjust(3)
    await callback.message.answer(f"Свободное время на {day}:",
                                  reply_markup=kb.as_markup())


async def show_confirmation(message, state: FSMContext):
    data = await state.get_data()
    master = query_one("SELECT full_name AS name FROM masters WHERE id=%s", (data["master_id"],))
    service = query_one("""SELECT title AS name, price_rub AS price,
               duration_min AS duration FROM services WHERE id=%s""",
                        (data["service_id"],))
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Подтвердить запись", callback_data="confirm")
    kb.button(text="❌ Начать заново", callback_data="new")
    kb.adjust(1)
    await message.answer(
        f"Проверьте запись:\n\n"
        f"Мастер: {master['name']}\nПроцедура: {service['name']}\n"
        f"Дата: {data['day']}\nВремя: {data['start']}\n"
        f"Длительность: {service['duration']} мин\n"
        f"Стоимость: {service['price']} ₽\n\n"
        "Нажмите «Подтвердить запись».", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("slot:"))
async def choose_time(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        _, master, service, day, start = callback.data.split(":", 4)
        master_id, service_id = int(master), int(service)
    except (ValueError, IndexError):
        return
    if start not in get_times(master_id, service_id, day):
        await callback.message.answer("Время уже занято. Начните запись через /start")
        return
    await state.clear()
    await state.update_data(master_id=master_id, service_id=service_id,
                            day=day, start=start)
    client = query_one("SELECT phone FROM clients WHERE telegram_id=%s",
                       (callback.from_user.id,))
    if client:
        await state.update_data(phone=client["phone"])
        await state.set_state(Registration.confirm)
        await show_confirmation(callback.message, state)
    else:
        await state.set_state(Registration.phone)
        await callback.message.answer(
            "Для первой записи отправьте номер телефона (например, +79991234567) "
            "или нажмите кнопку ниже:",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📱 Отправить свой контакт",
                                          request_contact=True)]],
                resize_keyboard=True, one_time_keyboard=True))


@router.message(Registration.phone)
async def receive_phone(message: Message, state: FSMContext):
    if message.contact:
        if message.contact.user_id != message.from_user.id:
            await message.answer("Отправьте именно свой контакт.")
            return
        raw = message.contact.phone_number
    else:
        raw = message.text or ""
    phone = normalize_phone(raw)
    if not phone:
        await message.answer("Неверный номер. Введите российский номер, например +79991234567.")
        return
    await state.update_data(phone=phone)
    await state.set_state(Registration.confirm)
    await message.answer("Номер получен.", reply_markup=ReplyKeyboardRemove())
    await show_confirmation(message, state)


@router.callback_query(Registration.confirm, F.data == "confirm")
async def confirm(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    booking_id = save_booking(
        callback.from_user, data["phone"], data["master_id"],
        data["service_id"], data["day"], data["start"])
    await state.clear()
    if booking_id is None:
        await callback.message.answer(
            "К сожалению, выбранное время уже занято или прошло. "
            "Выберите другое время через /start")
    else:
        await callback.message.answer(
            f"✅ Вы записаны! Номер записи: {booking_id}\n"
            f"Дата: {data['day']}, время: {data['start']}\n\n"
            "Чтобы посмотреть или отменить запись, нажмите «Мои записи».",
            reply_markup=home_buttons())


@router.callback_query(F.data == "confirm")
async def old_confirmation(callback: CallbackQuery):
    await callback.answer("Запись устарела. Начните заново через /start", show_alert=True)


@router.callback_query(F.data == "mine")
async def my_bookings(callback: CallbackQuery):
    await callback.answer()
    rows = query_all("""
        SELECT b.id, b.visit_date, b.starts_at AS starts, b.ends_at AS ends,
               m.full_name AS master, s.title AS service, b.price_at_booking AS price
        FROM bookings b
        JOIN clients c ON c.id=b.client_id
        JOIN masters m ON m.id=b.master_id
        JOIN services s ON s.id=b.service_id
        WHERE c.telegram_id=%s AND b.status='booked'
          AND b.visit_date >= %s
        ORDER BY b.visit_date, b.starts_at LIMIT 15
    """, (callback.from_user.id, datetime.now(TIME_ZONE).date()))
    if not rows:
        await callback.message.answer("У вас пока нет предстоящих записей.",
                                      reply_markup=home_buttons())
        return
    for b in rows:
        kb = InlineKeyboardBuilder()
        kb.button(text="❌ Отменить запись", callback_data=f"cancel:{b['id']}")
        await callback.message.answer(
            f"Запись №{b['id']}\n{b['visit_date']} в "
            f"{b['starts'].strftime('%H:%M')}–{b['ends'].strftime('%H:%M')}\n"
            f"Мастер: {b['master']}\nПроцедура: {b['service']}\n"
            f"Цена: {b['price']} ₽", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_booking(callback: CallbackQuery):
    await callback.answer()
    try:
        booking_id = int(callback.data.split(":")[1])
    except (ValueError, IndexError):
        return
    now = datetime.now(TIME_ZONE)
    with database(write=True) as con:
        updated = con.execute("""
            UPDATE bookings SET status='cancelled'
            WHERE id=%s AND status='booked'
              AND (visit_date > %s OR (visit_date = %s AND starts_at > %s))
              AND client_id IN (
                  SELECT id FROM clients WHERE telegram_id=%s
              )
        """, (booking_id, now.date(), now.date(),
              now.time().replace(microsecond=0), callback.from_user.id)).rowcount


    if updated:
        await callback.message.answer(f"Запись №{booking_id} отменена.",
                                      reply_markup=home_buttons())
    else:
        await callback.message.answer("Запись уже отменена, прошла или не найдена.")


@router.message()
async def fallback(message: Message):
    await message.answer("Нажмите /start, чтобы открыть меню записи.")


async def main():
    if not TOKEN:
        raise SystemExit("Добавьте BOT_TOKEN в файл .env (инструкция — README.md)")
    check_database()
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    print("Бот запущен. Для остановки нажмите Ctrl+C")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
