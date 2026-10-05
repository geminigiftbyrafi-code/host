import logging
import os
import sys
import asyncio
import re
import httpx
import hashlib
import json
import csv
import html
from io import StringIO, BytesIO
from datetime import datetime, timedelta
import threading
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    ContextTypes, 
    CallbackQueryHandler
)
from telegram.error import BadRequest, Conflict, TimedOut, TelegramError, Forbidden

# =========================================================================
# --- WINDOWS TERMINAL UNICODE FIX & ADVANCED LOGGING ---
# =========================================================================
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_core_debug.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

# =========================================================================
# --- LOCAL JSON DATABASE CONFIGURATION ---
# =========================================================================
DB_FILE = "local_database.json"

def load_local_db():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading local DB: {e}")
    return {
        "users": {},
        "assignments": {},
        "withdrawals": {},
        "settings": {
            'otp_rate': '1.0',
            'min_withdraw': '1000',
            'global_cc_limit': '3'
        },
        "country_rates": {},
        "country_limits": {},
        "processed_messages": {}
    }

def save_local_db():
    try:
        data = {
            "users": CACHE_USERS,
            "assignments": CACHE_ASSIGNMENTS,
            "withdrawals": CACHE_WITHDRAWALS,
            "settings": CACHE_SETTINGS,
            "country_rates": CACHE_RATES,
            "country_limits": CACHE_LIMITS,
            "processed_messages": CACHE_PROCESSED
        }
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving local DB: {e}")

db_data = load_local_db()

CACHE_USERS = db_data.get("users", {})
CACHE_STOCK = {}
CACHE_ASSIGNMENTS = db_data.get("assignments", {})
CACHE_SETTINGS = db_data.get("settings", {})
CACHE_RATES = db_data.get("country_rates", {})
CACHE_LIMITS = db_data.get("country_limits", {})
CACHE_PROCESSED = db_data.get("processed_messages", {})
CACHE_WITHDRAWALS = db_data.get("withdrawals", {})

otp_process_lock = asyncio.Lock()

# =========================================================================
# --- BOT CONFIGURATION & GLOBAL SETTINGS ---
# =========================================================================
ADMIN_IDS = [6138186135]
SUPER_ADMIN_ID = 6138186135 
TOKEN = "8883727725:AAE9vx2W4Zw6c3TySOB-HrfwD2tpbHbGwyU" 
TARGET_GROUP_IDS = [-1004375045490] 
OTP_GROUP_LINK = "https://t.me/your_otp_group" 

API_SOURCES = [

    {
        "name": "Lamix", 
        "token": "37enC3fZIZ9NAztnIC7VeE_Q57ELIGVWamav3znVavA", 
        "url": "https://panel.lamix.org/api/v1/messages"
    },
 
]

processed_ids = set()

http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(5.0, connect=2.0, read=4.0), 
    limits=httpx.Limits(max_connections=500, max_keepalive_connections=100),
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "application/json"
    }
)

def init_default_settings():
    defaults = {
        'otp_rate': '1.0',
        'min_withdraw': '1000',
        'global_cc_limit': '3'
    }
    for k, v in defaults.items():
        if k not in CACHE_SETTINGS:
            CACHE_SETTINGS[k] = v
    for src in API_SOURCES:
        key = f"api_status_{src['name']}"
        if key not in CACHE_SETTINGS:
            CACHE_SETTINGS[key] = '1'
    save_local_db()

init_default_settings()

# =========================================================================
# --- CORE UTILITY HELPERS ---
# =========================================================================
async def get_config_val(key, default):
    return str(CACHE_SETTINGS.get(key, default))

async def set_config_val(key, value):
    val_str = str(value)
    CACHE_SETTINGS[key] = val_str
    save_local_db()

async def get_country_payout(country_name):
    if country_name in CACHE_RATES:
        return float(CACHE_RATES[country_name])
    default_rate = await get_config_val('otp_rate', '1.0')
    return float(default_rate)

async def get_country_cc_limit(country_name):
    if country_name in CACHE_LIMITS:
        return int(CACHE_LIMITS[country_name])
    global_limit = await get_config_val('global_cc_limit', '3')
    return int(global_limit)

def normalize_num(num_str):
    return re.sub(r'\D', '', str(num_str))

def parse_otp_body(text):
    if not text: return "Not found"
    numeric_match = re.search(r'\b(\d{4,8})(?!\d)', text)
    if numeric_match: 
        return numeric_match.group(1)
        
    mixed_match = re.search(r'\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{4,10}\b', text)
    if mixed_match:
        val = mixed_match.group(0)
        if not re.match(r'^\d+(st|nd|rd|th)$', val, re.IGNORECASE):
            return val
        
    triggers = ['code', 'otp', 'is', 'pin', 'verification', 'verify', 'anyone']
    STOP_WORDS = {
        'with', 'anyone', 'to', 'for', 'your', 'my', 'this', 'is', 'a', 'an', 'the', 
        'be', 'not', 'share', 'confirmation', 'verification', 'code', 'do', 'any', 
        'one', 'about', 'from', 'me', 'us', 'him', 'her', 'them', 'by', 'at', 'on', 
        'in', 'of', 'and', 'or', 'but', 'if', 'you', 'your', 'yours', 'yourself', 
        'please', 'never', 'don', 'dont', 'should', 'would', 'could', 'will', 'shall',
        'security', 'key', 'login', 'access'
    }
    
    lower_t = text.lower()
    for t in triggers:
        if t in lower_t:
            idx = lower_t.find(t) + len(t)
            rem = text[idx:].strip()
            words = re.split(r'\s+', rem)
            for w in words:
                clean_w = re.sub(r'\W+', '', w)
                if not clean_w: continue
                if clean_w.lower() in STOP_WORDS: continue
                if 4 <= len(clean_w) <= 12 and re.match(r'^[A-Za-z0-9]+$', clean_w):
                    return clean_w
                    
    return "Not found"

# =========================================================================
# --- STYLED INTERFACE SYSTEM ---
# =========================================================================
def rich_btn(text, style=None, callback_data=None, url=None, copy_text=None):
    btn = {"text": text}
    if style: btn["style"] = style 
    if callback_data: btn["callback_data"] = callback_data
    if url: btn["url"] = url
    if copy_text: btn["copy_text"] = {"text": copy_text}
    return btn

async def send_rich_message(bot, chat_id, text, keyboard_rows, parse_mode='HTML', **kwargs):
    payload = {
        "chat_id": chat_id, "text": text, "parse_mode": parse_mode,
        "reply_markup": {"inline_keyboard": keyboard_rows}
    }
    payload.update(kwargs)
    url = f"https://api.telegram.org/bot{bot.token}/sendMessage"
    try:
        resp = await http_client.post(url, json=payload)
        return resp.json()
    except Exception as e: logger.error(f"Dispatch failure: {e}")

async def edit_rich_message(bot, chat_id, message_id, text, keyboard_rows, parse_mode='HTML'):
    payload = {
        "chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode,
        "reply_markup": {"inline_keyboard": keyboard_rows}
    }
    url = f"https://api.telegram.org/bot{bot.token}/editMessageText"
    try:
        resp = await http_client.post(url, json=payload)
        return resp.json()
    except Exception as e: logger.error(f"Edit failure: {e}")

# =========================================================================
# --- KEYBOARD LAYOUT ARCHITECTURE ---
# =========================================================================
def build_admin_main(uid):
    kb = [
        [KeyboardButton("📥 Number Upload"), KeyboardButton("🗑️ Number Delete")],
        [KeyboardButton("👥 User List"), KeyboardButton("📊 Panel Stats")],
        [KeyboardButton("💸 Withdraw Requests"), KeyboardButton("💰 Total Paid")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("🧹 Clear All Stocks")],
        [KeyboardButton("🚫 Ban User"), KeyboardButton("✅ Unban User")],
        [KeyboardButton("⚙️ Set CC Limit"), KeyboardButton("✍️ Country Rate Set")]
    ]
    if uid == SUPER_ADMIN_ID:
        kb.append([KeyboardButton("📤 Upload User Data")])
    
    kb.append([KeyboardButton("/start")])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def build_user_main():
    kb = [
        [KeyboardButton("⚡ Get Number 3"), KeyboardButton("🔥 Get Number 10")],
        [KeyboardButton("💳 My Balance"), KeyboardButton("💵 Withdraw Funds")],
        [KeyboardButton("🏆 Leaderboard"), KeyboardButton("📦 Stock History")],
        [KeyboardButton("/start")]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# =========================================================================
# --- ACCURATE USER STOCK ALLOCATION & ROUTING ENGINE ---
# =========================================================================
async def engine_assign_batch(user_id, country_name, count):
    try:
        skip_limit = await get_country_cc_limit(country_name)
        assigned_numbers = []
        ts_now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        for batch_id, b_data in list(CACHE_STOCK.items()):
            if isinstance(b_data, dict) and b_data.get("country") == country_name and b_data.get("numbers"):
                nums = b_data.get("numbers", [])
                if not nums: continue
                
                take_count = min(count - len(assigned_numbers), len(nums))
                taken = nums[:take_count]
                
                b_data["numbers"] = nums[take_count:]
                assigned_numbers.extend(taken)
                
                if len(assigned_numbers) >= count:
                    break

        if not assigned_numbers:
            return None, "⚠️ Selected region stock empty!"

        num_data_list = []
        for num in assigned_numbers:
            clean = normalize_num(num)
            short_val = clean[skip_limit:] if len(clean) > skip_limit else clean
            num_data_list.append({"full": clean, "short": short_val})
            
            assign_key = f"as_{clean}"
            assign_item = {
                'user_id': user_id,
                'number': clean,
                'country': country_name,
                'assigned_at': ts_now,
                'status': 'assigned'
            }
            CACHE_ASSIGNMENTS[assign_key] = assign_item

        save_local_db()
        header = f"📱 <b>Numbers Assigned for {country_name}:</b>"
        return {"header": header, "numbers": num_data_list, "start_time": ts_now}, None

    except Exception as e:
        logger.error(f"Assignment core failure: {e}")
        return None, "💥 Allocation process fail!"

async def engine_process_signal(application, record, silent=False):
    async with otp_process_lock:
        r_num = str(record.get('num', record.get('number', '')))
        r_msg = record.get('message', record.get('content', ''))
        if not r_num or not r_msg: return False
        
        n_clean = normalize_num(r_num)
        m_hash = hashlib.md5(f"{n_clean}_{r_msg}".encode()).hexdigest()
        
        if m_hash in processed_ids:
            return False

        try:
            matched_assign = None
            
            for as_key, as_data in CACHE_ASSIGNMENTS.items():
                if isinstance(as_data, dict) and as_data.get('status') == 'assigned':
                    as_num = normalize_num(as_data.get('number', ''))
                    if as_num.endswith(n_clean[-8:]) if len(n_clean) >= 8 else as_num == n_clean:
                        matched_assign = as_data
                        break

            if matched_assign:
                u_id = matched_assign.get('user_id')
                region = matched_assign.get('country', 'Global')
                
                u_data = CACHE_USERS.get(str(u_id), {}) if isinstance(CACHE_USERS.get(str(u_id)), dict) else {}
                u_name = u_data.get('name', 'User')

                u_msgs = CACHE_PROCESSED.get(str(u_id), {}) if isinstance(CACHE_PROCESSED.get(str(u_id)), dict) else {}
                
                if m_hash not in u_msgs:
                    processed_ids.add(m_hash)
                    payout = await get_country_payout(region)
                    total = 0.0
                    
                    if not silent:
                        curr_bal = float(u_data.get('balance', 0.0))
                        curr_otp = int(u_data.get('otp_count', 0))
                        total = curr_bal + payout
                        
                        up_u = {'balance': total, 'otp_count': curr_otp + 1}
                        u_data.update(up_u)

                        if str(u_id) not in CACHE_PROCESSED or not isinstance(CACHE_PROCESSED[str(u_id)], dict):
                            CACHE_PROCESSED[str(u_id)] = {}
                        
                        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        CACHE_PROCESSED[str(u_id)][m_hash] = {'timestamp': now_str}
                        save_local_db()

                    otp_code = parse_otp_body(r_msg)
                    escaped_body = html.escape(r_msg)
                    
                    body = (
                        f"🎉 <b>OTP Received Successfully</b> 🎉\n\n"
                        f"📱 <b>Number:</b> <code>{r_num}</code>\n"
                        f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>\n"
                        f"💼 <b>Service:</b> <code>{record.get('cli','Unknown')}</code>\n"
                        f"🌍 <b>Country:</b> <code>{region}</code>\n"
                        f"✉️ <b>Message:</b> <code>{escaped_body}</code>\n\n"
                        f"📡 <b>Source:</b> LIVE\n\n"
                        f"👤 <b>User:</b> {u_name} ({u_id})"
                    )

                    kb = [[rich_btn("📋 Copy OTP", style="primary", copy_text=otp_code)]]

                    for gid in TARGET_GROUP_IDS:
                        try: await send_rich_message(application.bot, gid, body, kb)
                        except Exception as e: logger.error(f"Group forward failed: {e}")
                    
                    if not silent:
                        alert = body + f'\n\n💵 <b>Tk {payout:.2f}</b> added to your balance!\n💳 <b>Balance:</b> Tk {total:.2f}'
                        try: await send_rich_message(application.bot, u_id, alert, kb)
                        except Exception as e: logger.error(f"Private notify failed: {e}")
                    return True
            else:
                if silent:
                    processed_ids.add(m_hash)
                    otp_code = parse_otp_body(r_msg)
                    escaped_body = html.escape(r_msg)
                    body = (
                        f"🎉 <b>OTP Received Successfully</b> 🎉\n\n"
                        f"📱 <b>Number:</b> <code>{r_num}</code>\n"
                        f"🔑 <b>OTP Code:</b> <code>{otp_code}</code>\n"
                        f"💼 <b>Service:</b> <code>{record.get('cli','Unknown')}</code>\n"
                        f"✉️ <b>Message:</b> <code>{escaped_body}</code>\n\n"
                        f"📡 <b>Source:</b> LIVE\n\n"
                        f"👤 <b>User:</b> System Sync"
                    )
                    kb = [[rich_btn("Copy OTP", style="primary", copy_text=otp_code)]]
                    for gid in TARGET_GROUP_IDS:
                        try: await send_rich_message(application.bot, gid, body, kb)
                        except: pass
            return False
        except Exception as e:
            logger.error(f"Signal Routing Error: {e}")
            return False

# =========================================================================
# --- ROUTING & HANDLERS ENGINE ---
# =========================================================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    uid, name = user.id, user.full_name
    if user.username:
        name = f"@{user.username}"
    
    if await check_is_restricted(uid):
        await update.message.reply_text("🚫 <b>Access Restricted!</b> You are banned from using this bot.", parse_mode='HTML')
        return
    
    u_str = str(uid)
    if u_str not in CACHE_USERS or not isinstance(CACHE_USERS[u_str], dict):
        u_obj = {
            'name': name,
            'balance': 0.0,
            'otp_count': 0,
            'status': 'active',
            'joined_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        CACHE_USERS[u_str] = u_obj
        save_local_db()
    else:
        CACHE_USERS[u_str]['name'] = name
        save_local_db()

    context.user_data['state'] = None
    if uid in ADMIN_IDS:
        await update.message.reply_text("👑 <b>Admin Authorization established.</b> Control board active!", reply_markup=build_admin_main(uid), parse_mode='HTML')
    else:
        await update.message.reply_text(f"👋 <b>Welcome {name}! Session established.</b>", reply_markup=build_user_main(), parse_mode='HTML')

async def router_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    uid, data = query.from_user.id, query.data
    if await check_is_restricted(uid): return

    if data == "select_country_menu":
        counts = {}
        for b_id, b_val in CACHE_STOCK.items():
            if isinstance(b_val, dict) and b_val.get('country'):
                c = b_val.get('country')
                cnt = len(b_val.get('numbers', []))
                if cnt > 0:
                    counts[c] = counts.get(c, 0) + cnt

        if not counts: 
            try: await query.answer("⚠️ Selected region stock depleted.", show_alert=True)
            except: pass
        else:
            btns = [[rich_btn(f"🌍 Region: {c} ({cnt})", "primary", f"alloc_{c}")] for c, cnt in counts.items()]
            btns.append([rich_btn("🔙 Return", "danger", "exit_session")])
            await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, "🌍 <b>Select Region Terminal:</b>", btns)

    elif data.startswith("alloc_") or data == "change_num":
        region = data.replace("alloc_", "") if data.startswith("alloc_") else context.user_data.get('l_c')
        if not region: 
            try: await query.answer("⚠️ Error. Region select করুন আবার।", show_alert=True)
            except: pass
            return

        context.user_data['l_c'] = region
        batch_size = context.user_data.get('p_count', 3)
        res, err = await engine_assign_batch(uid, region, batch_size)
        if err:
            try: await query.answer(err, show_alert=True)
            except: pass
        else:
            msg_numbers = ""
            for n in res['numbers']:
                msg_numbers += f"📱 Number: <code>+{n['full']}</code>\n\n"
            
            kb = [[rich_btn("⏳ Waiting for OTP...", "primary", "none")]]
            no_code_btns = []
            for n in res['numbers']:
                btn = rich_btn(f"No Code: {n['short']}", style="primary", copy_text=n['short'])
                no_code_btns.append(btn)
            
            if batch_size == 10:
                for i in range(0, len(no_code_btns), 2):
                    kb.append(no_code_btns[i:i+2])
            else:
                for btn in no_code_btns:
                    kb.append([btn])
            
            kb.append([rich_btn("🔄 Refresh Stock", style="success", callback_data="change_num"), 
                       rich_btn("🔙 Back", style="danger", callback_data="exit_session")])
            
            text = f"<b>{res['header']}</b>\n📋 Click numbers to copy.\n\n{msg_numbers}"
            await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, text, kb)

    elif data == "exit_session":
        try: await query.message.delete()
        except: pass
        dash = build_admin_main(uid) if uid in ADMIN_IDS else build_user_main()
        await context.bot.send_message(chat_id=uid, text="🏁 Dashboard terminal ready.", reply_markup=dash)

    elif data.startswith("adm_del_") and not data.startswith("adm_del_yes_"):
        if uid not in ADMIN_IDS: return
        reg = data.replace("adm_del_", "")
        
        kb = [
            [rich_btn("✅ Yes, Delete", style="danger", callback_data=f"adm_del_yes_{reg}")],
            [rich_btn("❌ Cancel", style="primary", callback_data="exit_session")]
        ]
        await edit_rich_message(
            context.bot, 
            query.message.chat_id, 
            query.message.message_id, 
            f"⚠️ <b>Are you sure?</b>\n\nআপনি কি সত্যিই <b>{reg}</b> এর সমস্ত স্টক এবং অ্যাসাইনমেন্ট মুছে ফেলতে চান?", 
            kb
        )

    elif data.startswith("adm_del_yes_"):
        if uid not in ADMIN_IDS: return
        reg = data.replace("adm_del_yes_", "")
        
        deleted_count = 0
        to_del = [b_id for b_id, b_val in CACHE_STOCK.items() if isinstance(b_val, dict) and b_val.get('country') == reg]
        for batch_id in to_del:
            cnt = len(CACHE_STOCK[batch_id].get('numbers', []))
            deleted_count += cnt
            del CACHE_STOCK[batch_id]
                
        to_del_as = [as_key for as_key, as_val in CACHE_ASSIGNMENTS.items() if isinstance(as_val, dict) and as_val.get('country') == reg]
        for as_key in to_del_as:
            del CACHE_ASSIGNMENTS[as_key]

        save_local_db()
        await query.edit_message_text(f"🗑️ <b>Super Fast Deleted!</b>\n\nRegion: {reg}\nDeleted Numbers: {deleted_count}", parse_mode='HTML')

    elif data.startswith("adm_cc_"):
        if uid not in ADMIN_IDS: return
        target_country = data.replace("adm_cc_", "")
        context.user_data['target_country_cc'] = target_country
        context.user_data['state'] = 'ADM_SET_CC_VAL'
        await context.bot.send_message(chat_id=uid, text=f"⚙️ Enter digits to skip for <b>{target_country}</b> 'No Code' numbers:", parse_mode='HTML')

    elif data.startswith("adm_rate_"):
        if uid not in ADMIN_IDS: return
        target_country = data.replace("adm_rate_", "")
        context.user_data['target_country_rate'] = target_country
        context.user_data['state'] = 'ADM_SET_RATE_VAL'
        await context.bot.send_message(chat_id=uid, text=f"✍️ Enter custom OTP payout rate for <b>{target_country}</b> (e.g. 2.50):", parse_mode='HTML')

    elif data.startswith("tog_api_"):
        if uid not in ADMIN_IDS: return
        api_name = data.replace("tog_api_", "")
        key = f"api_status_{api_name}"
        current_status = await get_config_val(key, "1")
        new_status = "0" if current_status == "1" else "1"
        await set_config_val(key, new_status)
        await dispatch_panel_stats_inline(query.message, context, edit=True)

    elif data.startswith("adm_pay_acc_"):
        if uid not in ADMIN_IDS: return
        w_id = data.replace("adm_pay_acc_", "")
        if w_id in CACHE_WITHDRAWALS and isinstance(CACHE_WITHDRAWALS[w_id], dict):
            CACHE_WITHDRAWALS[w_id]['status'] = 'accepted'
            save_local_db()
            await query.edit_message_text(f"✅ Req {w_id} Authorized.")

    elif data.startswith("adm_pay_rej_"):
        if uid not in ADMIN_IDS: return
        w_id = data.replace("adm_pay_rej_", "")
        if w_id in CACHE_WITHDRAWALS and isinstance(CACHE_WITHDRAWALS[w_id], dict):
            w_data = CACHE_WITHDRAWALS[w_id]
            req_u_id = str(w_data.get('user_id'))
            req_amt = float(w_data.get('amount', 0.0))
            
            w_data['status'] = 'rejected'
            if req_u_id in CACHE_USERS and isinstance(CACHE_USERS[req_u_id], dict):
                curr_bal = float(CACHE_USERS[req_u_id].get('balance', 0.0)) + req_amt
                CACHE_USERS[req_u_id]['balance'] = curr_bal
            
            save_local_db()
            await query.edit_message_text(f"❌ Withdrawal {w_id} Rejected. Funds restored.")

    elif data.startswith("w_method_"):
        channel = data.replace("w_method_", "")
        context.user_data['w_method'] = channel
        limit = float(await get_config_val('min_withdraw', '1000'))
        context.user_data['state'] = 'IN_W_AMT'
        await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, f"🛒 You selected <b>{channel}</b>.\n💵 <b>Enter payout amount</b> (Minimum: Tk {limit}):", [])

    elif data == "adm_total_paid_show":
        if uid not in ADMIN_IDS: return
        limit_date = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d %H:%M:%S')
        try:
            paid_users = set()
            total_sum = 0.0
            
            for w_id, w_val in CACHE_WITHDRAWALS.items():
                if isinstance(w_val, dict) and w_val.get('status') == 'accepted' and w_val.get('timestamp', '') >= limit_date:
                    paid_users.add(w_val.get('user_id'))
                    total_sum += float(w_val.get('amount', 0.0))
                    
            text = f"💵 <b>Total Paid Stats (Last 6 Days)</b>\n\n👥 Total Users Paid: {len(paid_users)}\n💵 Total Paid Amount: Tk {total_sum:.2f}"
            await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, text, [[rich_btn("🔙 Back", style="primary", callback_data="exit_session")]])
        except Exception as e: logger.error(f"Stat failure: {e}")

    elif data == "adm_total_paid_clear":
        if uid not in ADMIN_IDS: return
        try:
            to_del = [w_id for w_id, w_val in CACHE_WITHDRAWALS.items() if isinstance(w_val, dict) and w_val.get('status') == 'accepted']
            for w_id in to_del:
                del CACHE_WITHDRAWALS[w_id]
            save_local_db()
            await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, "✅ Payout history successfully cleared.", [[rich_btn("🔙 Back", style="primary", callback_data="exit_session")]])
        except Exception as e: logger.error(f"Clear failure: {e}")

    elif data.startswith("vstock_"):
        country = data.replace("vstock_", "")
        await display_country_stock(update, context, country)

    elif data.startswith("dlstock_"):
        country = data.replace("dlstock_", "")
        await download_country_stock_file(update, context, country)

    elif data == "back_stock_hist":
        await dispatch_stock_history_menu(update, context, edit_message_id=query.message.message_id)

async def router_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text: return
    raw = msg.text.strip()
    uid = msg.from_user.id
    name = msg.from_user.full_name
    if msg.from_user.username:
        name = f"@{msg.from_user.username}"

    state = context.user_data.get('state')

    if await check_is_restricted(uid): return

    if raw == "⚡ Get Number 3":
        context.user_data['p_count'] = 3
        await dispatch_country_ui(update, context)
        return
    elif raw == "🔥 Get Number 10":
        context.user_data['p_count'] = 10
        await dispatch_country_ui(update, context)
        return
    elif raw == "💳 My Balance":
        u_val = CACHE_USERS.get(str(uid), {})
        u_bal = u_val.get('balance', 0.0) if isinstance(u_val, dict) else 0.0
        await send_rich_message(context.bot, uid, f"💳 <b>Wallet Balance:</b> <code>Tk {float(u_bal):.2f}</code>", [])
        return
    elif raw == "🏆 Leaderboard": 
        await dispatch_leaderboard(update)
        return
    elif raw == "📦 Stock History":
        await dispatch_stock_history_menu(update, context)
        return
    elif raw == "💵 Withdraw Funds":
        kb = [[rich_btn("Bkash", style="primary", callback_data="w_method_Bkash"),
                rich_btn("Nagad", style="success", callback_data="w_method_Nagad"),
                rich_btn("Rocket", style="danger", callback_data="w_method_Rocket")]]
        await send_rich_message(context.bot, uid, "🛒 <b>Select Payout Channel:</b>", kb)
        return

    if uid in ADMIN_IDS:
        if raw == "📥 Number Upload":
            await msg.reply_text("📥 <b>Inventory Hub:</b> Enter region label:"); context.user_data['state'] = 'ADM_UP_C'
            return
        elif raw == "🗑️ Number Delete": 
            await dispatch_wipe_ui(update, context)
            return 
        elif raw == "👥 User List":
            await admin_export_user_db(update, context)
            return
        elif raw == "📊 Panel Stats": 
            await dispatch_panel_stats_inline(msg, context, edit=False)
            return
        elif raw == "💸 Withdraw Requests": 
            await dispatch_payout_ui(update, context)
            return
        elif raw == "🧹 Clear All Stocks": 
            await admin_wipe_all_assignments(update)
            return
        elif raw == "💰 Total Paid":
            kb = [[rich_btn("Total Amount Paid", style="success", callback_data="adm_total_paid_show")],
                  [rich_btn("Clear Data Total Paid", style="danger", callback_data="adm_total_paid_clear")]]
            await send_rich_message(context.bot, uid, "💰 <b>Payout Statistics Terminal:</b>", kb)
            return
        elif raw == "📢 Broadcast":
            await msg.reply_text("📢 <b>Enter transmission payload:</b>"); context.user_data['state'] = 'ADM_BROAD'
            return
        elif raw == "🚫 Ban User":
            await msg.reply_text("🚫 <b>Enter target ID to ban:</b>"); context.user_data['state'] = 'ADM_BAN_U'
            return
        elif raw == "✅ Unban User":
            await msg.reply_text("✅ <b>Enter target ID to unban:</b>"); context.user_data['state'] = 'ADM_UNBAN_U'
            return
        elif raw == "⚙️ Set CC Limit":
            await dispatch_cc_limit_ui(update, context)
            return
        elif raw == "✍️ Country Rate Set":
            await dispatch_country_rate_ui(update, context)
            return
        elif raw == "📤 Upload User Data" and uid == SUPER_ADMIN_ID:
            await msg.reply_text("📤 <b>Upload User Data:</b> দয়া করে আপনার আগের ইউজার লিস্টের ফরম্যাটের মতো অথবা JSON ডাটা ব্যাকআপ ফাইলটি এখানে সেন্ড করুন।", parse_mode='HTML')
            context.user_data['state'] = 'ADM_UP_USER_DB'
            return

    if state == 'ADM_UP_C':
        context.user_data['temp_c'], context.user_data['state'] = raw, 'ADM_UP_F'
        await msg.reply_text(f"🌍 <b>Region set:</b> {raw}.\n📥 Now upload inventory .txt segment.", parse_mode='HTML')
        return
    elif state == 'ADM_BROAD':
        asyncio.create_task(run_background_broadcast(context, raw))
        await msg.reply_text("📢 <b>Audit Alert:</b> Background broadcast transmission started.")
        context.user_data['state'] = None
        return
    elif state == 'ADM_BAN_U':
        try:
            if raw in CACHE_USERS and isinstance(CACHE_USERS[raw], dict):
                CACHE_USERS[raw]['status'] = 'banned'
                save_local_db()
            await msg.reply_text(f"🚫 User {raw} restricted successfully.")
        except Exception as e:
            await msg.reply_text(f"Failed to ban: {e}")
        context.user_data['state'] = None
        return
    elif state == 'ADM_UNBAN_U':
        try:
            if raw in CACHE_USERS and isinstance(CACHE_USERS[raw], dict):
                CACHE_USERS[raw]['status'] = 'active'
                save_local_db()
            await msg.reply_text(f"✅ User {raw} restored successfully.")
        except Exception as e:
            await msg.reply_text(f"Failed to unban: {e}")
        context.user_data['state'] = None
        return
    elif state == 'ADM_SET_CC_VAL':
        try:
            limit_v = int(raw)
            target_reg = context.user_data.get('target_country_cc')
            CACHE_LIMITS[target_reg] = limit_v
            save_local_db()
            await msg.reply_text(f"⚙️ <b>Audit Result:</b> CC Skip Limit set to {limit_v} digits for {target_reg}.", parse_mode='HTML')
        except: await msg.reply_text("Numerical input required.")
        context.user_data['state'] = None
        return
    elif state == 'ADM_SET_RATE_VAL':
        try:
            rate_v = float(raw)
            target_reg = context.user_data.get('target_country_rate')
            CACHE_RATES[target_reg] = rate_v
            save_local_db()
            await msg.reply_text(f"✍️ <b>Audit Result:</b> Custom Rate set to Tk {rate_v:.2f} for {target_reg}.", parse_mode='HTML')
        except: await msg.reply_text("Numerical or float rate required.")
        context.user_data['state'] = None
        return

    if state == 'IN_W_AMT':
        try:
            amt = float(raw)
            limit = float(await get_config_val('min_withdraw', '1000'))
            if amt < limit:
                await msg.reply_text(f"❌ Amount is below minimum requirement of Tk {limit}.")
                context.user_data['state'] = None
                return
            
            u_val = CACHE_USERS.get(str(uid), {})
            bal = float(u_val.get('balance', 0.0)) if isinstance(u_val, dict) else 0.0
            if bal < amt:
                await msg.reply_text("❌ Security Error: Insufficient funds.")
                context.user_data['state'] = None
                return
            context.user_data['temp_w_amt'] = amt
            context.user_data['state'] = 'IN_W_INFO'
            method = context.user_data.get('w_method', 'Bkash')
            await msg.reply_text(f"📱 <b>Enter your {method} Account Number:</b>", parse_mode='HTML')
        except ValueError: 
            await msg.reply_text("Numerical value required.")
            context.user_data['state'] = None
        return
    elif state == 'IN_W_INFO':
        amt = context.user_data['temp_w_amt']
        method = context.user_data.get('w_method', 'Bkash')
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        u_str = str(uid)
        u_val = CACHE_USERS.get(u_str, {})
        bal = float(u_val.get('balance', 0.0)) if isinstance(u_val, dict) else 0.0
        
        if bal >= amt:
            new_ref_id = f"w_{int(datetime.now().timestamp())}"
            w_obj = {
                'user_id': uid,
                'user_name': name,
                'amount': amt,
                'info': raw,
                'method': method,
                'status': 'pending',
                'timestamp': now_str
            }
            CACHE_WITHDRAWALS[new_ref_id] = w_obj

            new_bal = bal - amt
            if isinstance(CACHE_USERS.get(u_str), dict):
                CACHE_USERS[u_str]['balance'] = new_bal
            
            save_local_db()
            await msg.reply_text(f"✅ Your withdraw request of Tk {amt:.2f} via {method} has been submitted successfully.")
        else: 
            await msg.reply_text("❌ Security Error: Insufficient funds.")
        context.user_data['state'] = None
        return

# =========================================================================
# --- EXPORT USER LIST TO TXT FILE ---
# =========================================================================
async def admin_export_user_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not CACHE_USERS:
            await update.effective_chat.send_message("⚠️ <b>User List Empty:</b> কোনো ইউজার রেজিস্টার্ড হয়নি।", parse_mode='HTML')
            return
            
        stream = StringIO()
        stream.write("👥 Registered Active User List (Banned Excluded)\n" + "="*50 + "\n\n")
        
        user_count = 0
        for u_id, u_val in CACHE_USERS.items():
            if isinstance(u_val, dict) and int(u_id) not in ADMIN_IDS:
                status = u_val.get('status', 'active')
                if status == 'banned': continue
                    
                name = u_val.get('name', 'N/A')
                balance = float(u_val.get('balance', 0.0))
                otp_cnt = u_val.get('otp_count', 0)
                joined = u_val.get('joined_at', 'N/A')
                
                stream.write(f"ID: {u_id} | Name: {name} | Balance: Tk {balance:.2f} | OTPs: {otp_cnt} | Status: {status} | Joined: {joined}\n")
                user_count += 1
            
        bio = BytesIO(stream.getvalue().encode('utf-8'))
        bio.name = f"active_user_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=bio, 
            caption=f"👥 <b>Total Active Users Exported:</b> {user_count} (Banned & Admins Excluded)",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"User list export failed: {e}")
        await update.effective_chat.send_message(f"❌ <b>Export Error:</b> ইউজার লিস্ট এক্সপোর্ট করতে সমস্যা হয়েছে: {e}", parse_mode='HTML')

# =========================================================================
# --- INTERACTIVE STOCK HISTORY MANAGERS ---
# =========================================================================
async def dispatch_stock_history_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit_message_id=None):
    uid = update.callback_query.from_user.id if update.callback_query else update.effective_user.id
    chat_id = update.callback_query.message.chat_id if update.callback_query else update.message.chat_id
        
    counts = {}
    for as_key, as_val in CACHE_ASSIGNMENTS.items():
        if isinstance(as_val, dict) and as_val.get('user_id') == uid and as_val.get('status') == 'assigned':
            country = as_val.get('country', 'Global')
            counts[country] = counts.get(country, 0) + 1

    if not counts:
        text = "📦 <b>Your Active Stock History:</b>\n\n⚠️ You do not have any active numbers in stock right now."
        kb = [[rich_btn("🔙 Close Menu", style="danger", callback_data="exit_session")]]
    else:
        text = "📦 <b>Your Active Stock History:</b>\n\nSelect a country below to view or export your active stocked numbers:"
        kb = []
        for country, count in counts.items():
            kb.append([rich_btn(f"🌍 {country} ({count} numbers)", style="primary", callback_data=f"vstock_{country}")])
        kb.append([rich_btn("🔙 Close Menu", style="danger", callback_data="exit_session")])
        
    if edit_message_id:
        await edit_rich_message(context.bot, chat_id, edit_message_id, text, kb)
    else:
        await send_rich_message(context.bot, uid, text, kb)

async def display_country_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, country: str):
    query = update.callback_query
    uid = query.from_user.id
    
    numbers_list = []
    for as_key, as_val in CACHE_ASSIGNMENTS.items():
        if isinstance(as_val, dict) and as_val.get('user_id') == uid and as_val.get('country') == country and as_val.get('status') == 'assigned':
            numbers_list.append(as_val.get('number'))

    if not numbers_list:
        text = f"⚠️ No active stock found for <b>{country}</b>."
        kb = [[rich_btn("🔙 Back to Stock History", style="danger", callback_data="back_stock_hist")]]
        await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, text, kb)
        return
        
    count = len(numbers_list)
    display_text = f"📦 <b>Active stocked numbers for {country} ({count} nos):</b>\n\n"
    for num in numbers_list[:30]:
        clean = normalize_num(num)
        display_text += f"• <code>+{clean}</code>\n"
        
    if count > 30:
        display_text += f"\n<i>...and {count - 30} more numbers. Click 'Download List' to export all numbers as .txt file!</i>"
        
    kb = [
        [rich_btn("📥 Download .txt List", style="success", callback_data=f"dlstock_{country}")],
        [rich_btn("🔙 Back to Stock History", style="primary", callback_data="back_stock_hist")]
    ]
    await edit_rich_message(context.bot, query.message.chat_id, query.message.message_id, display_text, kb)

async def download_country_stock_file(update: Update, context: ContextTypes.DEFAULT_TYPE, country: str):
    query = update.callback_query
    uid = query.from_user.id
    
    numbers_list = []
    for as_key, as_val in CACHE_ASSIGNMENTS.items():
        if isinstance(as_val, dict) and as_val.get('user_id') == uid and as_val.get('country') == country and as_val.get('status') == 'assigned':
            numbers_list.append(as_val.get('number'))

    if not numbers_list:
        try: await query.answer("⚠️ No active stock found to export.", show_alert=True)
        except: pass
        return
        
    try: await query.answer("Compiling export stream...")
    except: pass
    
    stream = StringIO()
    stream.write(f"📦 Active Stock list for country: {country}\n")
    stream.write(f"Total synced: {len(numbers_list)}\n")
    stream.write("="*40 + "\n\n")
    for num in numbers_list:
        clean = normalize_num(num)
        stream.write(f"+{clean}\n")
        
    bio = BytesIO(stream.getvalue().encode('utf-8'))
    bio.name = f"{country}_active_stock_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    try:
        await context.bot.send_document(chat_id=uid, document=bio, caption=f"📄 Complete list of active numbers for <b>{country}</b> ({len(numbers_list)} numbers).")
    except Exception as e:
        logger.error(f"Failed to transmit file: {e}")
        await context.bot.send_message(chat_id=uid, text="❌ Export process failed. Please try again.")

# =========================================================================
# --- ADMINISTRATIVE CONTROL DISPATCHERS ---
# =========================================================================
async def run_background_broadcast(context, payload):
    for u_id in list(CACHE_USERS.keys()):
        try: 
            await send_rich_message(context.bot, int(u_id), f'📢 <b>Official Notice:</b>\n\n{payload}', [])
            await asyncio.sleep(0.035) 
        except: pass

async def dispatch_panel_stats_inline(message, context, edit=False):
    text = "📊 <b>Panel Control Stats</b>\n\nনিচের বাটনগুলো ক্লিক করে যেকোনো এপিআই সোর্স চালু বা বন্ধ করতে পারবেন।"
    kb = []
    for src in API_SOURCES:
        status_val = await get_config_val(f"api_status_{src['name']}", "1")
        indicator = "🟢 ON" if status_val == "1" else "🔴 OFF"
        kb.append([rich_btn(f"{src['name']} Panel | {indicator}", "primary", f"tog_api_{src['name']}")])
    kb.append([rich_btn("🔙 Close Menu", "danger", "exit_session")])
    
    if edit:
        await edit_rich_message(context.bot, message.chat_id, message.message_id, text, kb)
    else:
        await send_rich_message(context.bot, message.chat_id, text, kb)

async def dispatch_country_ui(update, context):
    counts = {}
    for b_id, b_val in CACHE_STOCK.items():
        if isinstance(b_val, dict) and b_val.get('country'):
            c = b_val.get('country')
            cnt = len(b_val.get('numbers', []))
            if cnt > 0:
                counts[c] = counts.get(c, 0) + cnt

    if counts:
        btns = [[rich_btn(f"🌍 Region: {c} ({cnt})", "primary", f"alloc_{c}")] for c, cnt in counts.items()]
        await send_rich_message(context.bot, update.message.chat_id, "🌍 <b>Select Region Terminal:</b>", btns, parse_mode='HTML')
    else: 
        await update.message.reply_text("⚠️ Inventory empty.")

async def dispatch_payout_ui(update, context):
    pending_found = False
    for w_id, w_val in CACHE_WITHDRAWALS.items():
        if isinstance(w_val, dict) and w_val.get('status') == 'pending':
            pending_found = True
            u_id = w_val.get('user_id')
            
            u_info = CACHE_USERS.get(str(u_id), {})
            u_name = w_val.get('user_name') or (u_info.get('name') if isinstance(u_info, dict) else None) or "Unknown User"
            
            kb = [
                [rich_btn("Copy Payment Details", "primary", copy_text=str(w_val.get('info')))],
                [rich_btn("Authorize", "success", f"adm_pay_acc_{w_id}"), 
                 rich_btn("Reject", "danger", f"adm_pay_rej_{w_id}")]
            ]
            
            msg_text = (
                f"💸 <b>Withdraw Request</b>\n"
                f"🆔 Req ID: <code>{w_id}</code>\n"
                f"👤 Name: <b>{html.escape(u_name)}</b>\n"
                f"🔢 UID: <code>{u_id}</code>\n"
                f"🛒 Method: {w_val.get('method')}\n"
                f"💵 Amount: Tk {w_val.get('amount')}\n"
                f"📱 Acc: <code>{w_val.get('info')}</code>"
            )
            await send_rich_message(context.bot, update.message.chat_id, msg_text, kb, parse_mode='HTML')
            
    if not pending_found:
        await update.message.reply_text("🏁 Withdraw queue empty.")

async def dispatch_wipe_ui(update, context):
    countries = set(b_val.get('country') for b_val in CACHE_STOCK.values() if isinstance(b_val, dict) and b_val.get('country'))
    if countries:
        btns = [[rich_btn(f"Purge: {c} Stock", "danger", f"adm_del_{c}")] for c in countries]
        await send_rich_message(context.bot, update.message.chat_id, "🚨 <b>Danger Zone: Purge stock level:</b>", btns, parse_mode='HTML')
    else: await update.message.reply_text("⚠️ Inventory table empty.")

async def dispatch_cc_limit_ui(update, context):
    countries = set(b_val.get('country') for b_val in CACHE_STOCK.values() if isinstance(b_val, dict) and b_val.get('country'))
    if countries:
        btns = [[rich_btn(f"⚙️ CC Limit: {c}", "primary", f"adm_cc_{c}")] for c in countries]
        await send_rich_message(context.bot, update.message.chat_id, "⚙️ <b>Select Country to set CC limit:</b>", btns, parse_mode='HTML')
    else: await update.message.reply_text("⚠️ No uploaded numbers found.")

async def dispatch_country_rate_ui(update, context):
    countries = set(b_val.get('country') for b_val in CACHE_STOCK.values() if isinstance(b_val, dict) and b_val.get('country'))
    if countries:
        btns = [[rich_btn(f"✍️ Rate: {c}", "primary", f"adm_rate_{c}")] for c in countries]
        await send_rich_message(context.bot, update.message.chat_id, "✍️ <b>Select Country to set custom payout rate:</b>", btns, parse_mode='HTML')
    else: await update.message.reply_text("⚠️ No stocked countries found.")

async def admin_wipe_all_assignments(update):
    CACHE_STOCK.clear()
    CACHE_ASSIGNMENTS.clear()
    save_local_db()

    await update.message.reply_text("🧹 <b>Audit Reset:</b> All stocks and user assignments cleared successfully!", parse_mode='HTML')

async def dispatch_leaderboard(update):
    midnight_str = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
    
    scores = []
    for u_id, p_msgs in CACHE_PROCESSED.items():
        if isinstance(p_msgs, dict):
            count = 0
            for m_hash, m_data in p_msgs.items():
                if isinstance(m_data, dict) and m_data.get('timestamp', '') >= midnight_str:
                    count += 1
            if count > 0:
                u_val = CACHE_USERS.get(str(u_id), {})
                u_name = u_val.get('name', 'User') if isinstance(u_val, dict) else 'User'
                scores.append((u_name, count))
            
    scores.sort(key=lambda x: x[1], reverse=True)
    
    if scores:
        out = f"🏆 <b>Daily Ranking (Since 12 AM Today):</b>\n\n"
        for i, (name, score) in enumerate(scores[:10], 1):
            cl_name = name[:-3] if len(name) > 3 else "User"
            out += f"{i}. {cl_name}... - OTP Success: {score}\n"
        await update.message.reply_text(out, parse_mode='HTML')
    else: 
        await update.message.reply_text("⏱️ Terminal Data: No activity yet.")

async def check_is_restricted(uid):
    u_val = CACHE_USERS.get(str(uid), {})
    status = u_val.get('status') if isinstance(u_val, dict) else None
    return status == 'banned'

# =========================================================================
# --- FILE UPLOADS (SUPPORTING BOTH .TXT USER LIST AND .JSON BACKUP) ---
# =========================================================================
async def handler_file_up(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: return
    state = context.user_data.get('state')
    
    if state == 'ADM_UP_USER_DB' and uid == SUPER_ADMIN_ID:
        try:
            doc = await update.message.document.get_file()
            path = f"tmp_user_db_{uid}.txt"
            await doc.download_to_drive(path)
            
            with open(path, "r", encoding='utf-8') as f:
                content = f.read()
                
            if "ID:" in content and "Balance:" in content:
                global CACHE_USERS
                lines = content.splitlines()
                imported_count = 0
                for line in lines:
                    if "ID:" in line and "Balance:" in line:
                        try:
                            parts = line.split("|")
                            u_id_str = parts[0].replace("ID:", "").strip()
                            name_str = parts[1].replace("Name:", "").strip()
                            bal_str = parts[2].replace("Balance: Tk", "").strip()
                            otp_str = parts[3].replace("OTPs:", "").strip()
                            status_str = parts[4].replace("Status:", "").strip()
                            joined_str = parts[5].replace("Joined:", "").strip()
                            
                            CACHE_USERS[u_id_str] = {
                                "name": name_str,
                                "balance": float(bal_str),
                                "otp_count": int(otp_str),
                                "status": status_str,
                                "joined_at": joined_str
                            }
                            imported_count += 1
                        except Exception:
                            continue
                save_local_db()
                await update.message.reply_text(f"✅ <b>Successfully Parsed & Imported {imported_count} Users from Text List!</b>", parse_mode='HTML')
            else:
                try:
                    uploaded_data = json.loads(content)
                    if isinstance(uploaded_data, dict) and "users" in uploaded_data:
                        global CACHE_ASSIGNMENTS, CACHE_WITHDRAWALS
                        CACHE_USERS = uploaded_data.get("users", CACHE_USERS)
                        if "assignments" in uploaded_data:
                            CACHE_ASSIGNMENTS = uploaded_data.get("assignments", CACHE_ASSIGNMENTS)
                        if "withdrawals" in uploaded_data:
                            CACHE_WITHDRAWALS = uploaded_data.get("withdrawals", CACHE_WITHDRAWALS)
                        save_local_db()
                        await update.message.reply_text("✅ <b>User Database JSON Successfully Synced!</b>", parse_mode='HTML')
                    else:
                        await update.message.reply_text("❌ <b>Error:</b> সঠিক ফরম্যাটের ফাইল দিন।", parse_mode='HTML')
                except Exception:
                    await update.message.reply_text("❌ <b>Error:</b> ফাইল পার্স করতে সমস্যা হয়েছে।", parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ Upload Error: {e}")
        finally:
            if 'path' in locals() and os.path.exists(path): 
                os.remove(path)
            context.user_data['state'] = None
            return

    if state != 'ADM_UP_F': return
    
    try:
        reg = context.user_data.get('temp_c', 'Unknown')
        doc = await update.message.document.get_file()
        path = f"tmp_sync_{uid}.txt"
        await doc.download_to_drive(path)
        
        with open(path, "r", encoding='utf-8') as f:
            raw_numbers = [line.strip() for line in f if line.strip()]

        if not raw_numbers:
            await update.message.reply_text("⚠️ File is empty!")
            return

        batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uid)[:4]}"
        
        batch_data = {
            "country": reg,
            "numbers": raw_numbers,
            "uploaded_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        CACHE_STOCK[batch_id] = batch_data

        await update.message.reply_text(
            f"⚡ <b>1-Second Instant Upload Success (RAM Only)!</b>\n"
            f"📥 <b>Region:</b> {reg}\n"
            f"🔢 <b>Total Numbers:</b> <code>{len(raw_numbers)}</code>\n"
            f"🆔 <b>Batch ID:</b> <code>{batch_id}</code>", 
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Instant Upload Error: {e}")
        await update.message.reply_text(f"❌ Upload Error: {e}")
    finally:
        if 'path' in locals() and os.path.exists(path): 
            os.remove(path)
        context.user_data['state'] = None

# =========================================================================
# --- LIFECYCLE MANAGEMENT ---
# =========================================================================
async def poll_single_source(application, api):
    logger.info(f"High-Speed Engine: Polling thread started for {api['name']}")
    while True:
        try:
            status_val = await get_config_val(f"api_status_{api['name']}", "1")
            if status_val == "0":
                await asyncio.sleep(4.0)
                continue
                
            res = await http_client.get(api["url"], params={"token": api["token"], "limit": 30})
            if res.status_code == 200:
                resp_json = res.json()
                data = resp_json.get("records", resp_json.get("data", [])) if isinstance(resp_json, dict) else resp_json
                if not isinstance(data, list): data = [data]
                
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        item = {'cli': item[0], 'num': item[1], 'message': item[2]}
                    if not isinstance(item, dict): continue
                    
                    r_num = str(item.get('num', item.get('number', '')))
                    r_msg = item.get('message', item.get('content', ''))
                    
                    uid_hash = hashlib.md5(f"{r_num}_{r_msg}".encode()).hexdigest()
                    if uid_hash not in processed_ids:
                        await engine_process_signal(application, item, silent=False)
                        processed_ids.add(uid_hash)
                        if len(processed_ids) > 100000: processed_ids.clear()
        except Exception as e:
            logger.debug(f"Source {api['name']} Connection Skip: {e}")
        await asyncio.sleep(1.5)

async def startup_sync(application):
    for api in API_SOURCES:
        try:
            status_val = await get_config_val(f"api_status_{api['name']}", "1")
            if status_val == "0": continue
            
            res = await http_client.get(api["url"], params={"token": api["token"], "limit": 5})
            if res.status_code == 200:
                resp_json = res.json()
                data = resp_json.get("records", resp_json.get("data", [])) if isinstance(resp_json, dict) else resp_json
                if not isinstance(data, list): data = [data]
                for item in reversed(data):
                    if isinstance(item, list) and len(item) >= 3:
                        item = {'cli': item[0], 'num': item[1], 'message': item[2]}
                    if not isinstance(item, dict): continue
                    
                    r_num = str(item.get('num', item.get('number', '')))
                    r_msg = item.get('message', item.get('content', ''))
                    
                    uid_hash = hashlib.md5(f"{r_num}_{r_msg}".encode()).hexdigest()
                    if uid_hash not in processed_ids:
                        await engine_process_signal(application, item, silent=True)
                        processed_ids.add(uid_hash)
        except Exception: pass

async def app_post_init(app):
    await startup_sync(app)
    for api in API_SOURCES:
        asyncio.create_task(poll_single_source(app, api))

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception occurred during live update cycle:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ <b>System Notification:</b> An unexpected request error was logged. Please request again.",
                parse_mode='HTML'
            )
        except Exception: pass

if __name__ == '__main__':
    try:
        instance = ApplicationBuilder().token(TOKEN).post_init(app_post_init).build()
        instance.add_handler(CommandHandler("start", handle_start))
        instance.add_handler(CallbackQueryHandler(router_callbacks))
        instance.add_handler(MessageHandler(filters.Document.ALL, handler_file_up))
        instance.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), router_text))
        instance.add_error_handler(error_handler)
        
        logger.info("Terminal tactical build stabilized with Local JSON Storage & Super Fast Speed.")
        instance.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.critical(f"Panic Shutdown: {e}")
