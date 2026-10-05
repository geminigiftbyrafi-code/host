import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import threading
import re
import sys
import uuid
import atexit
import requests
import io
import base64

# --- Flask Keep Alive ---
from flask import Flask

app = Flask('')

@app.route('/')
def home():
    return "I'm Marco File Host"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive started.")

# --- Obfuscated Security Config ---
# টোকেনটি ভেঙে টুকরো করে রাখা হয়েছে যাতে কেউ একবারে পুরোটা বুঝতে না পারে
_part1 = "8958211506"
_part2 = ":"
_part3 = "AAFpKSdeQNqY"
_part4 = "JCl4Q1nVWXMWnberNcLNPb4"
TOKEN = f"{_part1}{_part2}{_part3}{_part4}"
OWNER_ID = 6138186135
ADMIN_ID = 6138186135
YOUR_USERNAME = '@rafian40'
UPDATE_CHANNEL = 'https://t.me/rafian40'

# ২ টি বাধ্যতামূলক চ্যানেল (বটকে অবশ্যই চ্যানেল দুটিতে অ্যাডমিন রাখতে হবে)
REQUIRED_CHANNELS = [
    {"username": "@customsmsfree", "url": "https://t.me/customsmsfree", "name": "Custom SMS Free"},
    {"username": "@free_income_13", "url": "https://t.me/free_income_13", "name": "Free Income 13"}
]

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

FREE_USER_LIMIT = 3
SUBSCRIBED_USER_LIMIT = 15
ADMIN_LIMIT = 99999
OWNER_LIMIT = float('inf')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

# --- Data ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False
pending_approvals = {}

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Premium Emojis ---
PEM = {
    "ok": '<tg-emoji emoji-id="6111726981760423576">✅</tg-emoji>',
    "no": '<tg-emoji emoji-id="6311965254817423602">❌</tg-emoji>',
    "warn": '<tg-emoji emoji-id="6314510813214284503">⚠️</tg-emoji>',
    "admin": '<tg-emoji emoji-id="5353032893096567467">📊</tg-emoji>',
    "user": '<tg-emoji emoji-id="5352861489541714456">👤</tg-emoji>',
    "money": '<tg-emoji emoji-id="6111799373434197692">💸</tg-emoji>',
    "msg": '<tg-emoji emoji-id="5337302974806922068">💬</tg-emoji>',
    "rocket": '<tg-emoji emoji-id="5352597830089347330">🚀</tg-emoji>',
    "pin": '<tg-emoji emoji-id="6111410240807245099">📌</tg-emoji>',
    "hi": '<tg-emoji emoji-id="5353027129250453493">👋</tg-emoji>',
    "add": '<tg-emoji emoji-id="6188038822509418008">➕</tg-emoji>',
    "rem": '<tg-emoji emoji-id="6188343249791358585">➖</tg-emoji>',
    "view": '<tg-emoji emoji-id="6188447235244562676">👀</tg-emoji>',
    "wait": '<tg-emoji emoji-id="6233136657722251031">⏳</tg-emoji>',
    "bell": '<tg-emoji emoji-id="6260082445018731350">🔔</tg-emoji>',
    "crown": '<tg-emoji emoji-id="6183661284467152997">👑</tg-emoji>',
    "gear": '<tg-emoji emoji-id="6260111633616475361">⚙️</tg-emoji>',
    "check": '<tg-emoji emoji-id="6188038822509418008">✅</tg-emoji>',
    "file": '<tg-emoji emoji-id="5352721946054268944">📁</tg-emoji>',
    "key": '<tg-emoji emoji-id="6233302765582424442">🔑</tg-emoji>',
    "join": '<tg-emoji emoji-id="5352597830089347330">➡️</tg-emoji>',
    "gift": '<tg-emoji emoji-id="6111799373434197692">🎁</tg-emoji>'
}

# --- Force Join Logic ---
def check_user_joined(user_id):
    if user_id in admin_ids or user_id == OWNER_ID:
        return True
    for ch in REQUIRED_CHANNELS:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.warning(f"Error checking membership for {ch['username']}: {e}")
            return False
    return True

def send_force_join_prompt(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    for ch in REQUIRED_CHANNELS:
        markup.add(types.InlineKeyboardButton(f"📢 Join {ch['name']}", url=ch["url"]))
    markup.add(types.InlineKeyboardButton("🔄 Verify / Joined", callback_data="check_join_status"))
    
    text = (
        f"{PEM['warn']} <b>বটটি ব্যবহার করতে আপনাকে অবশ্যই নিচের চ্যানেল দুটিতে জয়েন হতে হবে!</b>\n\n"
        f"১. <a href='https://t.me/customsmsfree'>Custom SMS Free</a>\n"
        f"২. <a href='https://t.me/free_income_13'>Free Income 13</a>\n\n"
        f"জয়েন সম্পন্ন হলে নিচের <b>'Verify / Joined'</b> বাটনে ক্লিক করুন:"
    )
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=markup, disable_web_page_preview=True)

# --- RAW API for sending reply keyboard with premium emoji ---
def raw_send(chat_id, text, reply_keyboard=None, parse_mode="HTML"):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    if reply_keyboard:
        payload["reply_markup"] = {
            "keyboard": reply_keyboard,
            "resize_keyboard": True
        }
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          json=payload, timeout=60)
        return r.json()
    except Exception as e:
        logger.error(f"raw_send err: {e}")
        return {}

def raw_answer_cb(cb_id, text="", alert=False):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery",
                      json={"callback_query_id": cb_id, "text": text, "show_alert": alert},
                      timeout=30)
    except: pass

def rbtn(text, emoji_id=None, style=None):
    b = {"text": text}
    if emoji_id: b["icon_custom_emoji_id"] = emoji_id
    if style: b["style"] = style
    return b

# --- Main Reply Keyboards ---
def get_main_kb(user_id):
    if user_id in admin_ids:
        return [
            [rbtn("Updates Channel", "5352597830089347330", "primary")],
            [rbtn("Upload File", "5352721946054268944", "primary"),
             rbtn("Check Files", "6188447235244562676", "primary")],
            [rbtn("Bot Speed", "6186175669991379791", "primary"),
             rbtn("Statistics", "5353032893096567467", "success")],
            [rbtn("Subscriptions", "6111799373434197692", "primary"),
             rbtn("Broadcast", "5337302974806922068", "success")],
            [rbtn("Lock Bot", "6311965254817423602", "danger"),
             rbtn("Running All Code", "5352597830089347330", "success")],
            [rbtn("Admin Panel", "6183661284467152997", "primary"),
             rbtn("Contact Owner", "5337302974806922068", "primary")]
        ]
    else:
        return [
            [rbtn("Updates Channel", "5352597830089347330", "primary")],
            [rbtn("Upload File", "5352721946054268944", "primary"),
             rbtn("Check Files", "6188447235244562676", "primary")],
            [rbtn("Bot Speed", "6186175669991379791", "primary"),
             rbtn("Statistics", "5353032893096567467", "success")],
            [rbtn("Contact Owner", "5337302974806922068", "primary")]
        ]

# --- DB ---
def init_db():
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS user_files (user_id INTEGER, file_name TEXT, file_type TEXT, PRIMARY KEY (user_id, file_name))')
        c.execute('CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit(); conn.close()
        logger.info("DB OK.")
    except Exception as e:
        logger.error(f"DB err: {e}")

def load_data():
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry FROM subscriptions')
        for u, e in c.fetchall():
            try: user_subscriptions[u] = {'expiry': datetime.fromisoformat(e)}
            except: pass
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for u, fn, ft in c.fetchall():
            user_files.setdefault(u, []).append((fn, ft))
        c.execute('SELECT user_id FROM active_users')
        active_users.update(x for (x,) in c.fetchall())
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(x for (x,) in c.fetchall())
        conn.close()
        logger.info(f"Loaded: {len(active_users)} users")
    except Exception as e:
        logger.error(f"Load err: {e}")

init_db()
load_data()

# --- Helpers ---
def get_user_folder(uid):
    f = os.path.join(UPLOAD_BOTS_DIR, str(uid))
    os.makedirs(f, exist_ok=True)
    return f

def get_user_file_limit(uid):
    if uid == OWNER_ID: return OWNER_LIMIT
    if uid in admin_ids: return ADMIN_LIMIT
    if uid in user_subscriptions and user_subscriptions[uid]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(uid):
    return len(user_files.get(uid, []))

def is_bot_running(owner, fn):
    key = f"{owner}_{fn}"
    info = bot_scripts.get(key)
    if info and info.get('process'):
        try:
            p = psutil.Process(info['process'].pid)
            r = p.is_running() and p.status() != psutil.STATUS_ZOMBIE
            if not r:
                if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
                    try: info['log_file'].close()
                    except: pass
                bot_scripts.pop(key, None)
            return r
        except psutil.NoSuchProcess:
            if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
                try: info['log_file'].close()
                except: pass
            bot_scripts.pop(key, None)
            return False
        except: return False
    return False

def kill_process_tree(info):
    try:
        if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
            try: info['log_file'].close()
            except: pass
        p = info.get('process')
        if p and hasattr(p, 'pid'):
            pid = p.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for ch in children:
                        try: ch.terminate()
                        except:
                            try: ch.kill()
                            except: pass
                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for x in alive:
                        try: x.kill()
                        except: pass
                    try:
                        parent.terminate()
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired: parent.kill()
                    except psutil.NoSuchProcess: pass
                    except:
                        try: parent.kill()
                        except: pass
                except psutil.NoSuchProcess: pass
    except Exception as e:
        logger.error(f"kill err: {e}")

# --- Auto Install ---
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI', 'telegram': 'python-telegram-bot',
    'aiogram': 'aiogram', 'pyrogram': 'pyrogram', 'telethon': 'telethon',
    'requests': 'requests', 'bs4': 'beautifulsoup4', 'pillow': 'Pillow',
    'cv2': 'opencv-python', 'yaml': 'PyYAML', 'dotenv': 'python-dotenv',
    'pandas': 'pandas', 'numpy': 'numpy', 'flask': 'Flask',
    'psutil': 'psutil', 'uuid': None, 'asyncio': None, 'json': None,
    'datetime': None, 'os': None, 'sys': None, 're': None, 'time': None,
    'math': None, 'random': None, 'logging': None, 'threading': None,
    'subprocess': None, 'zipfile': None, 'tempfile': None, 'shutil': None,
    'sqlite3': None, 'atexit': None
}

def attempt_install_pip(mod, msg):
    pkg = TELEGRAM_MODULES.get(mod.lower(), mod)
    if pkg is None: return False
    try:
        bot.reply_to(msg, f"🐍 Installing `{pkg}`...", parse_mode='Markdown')
        r = subprocess.run([sys.executable, '-m', 'pip', 'install', pkg],
                           capture_output=True, text=True, check=False,
                           encoding='utf-8', errors='ignore')
        if r.returncode == 0:
            bot.reply_to(msg, f"{PEM['ok']} Installed `{pkg}`.", parse_mode='HTML')
            return True
        else:
            err = f"{PEM['no']} Failed.\n<pre>{r.stderr or r.stdout}</pre>"
            if len(err) > 4000: err = err[:4000] + "\n..."
            bot.reply_to(msg, err, parse_mode='HTML')
            return False
    except Exception as e:
        bot.reply_to(msg, f"{PEM['no']} Error: {e}", parse_mode='HTML')
        return False

def attempt_install_npm(mod, folder, msg):
    try:
        bot.reply_to(msg, f"Installing npm `{mod}`...")
        r = subprocess.run(['npm', 'install', mod], capture_output=True, text=True,
                           check=False, cwd=folder, encoding='utf-8', errors='ignore')
        if r.returncode == 0:
            bot.reply_to(msg, f"{PEM['ok']} npm `{mod}` installed.", parse_mode='HTML')
            return True
        else:
            err = f"{PEM['no']} npm failed.\n<pre>{r.stderr or r.stdout}</pre>"
            if len(err) > 4000: err = err[:4000] + "\n..."
            bot.reply_to(msg, err, parse_mode='HTML')
            return False
    except FileNotFoundError:
        bot.reply_to(msg, f"{PEM['no']} 'npm' not found.", parse_mode='HTML')
        return False
    except Exception as e:
        bot.reply_to(msg, f"{PEM['no']} Error: {e}", parse_mode='HTML')
        return False

# --- Run Scripts ---
def run_script(path, owner, folder, fn, msg_obj, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(msg_obj, f"{PEM['no']} Failed after {max_attempts} attempts.", parse_mode='HTML')
        return
    key = f"{owner}_{fn}"
    try:
        if not os.path.exists(path):
            bot.reply_to(msg_obj, f"{PEM['no']} Script not found.", parse_mode='HTML')
            if owner in user_files:
                user_files[owner] = [f for f in user_files.get(owner, []) if f[0] != fn]
            remove_user_file_db(owner, fn)
            return
        if attempt == 1:
            cp = None
            try:
                cp = subprocess.Popen([sys.executable, path], cwd=folder,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8', errors='ignore')
                out, err = cp.communicate(timeout=5)
                rc = cp.returncode
                if rc != 0 and err:
                    m = re.search(r"ModuleNotFoundError: No module named '(.+?)'", err)
                    if m:
                        mod = m.group(1).strip().strip("'\"")
                        if attempt_install_pip(mod, msg_obj):
                            bot.reply_to(msg_obj, f"{PEM['wait']} Retrying...", parse_mode='HTML')
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(path, owner, folder, fn, msg_obj, attempt+1)).start()
                            return
                        return
                    else:
                        bot.reply_to(msg_obj, f"{PEM['no']} Error:\n<pre>{err[:500]}</pre>", parse_mode='HTML')
                        return
            except subprocess.TimeoutExpired:
                if cp and cp.poll() is None: cp.kill(); cp.communicate()
            except FileNotFoundError:
                bot.reply_to(msg_obj, f"{PEM['no']} Python not found.", parse_mode='HTML'); return
            except Exception as e:
                bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML'); return
            finally:
                if cp and cp.poll() is None: cp.kill(); cp.communicate()
        log_path = os.path.join(folder, f"{os.path.splitext(fn)[0]}.log")
        lf = None; pr = None
        try: lf = open(log_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(msg_obj, f"{PEM['no']} Log open failed: {e}", parse_mode='HTML'); return
        try:
            si = None; cf = 0
            if os.name == 'nt':
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
            pr = subprocess.Popen([sys.executable, path], cwd=folder,
                                  stdout=lf, stderr=lf, stdin=subprocess.PIPE,
                                  startupinfo=si, creationflags=cf,
                                  encoding='utf-8', errors='ignore')
            bot_scripts[key] = {
                'process': pr, 'log_file': lf, 'file_name': fn,
                'chat_id': msg_obj.chat.id, 'script_owner_id': owner,
                'start_time': datetime.now(), 'user_folder': folder,
                'type': 'py', 'script_key': key
            }
            bot.reply_to(msg_obj, f"{PEM['ok']} Python script '{fn}' started! (PID: {pr.pid})", parse_mode='HTML')
        except FileNotFoundError:
            if lf and not lf.closed: lf.close()
            bot.reply_to(msg_obj, f"{PEM['no']} Python not found.", parse_mode='HTML')
            bot_scripts.pop(key, None)
        except Exception as e:
            if lf and not lf.closed: lf.close()
            bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML')
            if pr and pr.poll() is None:
                kill_process_tree({'process': pr, 'log_file': lf, 'script_key': key})
            bot_scripts.pop(key, None)
    except Exception as e:
        bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML')
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key]); del bot_scripts[key]

def run_js_script(path, owner, folder, fn, msg_obj, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(msg_obj, f"{PEM['no']} Failed after {max_attempts} attempts.", parse_mode='HTML')
        return
    key = f"{owner}_{fn}"
    try:
        if not os.path.exists(path):
            bot.reply_to(msg_obj, f"{PEM['no']} Script not found.", parse_mode='HTML')
            if owner in user_files:
                user_files[owner] = [f for f in user_files.get(owner, []) if f[0] != fn]
            remove_user_file_db(owner, fn)
            return
        if attempt == 1:
            cp = None
            try:
                cp = subprocess.Popen(['node', path], cwd=folder,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding='utf-8', errors='ignore')
                out, err = cp.communicate(timeout=5)
                rc = cp.returncode
                if rc != 0 and err:
                    m = re.search(r"Cannot find module '(.+?)'", err)
                    if m:
                        mod = m.group(1).strip().strip("'\"")
                        if not mod.startswith('.') and not mod.startswith('/'):
                            if attempt_install_npm(mod, folder, msg_obj):
                                bot.reply_to(msg_obj, f"{PEM['wait']} Retrying...", parse_mode='HTML')
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(path, owner, folder, fn, msg_obj, attempt+1)).start()
                                return
                            return
                    bot.reply_to(msg_obj, f"{PEM['no']} Error:\n<pre>{err[:500]}</pre>", parse_mode='HTML')
                    return
            except subprocess.TimeoutExpired:
                if cp and cp.poll() is None: cp.kill(); cp.communicate()
            except FileNotFoundError:
                bot.reply_to(msg_obj, f"{PEM['no']} 'node' not found.", parse_mode='HTML'); return
            except Exception as e:
                bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML'); return
            finally:
                if cp and cp.poll() is None: cp.kill(); cp.communicate()
        log_path = os.path.join(folder, f"{os.path.splitext(fn)[0]}.log")
        lf = None; pr = None
        try: lf = open(log_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(msg_obj, f"{PEM['no']} Log: {e}", parse_mode='HTML'); return
        try:
            si = None; cf = 0
            if os.name == 'nt':
                si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = subprocess.SW_HIDE
            pr = subprocess.Popen(['node', path], cwd=folder,
                                  stdout=lf, stderr=lf, stdin=subprocess.PIPE,
                                  startupinfo=si, creationflags=cf,
                                  encoding='utf-8', errors='ignore')
            bot_scripts[key] = {
                'process': pr, 'log_file': lf, 'file_name': fn,
                'chat_id': msg_obj.chat.id, 'script_owner_id': owner,
                'start_time': datetime.now(), 'user_folder': folder,
                'type': 'js', 'script_key': key
            }
            bot.reply_to(msg_obj, f"{PEM['ok']} JS script '{fn}' started! (PID: {pr.pid})", parse_mode='HTML')
        except FileNotFoundError:
            if lf and not lf.closed: lf.close()
            bot.reply_to(msg_obj, f"{PEM['no']} 'node' not found.", parse_mode='HTML')
            bot_scripts.pop(key, None)
        except Exception as e:
            if lf and not lf.closed: lf.close()
            bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML')
            if pr and pr.poll() is None:
                kill_process_tree({'process': pr, 'log_file': lf, 'script_key': key})
            bot_scripts.pop(key, None)
    except Exception as e:
        bot.reply_to(msg_obj, f"{PEM['no']} Error: {e}", parse_mode='HTML')
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key]); del bot_scripts[key]

# --- DB Ops ---
DB_LOCK = threading.Lock()

def save_user_file(uid, fn, ft='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)', (uid, fn, ft))
            conn.commit()
            if uid not in user_files: user_files[uid] = []
            user_files[uid] = [(n, t) for n, t in user_files[uid] if n != fn]
            user_files[uid].append((fn, ft))
        except Exception as e: logger.error(f"save_user_file: {e}")
        finally: conn.close()

def remove_user_file_db(uid, fn):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (uid, fn))
            conn.commit()
            if uid in user_files:
                user_files[uid] = [f for f in user_files[uid] if f[0] != fn]
                if not user_files[uid]: del user_files[uid]
        except Exception as e: logger.error(f"remove_user_file: {e}")
        finally: conn.close()

def add_active_user(uid):
    active_users.add(uid)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (uid,))
            conn.commit()
        except Exception as e: logger.error(f"add_active_user: {e}")
        finally: conn.close()

def save_subscription(uid, exp):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (uid, exp.isoformat()))
            conn.commit()
            user_subscriptions[uid] = {'expiry': exp}
        except Exception as e: logger.error(f"save_sub: {e}")
        finally: conn.close()

def remove_subscription_db(uid):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (uid,))
            conn.commit()
            user_subscriptions.pop(uid, None)
        except Exception as e: logger.error(f"remove_sub: {e}")
        finally: conn.close()

def add_admin_db(uid):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (uid,))
            conn.commit()
            admin_ids.add(uid)
        except Exception as e: logger.error(f"add_admin: {e}")
        finally: conn.close()

def remove_admin_db(uid):
    if uid == OWNER_ID: return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('DELETE FROM admins WHERE user_id = ?', (uid,))
            conn.commit()
            removed = c.rowcount > 0
            if removed: admin_ids.discard(uid)
            return removed
        except Exception as e: logger.error(f"remove_admin: {e}"); return False
        finally: conn.close()

# --- Notifications & Sending File as TXT to Admin ---
def notify_admin_new_file(aid, uid, uname, fname, fn, ft, is_zip=False, file_path=None):
    txt = (
        f"{PEM['bell']} <b>New File Upload — Approval Needed!</b>\n\n"
        f"{PEM['user']} Name: <b>{fname}</b>\n"
        f"{PEM['user']} Username: @{uname or 'N/A'}\n"
        f"{PEM['user']} User ID: <code>{uid}</code>\n\n"
        f"{PEM['file']} File: <code>{fn}</code>\n"
        f"{PEM['gear']} Type: <b>{ft.upper()}</b>"
        + (f"\n📦 (ZIP Archive)" if is_zip else "") +
        f"\n\n{PEM['pin']} Approval ID: <code>{aid}</code>\n\n"
        f"{PEM['wait']} Approve to run, or Reject to delete.\n\n"
        f"👉 Send: <code>approve {aid}</code> or <code>reject {aid}</code>"
    )
    
    admins_to_notify = set([int(ADMIN_ID)] + list(admin_ids))
    for admin in admins_to_notify:
        try:
            raw_send(admin, txt)
            if file_path and os.path.exists(file_path):
                if is_zip:
                    with open(file_path, 'rb') as f:
                        bot.send_document(admin, f, caption=f"📦 Original ZIP Archive: {fn}\nFrom User: {uid}")
                else:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as code_f:
                            code_data = code_f.read()
                        txt_io = io.BytesIO(code_data.encode('utf-8'))
                        txt_filename = f"{os.path.splitext(fn)[0]}_{ft}_code.txt"
                        txt_io.name = txt_filename
                        bot.send_document(
                            admin,
                            txt_io,
                            caption=f"📄 Source Code (as .txt): <code>{fn}</code>\nUploaded by: <code>{uid}</code>",
                            parse_mode='HTML'
                        )
                    except Exception as fe:
                        logger.error(f"Error sending txt file: {fe}")
        except Exception as e:
            logger.error(f"notify admin {admin}: {e}")

def notify_user_approved(uid, fn, ft):
    try:
        txt = (f"{PEM['ok']} <b>File Approved & Started!</b>\n\n"
               f"{PEM['file']} File: <code>{fn}</code>\n"
               f"{PEM['gear']} Type: {ft.upper()}\n\n"
               f"{PEM['rocket']} Your file is now running!")
        raw_send(uid, txt, reply_keyboard=get_main_kb(uid))
    except Exception as e: logger.error(f"notify_user_approved: {e}")

def notify_user_rejected(uid, fn, reason=""):
    try:
        txt = (f"{PEM['no']} <b>File Rejected!</b>\n\n"
               f"{PEM['file']} File: <code>{fn}</code>\n\n")
        if reason: txt += f"{PEM['msg']} Reason: {reason}\n\n"
        txt += f"{PEM['wait']} Contact support if needed."
        raw_send(uid, txt, reply_keyboard=get_main_kb(uid))
    except Exception as e: logger.error(f"notify_user_rejected: {e}")

# --- File Handling ---
def handle_zip(content, zname, message):
    uid = message.from_user.id
    folder = get_user_folder(uid)
    tdir = None
    try:
        tdir = tempfile.mkdtemp(prefix=f"u_{uid}_zip_")
        zp = os.path.join(tdir, zname)
        with open(zp, 'wb') as f: f.write(content)
        with zipfile.ZipFile(zp, 'r') as z:
            for m in z.infolist():
                mp = os.path.abspath(os.path.join(tdir, m.filename))
                if not mp.startswith(os.path.abspath(tdir)):
                    raise zipfile.BadZipFile(f"Unsafe: {m.filename}")
            z.extractall(tdir)
        items = os.listdir(tdir)
        py_f = [f for f in items if f.endswith('.py')]
        js_f = [f for f in items if f.endswith('.js')]
        req = 'requirements.txt' if 'requirements.txt' in items else None
        pkg = 'package.json' if 'package.json' in items else None
        if req:
            rp = os.path.join(tdir, req)
            bot.reply_to(message, f"{PEM['wait']} Installing Python deps...", parse_mode='HTML')
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', rp],
                               capture_output=True, text=True, check=True,
                               encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"{PEM['ok']} Python deps installed.", parse_mode='HTML')
            except subprocess.CalledProcessError as e:
                err = f"{PEM['no']} Failed.\n<pre>{e.stderr or e.stdout}</pre>"
                if len(err) > 4000: err = err[:4000] + "\n..."
                bot.reply_to(message, err, parse_mode='HTML'); return
        if pkg:
            bot.reply_to(message, f"{PEM['wait']} Installing Node deps...", parse_mode='HTML')
            try:
                subprocess.run(['npm', 'install'], capture_output=True, text=True,
                               check=True, cwd=tdir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"{PEM['ok']} Node deps installed.", parse_mode='HTML')
            except FileNotFoundError:
                bot.reply_to(message, f"{PEM['no']} 'npm' not found.", parse_mode='HTML'); return
            except subprocess.CalledProcessError as e:
                err = f"{PEM['no']} Failed.\n<pre>{e.stderr or e.stdout}</pre>"
                if len(err) > 4000: err = err[:4000] + "\n..."
                bot.reply_to(message, err, parse_mode='HTML'); return
        main_s = None; ft = None
        for p in ['main.py', 'bot.py', 'app.py']:
            if p in py_f: main_s = p; ft = 'py'; break
        if not main_s:
            for p in ['index.js', 'main.js', 'bot.js', 'app.js']:
                if p in js_f: main_s = p; ft = 'js'; break
        if not main_s:
            if py_f: main_s = py_f[0]; ft = 'py'
            elif js_f: main_s = js_f[0]; ft = 'js'
        if not main_s:
            bot.reply_to(message, f"{PEM['no']} No .py or .js found!", parse_mode='HTML'); return

        permanent_zip = os.path.join(folder, zname)
        with open(permanent_zip, 'wb') as f: f.write(content)

        for name in os.listdir(tdir):
            src = os.path.join(tdir, name)
            dst = os.path.join(folder, name)
            if os.path.isdir(dst): shutil.rmtree(dst)
            elif os.path.exists(dst): os.remove(dst)
            shutil.move(src, dst)
        save_user_file(uid, main_s, ft)
        aid = str(uuid.uuid4())[:8].upper()
        pending_approvals[aid] = {
            'user_id': uid, 'file_name': main_s, 'file_type': ft,
            'file_path': os.path.join(folder, main_s),
            'user_folder': folder, 'message_info': message,
            'is_zip': True, 'main_script': main_s, 'timestamp': time.time()
        }
        txt = (f"{PEM['ok']} <b>Files extracted & deps installed!</b>\n\n"
               f"{PEM['wait']} Waiting for <b>Admin Approval</b>.\n"
               f"{PEM['pin']} Approval ID: <code>{aid}</code>\n\n"
               f"You will be notified once approved.")
        raw_send(uid, txt, reply_keyboard=get_main_kb(uid))
        notify_admin_new_file(aid, uid, message.from_user.username,
                              message.from_user.first_name, main_s, ft, is_zip=True, file_path=permanent_zip)
    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"{PEM['no']} Invalid ZIP: {e}", parse_mode='HTML')
    except Exception as e:
        logger.error(f"zip err: {e}", exc_info=True)
        bot.reply_to(message, f"{PEM['no']} Error: {e}", parse_mode='HTML')
    finally:
        if tdir and os.path.exists(tdir):
            try: shutil.rmtree(tdir)
            except: pass

def handle_js(path, uid, folder, fn, message):
    try:
        save_user_file(uid, fn, 'js')
        aid = str(uuid.uuid4())[:8].upper()
        pending_approvals[aid] = {
            'user_id': uid, 'file_name': fn, 'file_type': 'js',
            'file_path': path, 'user_folder': folder,
            'message_info': message, 'is_zip': False,
            'main_script': fn, 'timestamp': time.time()
        }
        txt = (f"{PEM['ok']} <b>JS file received!</b>\n\n"
               f"{PEM['wait']} Waiting for <b>Admin Approval</b>.\n"
               f"{PEM['pin']} Approval ID: <code>{aid}</code>")
        raw_send(uid, txt, reply_keyboard=get_main_kb(uid))
        notify_admin_new_file(aid, uid, message.from_user.username,
                              message.from_user.first_name, fn, 'js', is_zip=False, file_path=path)
    except Exception as e:
        logger.error(f"js err: {e}", exc_info=True)
        bot.reply_to(message, f"{PEM['no']} Error: {e}", parse_mode='HTML')

def handle_py(path, uid, folder, fn, message):
    try:
        save_user_file(uid, fn, 'py')
        aid = str(uuid.uuid4())[:8].upper()
        pending_approvals[aid] = {
            'user_id': uid, 'file_name': fn, 'file_type': 'py',
            'file_path': path, 'user_folder': folder,
            'message_info': message, 'is_zip': False,
            'main_script': fn, 'timestamp': time.time()
        }
        txt = (f"{PEM['ok']} <b>Python file received!</b>\n\n"
               f"{PEM['wait']} Waiting for <b>Admin Approval</b>.\n"
               f"{PEM['pin']} Approval ID: <code>{aid}</code>")
        raw_send(uid, txt, reply_keyboard=get_main_kb(uid))
        notify_admin_new_file(aid, uid, message.from_user.username,
                              message.from_user.first_name, fn, 'py', is_zip=False, file_path=path)
    except Exception as e:
        logger.error(f"py err: {e}", exc_info=True)
        bot.reply_to(message, f"{PEM['no']} Error: {e}", parse_mode='HTML')

# --- Welcome ---
def send_welcome(chat_id, user_id, first_name, username):
    global bot_locked
    if not check_user_joined(user_id):
        send_force_join_prompt(chat_id)
        return

    if bot_locked and user_id not in admin_ids:
        raw_send(chat_id, f"{PEM['warn']} Bot locked by admin.", reply_keyboard=get_main_kb(user_id))
        return
    if user_id not in active_users:
        add_active_user(user_id)
        try:
            bot.send_message(OWNER_ID,
                f"New user!\n👤 {first_name}\n✳️ @{username or 'N/A'}\n🆔 <code>{user_id}</code>",
                parse_mode='HTML')
        except: pass
    limit = get_user_file_limit(user_id)
    curr = get_user_file_count(user_id)
    lim_str = str(limit) if limit != float('inf') else "Unlimited"
    exp_info = ""
    if user_id == OWNER_ID: st = f"{PEM['crown']} Owner"
    elif user_id in admin_ids: st = f"{PEM['admin']} Admin"
    elif user_id in user_subscriptions:
        e = user_subscriptions[user_id].get('expiry')
        if e and e > datetime.now():
            st = f"{PEM['check']} Premium"; dl = (e - datetime.now()).days
            exp_info = f"\n{PEM['wait']} Expires in {dl} days"
        else: st = f"{PEM['user']} Free (Expired)"; remove_subscription_db(user_id)
    else: st = f"{PEM['user']} Free User"
    txt = (f"{PEM['hi']} <b>Welcome, {first_name}!</b>\n\n"
           f"{PEM['user']} ID: <code>{user_id}</code>\n"
           f"✳️ Username: @{username or 'Not set'}\n"
           f"🔰 Status: {st}{exp_info}\n"
           f"{PEM['file']} Files: {curr} / {lim_str}\n\n"
           f"{PEM['gear']} Host & run Python (`.py`) or JS (`.js`) scripts.\n"
           f"{PEM['warn']} All files need <b>Admin Approval</b> before running.\n\n"
           f"{PEM['pin']} Use buttons below.")
    raw_send(chat_id, txt, reply_keyboard=get_main_kb(user_id))

# --- Force Join Callback ---
@bot.callback_query_handler(func=lambda call: call.data == "check_join_status")
def callback_check_join(call):
    if check_user_joined(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ ধন্যবাদ! আপনি সফলভাবে চ্যানেলগুলোতে জয়েন করেছেন।")
        try: bot.delete_message(call.message.chat.id, call.message.message_id)
        except: pass
        send_welcome(call.message.chat.id, call.from_user.id, call.from_user.first_name, call.from_user.username)
    else:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো ২টি চ্যানেলে জয়েন করেননি! দয়া করে জয়েন করুন।", show_alert=True)

# --- Commands ---
@bot.message_handler(commands=['start', 'help'])
def cmd_start(m):
    send_welcome(m.chat.id, m.from_user.id, m.from_user.first_name, m.from_user.username)

@bot.message_handler(commands=['admin'])
def cmd_admin(m):
    if m.from_user.id in admin_ids:
        raw_send(m.chat.id, f"{PEM['admin']} <b>Admin Panel</b>\n{PEM['pin']} Use buttons below.",
                 reply_keyboard=get_main_kb(m.from_user.id))
    else:
        bot.reply_to(m, f"{PEM['no']} Not admin.", parse_mode='HTML')

# --- Approve / Reject via text command ---
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith("approve ") or m.text.lower().startswith("reject ")))
def handle_approval_text(m):
    uid = m.from_user.id
    if uid not in admin_ids:
        bot.reply_to(m, f"{PEM['no']} Admin only.", parse_mode='HTML')
        return
    parts = m.text.strip().split()
    if len(parts) != 2:
        bot.reply_to(m, f"{PEM['warn']} Use: <code>approve ABCD1234</code> or <code>reject ABCD1234</code>", parse_mode='HTML')
        return
    action = parts[0].lower()
    aid = parts[1].upper()
    if aid not in pending_approvals:
        bot.reply_to(m, f"{PEM['no']} Approval ID not found or already handled.", parse_mode='HTML')
        return
    ap = pending_approvals[aid]
    file_uid = ap['user_id']; fn = ap['file_name']; ft = ap['file_type']
    fp = ap['file_path']; folder = ap['user_folder']; om = ap.get('message_info')

    if action == "approve":
        del pending_approvals[aid]
        try:
            target = om if om else m
            if ft == 'py':
                threading.Thread(target=run_script, args=(fp, file_uid, folder, fn, target)).start()
            elif ft == 'js':
                threading.Thread(target=run_js_script, args=(fp, file_uid, folder, fn, target)).start()
            notify_user_approved(file_uid, fn, ft)
            bot.reply_to(m,
                f"{PEM['ok']} <b>Approved & Started!</b>\n\n"
                f"{PEM['user']} User: <code>{file_uid}</code>\n"
                f"{PEM['file']} File: <code>{fn}</code>",
                parse_mode='HTML')
        except Exception as e:
            logger.error(f"approve err: {e}", exc_info=True)
            bot.reply_to(m, f"{PEM['no']} Error: {e}", parse_mode='HTML')
    elif action == "reject":
        del pending_approvals[aid]
        try:
            if os.path.exists(fp): os.remove(fp)
            remove_user_file_db(file_uid, fn)
        except Exception as e: logger.error(f"reject del: {e}")
        notify_user_rejected(file_uid, fn, reason="Admin rejected the file.")
        bot.reply_to(m,
            f"{PEM['no']} <b>Rejected & Deleted!</b>\n\n"
            f"{PEM['user']} User: <code>{file_uid}</code>\n"
            f"{PEM['file']} File: <code>{fn}</code>",
            parse_mode='HTML')

# --- Button Text Handler ---
@bot.message_handler(func=lambda m: m.text in [
    "Updates Channel", "Upload File", "Check Files",
    "Bot Speed", "Contact Owner", "Statistics",
    "Subscriptions", "Broadcast", "Lock Bot",
    "Running All Code", "Admin Panel", "Run All"
])
def handle_btn(m):
    global bot_locked
    uid = m.from_user.id
    if not check_user_joined(uid):
        send_force_join_prompt(m.chat.id)
        return

    t = m.text
    if t == "Updates Channel":
        raw_send(m.chat.id, f"{PEM['msg']} <b>Updates Channel:</b>\n{UPDATE_CHANNEL}",
                 reply_keyboard=get_main_kb(uid))
    elif t == "Upload File":
        limit = get_user_file_limit(uid); curr = get_user_file_count(uid)
        if curr >= limit:
            lim_str = str(limit) if limit != float('inf') else "Unlimited"
            raw_send(m.chat.id, f"{PEM['warn']} Limit ({curr}/{lim_str}).", reply_keyboard=get_main_kb(uid)); return
        raw_send(m.chat.id,
                 f"{PEM['file']} Send .py, .js or .zip file.\n{PEM['warn']} Admin approval required.",
                 reply_keyboard=get_main_kb(uid))
    elif t == "Check Files":
        files = user_files.get(uid, [])
        if not files:
            raw_send(m.chat.id, f"{PEM['file']} No files.", reply_keyboard=get_main_kb(uid)); return
        msg = f"{PEM['file']} <b>Your files:</b>\n\n"
        kb = []
        for fn, ft in sorted(files):
            r = is_bot_running(uid, fn)
            icon = "🟢" if r else "🔴"
            msg += f"{icon} <code>{fn}</code> ({ft})\n"
            kb.append([rbtn(f"{'Stop' if r else 'Start'} {fn}", "6111726981760423576" if not r else "6311965254817423602",
                           "danger" if r else "success"),
                       rbtn(f"Delete {fn}", "6188343249791358585", "danger")])
        kb.append([rbtn("Back", "6109360506319935223", "primary")])
        raw_send(m.chat.id, msg, reply_keyboard=kb)
    elif t == "Bot Speed":
        t0 = time.time()
        wm = bot.reply_to(m, f"{PEM['wait']} Testing...", parse_mode='HTML')
        try:
            bot.send_chat_action(m.chat.id, 'typing')
            rt = round((time.time() - t0) * 1000, 2)
            st = f"{PEM['check']} Unlocked" if not bot_locked else f"{PEM['warn']} Locked"
            if uid == OWNER_ID: lvl = f"{PEM['crown']} Owner"
            elif uid in admin_ids: lvl = f"{PEM['admin']} Admin"
            elif uid in user_subscriptions and user_subscriptions[uid].get('expiry', datetime.min) > datetime.now(): lvl = f"{PEM['check']} Premium"
            else: lvl = f"{PEM['user']} Free"
            bot.edit_message_text(f"{PEM['rocket']} Speed: {rt} ms\n🚦 {st}\n👤 {lvl}",
                                  m.chat.id, wm.message_id, parse_mode='HTML')
        except: pass
    elif t == "Contact Owner":
        raw_send(m.chat.id, f"{PEM['msg']} <b>Contact Owner:</b>\nhttps://t.me/{YOUR_USERNAME.replace('@', '')}",
                 reply_keyboard=get_main_kb(uid))
    elif t == "Statistics":
        total_users = len(active_users)
        total_files = sum(len(f) for f in user_files.values())
        running = 0; mine = 0
        for k, v in list(bot_scripts.items()):
            owner, _ = k.split('_', 1)
            if is_bot_running(int(owner), v['file_name']):
                running += 1
                if int(owner) == uid: mine += 1
        msg = (f"{PEM['admin']} <b>Statistics:</b>\n\n"
               f"{PEM['user']} Users: {total_users}\n"
               f"{PEM['file']} Files: {total_files}\n"
               f"Running: {running}\n"
               f"{PEM['wait']} Pending: {len(pending_approvals)}\n")
        if uid in admin_ids:
            msg += f"Bot: {'Locked' if bot_locked else 'Unlocked'}\nYour Bots: {mine}"
        else:
            msg += f"Your Bots: {mine}"
        raw_send(m.chat.id, msg, reply_keyboard=get_main_kb(uid))
    elif t == "Subscriptions":
        if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
        raw_send(m.chat.id,
                 f"{PEM['money']} <b>Subscription Management</b>\n\n"
                 f"Send: <code>addsub ID DAYS</code>\n"
                 f"Send: <code>removesub ID</code>\n"
                 f"Send: <code>checksub ID</code>",
                 reply_keyboard=get_main_kb(uid))
    elif t == "Broadcast":
        if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
        msg = bot.reply_to(m, f"{PEM['msg']} Send broadcast message.\n/cancel to abort.", parse_mode='HTML')
        bot.register_next_step_handler(msg, process_broadcast)
    elif t == "Lock Bot":
        if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
        bot_locked = not bot_locked
        raw_send(m.chat.id, f"{'Bot locked.' if bot_locked else 'Bot unlocked.'}", reply_keyboard=get_main_kb(uid))
    elif t in ["Running All Code", "Run All"]:
        if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
        run_all_scripts(m)
    elif t == "Admin Panel":
        if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
        raw_send(m.chat.id,
                 f"{PEM['crown']} <b>Admin Panel</b>\n\n"
                 f"Send: <code>addadmin ID</code>\n"
                 f"Send: <code>removeadmin ID</code>\n"
                 f"Send: <code>listadmins</code>",
                 reply_keyboard=get_main_kb(uid))

# --- File Control via Text Commands ---
@bot.message_handler(func=lambda m: m.text and (
    m.text.startswith("Start ") or m.text.startswith("Stop ") or
    m.text.startswith("Delete ") or m.text.startswith("Logs ")
))
def handle_file_cmd(m):
    global bot_locked
    uid = m.from_user.id
    if not check_user_joined(uid):
        send_force_join_prompt(m.chat.id)
        return

    parts = m.text.split(maxsplit=1)
    if len(parts) != 2: return
    action = parts[0].lower()
    fn = parts[1].strip()

    owner = None
    for o, files in user_files.items():
        if any(f[0] == fn for f in files):
            owner = o
            break
    if owner is None:
        raw_send(m.chat.id, f"{PEM['no']} File not found.", reply_keyboard=get_main_kb(uid)); return
    if not (uid == owner or uid in admin_ids):
        raw_send(m.chat.id, f"{PEM['no']} Not yours.", reply_keyboard=get_main_kb(uid)); return

    folder = get_user_folder(owner); fp = os.path.join(folder, fn)
    ft = next((f[1] for f in user_files.get(owner, []) if f[0] == fn), 'py')
    key = f"{owner}_{fn}"

    if action == "start":
        if is_bot_running(owner, fn):
            raw_send(m.chat.id, f"{PEM['warn']} Already running.", reply_keyboard=get_main_kb(uid)); return
        if not os.path.exists(fp):
            raw_send(m.chat.id, f"{PEM['no']} Missing file.", reply_keyboard=get_main_kb(uid))
            remove_user_file_db(owner, fn); return
        if ft == 'py':
            threading.Thread(target=run_script, args=(fp, owner, folder, fn, m)).start()
        elif ft == 'js':
            threading.Thread(target=run_js_script, args=(fp, owner, folder, fn, m)).start()
    elif action == "stop":
        if not is_bot_running(owner, fn):
            raw_send(m.chat.id, f"{PEM['warn']} Already stopped.", reply_keyboard=get_main_kb(uid)); return
        pi = bot_scripts.get(key)
        if pi: kill_process_tree(pi)
        bot_scripts.pop(key, None)
        raw_send(m.chat.id, f"{PEM['ok']} Stopped {fn}.", reply_keyboard=get_main_kb(uid))
    elif action == "delete":
        if is_bot_running(owner, fn):
            pi = bot_scripts.get(key)
            if pi: kill_process_tree(pi)
            bot_scripts.pop(key, None)
        if os.path.exists(fp): os.remove(fp)
        lp = os.path.join(folder, f"{os.path.splitext(fn)[0]}.log")
        if os.path.exists(lp): os.remove(lp)
        remove_user_file_db(owner, fn)
        raw_send(m.chat.id, f"{PEM['ok']} Deleted {fn}.", reply_keyboard=get_main_kb(uid))
    elif action == "logs":
        lp = os.path.join(folder, f"{os.path.splitext(fn)[0]}.log")
        if not os.path.exists(lp):
            raw_send(m.chat.id, f"{PEM['no']} No logs.", reply_keyboard=get_main_kb(uid)); return
        try:
            content = ""; fs = os.path.getsize(lp)
            max_kb = 100; max_msg = 3800
            if fs == 0: content = "(Empty)"
            elif fs > max_kb * 1024:
                with open(lp, 'rb') as f:
                    f.seek(-max_kb * 1024, os.SEEK_END)
                    content = f.read().decode('utf-8', errors='ignore')
                content = f"(Last {max_kb} KB)\n...\n" + content
            else:
                with open(lp, 'r', encoding='utf-8', errors='ignore') as f: content = f.read()
            if len(content) > max_msg:
                content = content[-max_msg:]
                nl = content.find('\n')
                if nl != -1: content = "...\n" + content[nl+1:]
            if not content.strip(): content = "(No content)"
            raw_send(m.chat.id, f"{PEM['file']} Logs for <b>{fn}</b>:\n<pre>{content}</pre>",
                     reply_keyboard=get_main_kb(uid))
        except Exception as e:
            raw_send(m.chat.id, f"{PEM['no']} Error: {e}", reply_keyboard=get_main_kb(uid))

# --- Text Commands for Admin Panel & Subscriptions ---
@bot.message_handler(func=lambda m: m.text and (
    m.text.startswith("addadmin ") or m.text.startswith("removeadmin ") or
    m.text.lower() == "listadmins" or
    m.text.startswith("addsub ") or m.text.startswith("removesub ") or
    m.text.startswith("checksub ")
))
def handle_admin_cmd(m):
    uid = m.from_user.id
    if uid not in admin_ids:
        raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
    txt = m.text.strip()
    low = txt.lower()

    if low == "listadmins":
        lst = "\n".join(f"- <code>{a}</code> {'(Owner)' if a == OWNER_ID else ''}" for a in sorted(admin_ids))
        if not lst: lst = "(None)"
        raw_send(m.chat.id, f"{PEM['crown']} <b>Admins:</b>\n\n{lst}", reply_keyboard=get_main_kb(uid))
        return

    if low.startswith("addadmin "):
        if uid != OWNER_ID:
            raw_send(m.chat.id, f"{PEM['no']} Owner only.", reply_keyboard=get_main_kb(uid)); return
        try:
            nid = int(txt.split()[1])
            if nid == OWNER_ID or nid in admin_ids:
                raw_send(m.chat.id, f"{PEM['warn']} Already admin.", reply_keyboard=get_main_kb(uid)); return
            add_admin_db(nid)
            raw_send(m.chat.id, f"{PEM['ok']} Added admin <code>{nid}</code>.", reply_keyboard=get_main_kb(uid))
            try: bot.send_message(nid, f"{PEM['crown']} You are now Admin!", parse_mode='HTML')
            except: pass
        except:
            raw_send(m.chat.id, f"{PEM['no']} Usage: addadmin ID", reply_keyboard=get_main_kb(uid))
        return

    if low.startswith("removeadmin "):
        if uid != OWNER_ID:
            raw_send(m.chat.id, f"{PEM['no']} Owner only.", reply_keyboard=get_main_kb(uid)); return
        try:
            rid = int(txt.split()[1])
            if remove_admin_db(rid):
                raw_send(m.chat.id, f"{PEM['ok']} Removed admin <code>{rid}</code>.", reply_keyboard=get_main_kb(uid))
            else:
                raw_send(m.chat.id, f"{PEM['warn']} Not admin.", reply_keyboard=get_main_kb(uid))
        except:
            raw_send(m.chat.id, f"{PEM['no']} Usage: removeadmin ID", reply_keyboard=get_main_kb(uid))
        return

    if low.startswith("addsub "):
        try:
            parts = txt.split()
            sid = int(parts[1]); days = int(parts[2])
            if sid <= 0 or days <= 0: raise ValueError()
            ce = user_subscriptions.get(sid, {}).get('expiry')
            start = datetime.now()
            if ce and ce > start: start = ce
            ne = start + timedelta(days=days)
            save_subscription(sid, ne)
            raw_send(m.chat.id, f"{PEM['ok']} Sub added. Expiry: {ne:%Y-%m-%d}", reply_keyboard=get_main_kb(uid))
            try: bot.send_message(sid, f"{PEM['gift']} Sub active! Expires: {ne:%Y-%m-%d}.", parse_mode='HTML')
            except: pass
        except:
            raw_send(m.chat.id, f"{PEM['no']} Usage: addsub ID DAYS", reply_keyboard=get_main_kb(uid))
        return

    if low.startswith("removesub "):
        try:
            sid = int(txt.split()[1])
            remove_subscription_db(sid)
            raw_send(m.chat.id, f"{PEM['ok']} Sub removed.", reply_keyboard=get_main_kb(uid))
            try: bot.send_message(sid, f"{PEM['no']} Subscription removed.", parse_mode='HTML')
            except: pass
        except:
            raw_send(m.chat.id, f"{PEM['no']} Usage: removesub ID", reply_keyboard=get_main_kb(uid))
        return

    if low.startswith("checksub "):
        try:
            sid = int(txt.split()[1])
            if sid in user_subscriptions:
                e = user_subscriptions[sid].get('expiry')
                if e:
                    if e > datetime.now():
                        dl = (e - datetime.now()).days
                        raw_send(m.chat.id, f"{PEM['ok']} <code>{sid}</code> active. Expires: {e:%Y-%m-%d} ({dl} days)", reply_keyboard=get_main_kb(uid))
                    else:
                        raw_send(m.chat.id, f"{PEM['warn']} <code>{sid}</code> expired.", reply_keyboard=get_main_kb(uid))
                        remove_subscription_db(sid)
                else:
                    raw_send(m.chat.id, f"{PEM['warn']} Expiry missing.", reply_keyboard=get_main_kb(uid))
            else:
                raw_send(m.chat.id, f"{PEM['user']} No sub.", reply_keyboard=get_main_kb(uid))
        except:
            raw_send(m.chat.id, f"{PEM['no']} Usage: checksub ID", reply_keyboard=get_main_kb(uid))
        return

# --- Document Handler ---
@bot.message_handler(content_types=['document'])
def handle_doc(m):
    uid = m.from_user.id
    if not check_user_joined(uid):
        send_force_join_prompt(m.chat.id)
        return

    doc = m.document
    if bot_locked and uid not in admin_ids:
        raw_send(m.chat.id, f"{PEM['warn']} Bot locked.", reply_keyboard=get_main_kb(uid)); return
    limit = get_user_file_limit(uid); curr = get_user_file_count(uid)
    if curr >= limit:
        lim_str = str(limit) if limit != float('inf') else "Unlimited"
        raw_send(m.chat.id, f"{PEM['warn']} Limit ({curr}/{lim_str}).", reply_keyboard=get_main_kb(uid)); return
    fn = doc.file_name
    if not fn: raw_send(m.chat.id, f"{PEM['no']} No file name.", reply_keyboard=get_main_kb(uid)); return
    ext = os.path.splitext(fn)[1].lower()
    if ext not in ['.py', '.js', '.zip']:
        raw_send(m.chat.id, f"{PEM['no']} Only .py, .js, .zip.", reply_keyboard=get_main_kb(uid)); return
    if doc.file_size > 20 * 1024 * 1024:
        raw_send(m.chat.id, f"{PEM['no']} Max 20MB.", reply_keyboard=get_main_kb(uid)); return
    try:
        wm = bot.reply_to(m, f"{PEM['wait']} Downloading `{fn}`...", parse_mode='HTML')
        fi = bot.get_file(doc.file_id)
        content = bot.download_file(fi.file_path)
        bot.edit_message_text(f"{PEM['ok']} Downloaded. Processing...", m.chat.id, wm.message_id, parse_mode='HTML')
        folder = get_user_folder(uid)
        if ext == '.zip':
            handle_zip(content, fn, m)
        else:
            fp = os.path.join(folder, fn)
            with open(fp, 'wb') as f: f.write(content)
            if ext == '.js': handle_js(fp, uid, folder, fn, m)
            elif ext == '.py': handle_py(fp, uid, folder, fn, m)
    except telebot.apihelper.ApiTelegramException as e:
        if "file is too big" in str(e).lower():
            raw_send(m.chat.id, f"{PEM['no']} File too large.", reply_keyboard=get_main_kb(uid))
        else:
            raw_send(m.chat.id, f"{PEM['no']} TG Error: {e}", reply_keyboard=get_main_kb(uid))
    except Exception as e:
        logger.error(f"doc err: {e}", exc_info=True)
        raw_send(m.chat.id, f"{PEM['no']} Error: {e}", reply_keyboard=get_main_kb(uid))

# --- Broadcast ---
def process_broadcast(m):
    uid = m.from_user.id
    if uid not in admin_ids: raw_send(m.chat.id, f"{PEM['no']} Admin only.", reply_keyboard=get_main_kb(uid)); return
    if m.text and m.text.lower() == '/cancel': raw_send(m.chat.id, "Cancelled.", reply_keyboard=get_main_kb(uid)); return
    content = m.text
    if not content and not (m.photo or m.video or m.document or m.sticker):
        raw_send(m.chat.id, f"{PEM['no']} Empty.", reply_keyboard=get_main_kb(uid)); return
    raw_send(m.chat.id, f"{PEM['wait']} Broadcasting to {len(active_users)} users...", reply_keyboard=get_main_kb(uid))
    threading.Thread(target=do_broadcast, args=(content, m.chat.id)).start()

def do_broadcast(text, chat_id):
    sent = 0; failed = 0; blocked = 0
    users = list(active_users); total = len(users)
    for i, u in enumerate(users):
        try:
            bot.send_message(u, f"{PEM['bell']} {text}", parse_mode='HTML')
            sent += 1
        except telebot.apihelper.ApiTelegramException as e:
            ed = str(e).lower()
            if any(s in ed for s in ["blocked", "deactivated", "chat not found", "kicked", "restricted"]):
                blocked += 1
            else: failed += 1
        except: failed += 1
        if (i + 1) % 25 == 0: time.sleep(1.5)
        elif i % 5 == 0: time.sleep(0.2)
    raw_send(chat_id, f"{PEM['ok']} <b>Broadcast Complete!</b>\n\n✅ Sent: {sent}\n❌ Failed: {failed}\n🚫 Blocked: {blocked}\n👥 Total: {total}")

# --- Run All Scripts ---
def run_all_scripts(m):
    uid = m.from_user.id; chat_id = m.chat.id
    if uid not in admin_ids: return
    raw_send(chat_id, f"{PEM['wait']} Starting all scripts...", reply_keyboard=get_main_kb(uid))
    threading.Thread(target=run_all_scripts_bg, args=(chat_id,)).start()

def run_all_scripts_bg(chat_id):
    started = 0; users_count = 0; skipped = 0
    snapshot = dict(user_files)
    for tuid, files in snapshot.items():
        if not files: continue
        users_count += 1
        uf = get_user_folder(tuid)
        for fn, ft in files:
            if not is_bot_running(tuid, fn):
                fp = os.path.join(uf, fn)
                if os.path.exists(fp):
                    try:
                        if ft == 'py':
                            threading.Thread(target=run_script, args=(fp, tuid, uf, fn, _FakeMsg(chat_id))).start()
                        elif ft == 'js':
                            threading.Thread(target=run_js_script, args=(fp, tuid, uf, fn, _FakeMsg(chat_id))).start()
                        started += 1
                        time.sleep(0.7)
                    except: skipped += 1
                else:
                    skipped += 1
    msg = f"{PEM['ok']} Started: {started}\n👥 Users: {users_count}\n"
    if skipped: msg += f"{PEM['warn']} Skipped: {skipped}\n"
    raw_send(chat_id, msg)

class _FakeMsg:
    def __init__(self, chat_id):
        self.chat = type('C', (), {'id': chat_id})()

# --- Cleanup ---
def cleanup():
    logger.warning("Shutting down...")
    for k in list(bot_scripts.keys()):
        if k in bot_scripts: kill_process_tree(bot_scripts[k])
atexit.register(cleanup)

# --- Main ---
if __name__ == '__main__':
    logger.info("=" * 40 + f"\n🤖 Bot Starting...\n🔑 Owner: {OWNER_ID}\n🛡️ Admins: {admin_ids}\n" + "=" * 40)
    keep_alive()
    logger.info("🚀 Polling started...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("ReadTimeout. 5s..."); time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"ConnError: {ce}. 15s..."); time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Polling error: {e}", exc_info=True); time.sleep(30)
        finally:
            time.sleep(1)
