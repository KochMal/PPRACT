import asyncio
import os
import sys
import logging
import psycopg2
import re
import uuid
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QPushButton, QDialog, QFormLayout, QLineEdit, QComboBox,
    QTextEdit, QMessageBox, QLabel, QHBoxLayout, QWidget, QInputDialog, QCheckBox
)
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QIcon, QColor
from dotenv import load_dotenv
from aiogram import Bot
import hashlib

load_dotenv('BOT_TOKEN.env')

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

# Общие стили
STYLES = """
    QMainWindow, QDialog {
        background-color: #252526;
        color: #D4D4D4;
    }
    QTabWidget::pane {
        border: 1px solid #555555;
        background-color: #2D2D30;
    }
    QTabBar::tab {
        background-color: #3C3C3C;
        color: #D4D4D4;
        padding: 10px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
    }
    QTabBar::tab:selected {
        background-color: #4A90E2;
        color: #D4D4D4;
    }
    QTabBar::tab:hover {
        background-color: #357ABD;
    }
    QTableWidget {
        background-color: #2D2D30;
        color: #D4D4D4;
        border: 1px solid #555555;
        alternate-background-color: #3C3C3C;
    }
    QTableWidget::item:hover {
        background-color: #357ABD;
    }
    QHeaderView::section {
        background-color: #4A90E2;
        color: #D4D4D4;
        padding: 5px;
        border: none;
    }
    QLineEdit, QComboBox, QTextEdit {
        background-color: #3C3C3C;
        color: #D4D4D4;
        border: 1px solid #555555;
        border-radius: 5px;
        padding: 5px;
    }
    QPushButton {
        background-color: #4A90E2;
        color: #D4D4D4;
        border-radius: 5px;
        padding: 5px;
    }
    QPushButton:hover {
        background-color: #357ABD;
    }
    QLabel, QCheckBox {
        color: #D4D4D4;
    }
"""

class FeedbackSender(QThread):
    def __init__(self, user_id, message, bot_token):
        super().__init__()
        self.user_id = user_id
        self.message = message
        self.bot_token = bot_token
    
    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = Bot(token=self.bot_token)
        try:
            loop.run_until_complete(bot.send_message(self.user_id, self.message))
        except Exception as e:
            logging.error(f"Feedback sending error: {e}")
        finally:
            loop.run_until_complete(bot.session.close())
            loop.close()

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Вход в админ-панель")
        layout = QFormLayout()
        
        self.login_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        
        layout.addRow("Логин:", self.login_input)
        layout.addRow("Пароль:", self.password_input)
        
        self.login_btn = QPushButton("Войти")
        self.login_btn.clicked.connect(self.check_credentials)
        layout.addRow(self.login_btn)
        
        self.setLayout(layout)
        self.setStyleSheet(STYLES)
    
    def check_credentials(self):
        login = self.login_input.text()
        password = self.password_input.text()
        hashed_password = hashlib.sha256(password.encode()).hexdigest()
        
        if login == "admin" and hashed_password == hashlib.sha256("password123".encode()).hexdigest():
            self.accept()
        else:
            QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль")

class UserEditDialog(QDialog):
    def __init__(self, user_data=None):
        super().__init__()
        self.setWindowTitle("Редактирование пользователя")
        layout = QFormLayout()
        
        self.role_combo = QComboBox()
        self.role_combo.addItems(['client', 'admin'])
        self.registered_check = QCheckBox("Зарегистрирован")
        
        if user_data:
            self.user_id = user_data[0]
            self.full_name = QLineEdit(user_data[1])
            self.phone = QLineEdit(user_data[2])
            self.role_combo.setCurrentText(user_data[3])
            self.registered_check.setChecked(user_data[4])
        else:
            self.user_id = None
            self.full_name = QLineEdit()
            self.phone = QLineEdit()
            self.role_combo.setCurrentText('client')
            self.registered_check.setChecked(False)
        
        layout.addRow("ФИО:", self.full_name)
        layout.addRow("Телефон:", self.phone)
        layout.addRow("Роль:", self.role_combo)
        layout.addRow(self.registered_check)
        
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self.save_changes)
        layout.addRow(self.save_btn)
        
        self.setLayout(layout)
        self.setStyleSheet(STYLES)
    
    def validate_input(self):
        if not self.full_name.text().strip():
            QMessageBox.warning(self, "Ошибка", "Поле ФИО не может быть пустым")
            return False
        if not re.match(r'^\+\d{10,15}$', self.phone.text().strip()):
            QMessageBox.warning(self, "Ошибка", "Неверный формат телефона (пример: +71234567890)")
            return False
        return True

    def save_changes(self):
        if not self.validate_input():
            return

        try:
            with Database() as cursor:
                if self.user_id:
                    cursor.execute('''
                        UPDATE users 
                        SET full_name = %s, phone = %s, role = %s, registered = %s
                        WHERE telegram_id = %s
                    ''', (self.full_name.text(), self.phone.text(), self.role_combo.currentText(), 
                          self.registered_check.isChecked(), self.user_id))
                    if self.role_combo.currentText() == 'admin':
                        cursor.execute("DELETE FROM masters WHERE user_id = %s", (self.user_id,))
                else:
                    new_id = str(uuid.uuid4())
                    cursor.execute('''
                        INSERT INTO users 
                        (telegram_id, full_name, phone, role, registered) 
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (new_id, self.full_name.text(), self.phone.text(), self.role_combo.currentText(), 
                          self.registered_check.isChecked()))
                    self.user_id = new_id
            QMessageBox.information(self, "Успех", "Пользователь обновлен")
            self.accept()
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить изменения")

class RequestEditDialog(QDialog):
    def __init__(self, request_id):
        super().__init__()
        self.request_id = request_id
        self.setWindowTitle("Редактирование заявки")
        layout = QVBoxLayout()
        
        self.status_combo = QComboBox()
        self.status_combo.addItems(['pending', 'in_progress', 'completed'])
        self.master_combo = QComboBox()
        self.load_masters()
        
        layout.addWidget(QLabel("Статус:"))
        layout.addWidget(self.status_combo)
        layout.addWidget(QLabel("Мастер:"))
        layout.addWidget(self.master_combo)
        
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self.save_changes)
        layout.addWidget(self.save_btn)
        
        self.setLayout(layout)
        self.setStyleSheet(STYLES)
    
    def load_masters(self):
        try:
            with Database() as cursor:
                cursor.execute('SELECT m.user_id, u.full_name FROM masters m JOIN users u ON m.user_id = u.telegram_id')
                masters = cursor.fetchall()
            self.master_combo.addItem("Не назначен", None)
            for master in masters:
                self.master_combo.addItem(master[1], master[0])
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")

    def save_changes(self):
        try:
            with Database() as cursor:
                cursor.execute('''
                    UPDATE requests 
                    SET status = %s, master_id = %s
                    WHERE id = %s
                ''', (self.status_combo.currentText(), self.master_combo.currentData(), self.request_id))
            self.accept()
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить изменения")

class FeedbackDialog(QDialog):
    def __init__(self, report_id, bot_token: str):
        super().__init__()
        self.report_id = report_id
        self.bot_token = bot_token
        self.setWindowTitle("Отправка фидбека")
        layout = QVBoxLayout()
        
        self.feedback_edit = QTextEdit()
        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.save_feedback)
        
        layout.addWidget(QLabel("Текст фидбека:"))
        layout.addWidget(self.feedback_edit)
        layout.addWidget(self.send_btn)
        
        self.setLayout(layout)
        self.setStyleSheet(STYLES)
    
    def save_feedback(self):
        try:
            with Database() as cursor:
                cursor.execute('''
                    UPDATE reports 
                    SET admin_feedback = %s
                    WHERE id = %s
                ''', (self.feedback_edit.toPlainText(), self.report_id))
                
                cursor.execute('''
                    SELECT u.telegram_id, r.report_text 
                    FROM reports r 
                    JOIN users u ON r.user_id = u.telegram_id 
                    WHERE r.id = %s
                ''', (self.report_id,))
                user_data = cursor.fetchone()
                
                if user_data:
                    user_id, report_text = user_data
                    message = (
                        f"📢 Новый фидбек по вашему отчету:\n\n"
                        f"Ваш отчет: {report_text}\n\n"
                        f"Фидбек администратора: {self.feedback_edit.toPlainText()}"
                    )
                    thread = FeedbackSender(user_id, message, self.bot_token)
                    thread.start()
                    thread.wait()
            
            QMessageBox.information(self, "Успех", "Фидбек успешно отправлен!")
            self.accept()
        except Exception as e:
            logging.error(f"Error: {e}")
            QMessageBox.critical(self, "Ошибка", f"Произошла ошибка: {str(e)}")

class AdminPanel(QMainWindow):
    def __init__(self, bot_token: str):
        super().__init__()
        self.bot_token = bot_token
        self.setWindowTitle("Админ-панель")
        self.setGeometry(100, 100, 1280, 720)
        
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.init_ui()
        self.load_all_data()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load_all_data)
        self.timer.start(5000)
        self.setStyleSheet(STYLES)
    
    def init_ui(self):
        self.tables = {}
        self.init_tab("👥 Пользователи", ['ID', 'ФИО', 'Телефон', 'Зарегистрирован'], self.edit_user, add_btn=True)
        self.init_tab("📋 Отчеты", ['ID', 'Клиент', 'Отчет', 'Дата'], self.show_report_details)
        self.init_tab("🔧 Заявки", ['ID', 'Клиент', 'Мастер', 'Адрес', 'Статус', 'Дата создания'], self.edit_request)
        self.init_tab("📨 Фидбек", ['ID', 'Клиент', 'Отчет', 'Фидбек'], self.edit_feedback)
        self.init_tab("👨‍🔧 Мастера", ['ID', 'Мастер', 'Загруженность'], self.edit_master)
        self.init_tab("✅ Запросы мастеров", ['ID', 'Имя'], self.confirm_or_reject_master)
        
        # Вкладка статистики
        widget = QWidget()
        layout = QVBoxLayout()
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)
        widget.setLayout(layout)
        self.tabs.addTab(widget, "📊 Статистика")

    def init_tab(self, title, headers, double_click_handler, add_btn=False):
        widget = QWidget()
        layout = QVBoxLayout()
        
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.doubleClicked.connect(double_click_handler)
        
        if add_btn:
            btn_layout = QHBoxLayout()
            add_btn = QPushButton("Добавить пользователя")
            add_btn.clicked.connect(self.add_user)
            btn_layout.addWidget(add_btn)
            layout.addLayout(btn_layout)
        
        layout.addWidget(table)
        widget.setLayout(layout)
        self.tables[title] = table
        self.tabs.addTab(widget, title)

    def load_table_data(self, table, query, transform_row=None):
        try:
            with Database() as cursor:
                cursor.execute(query)
                data = cursor.fetchall()
            
            table.setRowCount(len(data))
            for row_idx, row in enumerate(data):
                row_data = transform_row(row) if transform_row else row
                for col_idx, value in enumerate(row_data):
                    item = QTableWidgetItem(str(value) if value is not None else "Не назначен")
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    table.setItem(row_idx, col_idx, item)
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")

    def load_all_data(self):
        self.load_table_data(self.tables["👥 Пользователи"], 
                             "SELECT telegram_id, full_name, phone, registered FROM users")
        self.load_table_data(self.tables["📋 Отчеты"], 
                             "SELECT r.id, u.full_name, r.report_text, r.created_at FROM reports r JOIN users u ON r.user_id = u.telegram_id")
        self.load_table_data(self.tables["🔧 Заявки"], 
                             "SELECT r.id, c.full_name, m.full_name, r.address, r.status, r.created_at FROM requests r LEFT JOIN users c ON r.client_id = c.telegram_id LEFT JOIN users m ON r.master_id = m.telegram_id")
        self.load_table_data(self.tables["📨 Фидбек"], 
                             "SELECT r.id, u.full_name, r.report_text, r.admin_feedback FROM reports r JOIN users u ON r.user_id = u.telegram_id")
        self.load_table_data(self.tables["👨‍🔧 Мастера"], 
                             "SELECT u.telegram_id, u.full_name, m.busyness FROM users u JOIN masters m ON u.telegram_id = m.user_id")
        self.load_table_data(self.tables["✅ Запросы мастеров"], 
                             "SELECT mr.user_id, u.full_name FROM master_requests mr JOIN users u ON mr.user_id = u.telegram_id")
        self.load_stats()

    def load_stats(self):
        try:
            with Database() as cursor:
                cursor.execute("SELECT COUNT(*) FROM users")
                total_users = cursor.fetchone()[0] or 0
                cursor.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'")
                pending = cursor.fetchone()[0] or 0
                cursor.execute("SELECT COALESCE(AVG(busyness), 0) FROM masters")
                avg_load = float(cursor.fetchone()[0] or 0)
            
            self.stats_label.setText(f"""
📈 Статистика:
👥 Всего пользователей: {total_users}
⏳ Ожидающих заявок: {pending}
📦 Средняя загрузка мастеров: {avg_load:.1f}
""")
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            self.stats_label.setText("Ошибка загрузки статистики")

    def add_user(self):
        dialog = UserEditDialog()
        if dialog.exec() == QDialog.Accepted:
            self.load_table_data(self.tables["👥 Пользователи"], 
                                 "SELECT telegram_id, full_name, phone, registered FROM users")

    def edit_user(self, index):
        user_id = self.tables["👥 Пользователи"].item(index.row(), 0).text()
        try:
            with Database() as cursor:
                cursor.execute('SELECT full_name, phone, role, registered FROM users WHERE telegram_id = %s', (user_id,))
                user_data = cursor.fetchone()
            
            dialog = UserEditDialog((user_id, *user_data))
            if dialog.exec() == QDialog.Accepted:
                self.load_table_data(self.tables["👥 Пользователи"], 
                                     "SELECT telegram_id, full_name, phone, registered FROM users")
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось обновить пользователя")

    def edit_request(self, index):
        request_id = self.tables["🔧 Заявки"].item(index.row(), 0).text()
        dialog = RequestEditDialog(request_id)
        if dialog.exec() == QDialog.Accepted:
            self.load_table_data(self.tables["🔧 Заявки"], 
                                 "SELECT r.id, c.full_name, m.full_name, r.address, r.status, r.created_at FROM requests r LEFT JOIN users c ON r.client_id = c.telegram_id LEFT JOIN users m ON r.master_id = m.telegram_id")
            self.load_table_data(self.tables["👨‍🔧 Мастера"], 
                                 "SELECT u.telegram_id, u.full_name, m.busyness FROM users u JOIN masters m ON u.telegram_id = m.user_id")
            QMessageBox.information(self, "Успех", "Заявка успешно обновлена!")

    def edit_feedback(self, index):
        report_id = self.tables["📨 Фидбек"].item(index.row(), 0).text()
        dialog = FeedbackDialog(report_id, self.bot_token)
        if dialog.exec() == QDialog.Accepted:
            self.load_table_data(self.tables["📨 Фидбек"], 
                                 "SELECT r.id, u.full_name, r.report_text, r.admin_feedback FROM reports r JOIN users u ON r.user_id = u.telegram_id")

    def edit_master(self, index):
        master_id = self.tables["👨‍🔧 Мастера"].item(index.row(), 0).text()
        try:
            with Database() as cursor:
                cursor.execute('SELECT busyness FROM masters WHERE user_id = %s', (master_id,))
                busyness = cursor.fetchone()[0]
                
                new_busyness, ok = QInputDialog.getInt(self, "Редактирование загруженности", "Новая загруженность:", busyness, 0, 100)
                if ok:
                    cursor.execute('UPDATE masters SET busyness = %s WHERE user_id = %s', (new_busyness, master_id))
                    self.load_table_data(self.tables["👨‍🔧 Мастера"], 
                                         "SELECT u.telegram_id, u.full_name, m.busyness FROM users u JOIN masters m ON u.telegram_id = m.user_id")
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось обновить загруженность мастера")

    def confirm_or_reject_master(self, index):
        user_id = self.tables["✅ Запросы мастеров"].item(index.row(), 0).text()
        action, ok = QInputDialog.getItem(self, "Подтверждение", "Выберите действие:", ["Подтвердить", "Отклонить"], 0, False)
        if not ok:
            return
        
        try:
            with Database() as cursor:
                cursor.execute("SELECT full_name FROM users WHERE telegram_id = %s", (user_id,))
                user_name = cursor.fetchone()[0]
                
                if action == "Подтвердить":
                    cursor.execute("INSERT INTO masters (user_id, busyness) VALUES (%s, 0) ON CONFLICT (user_id) DO NOTHING", (user_id,))
                    QMessageBox.information(self, "Успех", f"Пользователь {user_name} теперь мастер.")
                else:
                    QMessageBox.information(self, "Успех", f"Запрос пользователя {user_name} отклонен.")
                
                cursor.execute("DELETE FROM master_requests WHERE user_id = %s", (user_id,))
                self.load_table_data(self.tables["✅ Запросы мастеров"], 
                                     "SELECT mr.user_id, u.full_name FROM master_requests mr JOIN users u ON mr.user_id = u.telegram_id")
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось обработать запрос.")

    def show_report_details(self, index):
        report_id = self.tables["📋 Отчеты"].item(index.row(), 0).text()
        try:
            with Database() as cursor:
                cursor.execute('SELECT report_text, admin_feedback FROM reports WHERE id = %s', (report_id,))
                report_data = cursor.fetchone()
            
            dialog = QDialog(self)
            dialog.setWindowTitle("Детали отчета")
            layout = QVBoxLayout()
            
            text_edit = QTextEdit()
            text_edit.setPlainText(report_data[0])
            text_edit.setReadOnly(True)
            
            feedback_edit = QTextEdit()
            feedback_edit.setPlainText(report_data[1] or "Нет фидбека")
            feedback_edit.setReadOnly(True)
            
            layout.addWidget(QLabel("Текст отчета:"))
            layout.addWidget(text_edit)
            layout.addWidget(QLabel("Фидбек администратора:"))
            layout.addWidget(feedback_edit)
            
            dialog.setLayout(layout)
            dialog.setStyleSheet(STYLES)
            dialog.exec()
        except psycopg2.Error as e:
            logging.error(f"Database error: {e}")
            QMessageBox.critical(self, "Ошибка", "Не удалось загрузить детали отчета")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    bot_token = os.getenv("BOT_TOKEN")
    
    if not bot_token:
        QMessageBox.critical(None, "Ошибка", "Токен бота не найден в .env файле!")
        sys.exit(1)
    
    login_dialog = LoginDialog()
    if login_dialog.exec() != QDialog.Accepted:
        sys.exit(0)
    
    window = AdminPanel(bot_token)
    window.show()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        logging.info("Приложение прервано пользователем")
        sys.exit(0)