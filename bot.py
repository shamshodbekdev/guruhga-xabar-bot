#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import logging
import asyncio
import aiofiles
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import re
import random
import string

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import User, Channel, Chat
from telethon.tl.functions.messages import GetDialogsRequest
from telethon.tl.types import InputPeerEmpty
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
    ChannelInvalidError,
    ChatAdminRequiredError,
    UserNotParticipantError,
    PhoneNumberInvalidError,
    ApiIdInvalidError,
    AuthKeyUnregisteredError
)

# ==================== KONFIGURATSIYA ====================
class Config:
    """Bot konfiguratsiyasi"""
    
    # Telegram API (my.telegram.org)
    API_ID = 39537437
    API_HASH = "c86409e908d96dbea91dfb3491780679"
    
    # Bot Token (BotFather)
    BOT_TOKEN = "8588957406:AAH2qwa3Kkygpa5gbChj32YPuq3BPKI4lUE"  # O'ZGARTIRING!
    
    # Admin ID (o'z Telegram ID'ingiz)
    ADMIN_ID = 7640502387  # O'ZGARTIRING!
    
    # Majburiy obuna kanallari
    MANDATORY_CHANNELS = [
        {"id": -1001234567890, "username": "@avto_xabar_jonat", "title": "Avto Xabar Jonat"}
    ]
    
    # Cheklovlar
    MAX_PROFILES_PER_USER = 5
    MAX_GROUPS_PER_USER = 50
    MAX_MESSAGES_PER_DAY = 1000
    DEFAULT_INTERVAL = 5  # daqiqa
    
    # Fayl yo'llari
    BASE_DIR = Path(__file__).parent
    DATA_DIR = BASE_DIR / "data"
    SESSIONS_DIR = DATA_DIR / "sessions"
    PHOTOS_DIR = DATA_DIR / "photos"
    LOGS_DIR = DATA_DIR / "logs"
    DB_FILE = DATA_DIR / "bot_database.db"
    JSON_BACKUP = DATA_DIR / "backup.json"
    
    @classmethod
    def init_dirs(cls):
        """Papkalarni yaratish"""
        cls.DATA_DIR.mkdir(exist_ok=True)
        cls.SESSIONS_DIR.mkdir(exist_ok=True)
        cls.PHOTOS_DIR.mkdir(exist_ok=True)
        cls.LOGS_DIR.mkdir(exist_ok=True)

# ==================== LOGGING ====================
class Logger:
    """Log yozish"""
    
    @staticmethod
    def setup():
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(Config.LOGS_DIR / "bot.log"),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)

# ==================== DATABASE ====================
class Database:
    """SQLite database"""
    
    def __init__(self):
        self.conn = sqlite3.connect(Config.DB_FILE, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.init_db()
    
    def init_db(self):
        """Database yaratish"""
        cursor = self.conn.cursor()
        
        # Users
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active',
                subscription_checked INTEGER DEFAULT 0,
                language TEXT DEFAULT 'uz'
            )
        ''')
        
        # Profiles
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT NOT NULL,
                session_string TEXT,
                first_name TEXT,
                username TEXT,
                two_fa_password TEXT,
                last_login TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Groups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                profile_id INTEGER,
                group_id INTEGER NOT NULL,
                group_username TEXT,
                group_title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                UNIQUE(profile_id, group_id)
            )
        ''')
        
        # Messages
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_type TEXT DEFAULT 'text',
                message_text TEXT,
                media_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        ''')
        
        # Schedules
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                profile_id INTEGER,
                group_id INTEGER,
                message_id INTEGER,
                interval_minutes INTEGER DEFAULT 5,
                status TEXT DEFAULT 'paused',
                last_sent TIMESTAMP,
                next_send TIMESTAMP,
                sent_count INTEGER DEFAULT 0,
                today_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            )
        ''')
        
        # Mandatory channels
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mandatory_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER UNIQUE NOT NULL,
                channel_username TEXT,
                channel_title TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # User sessions (states)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                state TEXT,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Verification codes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT NOT NULL,
                code TEXT,
                phone_code_hash TEXT,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Statistics
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date DATE NOT NULL,
                messages_sent INTEGER DEFAULT 0,
                profiles_added INTEGER DEFAULT 0,
                groups_added INTEGER DEFAULT 0,
                UNIQUE(user_id, date)
            )
        ''')
        
        # Admin actions
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action_type TEXT,
                action_details TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def execute(self, query, params=()):
        """Query bajarish"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor
    
    def fetchone(self, query, params=()):
        """Bitta row olish"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query, params=()):
        """Barcha rowlarni olish"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
    
    def close(self):
        """Database yopish"""
        self.conn.close()

# ==================== JSON MANAGER ====================
class JSONManager:
    """JSON orqali ma'lumot saqlash"""
    
    def __init__(self):
        self.data_file = Config.JSON_BACKUP
        self.data = self.load_data()
    
    def load_data(self):
        """Ma'lumotlarni yuklash"""
        if self.data_file.exists():
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    async def save_data(self):
        """Ma'lumotlarni saqlash"""
        try:
            async with aiofiles.open(self.data_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self.data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"JSON saqlash xatolik: {e}")
    
    def backup_database(self, db):
        """Database ni JSON ga backup qilish"""
        data = {
            'users': [],
            'profiles': [],
            'groups': [],
            'messages': [],
            'schedules': [],
            'backup_time': datetime.now().isoformat()
        }
        
        # Users
        users = db.fetchall("SELECT * FROM users")
        for user in users:
            data['users'].append(dict(user))
        
        # Profiles
        profiles = db.fetchall("SELECT * FROM profiles")
        for profile in profiles:
            p = dict(profile)
            if 'session_string' in p:
                p['session_string'] = '***HIDDEN***'
            data['profiles'].append(p)
        
        # Groups
        groups = db.fetchall("SELECT * FROM groups")
        for group in groups:
            data['groups'].append(dict(group))
        
        # Messages
        messages = db.fetchall("SELECT * FROM messages")
        for message in messages:
            data['messages'].append(dict(message))
        
        # Schedules
        schedules = db.fetchall("SELECT * FROM schedules")
        for schedule in schedules:
            data['schedules'].append(dict(schedule))
        
        self.data = data
        asyncio.create_task(self.save_data())

# ==================== BOT MANAGER ====================
class TelegramAutoBot:
    """Asosiy bot klass"""
    
    def __init__(self):
        Config.init_dirs()
        self.logger = Logger.setup()
        self.db = Database()
        self.json_mgr = JSONManager()
        self.bot = None
        self.active_clients = {}
        self.user_states = {}
        self.scheduler_task = None
        self.is_running = True
        self.logger.info("🤖 Bot initialized")
    
    # ==================== START ====================
    
    async def start(self):
        """Botni ishga tushirish"""
        try:
            # Botni yaratish
            self.bot = TelegramClient('bot', Config.API_ID, Config.API_HASH)
            await self.bot.start(bot_token=Config.BOT_TOKEN)
            
            # Bot ma'lumotlari
            me = await self.bot.get_me()
            self.logger.info(f"🤖 Bot ishga tushdi: @{me.username}")
            self.logger.info(f"🆔 Bot ID: {me.id}")
            self.logger.info(f"👑 Admin ID: {Config.ADMIN_ID}")
            
            # Majburiy kanallarni qo'shish
            for channel in Config.MANDATORY_CHANNELS:
                self.db.execute('''
                    INSERT OR IGNORE INTO mandatory_channels 
                    (channel_id, channel_username, channel_title) 
                    VALUES (?, ?, ?)
                ''', (channel['id'], channel['username'], channel['title']))
            
            # Handlerlarni sozlash
            await self.setup_handlers()
            
            # Scheduler ni ishga tushirish
            self.scheduler_task = asyncio.create_task(self.scheduler_worker())
            
            # Backup qilish
            asyncio.create_task(self.periodic_backup())
            
            # Botni run qilish
            print("\n" + "="*60)
            print("✅ TELEGRAM AUTO MESSAGE BOT ISHGA TUSHDI!")
            print("="*60)
            print(f"🤖 Bot: @{me.username}")
            print(f"📁 Data: {Config.DATA_DIR}")
            print(f"📊 Database: {Config.DB_FILE}")
            print(f"📝 Log: {Config.LOGS_DIR}/bot.log")
            print("="*60)
            print("📱 Telegram da botni oching va /start bosing")
            print("="*60 + "\n")
            
            await self.bot.run_until_disconnected()
            
        except ApiIdInvalidError:
            self.logger.error("❌ API_ID yoki API_HASH noto'g'ri!")
            print("\n❌ XATOLIK: API_ID yoki API_HASH noto'g'ri!")
            print("👉 https://my.telegram.org dan to'g'ri ma'lumotlarni oling")
        except Exception as e:
            self.logger.error(f"Botni ishga tushirishda xatolik: {e}")
            print(f"\n❌ XATOLIK: {e}")
    
    # ==================== HANDLER SETUP ====================
    
    async def setup_handlers(self):
        """Handlerlarni sozlash"""
        
        # /start
        @self.bot.on(events.NewMessage(pattern='/start'))
        async def handler(event):
            await self.handle_start(event)
        
        # /help
        @self.bot.on(events.NewMessage(pattern='/help'))
        async def handler(event):
            await self.handle_help(event)
        
        # /panel (admin)
        @self.bot.on(events.NewMessage(pattern='/panel'))
        async def handler(event):
            await self.handle_panel(event)
        
        # /stats
        @self.bot.on(events.NewMessage(pattern='/stats'))
        async def handler(event):
            await self.handle_stats_command(event)
        
        # Barcha xabarlar
        @self.bot.on(events.NewMessage())
        async def handler(event):
            await self.handle_message(event)
        
        # Inline buttonlar
        @self.bot.on(events.CallbackQuery())
        async def handler(event):
            await self.handle_callback(event)
        
        # Kontakt yuborish
        @self.bot.on(events.NewMessage(func=lambda e: e.message.contact))
        async def handler(event):
            await self.handle_contact(event)
        
        # Rasm yuborish
        @self.bot.on(events.NewMessage(func=lambda e: e.message.photo))
        async def handler(event):
            await self.handle_photo(event)
        
        self.logger.info("✅ Handlerlar sozlandi")
    
    # ==================== MAIN HANDLERS ====================
    
    async def handle_start(self, event):
        """Start command"""
        user = event.sender
        chat_id = event.chat_id
        
        # Foydalanuvchini saqlash/yangilash
        self.db.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, last_active)
            VALUES (?, ?, ?, ?, datetime('now'))
        ''', (user.id, user.username, user.first_name, user.last_name or ''))
        
        # Majburiy obunani tekshirish
        if user.id != Config.ADMIN_ID:
            if not await self.check_subscription(user.id):
                await self.show_subscription_required(chat_id)
                return
        
        # Welcome message
        welcome_text = f"""🚀 *Assalomu alaykum {user.first_name}!* 

🤖 *Telegram Auto Message Bot* ga xush kelibsiz!

📌 *Bot funksiyalari:*
✅ Profil ulash (cheksiz)
✅ Guruhlarga avtomatik xabar
✅ Rasm va matn xabarlari
✅ Interval sozlash
✅ To'liq statistika
✅ Admin panel

👇 *Quyidagilardan birini tanlang:*"""
        
        await event.respond(welcome_text, buttons=self.get_main_menu(user.id), parse_mode='markdown')
    
    async def handle_help(self, event):
        """Help command"""
        help_text = """🆘 *Yordam va ko'rsatmalar*

*Asosiy buyruqlar:*
/start - Botni ishga tushirish
/help - Yordam
/stats - Statistika
/panel - Admin panel (faqat admin)

*Ishlash tartibi:*
1. 👥 Profillar - Telegram akkauntingizni ulang
2. 📋 Guruhlar - Xabar yuboradigan guruhlarni tanlang
3. 💬 Xabar - Yuboriladigan xabarni yozing
4. ⏱ Interval - Xabar yuborish oralig'ini tanlang
5. ▶️ Ishga tushirish - Boshlang

*Qo'llab-quvvatlash:* @brat_buxorodan"""
        
        await event.respond(help_text, parse_mode='markdown')
    
    async def handle_panel(self, event):
        """Panel command (admin)"""
        if event.sender.id != Config.ADMIN_ID:
            await event.respond("❌ Siz admin emassiz!")
            return
        
        text = """👑 *Admin Panel*

📊 Botni to'liq boshqarish paneli

👇 *Quyidagilardan birini tanlang:*"""
        
        buttons = [
            [Button.inline("📤 Broadcast", b"admin_broadcast")],
            [Button.inline("📊 Statistika", b"admin_stats")],
            [Button.inline("🤖 Bot holati", b"admin_bot_status")],
            [Button.inline("📎 Majburiy obunalar", b"admin_channels")],
            [Button.inline("🔙 Orqaga", b"back_main")]
        ]
        
        await event.respond(text, buttons=buttons, parse_mode='markdown')
    
    async def handle_stats_command(self, event):
        """Stats command"""
        user = event.sender
        stats = self.db.fetchone('''
            SELECT 
                COUNT(DISTINCT p.id) as profiles,
                COUNT(DISTINCT g.id) as groups,
                COALESCE(SUM(s.sent_count), 0) as total_msgs,
                COALESCE(SUM(s.today_count), 0) as today_msgs
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.user_id AND p.is_active = 1
            LEFT JOIN groups g ON g.user_id = u.user_id AND g.is_active = 1
            LEFT JOIN schedules sch ON sch.user_id = u.user_id
            WHERE u.user_id = ?
        ''', (user.id,))
        
        if not stats:
            stats = {'profiles': 0, 'groups': 0, 'total_msgs': 0, 'today_msgs': 0}
        
        text = f"""📊 *Sizning statistikangiz:*

👥 Profillar: {stats['profiles']} ta
📋 Guruhlar: {stats['groups']} ta
📤 Jami xabarlar: {stats['total_msgs']} ta
📅 Bugungi xabarlar: {stats['today_msgs']} ta

📈 *Faollik:* {stats['total_msgs'] + stats['profiles'] + stats['groups']}"""
        
        await event.respond(text, parse_mode='markdown')
    
    async def handle_message(self, event):
        """Barcha xabarlar"""
        if event.message.text and event.message.text.startswith('/'):
            return
        
        user = event.sender
        text = event.message.text or ""
        chat_id = event.chat_id
        
        # Foydalanuvchi holatini tekshirish
        state_data = self.db.fetchone('SELECT state, data FROM user_sessions WHERE user_id = ?', (user.id,))
        
        if state_data:
            state = state_data['state']
            data = json.loads(state_data['data']) if state_data['data'] else {}
            
            if state == 'waiting_phone':
                await self.process_phone_input(user.id, chat_id, text)
            elif state == 'waiting_code':
                await self.process_code_input(user.id, chat_id, text, data)
            elif state == 'waiting_password':
                await self.process_password_input(user.id, chat_id, text, data)
            elif state == 'waiting_company_name':
                await self.process_company_name(user.id, chat_id, text)
            elif state == 'waiting_message_text':
                await self.process_message_text(user.id, chat_id, text)
            elif state == 'waiting_group_input':
                await self.process_group_input(user.id, chat_id, text)
            elif state == 'waiting_interval':
                await self.process_interval_input(user.id, chat_id, text)
            elif state == 'admin_broadcast':
                await self.process_admin_broadcast(user.id, chat_id, text)
            else:
                await self.show_main_menu(chat_id, user.id)
        else:
            await self.show_main_menu(chat_id, user.id)
    
    async def handle_callback(self, event):
        """Inline buttonlar"""
        user = event.sender
        data = event.data.decode('utf-8')
        chat_id = event.chat_id
        message_id = event.message_id
        
        await event.answer()
        
        # Majburiy obuna tekshirish
        if user.id != Config.ADMIN_ID and not data.startswith('check_'):
            if not await self.check_subscription(user.id):
                await self.show_subscription_required_callback(event)
                return
        
        # Callback ni qayta ishlash
        parts = data.split('_')
        action = parts[0]
        
        try:
            if action == 'profiles':
                await self.show_profiles_menu(chat_id, user.id, message_id)
            elif action == 'addprofile':
                await self.add_profile(chat_id, user.id, message_id)
            elif action == 'selectprofile':
                if len(parts) > 1:
                    profile_id = int(parts[1])
                    await self.select_profile(chat_id, user.id, profile_id, message_id)
            elif action == 'deleteprofile':
                if len(parts) > 1:
                    profile_id = int(parts[1])
                    await self.delete_profile(chat_id, user.id, profile_id, message_id)
            elif action == 'stats':
                await self.show_stats(chat_id, user.id, message_id)
            elif action == 'message':
                await self.handle_message_menu(chat_id, user.id, message_id, parts)
            elif action == 'groups':
                await self.handle_groups_menu(chat_id, user.id, message_id, parts)
            elif action == 'start':
                await self.handle_start_stop(chat_id, user.id, message_id, parts)
            elif action == 'interval':
                await self.handle_interval_menu(chat_id, user.id, message_id, parts)
            elif action == 'admin':
                await self.handle_admin_panel(chat_id, user.id, message_id, parts)
            elif action == 'check':
                if data == 'check_subscription':
                    await self.check_subscription_handler(chat_id, user.id, message_id)
            elif action == 'back':
                await self.handle_back_button(chat_id, user.id, message_id, parts)
            elif action == 'codnot':
                await self.handle_code_not_received(chat_id, user.id, message_id)
            elif action == 'broadcast':
                await self.handle_broadcast(chat_id, user.id, message_id, parts)
            
        except Exception as e:
            self.logger.error(f"Callback error: {e}")
            await event.answer("❌ Xatolik yuz berdi", alert=True)
    
    async def handle_contact(self, event):
        """Kontakt yuborilganda"""
        user = event.sender
        contact = event.message.contact
        
        if contact.user_id == user.id:
            await self.process_phone_input(user.id, event.chat_id, contact.phone_number)
    
    async def handle_photo(self, event):
        """Rasm yuborilganda"""
        user = event.sender
        state_data = self.db.fetchone('SELECT state, data FROM user_sessions WHERE user_id = ?', (user.id,))
        
        if state_data and state_data['state'] == 'waiting_message_photo':
            # Rasmni saqlash
            photo = event.message.photo
            file = await self.bot.download_media(photo, file=Config.PHOTOS_DIR)
            
            # Xabarni saqlash
            caption = event.message.text or ""
            self.db.execute('''
                INSERT INTO messages (user_id, message_type, message_text, media_path)
                VALUES (?, 'photo', ?, ?)
            ''', (user.id, caption, str(file)))
            
            # Holatni tozalash
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user.id,))
            
            await event.respond(
                "✅ *Rasm bilan xabar saqlandi!*\n\n"
                "Endi guruhlarni tanlang va ishga tushiring.",
                buttons=[
                    [Button.inline("📋 Guruhlar", b"groups_menu")],
                    [Button.inline("▶️ Ishga tushirish", b"start_all")]
                ],
                parse_mode='markdown'
            )
    
    # ==================== PROFIL FUNCTIONS ====================
    
    async def show_profiles_menu(self, chat_id, user_id, message_id=None):
        """Profil menyusi"""
        profiles = self.db.fetchall('''
            SELECT * FROM profiles 
            WHERE user_id = ? AND is_active = 1 
            ORDER BY created_at DESC
        ''', (user_id,))
        
        text = "👥 *Profillardan birini tanlang:*\n\n"
        buttons = []
        
        if not profiles:
            text = "📱 *Sizda hali profillar mavjud emas.*\n\n" \
                   "Botdan to'liq foydalanish uchun kamida bitta profil qo'shing."
            buttons = [[Button.inline("➕ Profil qo'shish", b"addprofile")]]
        else:
            for profile in profiles:
                phone = profile['phone']
                phone_display = phone[:6] + '****' + phone[-2:]
                profile_name = profile['first_name'] or f"Profil ({phone_display})"
                
                buttons.append([
                    Button.inline(f"📱 {profile_name}", f"selectprofile_{profile['id']}".encode()),
                    Button.inline("🗑", f"deleteprofile_{profile['id']}".encode())
                ])
            
            buttons.append([Button.inline("➕ Profil qo'shish", b"addprofile")])
        
        buttons.append([Button.inline("⬅️ Orqaga", b"back_main")])
        
        if message_id:
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
        else:
            await self.bot.send_message(chat_id, text, buttons=buttons, parse_mode='markdown')
    
    async def add_profile(self, chat_id, user_id, message_id):
        """Profil qo'shish"""
        # Profillar sonini tekshirish
        profiles = self.db.fetchall('SELECT COUNT(*) as count FROM profiles WHERE user_id = ? AND is_active = 1', (user_id,))
        if profiles and profiles[0]['count'] >= Config.MAX_PROFILES_PER_USER:
            await self.bot.edit_message(
                chat_id, message_id,
                f"❌ *Profil cheklovi!*\n\n"
                f"Siz maksimal {Config.MAX_PROFILES_PER_USER} ta profil qo'sha olasiz.\n"
                f"Iltimos, avval mavjud profillaringizni o'chiring.",
                buttons=[[Button.inline("👥 Profillar", b"profiles")]]
            )
            return
        
        text = """📲 *Telegram akkauntingizni ulash uchun telefon raqamingiz kerak.*

👉 «📱 Raqamni yuborish» tugmasini bosing yoki +998... formatida yozing."""
        
        buttons = [[
            Button.request_phone("📱 Raqamni yuborish")
        ]]
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
        
        # Holatni o'rnatish
        self.db.execute('''
            INSERT OR REPLACE INTO user_sessions (user_id, state, data)
            VALUES (?, 'waiting_phone', ?)
        ''', (user_id, json.dumps({'step': 'add_profile'})))
    
    async def process_phone_input(self, user_id, chat_id, phone):
        """Telefon raqamni qabul qilish"""
        phone = self.clean_phone(phone)
        
        if not phone:
            await self.bot.send_message(
                chat_id,
                "❌ *Telefon raqam noto'g'ri formatda!*\n\n"
                "✅ To'g'ri format: +998901234567\n"
                "Yoki «📱 Raqamni yuborish» tugmasini bosing",
                buttons=[[Button.request_phone("📱 Raqamni yuborish")]]
            )
            return
        
        try:
            # Telethon client yaratish
            client = TelegramClient(StringSession(), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            # Kod yuborish
            sent = await client.send_code_request(phone)
            
            # Ma'lumotlarni saqlash
            self.db.execute('''
                INSERT INTO verification_codes 
                (user_id, phone, phone_code_hash, expires_at)
                VALUES (?, ?, ?, datetime('now', '+5 minutes'))
            ''', (user_id, phone, sent.phone_code_hash))
            
            # Holatni yangilash
            self.db.execute('''
                INSERT OR REPLACE INTO user_sessions (user_id, state, data)
                VALUES (?, 'waiting_code', ?)
            ''', (user_id, json.dumps({
                'phone': phone,
                'phone_code_hash': sent.phone_code_hash,
                'client_session': client.session.save()
            })))
            
            await client.disconnect()
            
            await self.bot.send_message(
                chat_id,
                "✅ *Kod yuborildi.*\n\n"
                "📩 Telegram'dan kelgan kodni yuboring.\n"
                "🔸 Kodni nuqta (.) bilan yozing.\n"
                "✅ Masalan: 54.568\n\n"
                "⏱ Agar kod 1 daqiqada kelmasa, pastdagi tugmani bosing:",
                buttons=[[Button.inline("❗️ Kod kelmadi", b"codnot")]]
            )
            
        except FloodWaitError as e:
            hours = e.seconds // 3600
            minutes = (e.seconds % 3600) // 60
            
            await self.bot.send_message(
                chat_id,
                f"⚠️ *Telegram cheklovi!*\n\n"
                f"Bu telefon raqam bilan {hours} soat {minutes} daqiqa kutish kerak.\n\n"
                f"*Yechim:*\n"
                f"• Boshqa telefon raqam ishlatib ko'ring\n"
                f"• Yoki {hours} soatdan keyin qaytadan urinib ko'ring",
                parse_mode='markdown'
            )
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        except Exception as e:
            self.logger.error(f"Phone input error: {e}")
            await self.bot.send_message(
                chat_id,
                f"❌ *Xatolik:* {str(e)[:100]}\n\n"
                "Iltimos, qaytadan urinib ko'ring."
            )
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    
    async def process_code_input(self, user_id, chat_id, code, state_data):
        """Kodni qabul qilish"""
        code = code.replace('.', '').strip()
        
        if not code.isdigit() or len(code) < 5:
            await self.bot.send_message(
                chat_id,
                "❌ *Kod noto'g'ri formatda!*\n\n"
                "Faqat raqamlar kiriting (masalan: 12345 yoki 12.345)"
            )
            return
        
        phone = state_data.get('phone')
        phone_code_hash = state_data.get('phone_code_hash')
        session_string = state_data.get('client_session')
        
        if not all([phone, phone_code_hash, session_string]):
            await self.bot.send_message(chat_id, "❌ Sessiya ma'lumotlari topilmadi.")
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            return
        
        try:
            # Client yaratish
            client = TelegramClient(StringSession(session_string), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            # Sign in qilish
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            
            # Profil ma'lumotlarini olish
            me = await client.get_me()
            new_session_string = client.session.save()
            
            await client.disconnect()
            
            # Profilni saqlash
            self.db.execute('''
                INSERT INTO profiles 
                (user_id, phone, session_string, first_name, username, last_login)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            ''', (user_id, phone, new_session_string, me.first_name, me.username))
            
            # Active clients ga qo'shish
            profile_id = self.db.fetchone('SELECT last_insert_rowid() as id').get('id')
            self.active_clients[profile_id] = client
            
            # Holatni tozalash
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            
            await self.bot.send_message(
                chat_id,
                f"✅ *Profil qo'shildi.*\n\n"
                f"✅ {me.first_name or 'Foydalanuvchi'}, bot tayyor.\n"
                f"👥 Profillar bo'limidan profilni tanlab ishlating.",
                buttons=[[Button.inline("👥 Profillar", b"profiles")]]
            )
            
        except SessionPasswordNeededError:
            # 2FA parol kerak
            self.db.execute('''
                UPDATE user_sessions SET state = 'waiting_password', data = ?
                WHERE user_id = ?
            ''', (json.dumps({
                'phone': phone,
                'client_session': client.session.save(),
                'step': '2fa'
            }), user_id))
            
            await self.bot.send_message(chat_id, "🔐 *Two-step parolni yuboring:*")
            
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await self.bot.send_message(
                chat_id,
                "❌ *Kod noto'g'ri yoki muddati o'tgan!*\n\n"
                "Iltimos, qaytadan urinib ko'ring."
            )
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        except Exception as e:
            self.logger.error(f"Code input error: {e}")
            await self.bot.send_message(
                chat_id,
                f"❌ *Xatolik:* {str(e)[:100]}\n\n"
                "Iltimos, qaytadan urinib ko'ring."
            )
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    
    async def process_password_input(self, user_id, chat_id, password, state_data):
        """2FA parolni qabul qilish"""
        session_string = state_data.get('client_session')
        phone = state_data.get('phone')
        
        if not session_string:
            await self.bot.send_message(chat_id, "❌ Sessiya ma'lumotlari topilmadi.")
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            return
        
        try:
            client = TelegramClient(StringSession(session_string), Config.API_ID, Config.API_HASH)
            await client.connect()
            
            # 2FA bilan sign in
            await client.sign_in(password=password)
            
            # Profil ma'lumotlarini olish
            me = await client.get_me()
            new_session_string = client.session.save()
            
            await client.disconnect()
            
            # Profilni saqlash
            self.db.execute('''
                INSERT INTO profiles 
                (user_id, phone, session_string, first_name, username, last_login, two_fa_password)
                VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
            ''', (user_id, phone, new_session_string, me.first_name, me.username, password))
            
            # Active clients ga qo'shish
            profile_id = self.db.fetchone('SELECT last_insert_rowid() as id').get('id')
            self.active_clients[profile_id] = client
            
            # Holatni tozalash
            self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            
            await self.bot.send_message(
                chat_id,
                f"✅ *Profil qo'shildi (2FA).*\n\n"
                f"✅ {me.first_name or 'Foydalanuvchi'}, bot tayyor.\n"
                f"👥 Profillar bo'limidan profilni tanlab ishlating.",
                buttons=[[Button.inline("👥 Profillar", b"profiles")]]
            )
            
        except Exception as e:
            self.logger.error(f"Password error: {e}")
            await self.bot.send_message(
                chat_id,
                "❌ *Parol noto'g'ri!*\n\n"
                "Iltimos, to'g'ri parolni kiriting:"
            )
    
    async def select_profile(self, chat_id, user_id, profile_id, message_id):
        """Profilni tanlash"""
        profile = self.db.fetchone('SELECT * FROM profiles WHERE id = ? AND user_id = ?', (profile_id, user_id))
        
        if not profile:
            await self.bot.answer_callback(message_id, "❌ Profil topilmadi")
            return
        
        text = f"""📱 *Profil ma'lumotlari:*

👤 Ism: {profile['first_name'] or 'Noma\'lum'}
📞 Telefon: {profile['phone'][:6]}****{profile['phone'][-2:]}
🔗 Username: {profile['username'] or 'Yo\'q'}
📅 Oxirgi kirish: {profile['last_login'] or 'Noma\'lum'}

✅ *Profil tanlandi!* 

Endi quyidagilarni bajarishingiz mumkin:"""
        
        buttons = [
            [Button.inline("📋 Guruhlar", b"groups_menu")],
            [Button.inline("💬 Xabar", b"message_menu")],
            [Button.inline("⬅️ Orqaga", b"profiles")]
        ]
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    async def delete_profile(self, chat_id, user_id, profile_id, message_id):
        """Profilni o'chirish"""
        self.db.execute('UPDATE profiles SET is_active = 0 WHERE id = ? AND user_id = ?', (profile_id, user_id))
        
        # Active clients dan o'chirish
        if profile_id in self.active_clients:
            try:
                await self.active_clients[profile_id].disconnect()
            except:
                pass
            del self.active_clients[profile_id]
        
        await self.bot.answer_callback(message_id, "✅ Profil o'chirildi")
        await self.show_profiles_menu(chat_id, user_id, message_id)
    
    async def handle_code_not_received(self, chat_id, user_id, message_id):
        """Kod kelmadi handler"""
        text = """🔒 *Ro'yxatdan o'tish yopildi.*
/start orqali qayta urinib ko'ring.

ℹ️ *Ba'zan Telegram kodni kech yuborishi mumkin.*

🕛 00:00 dan 12:00 gacha kod kelishi mumkin.
Shu oraliqda Telegram profilingizni ulang.

🔒 *Hozir ro'yxatdan o'tish yopildi. Qayta urinish:* /start"""
        
        await self.bot.edit_message(chat_id, message_id, text, parse_mode='markdown')
        self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    
    # ==================== GURUHLAR ====================
    
    async def handle_groups_menu(self, chat_id, user_id, message_id, parts):
        """Guruhlar menyusi"""
        if len(parts) == 1:
            text = "📋 *Guruhlar menyusi:*\n\nGuruhlarni boshqarish uchun quyidagilardan birini tanlang:"
            
            buttons = [
                [Button.inline("📃 Ro'yxat", b"groups_list_1")],
                [Button.inline("➕ Qo'shish", b"groups_add")],
                [Button.inline("❌ O'chirish", b"groups_delete")],
                [Button.inline("⬅️ Orqaga", b"back_main")]
            ]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
            
        elif parts[1] == 'list':
            page = int(parts[2]) if len(parts) > 2 else 1
            await self.show_groups_list(chat_id, user_id, message_id, page)
        elif parts[1] == 'add':
            await self.show_add_groups_menu(chat_id, user_id, message_id)
        elif parts[1] == 'delete':
            await self.show_delete_groups_menu(chat_id, user_id, message_id)
    
    async def show_groups_list(self, chat_id, user_id, message_id, page=1):
        """Guruhlar ro'yxati"""
        limit = 10
        offset = (page - 1) * limit
        
        groups = self.db.fetchall('''
            SELECT g.*, p.phone 
            FROM groups g
            JOIN profiles p ON p.id = g.profile_id
            WHERE g.user_id = ? AND g.is_active = 1
            ORDER BY g.added_at DESC
            LIMIT ? OFFSET ?
        ''', (user_id, limit, offset))
        
        total = self.db.fetchone('SELECT COUNT(*) as count FROM groups WHERE user_id = ? AND is_active = 1', (user_id,))['count']
        total_pages = max(1, (total + limit - 1) // limit)
        
        text = f"📋 *Qo'shilgan guruhlar ro'yxati (Sahifa {page}/{total_pages}):*\n\n"
        
        if not groups:
            text += "Hozircha guruhlar yo'q.\n«➕ Qo'shish» tugmasi orqali guruh qo'shing."
        else:
            for group in groups:
                phone = group['phone']
                phone_display = phone[:6] + '****' + phone[-2:]
                group_name = group['group_title'] or group['group_username'] or f"ID: {group['group_id']}"
                text += f"• {group_name[:30]} ({phone_display})\n"
        
        buttons = []
        
        # Navigatsiya
        nav_buttons = []
        if page > 1:
            nav_buttons.append(Button.inline("⬅️ Oldingi", f"groups_list_{page-1}".encode()))
        if page < total_pages:
            nav_buttons.append(Button.inline("Keyingi ➡️", f"groups_list_{page+1}".encode()))
        
        if nav_buttons:
            buttons.append(nav_buttons)
        
        buttons.append([Button.inline("⬅️ Orqaga", b"groups")])
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    async def show_add_groups_menu(self, chat_id, user_id, message_id):
        """Guruh qo'shish menyusi"""
        # Profillarni tekshirish
        profiles = self.db.fetchall('SELECT * FROM profiles WHERE user_id = ? AND is_active = 1', (user_id,))
        
        if not profiles:
            text = "❌ *Avval profil qo'shing!*\n\nGuruh qo'shish uchun kamida bitta profil kerak."
            buttons = [
                [Button.inline("➕ Profil qo'shish", b"addprofile")],
                [Button.inline("⬅️ Orqaga", b"groups")]
            ]
        else:
            text = "➕ *Guruh qo'shish:*\n\nProfil orqali guruhlaringizni tanlang yoki guruh ID/username ni kiriting."
            buttons = [
                [Button.inline("🗒 Mening guruhlarimdan tanlash", b"select_my_groups")],
                [Button.inline("🔗 Guruh ID/username kiriting", b"add_group_manual")],
                [Button.inline("⬅️ Orqaga", b"groups")]
            ]
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    async def show_delete_groups_menu(self, chat_id, user_id, message_id):
        """Guruh o'chirish menyusi"""
        groups = self.db.fetchall('SELECT * FROM groups WHERE user_id = ? AND is_active = 1', (user_id,))
        
        if not groups:
            text = "❌ *O'chirish uchun guruh yo'q!*\n\nAvval guruh qo'shing."
            buttons = [[Button.inline("⬅️ Orqaga", b"groups")]]
        else:
            text = "❌ *O'chirmoqchi bo'lgan guruh:*\n\nQuyidagi guruhlardan birini tanlang:"
            buttons = []
            for group in groups:
                group_name = group['group_title'] or group['group_username'] or f"ID: {group['group_id']}"
                buttons.append([
                    Button.inline(f"🗑 {group_name[:20]}", f"delete_group_{group['id']}".encode())
                ])
            
            buttons.append([Button.inline("⬅️ Orqaga", b"groups")])
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    # ==================== XABAR FUNCTIONS ====================
    
    async def handle_message_menu(self, chat_id, user_id, message_id, parts):
        """Xabar menyusi"""
        if len(parts) == 1:
            text = "💬 *Xabar menyusi:*\n\nYubormoqchi bo'lgan xabaringiz turini tanlang:"
            
            buttons = [
                [Button.inline("📝 Matn xabari", b"message_text")],
                [Button.inline("🖼️ Rasm bilan xabar", b"message_photo")],
                [Button.inline("📂 Mening xabarlarim", b"my_messages")],
                [Button.inline("⬅️ Orqaga", b"back_main")]
            ]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
            
        elif parts[1] == 'text':
            self.db.execute('INSERT OR REPLACE INTO user_sessions (user_id, state) VALUES (?, "waiting_message_text")', (user_id,))
            await self.bot.edit_message(chat_id, message_id, "📝 *Matn xabarini kiriting:*\n\nYubormoqchi bo'lgan xabaringizni yozing:", parse_mode='markdown')
    
    async def process_message_text(self, user_id, chat_id, text):
        """Matn xabarini saqlash"""
        if not text.strip():
            await self.bot.send_message(chat_id, "❌ Xabar bo'sh bo'lishi mumkin emas!")
            return
        
        self.db.execute('''
            INSERT INTO messages (user_id, message_type, message_text)
            VALUES (?, 'text', ?)
        ''', (user_id, text))
        
        message_id = self.db.fetchone('SELECT last_insert_rowid() as id').get('id')
        
        self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        
        await self.bot.send_message(
            chat_id,
            f"✅ *Xabaringiz saqlandi!*\n\n"
            f"Xabar ID: {message_id}\n"
            f"Endi guruhlarni tanlang va ishga tushiring.",
            buttons=[
                [Button.inline("📋 Guruhlar", b"groups_menu")],
                [Button.inline("▶️ Ishga tushirish", b"start_all")]
            ],
            parse_mode='markdown'
        )
    
    # ==================== START/STOP ====================
    
    async def handle_start_stop(self, chat_id, user_id, message_id, parts):
        """Ishga tushirish/to'xtatish"""
        if parts[1] == 'all':
            # Barchasini ishga tushirish
            self.db.execute("UPDATE schedules SET status = 'running', next_send = datetime('now') WHERE user_id = ?", (user_id,))
            
            interval = self.db.fetchone('SELECT interval_minutes FROM schedules WHERE user_id = ? LIMIT 1', (user_id,))
            interval_value = interval['interval_minutes'] if interval else Config.DEFAULT_INTERVAL
            
            text = f"🟢 *Yuborish boshlandi.*\nHar {interval_value} daqiqada yuboriladi."
            buttons = [[Button.inline("⏹️ To'xtatish", b"stop_all")]]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
            
        elif parts[1] == 'stop':
            # To'xtatish
            self.db.execute("UPDATE schedules SET status = 'paused' WHERE user_id = ?", (user_id,))
            
            text = "🔴 *Yuborish to'xtatildi.*"
            buttons = [[Button.inline("▶️ Boshlash", b"start_all")]]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    # ==================== INTERVAL ====================
    
    async def handle_interval_menu(self, chat_id, user_id, message_id, parts):
        """Interval menyusi"""
        if len(parts) == 1:
            current_interval = Config.DEFAULT_INTERVAL
            
            text = f"""⏱ *Interval sozlamasi*

📌 Hozirgi interval: {current_interval} daqiqa

Quyidan tanlang:"""
            
            buttons = [
                [
                    Button.inline("⏱ 2 daqiqa", b"interval_set_2"),
                    Button.inline("⏱ 5 daqiqa", b"interval_set_5")
                ],
                [
                    Button.inline("⏱ 7 daqiqa", b"interval_set_7"),
                    Button.inline("⏱ 10 daqiqa", b"interval_set_10")
                ],
                [Button.inline("⏱ 15 daqiqa", b"interval_set_15")],
                [Button.inline("⏏️ Yopish", b"interval_close")]
            ]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
            
        elif parts[1] == 'set':
            interval = int(parts[2])
            self.db.execute('UPDATE schedules SET interval_minutes = ? WHERE user_id = ?', (interval, user_id))
            
            await self.bot.answer_callback(message_id, f"✅ Interval {interval} daqiqaga sozlandi!")
            await self.bot.delete_messages(chat_id, [message_id])
            
        elif parts[1] == 'close':
            await self.bot.delete_messages(chat_id, [message_id])
    
    # ==================== ADMIN ====================
    
    async def handle_admin_panel(self, chat_id, user_id, message_id, parts):
        """Admin paneli"""
        if user_id != Config.ADMIN_ID:
            await self.bot.answer_callback(message_id, "❌ Siz admin emassiz!")
            return
        
        if len(parts) == 1:
            text = "💎 *Admin panelidasiz:*\n\nQuyidagi funksiyalardan foydalaning:"
            
            buttons = [
                [Button.inline("📤 Xabar yuborish", b"admin_broadcast")],
                [
                    Button.inline("📊 Statistika", b"admin_stats"),
                    Button.inline("🤖 Bot holati", b"admin_bot_status")
                ],
                [Button.inline("📎 Majburiy obunalar", b"admin_channels")],
                [Button.inline("🔏 Panelni yopish", b"admin_close")]
            ]
            
            await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
            
        elif parts[1] == 'close':
            await self.bot.delete_messages(chat_id, [message_id])
            await self.show_main_menu(chat_id, user_id)
    
    async def handle_broadcast(self, chat_id, user_id, message_id, parts):
        """Broadcast menyusi"""
        if user_id != Config.ADMIN_ID:
            return
        
        if parts[1] == 'start':
            self.db.execute('INSERT OR REPLACE INTO user_sessions (user_id, state) VALUES (?, "admin_broadcast")', (user_id,))
            await self.bot.edit_message(chat_id, message_id, "📤 *Hammaga xabar yuborish:*\n\nYubormoqchi bo'lgan xabaringizni yozing:", parse_mode='markdown')
    
    async def process_admin_broadcast(self, user_id, chat_id, text):
        """Admin broadcast"""
        if user_id != Config.ADMIN_ID:
            return
        
        if not text.strip():
            await self.bot.send_message(chat_id, "❌ Xabar bo'sh bo'lishi mumkin emas!")
            return
        
        self.db.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
        
        # Broadcast qilish
        users = self.db.fetchall('SELECT user_id FROM users WHERE user_id != ?', (user_id,))
        
        sent = 0
        failed = 0
        
        broadcast_text = f"📢 *Admin xabari:*\n\n{text}"
        
        for user in users:
            try:
                await self.bot.send_message(user['user_id'], broadcast_text, parse_mode='markdown')
                sent += 1
                await asyncio.sleep(0.1)  # Rate limit
            except:
                failed += 1
        
        await self.bot.send_message(
            chat_id,
            f"📊 *Broadcast natijasi:*\n\n"
            f"✅ Yuborildi: {sent}\n"
            f"❌ Xato: {failed}\n"
            f"📊 Jami: {sent + failed}",
            parse_mode='markdown'
        )
    
    # ==================== SUBSCRIPTION ====================
    
    async def check_subscription(self, user_id):
        """Majburiy obunani tekshirish"""
        if user_id == Config.ADMIN_ID:
            return True
        
        channels = self.db.fetchall('SELECT * FROM mandatory_channels WHERE is_active = 1')
        
        if not channels:
            return True
        
        for channel in channels:
            try:
                participant = await self.bot.get_permissions(channel['channel_id'], user_id)
                if participant.is_banned:
                    return False
            except UserNotParticipantError:
                return False
            except:
                continue
        
        return True
    
    async def show_subscription_required(self, chat_id):
        """Obuna talab qilinadigan xabar"""
        channels = self.db.fetchall('SELECT * FROM mandatory_channels WHERE is_active = 1')
        
        if not channels:
            return
        
        text = "🔒 *Botdan foydalanish uchun kanalimizga obuna bo'ling!*\n\n"
        
        buttons = []
        for channel in channels:
            text += f"📢 {channel['channel_title']}\n"
            
            if channel['channel_username']:
                buttons.append([
                    Button.url(
                        f"📢 {channel['channel_title']}",
                        f"https://t.me/{channel['channel_username'][1:]}"
                    )
                ])
        
        text += "\nHar bir kanalga obuna bo'ling va «✅ Obunani tekshirish» tugmasini bosing."
        
        buttons.append([Button.inline("✅ Obunani tekshirish", b"check_subscription")])
        
        await self.bot.send_message(chat_id, text, buttons=buttons, parse_mode='markdown')
    
    async def show_subscription_required_callback(self, event):
        """Callback uchun obuna talab qilinadigan xabar"""
        channels = self.db.fetchall('SELECT * FROM mandatory_channels WHERE is_active = 1')
        
        if not channels:
            return
        
        text = "🔒 *Botdan foydalanish uchun kanalimizga obuna bo'ling!*\n\n"
        
        buttons = []
        for channel in channels:
            text += f"📢 {channel['channel_title']}\n"
            
            if channel['channel_username']:
                buttons.append([
                    Button.url(
                        f"📢 {channel['channel_title']}",
                        f"https://t.me/{channel['channel_username'][1:]}"
                    )
                ])
        
        text += "\nHar bir kanalga obuna bo'ling va «✅ Obunani tekshirish» tugmasini bosing."
        
        buttons.append([Button.inline("✅ Obunani tekshirish", b"check_subscription")])
        
        await event.edit(text, buttons=buttons, parse_mode='markdown')
    
    async def check_subscription_handler(self, chat_id, user_id, message_id):
        """Obunani tekshirish"""
        subscribed = await self.check_subscription(user_id)
        
        if subscribed:
            await self.bot.edit_message(
                chat_id, message_id,
                "✅ *Obuna tasdiqlandi!*\n\nEndi botdan to'liq foydalanishingiz mumkin.",
                buttons=[[Button.inline("🏠 Asosiy menyu", b"back_main")]],
                parse_mode='markdown'
            )
        else:
            await self.bot.answer_callback(message_id, "❌ Hali barcha kanallarga obuna bo'lmagansiz!")
    
    # ==================== HELPER FUNCTIONS ====================
    
    def get_main_menu(self, user_id):
        """Asosiy menyu tugmalari"""
        buttons = [
            [Button.inline("👥 Profillar", b"profiles")],
            [Button.inline("📊 Statistika", b"stats")],
            [Button.inline("💬 Xabar", b"message_menu")],
            [Button.inline("📋 Guruhlar", b"groups_menu")],
            [Button.inline("▶️ Ishga tushirish", b"start_all")],
            [Button.inline("⏱ Interval", b"interval_menu")]
        ]
        
        if user_id == Config.ADMIN_ID:
            buttons.append([Button.inline("🗄 Boshqaruv", b"admin_panel")])
        
        return buttons
    
    async def show_main_menu(self, chat_id, user_id):
        """Asosiy menyuni ko'rsatish"""
        welcome_text = f"""🚀 *Telegramda avto xabar yuboring*

⏱️ Vaqtingni tejagin
📨 Reklama va e'lonlar uchun

🤖 Bot xabarni o'zi yuboradi

👉 @Avto_xabar_jonat_bot

👇 *Quyidagilardan birini tanlang:*"""
        
        await self.bot.send_message(chat_id, welcome_text, buttons=self.get_main_menu(user_id), parse_mode='markdown')
    
    async def show_stats(self, chat_id, user_id, message_id):
        """Statistika ko'rsatish"""
        stats = self.db.fetchone('''
            SELECT 
                COUNT(DISTINCT p.id) as profiles_count,
                COUNT(DISTINCT g.id) as groups_count,
                COALESCE(SUM(s.sent_count), 0) as total_messages,
                COALESCE(SUM(s.today_count), 0) as today_messages
            FROM users u
            LEFT JOIN profiles p ON p.user_id = u.user_id AND p.is_active = 1
            LEFT JOIN groups g ON g.user_id = u.user_id AND g.is_active = 1
            LEFT JOIN schedules s ON s.user_id = u.user_id
            WHERE u.user_id = ?
        ''', (user_id,))
        
        if not stats:
            stats = {'profiles_count': 0, 'groups_count': 0, 'total_messages': 0, 'today_messages': 0}
        
        text = f"""📊 *Sizning statistikangiz:*

📌 Ulangan guruhlar: {stats['groups_count']} ta
📤 Jami yuborilgan xabarlar: {stats['total_messages']} ta
📅 Bugun yuborilganlar: {stats['today_messages']} ta

📱 Profillar: {stats['profiles_count']} ta"""
        
        buttons = [[Button.inline("⬅️ Orqaga", b"back_main")]]
        
        await self.bot.edit_message(chat_id, message_id, text, buttons=buttons, parse_mode='markdown')
    
    async def handle_back_button(self, chat_id, user_id, message_id, parts):
        """Orqaga tugmasi"""
        if len(parts) > 1 and parts[1] == 'main':
            await self.show_main_menu(chat_id, user_id)
            await self.bot.delete_messages(chat_id, [message_id])
    
    def clean_phone(self, phone):
        """Telefon raqamni tozalash"""
        phone = re.sub(r'[^\d+]', '', phone)
        
        if phone.startswith('+'):
            if len(phone) == 13 and phone.startswith('+998'):
                return phone
        else:
            if len(phone) == 9 and phone.startswith('90'):
                return '+998' + phone
            elif len(phone) == 12 and phone.startswith('998'):
                return '+' + phone
        
        return None
    
    # ==================== SCHEDULER ====================
    
    async def scheduler_worker(self):
        """Xabar yuborish scheduler'i"""
        self.logger.info("🔄 Scheduler worker started")
        
        while self.is_running:
            try:
                # Yuborish kerak bo'lgan xabarlarni olish
                schedules = self.db.fetchall('''
                    SELECT s.*, p.session_string, g.group_id, m.message_text, m.message_type, m.media_path
                    FROM schedules s
                    JOIN profiles p ON p.id = s.profile_id
                    JOIN groups g ON g.id = s.group_id
                    JOIN messages m ON m.id = s.message_id
                    WHERE s.status = 'running' 
                    AND (s.next_send IS NULL OR s.next_send <= datetime('now'))
                    ORDER BY s.next_send
                    LIMIT 10
                ''')
                
                for schedule in schedules:
                    asyncio.create_task(self.send_scheduled_message(schedule))
                
                await asyncio.sleep(10)  # 10 soniyada bir tekshirish
                
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(30)
    
    async def send_scheduled_message(self, schedule):
        """Rejalashtirilgan xabarni yuborish"""
        try:
            profile_id = schedule['profile_id']
            session_string = schedule['session_string']
            group_id = schedule['group_id']
            message_text = schedule['message_text'] or "Test xabar"
            message_type = schedule['message_type']
            media_path = schedule['media_path']
            
            # Client ni olish yoki yaratish
            client = None
            if profile_id in self.active_clients:
                client = self.active_clients[profile_id]
            else:
                client = TelegramClient(StringSession(session_string), Config.API_ID, Config.API_HASH)
                await client.connect()
                
                if not await client.is_user_authorized():
                    self.logger.error(f"Session not authorized for profile {profile_id}")
                    self.db.execute("UPDATE schedules SET status = 'error' WHERE id = ?", (schedule['id'],))
                    await client.disconnect()
                    return
                
                self.active_clients[profile_id] = client
            
            # Guruhni olish
            try:
                entity = await client.get_entity(int(group_id))
            except Exception as e:
                self.logger.error(f"Group not found: {e}")
                self.db.execute("UPDATE schedules SET status = 'error' WHERE id = ?", (schedule['id'],))
                return
            
            # Xabar yuborish
            try:
                if message_type == 'photo' and media_path and os.path.exists(media_path):
                    await client.send_file(entity, media_path, caption=message_text)
                else:
                    await client.send_message(entity, message_text)
                
                # Ma'lumotlarni yangilash
                self.db.execute('''
                    UPDATE schedules 
                    SET sent_count = sent_count + 1,
                        today_count = CASE 
                            WHEN DATE(last_sent) = DATE('now') THEN today_count + 1 
                            ELSE 1 
                        END,
                        last_sent = datetime('now'),
                        next_send = datetime('now', '+' || interval_minutes || ' minutes')
                    WHERE id = ?
                ''', (schedule['id'],))
                
                self.logger.info(f"✅ Message sent: schedule_id={schedule['id']}, group_id={group_id}")
                
            except FloodWaitError as e:
                wait_time = e.seconds
                next_send = datetime.now() + timedelta(seconds=wait_time)
                
                self.db.execute(
                    "UPDATE schedules SET next_send = ? WHERE id = ?",
                    (next_send.strftime('%Y-%m-%d %H:%M:%S'), schedule['id'])
                )
                
                self.logger.warning(f"⚠️ Flood wait: {wait_time} seconds for schedule {schedule['id']}")
                
            except Exception as e:
                self.logger.error(f"❌ Send message error: {e}")
                self.db.execute("UPDATE schedules SET status = 'error' WHERE id = ?", (schedule['id'],))
                
        except Exception as e:
            self.logger.error(f"❌ Send scheduled message error: {e}")
    
    # ==================== PERIODIC TASKS ====================
    
    async def periodic_backup(self):
        """Davriy backup"""
        while self.is_running:
            try:
                await asyncio.sleep(3600)  # Har 1 soatda
                self.json_mgr.backup_database(self.db)
                self.logger.info("✅ Database backed up to JSON")
            except Exception as e:
                self.logger.error(f"Backup error: {e}")
    
    # ==================== CLEANUP ====================
    
    async def cleanup(self):
        """Tozalash"""
        self.logger.info("🧹 Cleaning up...")
        self.is_running = False
        
        # Active clientlarni yopish
        for client in self.active_clients.values():
            try:
                await client.disconnect()
            except:
                pass
        
        # Database ni yopish
        self.db.close()
        
        self.logger.info("✅ Cleanup completed")

# ==================== MAIN ====================
async def main():
    """Asosiy funksiya"""
    print("\n" + "="*60)
    print("🤖 TELEGRAM AUTO MESSAGE BOT - 100% MUKAMMAL")
    print("="*60)
    
    bot = TelegramAutoBot()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        print("\n\n👋 Bot to'xtatildi")
    except Exception as e:
        print(f"\n❌ Xatolik: {e}")
    finally:
        await bot.cleanup()

# ==================== ISHGA TUSHIRISH ====================
if __name__ == "__main__":
    # Event loop sozlash
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    # Botni ishga tushirish
    asyncio.run(main())