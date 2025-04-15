import os
import logging
import psycopg2
import re
from functools import wraps
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

load_dotenv('BOT_TOKEN.env')

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Класс для работы с базой данных
class Database:
    def __init__(self):
        self.conn = psycopg2.connect(
            dbname="cursova",
            user="postgres",
            password="2791",  # Замени на свой пароль
            host="localhost",
            port="5432"
        )

    def __enter__(self):
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cursor.close()
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    @staticmethod
    def get_user_role(user_id: int) -> str:
        with Database() as cursor:
            cursor.execute("SELECT role FROM users WHERE telegram_id = %s", (str(user_id),))
            user_role = cursor.fetchone()
            if user_role and user_role[0] == 'admin':
                return 'admin'
            cursor.execute("SELECT COUNT(*) FROM masters WHERE user_id = %s", (str(user_id),))
            return 'master' if cursor.fetchone()[0] > 0 else 'client'

    @staticmethod
    def is_registered(user_id: int) -> bool:
        with Database() as cursor:
            cursor.execute("SELECT registered FROM users WHERE telegram_id = %s", (str(user_id),))
            result = cursor.fetchone()
            return bool(result[0]) if result else False

    @staticmethod
    def get_admin_id() -> int:
        with Database() as cursor:
            cursor.execute("SELECT telegram_id FROM users WHERE role = 'admin' LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else None

# Инициализация бота
router = Router()
bot = Bot(
    token=os.getenv("BOT_TOKEN"),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher(storage=MemoryStorage())
dp.include_router(router)

# Определение состояний для FSM
class Registration(StatesGroup):
    full_name = State()
    phone = State()

class Report(StatesGroup):
    text = State()

class RequestMaster(StatesGroup):
    address = State()

class MessageClient(StatesGroup):
    text = State()

# Декоратор для проверки ролей
def role_required(*allowed_roles):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(message: types.Message, *args, **kwargs):
            user_id = message.from_user.id
            user_role = Database.get_user_role(user_id)
            if user_role not in allowed_roles:
                await message.answer(f"⚠️ Эта команда доступна только {' или '.join(allowed_roles)}ам!")
                return
            return await handler(message, *args, **kwargs)
        return wrapper
    return decorator

# Меню для ролей
ROLE_MENUS = {
    'client': [
        ["📝 Отправить отчёт", "🔧 Вызвать мастера"],
        ["📨 Посмотреть фидбек"]
    ],
    'master': [
        ["📋 Мои заявки", "📍 Текущий адрес"],
        ["✉️ Сообщить клиенту", "🔄 Изменить статус заявки"]
    ],
    'admin': [
        ["👥 Пользователи", "📊 Статистика"],
        ["🔔 Новые заявки", "✅ Подтвердить мастера"]
    ]
}

async def show_main_menu(user_id: int):
    role = Database.get_user_role(user_id)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=text) for text in row] for row in ROLE_MENUS[role]],
        resize_keyboard=True
    )
    await bot.send_message(user_id, "Выберите действие:", reply_markup=keyboard)

# Команда /start
@router.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not Database.is_registered(user_id):
        await state.set_state(Registration.full_name)
        await message.answer("👋 Добро пожаловать! Для регистрации укажите ваше ФИО:", reply_markup=ReplyKeyboardRemove())
    else:
        await show_main_menu(user_id)

# Регистрация: получение ФИО
@router.message(Registration.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    full_name = message.text.strip()
    if not full_name or not re.match(r'^[a-zA-Zа-яА-Я\s]{3,}$', full_name):
        await message.answer("⚠️ Введите корректное ФИО (не менее 3 букв, только буквы и пробелы).")
        return
    
    await state.update_data(full_name=full_name)
    await state.set_state(Registration.phone)
    await message.answer("📱 Укажите ваш контактный телефон (например: +71234567890):")

# Регистрация: получение телефона
@router.message(Registration.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    if not re.match(r'^\+\d{10,15}$', phone):
        await message.answer("⚠️ Неверный формат телефона. Используйте международный формат (например: +71234567890).")
        return
    
    data = await state.get_data()
    user_id = message.from_user.id
    try:
        with Database() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users WHERE telegram_id = %s", (str(user_id),))
            if cursor.fetchone()[0] > 0:
                await message.answer("⚠️ Вы уже зарегистрированы!")
                await state.clear()
                await show_main_menu(user_id)
                return
            cursor.execute('''
                INSERT INTO users 
                (telegram_id, full_name, phone, role, registered) 
                VALUES (%s, %s, %s, 'client', TRUE)
            ''', (str(user_id), data['full_name'], phone))
        await state.clear()
        await show_main_menu(user_id)
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при регистрации. Попробуйте позже.")
        await state.clear()

# Команда /become_master
@router.message(F.text == "/become_master")
@role_required('client')
async def request_master_status(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        with Database() as cursor:
            cursor.execute("SELECT COUNT(*) FROM master_requests WHERE user_id = %s", (str(user_id),))
            if cursor.fetchone()[0] > 0:
                await message.answer("⚠️ Вы уже отправили запрос на статус мастера. Ожидайте подтверждения.")
                return
            cursor.execute("INSERT INTO master_requests (user_id) VALUES (%s)", (str(user_id),))
        
        admin_id = Database.get_admin_id()
        if admin_id:
            await bot.send_message(
                admin_id,
                f"Пользователь {message.from_user.full_name} (ID: {user_id}) запросил статус мастера."
            )
        await message.answer("✅ Запрос на статус мастера отправлен. Ожидайте подтверждения от администратора.")
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при отправке запроса.")

# Подтверждение мастера (админ)
@router.message(F.text == "✅ Подтвердить мастера")
@role_required('admin')
async def confirm_master_menu(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''
                SELECT mr.user_id, u.full_name 
                FROM master_requests mr 
                JOIN users u ON mr.user_id = u.telegram_id
            ''')
            requests = cursor.fetchall()
        
        if not requests:
            await message.answer("Нет запросов на статус мастера.")
            return
        
        response = ["Запросы на статус мастера:"]
        for req in requests:
            response.append(f"ID: {req[0]} | {req[1]}")
        await message.answer("\n".join(response))
        await message.answer("Введите ID пользователя для подтверждения или отклонения (например: '12345 confirm' или '12345 reject'):")
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении запросов.")

# Обработка подтверждения/отклонения мастера
@router.message(lambda message: message.text and len(message.text.split()) == 2 and message.text.split()[0].isdigit())
@role_required('admin')
async def process_master_confirmation(message: types.Message):
    try:
        user_id, action = message.text.split()
        user_id = str(user_id)
        if action not in ['confirm', 'reject']:
            await message.answer("⚠️ Используйте 'confirm' или 'reject'.")
            return
        
        with Database() as cursor:
            cursor.execute("SELECT full_name FROM users WHERE telegram_id = %s", (user_id,))
            user = cursor.fetchone()
            if not user:
                await message.answer("⚠️ Пользователь не найден.")
                return
            
            cursor.execute("SELECT COUNT(*) FROM master_requests WHERE user_id = %s", (user_id,))
            if cursor.fetchone()[0] == 0:
                await message.answer("⚠️ Запрос от этого пользователя не найден.")
                return
            
            if action == 'confirm':
                cursor.execute("INSERT INTO masters (user_id, busyness) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                await bot.send_message(user_id, "✅ Ваш запрос на статус мастера подтвержден!")
                await message.answer(f"Пользователь {user[0]} теперь мастер.")
            else:
                await bot.send_message(user_id, "❌ Ваш запрос на статус мастера отклонен.")
                await message.answer(f"Запрос пользователя {user[0]} отклонен.")
            
            cursor.execute("DELETE FROM master_requests WHERE user_id = %s", (user_id,))
        
        await show_main_menu(int(user_id))
    except (ValueError, psycopg2.Error) as e:
        logging.error(f"Error: {e}")
        await message.answer("⚠️ Ошибка. Формат: 'ID confirm' или 'ID reject'.")

# Отправка отчёта (клиент)
@router.message(F.text == "📝 Отправить отчёт")
@role_required('client')
async def start_report(message: types.Message, state: FSMContext):
    await state.set_state(Report.text)
    await message.answer("Напишите ваш отчёт о работе продукции:")

@router.message(Report.text)
async def save_report(message: types.Message, state: FSMContext):
    try:
        with Database() as cursor:
            cursor.execute("INSERT INTO reports (user_id, report_text) VALUES (%s, %s)", 
                           (str(message.from_user.id), message.text))
        await state.clear()
        await message.answer("✅ Отчёт успешно сохранён!")
        await show_main_menu(message.from_user.id)
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при сохранении отчёта")
        await state.clear()

# Просмотр фидбека (клиент)
@router.message(F.text == "📨 Посмотреть фидбек")
@role_required('client')
async def view_feedback(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''SELECT report_text, admin_feedback 
                            FROM reports 
                            WHERE user_id = %s 
                            ORDER BY created_at DESC LIMIT 5''',
                           (str(message.from_user.id),))
            reports = cursor.fetchall()
        
        if not reports:
            await message.answer("ℹ️ У вас пока нет отчетов.")
            return
        
        response = ["Ваши последние отчеты и фидбек:"]
        for report in reports:
            feedback = report[1] if report[1] else "Нет фидбека"
            response.append(f"Отчет: {report[0]}\nФидбек: {feedback}\n")
        await message.answer("\n".join(response))
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении данных")

# Вызов мастера (клиент)
@router.message(F.text == "🔧 Вызвать мастера")
@role_required('client')
async def request_master(message: types.Message, state: FSMContext):
    await state.set_state(RequestMaster.address)
    await message.answer("📌 Введите адрес, где требуется помощь мастера:")

@router.message(RequestMaster.address)
async def save_request(message: types.Message, state: FSMContext):
    try:
        with Database() as cursor:
            cursor.execute("SELECT COUNT(*) FROM requests WHERE client_id = %s AND status != 'completed'", 
                           (str(message.from_user.id),))
            if cursor.fetchone()[0] > 0:
                await message.answer("⚠️ У вас уже есть активная заявка!")
                await state.clear()
                await show_main_menu(message.from_user.id)
                return
            cursor.execute("INSERT INTO requests (client_id, address) VALUES (%s, %s)",
                           (str(message.from_user.id), message.text))
        await state.clear()
        await message.answer("✅ Заявка создана! Администратор назначит мастера в ближайшее время.")
        await show_main_menu(message.from_user.id)
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при создании заявки")
        await state.clear()

# Просмотр заявок (мастер)
@router.message(F.text == "📋 Мои заявки")
@role_required('master')
async def show_requests(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''
                SELECT r.id, r.address, r.status, u.full_name 
                FROM requests r 
                JOIN users u ON r.client_id = u.telegram_id 
                WHERE r.master_id = %s
            ''', (str(message.from_user.id),))
            requests = cursor.fetchall()
        
        if not requests:
            await message.answer("У вас нет активных заявок")
            return
        
        response = ["Ваши заявки:"]
        status_map = {'pending': '⏳ Ожидает', 'in_progress': '🚗 В процессе', 'completed': '✅ Завершена'}
        for req in requests:
            response.append(f"№{req[0]} | Адрес: {req[1]} | Статус: {status_map.get(req[2], '❓ Неизвестно')} | Клиент: {req[3]}")
        await message.answer("\n".join(response))
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении заявок")

# Просмотр текущего адреса (мастер)
@router.message(F.text == "📍 Текущий адрес")
@role_required('master')
async def show_current_address(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''SELECT address FROM requests 
                            WHERE master_id = %s AND status = 'in_progress' 
                            ORDER BY created_at DESC LIMIT 1''',
                            (str(message.from_user.id),))
            address = cursor.fetchone()
        
        if address:
            await message.answer(f"🏠 Текущий адрес: {address[0]}")
        else:
            await message.answer("У вас нет активных заявок в работе")
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении данных")

# Изменение статуса заявки (мастер)
@router.message(F.text == "🔄 Изменить статус заявки")
@role_required('master')
async def change_request_status(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''
                SELECT id, status 
                FROM requests 
                WHERE master_id = %s AND status != 'completed' 
                ORDER BY created_at DESC LIMIT 1
            ''', (str(message.from_user.id),))
            request = cursor.fetchone()
        
        if not request:
            await message.answer("⚠️ У вас нет активных заявок для изменения статуса.")
            return
        
        request_id, current_status = request
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="⏳ Ожидает"), KeyboardButton(text="🚗 В процессе")],
                [KeyboardButton(text="✅ Завершить")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )
        await message.answer(f"Текущий статус заявки №{request_id}: {current_status}. Выберите новый статус:", reply_markup=keyboard)
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении заявки")

# Обработка изменения статуса
@router.message(F.text.in_(["⏳ Ожидает", "🚗 В процессе", "✅ Завершить"]))
@role_required('master')
async def process_status_change(message: types.Message):
    status_map = {"⏳ Ожидает": "pending", "🚗 В процессе": "in_progress", "✅ Завершить": "completed"}
    new_status = status_map[message.text]
    
    try:
        with Database() as cursor:
            cursor.execute('''
                SELECT id, client_id, status 
                FROM requests 
                WHERE master_id = %s AND status != 'completed' 
                ORDER BY created_at DESC LIMIT 1
            ''', (str(message.from_user.id),))
            request = cursor.fetchone()
            
            if not request:
                await message.answer("⚠️ Нет активных заявок для изменения статуса.")
                return
            
            request_id, client_id, old_status = request
            if old_status == new_status:
                await message.answer("⚠️ Этот статус уже установлен.")
                return
            
            cursor.execute("UPDATE requests SET status = %s WHERE id = %s", (new_status, request_id))
        
        await bot.send_message(client_id, f"ℹ️ Статус вашей заявки №{request_id} изменён на: {message.text}")
        await message.answer(f"✅ Статус заявки №{request_id} изменён на: {message.text}", reply_markup=ReplyKeyboardRemove())
        await show_main_menu(message.from_user.id)
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при изменении статуса")

# Сообщение клиенту (мастер)
@router.message(F.text == "✉️ Сообщить клиенту")
@role_required('master')
async def message_client_start(message: types.Message, state: FSMContext):
    try:
        with Database() as cursor:
            cursor.execute('''
                SELECT client_id 
                FROM requests 
                WHERE master_id = %s AND status = 'in_progress' 
                ORDER BY created_at DESC LIMIT 1
            ''', (str(message.from_user.id),))
            client = cursor.fetchone()
        
        if not client:
            await message.answer("⚠️ У вас нет активных заявок для связи с клиентом.")
            return
        
        await state.update_data(client_id=client[0])
        await state.set_state(MessageClient.text)
        await message.answer("Введите сообщение для клиента:")
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении данных клиента")

@router.message(MessageClient.text)
async def send_message_to_client(message: types.Message, state: FSMContext):
    data = await state.get_data()
    client_id = data['client_id']
    try:
        await bot.send_message(client_id, f"Сообщение от мастера: {message.text}")
        await message.answer("✅ Сообщение отправлено клиенту!")
        await state.clear()
        await show_main_menu(message.from_user.id)
    except Exception as e:
        logging.error(f"Error sending message: {e}")
        await message.answer("⚠️ Ошибка при отправке сообщения")
        await state.clear()

# Статистика (админ)
@router.message(F.text == "📊 Статистика")
@role_required('admin')
async def show_stats(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'")
            pending = cursor.fetchone()[0]
            cursor.execute("SELECT AVG(busyness) FROM masters")
            avg_load = cursor.fetchone()[0] or 0
        
        await message.answer(f"""
📈 Статистика:
👥 Всего пользователей: {total_users}
⏳ Ожидающих заявок: {pending}
📦 Средняя загрузка мастеров: {avg_load:.1f}
""")
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении статистики")

# Новые заявки (админ)
@router.message(F.text == "🔔 Новые заявки")
@role_required('admin')
async def show_pending_requests(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''SELECT r.id, u.full_name, r.address 
                            FROM requests r 
                            JOIN users u ON r.client_id = u.telegram_id 
                            WHERE r.status = 'pending' ''')
            requests = cursor.fetchall()
        
        if not requests:
            await message.answer("Нет новых заявок")
            return
        
        response = ["Новые заявки:"]
        for req in requests:
            response.append(f"№{req[0]} | Клиент: {req[1]} | Адрес: {req[2]}")
        await message.answer("\n".join(response))
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении заявок")

# Список пользователей (админ)
@router.message(F.text == "👥 Пользователи")
@role_required('admin')
async def show_users(message: types.Message):
    try:
        with Database() as cursor:
            cursor.execute('''SELECT telegram_id, full_name FROM users''')
            users = cursor.fetchall()
            cursor.execute('''SELECT user_id FROM masters''')
            masters = set(row[0] for row in cursor.fetchall())

        response = ["Список пользователей:"]
        for user in users:
            role = '👨‍🔧 Мастер' if user[0] in masters else ('👑 Админ' if Database.get_user_role(int(user[0])) == 'admin' else '👤 Клиент')
            response.append(f"ID: {user[0]} | {user[1]} | {role}")
        await message.answer("\n".join(response))
    except psycopg2.Error as e:
        logging.error(f"Database error: {e}")
        await message.answer("⚠️ Ошибка при получении списка пользователей")

# Запуск бота
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    dp.run_polling(bot)