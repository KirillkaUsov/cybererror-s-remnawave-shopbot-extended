import sqlite3
from datetime import datetime, timezone, timedelta
import logging
from pathlib import Path
import json
import re
import time
from typing import Any

logger = logging.getLogger(__name__)


import os
if os.path.exists("/app/project/users.db"):

    DB_FILE = Path("/app/project/users.db")
elif os.path.exists("users-20251005-173430.db"):

    DB_FILE = Path("users-20251005-173430.db")
elif os.path.exists("users.db"):

    DB_FILE = Path("users.db")
else:

    DB_FILE = Path("users.db")


# ===== GET_MSK_TIME =====
def get_msk_time() -> datetime:
    return datetime.now(timezone(timedelta(hours=3)))
# ========================


# ===== _NOW_STR =====
def _now_str() -> str:
    return get_msk_time().strftime("%Y-%m-%d %H:%M:%S")
# ======================


# ===== _TO_DATETIME_STR =====
def _to_datetime_str(ts_ms: int | None) -> str | None:
    if ts_ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(get_msk_time().tzinfo)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
# ============================


# ===== _NORMALIZE_EMAIL =====
def _normalize_email(value: str | None) -> str | None:
    if value is None: return None
    cleaned = value.strip().lower(); return cleaned or None
# ============================


# ===== _NORMALIZE_KEY_ROW =====
def _normalize_key_row(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None: return None
    data = dict(row)
    email = _normalize_email(data.get("email") or data.get("key_email"))
    if email: data["email"] = email; data["key_email"] = email
    rem_uuid = data.get("remnawave_user_uuid") or data.get("xui_client_uuid")
    if rem_uuid: data["remnawave_user_uuid"] = rem_uuid; data["xui_client_uuid"] = rem_uuid
    expire_value = data.get("expire_at") or data.get("expiry_date")
    if expire_value:
        expire_str = expire_value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(expire_value, datetime) else str(expire_value)
        data["expire_at"] = expire_str
        data["expiry_date"] = expire_str
    created_value = data.get("created_at") or data.get("created_date")
    if created_value:
        created_str = created_value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(created_value, datetime) else str(created_value)
        data["created_at"] = created_str
        data["created_date"] = created_str
    subscription_url = data.get("subscription_url") or data.get("connection_string")
    if subscription_url: data["subscription_url"] = subscription_url; data.setdefault("connection_string", subscription_url)
    return data
# ==============================


# ===== _GET_TABLE_COLUMNS =====
def _get_table_columns(cursor: sqlite3.Cursor, table: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table})"); return {row[1] for row in cursor.fetchall()}
# ==============================


# ===== _ENSURE_TABLE_COLUMN =====
def _ensure_table_column(cursor: sqlite3.Cursor, table: str, column: str, definition: str) -> None:
    columns = _get_table_columns(cursor, table)
    if column not in columns: cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
# ================================


# ===== _ENSURE_UNIQUE_INDEX =====
def _ensure_unique_index(cursor: sqlite3.Cursor, name: str, table: str, column: str) -> None:
    cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table}({column})")
# ================================


# ===== _ENSURE_INDEX =====
def _ensure_index(cursor: sqlite3.Cursor, name: str, table: str, column: str) -> None:
    cursor.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({column})")
# ===========================


# ===== NORMALIZE_HOST_NAME =====
def normalize_host_name(name: str | None) -> str:
    s = (name or "").strip()
    for ch in ("\u00A0", "\u200B", "\u200C", "\u200D", "\uFEFF"): s = s.replace(ch, "")
    return s
# ===============================


# ===== GET_DB_CONNECTION =====
def get_db_connection():
    conn = sqlite3.connect(DB_FILE, timeout=30.0)
    wal_enabled = False
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_settings WHERE key='enable_wal_mode'")
        row = cursor.fetchone()
        if row and row[0] == '1':
            wal_enabled = True
    except Exception:
        pass
    if wal_enabled:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    else:
        conn.execute("PRAGMA journal_mode=DELETE")
    return conn
# ==============================





class DbExecResult:
    def __init__(self, cursor: sqlite3.Cursor):
        self.lastrowid = cursor.lastrowid; self.rowcount = cursor.rowcount

# ===== _EXEC =====
def _exec(sql: str, params: tuple | list = (), error_msg: str = "", commit: bool = True) -> DbExecResult | None:
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if commit: conn.commit()
            return DbExecResult(cursor)
    except sqlite3.Error as e:
        if error_msg: logging.error(f"{error_msg}: {e}")
        return None
# =================


# ===== _FETCH_ROW =====
def _fetch_row(sql: str, params: tuple | list = (), error_msg: str = "") -> dict | None:
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
    except sqlite3.Error as e:
        if error_msg: logging.error(f"{error_msg}: {e}")
        return None
# ======================


# ===== _FETCH_LIST =====
def _fetch_list(sql: str, params: tuple | list = (), error_msg: str = "") -> list[dict]:
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        if error_msg: logging.error(f"{error_msg}: {e}")
        return []
# =======================


# ===== _FETCH_VAL =====
def _fetch_val(sql: str, params: tuple | list = (), default: Any = None, error_msg: str = "") -> Any:
    row = _fetch_row(sql, params, error_msg)
    return list(row.values())[0] if row else default
# ======================

# ===== УНИВЕРСАЛЬНЫЕ ХЕЛПЕРЫ DRY =====

def _check_rowcount(cursor, entity_name: str, context: str = "") -> bool:
    if cursor and cursor.rowcount == 0:
        msg = f"{context}: {entity_name} не найден" if context else f"{entity_name} не найден"
        logging.warning(msg)
        return False
    return cursor is not None

def _exec_with_check(sql: str, params: tuple | list, entity_name: str, error_msg: str = "", context: str = "") -> bool:
    row = _fetch_row(f"SELECT 1 FROM {entity_name.split()[0] if ' ' in entity_name else entity_name}", params[:1] if params else (), "")
    if not row:
        if context: logging.warning(f"{context}: объект не найден")
        return False
    cursor = _exec(sql, params, error_msg)
    return cursor is not None

def _get_count_stat(query: str, default=0) -> int:
    r = _fetch_row(query, (), "")
    return int(r["c"]) if r and "c" in r else (int(r["s"]) if r and "s" in r else default)

# ========================


# ===== INITIALIZE_DB =====
def initialize_db():
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    username_manually_set BOOLEAN DEFAULT 0,
                    total_spent REAL DEFAULT 0,
                    total_months INTEGER DEFAULT 0,
                    trial_used BOOLEAN DEFAULT 0,
                    agreed_to_terms BOOLEAN DEFAULT 0,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_banned BOOLEAN DEFAULT 0,
                    balance REAL DEFAULT 0,
                    referred_by INTEGER,
                    referral_balance REAL DEFAULT 0,
                    referral_balance_all REAL DEFAULT 0,
                    referral_start_bonus_received BOOLEAN DEFAULT 0,
                    is_pinned BOOLEAN DEFAULT 0,
                    seller_active INTEGER DEFAULT 0,
                    app_theme TEXT DEFAULT 'violet',
                    email_verified INTEGER DEFAULT 0,
                    auth_token TEXT,
                    auth_email TEXT,
                    auth_pass TEXT
                )
            ''')

            # Связи «кто кого привёл», перенесённые из старого бота. Лежат
            # отдельно от users, потому что приглашённый может дойти до нового
            # бота через месяц — а связь должна дождаться его, а не пропасть.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referral_imports (
                    telegram_id INTEGER PRIMARY KEY,
                    referrer_id INTEGER NOT NULL,
                    source TEXT DEFAULT 'old_bot',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied_at TIMESTAMP
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_referral_imports_ref ON referral_imports(referrer_id)")

            # Бонус, который некому отдать: пригласивший ещё не заходил в
            # новый бот, строки в users у него нет. Раньше такие начисления
            # просто исчезали — add_to_balance возвращает False, и весь блок
            # начисления пропускался.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS referral_pending_bonuses (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    source_user_id INTEGER,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMP
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_referral_pending_unpaid "
                "ON referral_pending_bonuses(referrer_id, paid_at)")

            # История рассылок. Раньше итог существовал только в одном
            # сообщении админу и терялся сразу после прочтения.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS broadcasts (
                    broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    finished_at TIMESTAMP,
                    admin_id INTEGER,
                    admin_name TEXT,
                    preview TEXT,
                    has_media INTEGER DEFAULT 0,
                    button_text TEXT,
                    button_url TEXT,
                    total INTEGER DEFAULT 0,
                    sent INTEGER DEFAULT 0,
                    in_app INTEGER DEFAULT 0,
                    failed INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'running'
                )
            ''')

            # Ящик уведомлений внутри кабинета. Нужен тем, у кого Telegram нет
            # вовсе: они заходят только через сайт, и рассылка до них раньше не
            # доходила — их считали ошибкой доставки.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    broadcast_id INTEGER,
                    title TEXT,
                    body TEXT,
                    url TEXT,
                    url_text TEXT,
                    media_url TEXT,
                    media_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP
                )
            ''')
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_user "
                "ON user_notifications(user_id, read_at, created_at)")

            # Баланс, перенесённый из старого бота. Ждёт человека так же, как
            # реферальные связи: большинство владельцев до нового бота ещё не
            # дошли. Хранится отдельно от users.balance, иначе повторный запуск
            # переноса начислил бы деньги второй раз.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS balance_imports (
                    telegram_id INTEGER PRIMARY KEY,
                    amount REAL NOT NULL,
                    source TEXT DEFAULT 'old_bot',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    applied_at TIMESTAMP
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS pending_transactions (
                    payment_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    amount_rub REAL,
                    metadata TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vpn_keys (
                    key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    host_name TEXT,
                    squad_uuid TEXT,
                    remnawave_user_uuid TEXT,
                    short_uuid TEXT,
                    email TEXT UNIQUE,
                    key_email TEXT UNIQUE,
                    subscription_url TEXT,
                    expire_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    traffic_limit_bytes INTEGER,
                    traffic_limit_strategy TEXT DEFAULT 'NO_RESET',
                    tag TEXT,
                    description TEXT,
                    comment_key TEXT,
                    is_pinned BOOLEAN DEFAULT 0
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transactions (
                    username TEXT,
                    transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_id TEXT UNIQUE NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    amount_rub REAL NOT NULL,
                    amount_currency REAL,
                    currency_name TEXT,
                    payment_method TEXT,
                    metadata TEXT,
                    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Инициализация дефолтных настроек
            cursor.execute('''
                INSERT OR IGNORE INTO bot_settings (key, value) 
                VALUES (?, ?)
            ''', ('pay_info_comment', json.dumps({"id": 1, "username": 1, "first_name": 1, "host_name": 1})))
            
            cursor.execute('''
                INSERT OR IGNORE INTO bot_settings (key, value) 
                VALUES (?, ?)
            ''', ('skip_email', '0'))
            
            cursor.execute('''
                INSERT OR IGNORE INTO bot_settings (key, value) 
                VALUES (?, ?)
            ''', ('enable_wal_mode', '0'))

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS other (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Инициализация записи для рассылки
            _ensure_default_values(cursor, "other", {
                "newsletter": json.dumps({}),
                "sg_promt": "",
                "theme_newsletter": json.dumps({}),
                "auto_start_bot": "0"
            })

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS button_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    menu_type TEXT NOT NULL,
                    button_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    callback_data TEXT,
                    url TEXT,
                    row_position INTEGER DEFAULT 0,
                    column_position INTEGER DEFAULT 0,
                    button_width INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(menu_type, button_id)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS xui_hosts(
                    host_name TEXT PRIMARY KEY,
                    squad_uuid TEXT UNIQUE,
                    description TEXT,
                    default_traffic_limit_bytes INTEGER,
                    default_traffic_strategy TEXT DEFAULT 'NO_RESET',
                    host_url TEXT,
                    host_username TEXT,
                    host_pass TEXT,
                    host_inbound_id INTEGER,
                    subscription_url TEXT,
                    ssh_host TEXT,
                    ssh_port INTEGER,
                    ssh_user TEXT,
                    ssh_password TEXT,
                    ssh_key_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    metadata TEXT,
                    see INTEGER DEFAULT 1
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_name TEXT,
                    squad_uuid TEXT,
                    plan_name TEXT NOT NULL,
                    months INTEGER,
                    duration_days INTEGER,
                    price REAL NOT NULL,
                    traffic_limit_bytes INTEGER,
                    traffic_limit_strategy TEXT DEFAULT 'NO_RESET',
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    metadata TEXT,
                    hwid_limit INTEGER DEFAULT 0,
                    traffic_limit_gb INTEGER DEFAULT 0,
                    FOREIGN KEY (host_name) REFERENCES xui_hosts (host_name)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS support_tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT "open",
                    subject TEXT,
                    forum_chat_id TEXT,
                    message_thread_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS support_messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    sender TEXT NOT NULL,
                    content TEXT NOT NULL,
                    media TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (ticket_id) REFERENCES support_tickets (ticket_id)
                )
            ''')

            _ensure_index(cursor, "idx_support_tickets_status", "support_tickets", "status")
            _ensure_index(cursor, "idx_support_tickets_thread", "support_tickets", "forum_chat_id, message_thread_id")
            _ensure_index(cursor, "idx_support_messages_ticket_id", "support_messages", "ticket_id")
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS seller_users (
                    id_seller INTEGER PRIMARY KEY AUTOINCREMENT,
                    seller_sale REAL DEFAULT 0,
                    seller_ref REAL DEFAULT 0,
                    seller_uuid TEXT DEFAULT '0',
                    user_id INTEGER UNIQUE
                )
            ''')
            _ensure_unique_index(cursor, "idx_seller_users_user_id", "seller_users", "user_id")

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_thread ON support_tickets(forum_chat_id, message_thread_id)")
            except Exception:
                pass
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS host_speedtests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host_name TEXT NOT NULL,
                    method TEXT NOT NULL,
                    ping_ms REAL,
                    jitter_ms REAL,
                    download_mbps REAL,
                    upload_mbps REAL,
                    server_name TEXT,
                    server_id TEXT,
                    ok INTEGER NOT NULL DEFAULT 1,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_host_speedtests_host_time ON host_speedtests(host_name, created_at DESC)")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS resource_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,                -- 'local' | 'host' | 'target'
                    object_name TEXT NOT NULL,          -- 'panel' | host_name | target_name
                    cpu_percent REAL,
                    mem_percent REAL,
                    disk_percent REAL,
                    load1 REAL,
                    net_bytes_sent INTEGER,
                    net_bytes_recv INTEGER,
                    raw_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_metrics_scope_time ON resource_metrics(scope, object_name, created_at DESC)")

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS speedtest_ssh_targets (
                    target_name TEXT PRIMARY KEY,
                    ssh_host TEXT NOT NULL,
                    ssh_port INTEGER DEFAULT 22,
                    ssh_user TEXT,
                    ssh_password TEXT, 
                    ssh_key_path TEXT,
                    description TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    metadata TEXT
                )
            ''')
            default_settings = {
                "panel_login": "admin",
                "panel_password": "admin",
                "about_text": None,
                "terms_url": None,
                "privacy_url": None,
                "support_user": None,
                "support_text": None,
                # Общий рубильник поддержки и часы приёма. Держать открытым
                # круглосуточно окно, за которым никого нет, хуже, чем честно
                # сказать, когда придёт ответ.
                "support_enabled": "true",
                "support_schedule_enabled": "false",
                "support_schedule_start": "10:00",
                "support_schedule_end": "23:00",
                "channel_url": None,
                "force_subscription": "true",
                # Подписка на канал ради бесплатных дней, а не ради входа:
                # на пороге такое требование отпугивает, перед подарком — нет.
                "trial_requires_subscription": "false",
                "receipt_email": "example@example.com",
                "telegram_bot_token": None,
                "telegram_bot_username": None,
                "trial_enabled": "true",
                "trial_duration_days": "3",
                "trial_internal_squad_uuid": None,
                "enable_referrals": "true",
                "referral_percentage": "10",
                "referral_discount": "5",
                "minimum_withdrawal": "100",
                "admin_telegram_id": None,
                "admin_telegram_ids": None,
                "support_media_enabled": "true",
                "support_media_max_mb": "10",
                "support_media_allowed": "jpg,jpeg,png,webp,gif,mp4,mov,pdf",
                "support_media_keep_days": "0",
                "yookassa_shop_id": None,
                "yookassa_secret_key": None,
                "sbp_enabled": "false",
                "cryptobot_token": None,
                "heleket_merchant_id": None,
                "heleket_api_key": None,
                "domain": None,
                "ton_wallet_address": None,
                "tonapi_key": None,
                "support_forum_chat_id": None,
                "enable_fixed_referral_bonus": "false",
                "fixed_referral_bonus_amount": "50",
                "referral_reward_type": "percent_purchase",
                "referral_on_start_referrer_amount": "20",
                "backup_interval_days": "1",
                "backup_interval_unit": "days",

                "monitoring_enabled": "true",
                "monitoring_interval_sec": "300",
                "monitoring_cpu_threshold": "90",
                "monitoring_mem_threshold": "90",
                "monitoring_disk_threshold": "90",
                "monitoring_alert_cooldown_sec": "3600",

                # Отправка почты: подтверждение адреса и сброс пароля в веб-аппе.
                "smtp_enabled": "false",
                "smtp_host": None,
                "smtp_port": "587",
                "smtp_security": "starttls",
                "smtp_user": None,
                "smtp_password": None,
                "smtp_from_email": None,
                "smtp_from_name": None,
                # Пускать в кабинет до подтверждения адреса или нет.
                "email_verification_required": "false",

                "payment_button_balance_text": None,
                "payment_button_yookassa_text": None,
                "payment_button_platega_payform_text": None,
                "payment_button_platega_text": None,
                "payment_button_platega_crypto_text": None,
                "payment_button_cryptobot_text": None,
                "payment_button_heleket_text": None,
                "payment_button_tonconnect_text": None,
                "payment_button_stars_text": None,
                "payment_button_yoomoney_text": None,

                "remnawave_base_url": None,
                "remnawave_api_token": None,
                "remnawave_cookies": "{}",
                "remnawave_is_local_network": "false",
                "default_extension_days": "30",

                "main_menu_text": None,
                "howto_intro_text": None,
                "howto_android_text": None,
                "howto_ios_text": None,
                "howto_windows_text": None,
                "howto_linux_text": None,

                "btn_trial_text": None,
                "btn_profile_text": None,
                "btn_my_keys_text": None,
                "btn_buy_key_text": None,
                "btn_topup_text": None,
                "btn_referral_text": None,
                "btn_support_text": None,
                "btn_about_text": None,
                "btn_speed_text": None,
                "btn_howto_text": None,
                "btn_admin_text": None,
                "btn_back_to_menu_text": None,
                "btn_trial_button_style": None,
                "btn_trial_icon_emoji_id": None,
                "btn_profile_button_style": None,
                "btn_profile_icon_emoji_id": None,
                "btn_my_keys_button_style": None,
                "btn_my_keys_icon_emoji_id": None,
                "btn_buy_key_button_style": None,
                "btn_buy_key_icon_emoji_id": None,
                "btn_topup_button_style": None,
                "btn_topup_icon_emoji_id": None,
                "btn_referral_button_style": None,
                "btn_referral_icon_emoji_id": None,
                "btn_support_button_style": None,
                "btn_support_icon_emoji_id": None,
                "btn_about_button_style": None,
                "btn_about_icon_emoji_id": None,
                "btn_howto_button_style": None,
                "btn_howto_icon_emoji_id": None,
                "btn_speed_button_style": None,
                "btn_speed_icon_emoji_id": None,
                "btn_admin_button_style": None,
                "btn_admin_icon_emoji_id": None,
                "btn_back_to_menu_button_style": None,
                "btn_back_to_menu_icon_emoji_id": None,

                "stars_enabled": "false",
                "yoomoney_enabled": "false",
                "yoomoney_wallet": None,
                "yoomoney_secret": None,

                "yoomoney_api_token": None,
                "yoomoney_client_id": None,
                "yoomoney_client_secret": None,
                "yoomoney_redirect_uri": None,
                "stars_per_rub": "1",
                
                "platega_enabled": "false",
                "platega_crypto_enabled": "false",
                "platega_merchant_id": None,
                "platega_api_key": None,

                "main_menu_image": None,
                "profile_image": None,  
                "topup_image": None, 
                "referral_image": None,
                "support_image": None,
                "about_image": None,
                "speedtest_image": None,
                "howto_image": None,
                "topup_amount_image": None,

                "payment_image": None,
                "buy_server_image": None,
                "buy_plan_image": None,
                "enter_email_image": None,
                "key_info_image": None,
                "extend_plan_image": None,
                "keys_list_image": None,
                "payment_method_image": None,
                "key_comments_image": None,
                "key_ready_image": None,
                "devices_list_image": None,
                "key_gemini": None,
                "stealth_login_enabled": "0",
                "stealth_login_hotkey": "ctrl+b",
                "dashboard_layout": "sidebar",
                "demo_mode_enabled": "0",
            }
            _ensure_default_values(cursor, "bot_settings", default_settings)
            conn.commit()
            

            



            try:
                cursor.execute("ALTER TABLE button_configs ADD COLUMN button_width INTEGER DEFAULT 1")
                logging.info("Добавлена колонка button_width в таблицу button_configs")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE button_configs ADD COLUMN button_color TEXT DEFAULT NULL")
                logging.info("Добавлена колонка button_color в таблицу button_configs")
            except sqlite3.OperationalError:
                pass

            try:
                cursor.execute("ALTER TABLE button_configs ADD COLUMN emoji_id TEXT DEFAULT NULL")
                logging.info("Добавлена колонка emoji_id в таблицу button_configs")
            except sqlite3.OperationalError:
                pass
            
            logging.info("База данных инициализирована")
        
        run_migration()
        
    except sqlite3.Error as e:
        logging.error("Не удалось инициализировать базу данных: %s", e)
# =========================


# ===== _ENSURE_DEFAULT_VALUES =====
def _ensure_default_values(cursor: sqlite3.Cursor, table: str, defaults: dict) -> None:
    for key, value in defaults.items():
        try:
            cursor.execute(
                f"INSERT OR IGNORE INTO {table} (key, value) VALUES (?, ?)",
                (key, value)
            )
        except Exception: pass
# ==================================


# ===== _ENSURE_USERS_COLUMNS =====
# Диапазон синтетических id, которые выдаются аккаунтам, заведённым по
# почте (см. create_user_by_email). Настоящие Telegram id сюда не
# попадают, но полагаться только на диапазон нельзя — он конечен,
# поэтому основной источник правды это колонка tg_linked.
SYNTHETIC_ID_MIN = 9_991_000_000
SYNTHETIC_ID_MAX = 9_999_999_999


def is_telegram_account(user) -> bool:
    """
    Привязан ли к аккаунту настоящий Telegram.

    Принимает и словарь пользователя, и голый id. Колонка tg_linked
    заполняется миграцией и при создании; если её почему-то нет,
    откатываемся на проверку по диапазону синтетических id.
    """
    if isinstance(user, dict):
        flag = user.get("tg_linked")
        if flag is not None:
            return bool(int(flag))
        user_id = user.get("telegram_id")
    else:
        user_id = user

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False

    return uid > 0 and not (SYNTHETIC_ID_MIN <= uid <= SYNTHETIC_ID_MAX)


def _ensure_users_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if not cursor.fetchone(): return
    mapping = {
        "referred_by": "INTEGER",
        "balance": "REAL DEFAULT 0",
        "referral_balance": "REAL DEFAULT 0",
        "referral_balance_all": "REAL DEFAULT 0",
        "referral_start_bonus_received": "BOOLEAN DEFAULT 0",
        "is_pinned": "BOOLEAN DEFAULT 0",
        "seller_active": "INTEGER DEFAULT 0",
        # Цветовая схема веб-аппа, выбранная самим пользователем.
        "app_theme": "TEXT DEFAULT 'violet'",
        # 1 — адрес почты подтверждён кодом из письма.
        "email_verified": "INTEGER DEFAULT 0",
        # 1 — имя задано вручную в панели, автосинк из Telegram его не трогает.
        "username_manually_set": "BOOLEAN DEFAULT 0",
        "auth_token": "TEXT",
        "auth_email": "TEXT",
        "auth_pass": "TEXT",
        # 1 — аккаунт заведён/привязан через Telegram, 0 — только почта.
        # Раньше «телеграмность» определяли по знаку telegram_id, но
        # create_user_by_email выдаёт положительные синтетические id вида
        # 999XXXXXXX, поэтому проверка не срабатывала никогда.
        "tg_linked": "INTEGER",
        # колесо удачи: момент последнего бесплатного прокрута, запас
        # билетов и персональное согласие на напоминания
        "last_wheel_spin": "TIMESTAMP",
        "wheel_tickets": "INTEGER DEFAULT 0",
        "wheel_notify": "INTEGER DEFAULT 1",
        "wheel_notified_at": "TIMESTAMP",
        # Короткий код для веб-ссылки приглашения. Отдельно от telegram_id:
        # эту ссылку рассылают по чатам, и id в ней светить незачем.
        "ref_code": "TEXT",
        # 1 — билет колеса за этого приглашённого пригласившему уже выдан.
        # Отметка живёт на строке приглашённого, а не пригласившего: билет
        # положен только за телеграм-аккаунт, а Telegram у почтового
        # аккаунта появляется позже регистрации.
        "referral_ticket_granted": "INTEGER DEFAULT 0",
    }
    for column, definition in mapping.items():
        _ensure_table_column(cursor, "users", column, definition)

    # Код ищется по ссылке, поэтому он и индекс, и гарантия уникальности.
    # Частичный индекс — потому что ref_code пустой почти у всех: код
    # заводится, только когда человек открыл экран приглашений.
    try:
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_ref_code "
                       "ON users(ref_code) WHERE ref_code IS NOT NULL")
    except sqlite3.Error as e:
        logger.warning(f"Не удалось создать индекс по ref_code: {e}")

    # Разовое заполнение для уже существующих записей: синтетический
    # диапазон — почтовые аккаунты, всё остальное — настоящий Telegram.
    try:
        cursor.execute(
            "UPDATE users SET tg_linked = CASE "
            "WHEN telegram_id BETWEEN ? AND ? THEN 0 "
            "WHEN telegram_id <= 0 THEN 0 ELSE 1 END "
            "WHERE tg_linked IS NULL",
            (SYNTHETIC_ID_MIN, SYNTHETIC_ID_MAX),
        )
    except sqlite3.Error as e:
        logger.warning(f"Не удалось заполнить tg_linked: {e}")


# =================================

# ===== DELETE_USER =====
def delete_user(telegram_id: int) -> bool:
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Ошибка удаления пользователя {telegram_id}: {e}")
        return False
# =======================


# ===== _ENSURE_HOSTS_COLUMNS =====
def _ensure_hosts_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='xui_hosts'")
    if not cursor.fetchone(): return
    extras = {
        "squad_uuid": "TEXT",
        "description": "TEXT",
        "default_traffic_limit_bytes": "INTEGER",
        "default_traffic_strategy": "TEXT DEFAULT 'NO_RESET'",
        "default_traffic_reset_at": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "metadata": "TEXT",
        "subscription_url": "TEXT",
        "ssh_host": "TEXT",
        "ssh_port": "INTEGER",
        "ssh_user": "TEXT",
        "ssh_password": "TEXT",
        "ssh_key_path": "TEXT",

        "remnawave_base_url": "TEXT",
        "remnawave_api_token": "TEXT",
        "see": "INTEGER DEFAULT 1",
        "traffic_limit_strategy": "TEXT DEFAULT 'NO_RESET'",
        "device_mode": "TEXT DEFAULT 'plan'",
        "tier_lock_extend": "INTEGER DEFAULT 0",
        "button_style": "TEXT DEFAULT NULL",
        "icon_emoji_id": "TEXT DEFAULT NULL",
    }
    for column, definition in extras.items():
        _ensure_table_column(cursor, "xui_hosts", column, definition)


# =================================


def _ensure_device_tiers_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS device_tiers (
            tier_id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_name TEXT NOT NULL,
            device_count INTEGER NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            UNIQUE(host_name, device_count)
        )
    ''')



# ===== КОЛЕСО УДАЧИ =====
def _ensure_wheel_tables(cursor: sqlite3.Cursor) -> None:
    """Призы колеса и журнал прокрутов.

    Призы держим в базе, а не в коде: состав секторов и их вероятности —
    это настройка магазина, её меняют из панели, не пересобирая бота.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_prizes (
            prize_id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            prize_type TEXT NOT NULL DEFAULT 'days',
            amount REAL NOT NULL DEFAULT 0,
            weight INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)
    # Журнал нужен, чтобы разбирать спорные случаи: что именно выпало
    # человеку и куда ушли дни.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_spins (
            spin_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            prize_id INTEGER,
            label TEXT,
            prize_type TEXT,
            amount REAL DEFAULT 0,
            key_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_spins_user ON wheel_spins(user_id, created_at)")
    # Приз с выбором подписки выдаётся не сразу: пока человек выбирает, запись
    # висит в состоянии pending — так выигрыш не теряется, если он отвлёкся.
    _ensure_table_column(cursor, "wheel_spins", "status", "TEXT DEFAULT 'done'")
    _ensure_table_column(cursor, "wheel_spins", "detail", "TEXT")
    _ensure_table_column(cursor, "wheel_spins", "source", "TEXT DEFAULT 'free'")
    # Невыданный приз живёт ограниченное время: иначе они копятся годами,
    # а магазин остаётся должен по каждому.
    _ensure_table_column(cursor, "wheel_spins", "expires_at", "TIMESTAMP")
    # Шанс сектора на момент прокрута. Веса правят на ходу, и без этого
    # снимка нельзя проверить, честно ли колесо: сравнивать выпадения
    # с сегодняшней настройкой бессмысленно.
    _ensure_table_column(cursor, "wheel_spins", "chance", "REAL")

    # Движение билетов ведём отдельно: по одному лишь остатку не разобрать,
    # откуда он взялся и на что ушёл.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wheel_ticket_log (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            reason TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_ticket_log_user ON wheel_ticket_log(user_id, created_at)")

    cursor.execute("SELECT COUNT(*) FROM wheel_prizes")
    if (cursor.fetchone() or [0])[0]:
        return
    # Веса подобраны так, чтобы в сумме дать 100 — тогда вес читается как
    # проценты и владельцу магазина не приходится ничего пересчитывать.
    defaults = [
        ("Мимо", "nothing", 0, 39, 0),
        ("1 день", "days", 1, 25, 1),
        ("2 дня", "days", 2, 14, 2),
        ("3 дня", "days", 3, 9, 3),
        ("50 ₽ на баланс", "balance", 50, 6, 4),
        ("7 дней", "days", 7, 4, 5),
        ("14 дней", "days", 14, 2, 6),
        ("30 дней", "days", 30, 1, 7),
    ]
    cursor.executemany(
        "INSERT INTO wheel_prizes (label, prize_type, amount, weight, sort_order) VALUES (?,?,?,?,?)",
        defaults,
    )
    logging.info("Колесо удачи: засеяны призы по умолчанию (%d секторов)", len(defaults))


def get_wheel_prizes(active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM wheel_prizes"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY sort_order, prize_id"
    return _fetch_list(sql, (), "Не удалось получить призы колеса")


def get_wheel_prize(prize_id: int) -> dict | None:
    return _fetch_row("SELECT * FROM wheel_prizes WHERE prize_id = ?", (prize_id,))


def add_wheel_prize(label: str, prize_type: str, amount: float, weight: int) -> int | None:
    cursor = _exec(
        "INSERT INTO wheel_prizes (label, prize_type, amount, weight, sort_order) "
        "VALUES (?,?,?,?, COALESCE((SELECT MAX(sort_order) + 1 FROM wheel_prizes), 0))",
        (label, prize_type, float(amount), int(weight)),
        "Не удалось добавить приз колеса",
    )
    return cursor.lastrowid if cursor else None


def update_wheel_prize(prize_id: int, label: str, prize_type: str, amount: float,
                       weight: int, is_active: int = 1) -> bool:
    cursor = _exec(
        "UPDATE wheel_prizes SET label=?, prize_type=?, amount=?, weight=?, is_active=? WHERE prize_id=?",
        (label, prize_type, float(amount), int(weight), int(is_active), prize_id),
        "Не удалось изменить приз колеса",
    )
    return bool(cursor and cursor.rowcount)


def delete_wheel_prize(prize_id: int) -> bool:
    cursor = _exec("DELETE FROM wheel_prizes WHERE prize_id=?", (prize_id,), "Не удалось удалить приз колеса")
    return bool(cursor and cursor.rowcount)


def get_last_wheel_spin(user_id: int) -> str | None:
    row = _fetch_row("SELECT last_wheel_spin FROM users WHERE telegram_id = ?", (user_id,))
    return row["last_wheel_spin"] if row else None


def claim_wheel_spin(user_id: int, now_iso: str, allowed_before_iso: str) -> bool:
    """Занимает прокрут, если кулдаун уже прошёл.

    Проверка и запись — одним UPDATE: иначе два быстрых нажатия успевали
    прочитать старое время каждый и прокрутить колесо дважды.
    """
    cursor = _exec(
        "UPDATE users SET last_wheel_spin = ? WHERE telegram_id = ? "
        "AND (last_wheel_spin IS NULL OR last_wheel_spin <= ?)",
        (now_iso, user_id, allowed_before_iso),
        f"Не удалось занять прокрут колеса для {user_id}",
    )
    return bool(cursor and cursor.rowcount)


def release_wheel_spin(user_id: int, previous_iso: str | None) -> bool:
    """Возвращает прежнее время: приз выдать не удалось — попытка не сгорает."""
    cursor = _exec(
        "UPDATE users SET last_wheel_spin = ? WHERE telegram_id = ?",
        (previous_iso, user_id),
        f"Не удалось вернуть попытку колеса для {user_id}",
    )
    return bool(cursor and cursor.rowcount)


def log_wheel_spin(user_id: int, prize: dict, key_id: int | None = None) -> int | None:
    cursor = _exec(
        "INSERT INTO wheel_spins (user_id, prize_id, label, prize_type, amount, key_id) VALUES (?,?,?,?,?,?)",
        (user_id, prize.get("prize_id"), prize.get("label"), prize.get("prize_type"),
         float(prize.get("amount") or 0), key_id),
        "Не удалось записать прокрут колеса",
    )
    return cursor.lastrowid if cursor else None


def get_wheel_spins(limit: int = 50) -> list[dict]:
    return _fetch_list(
        "SELECT s.*, u.username FROM wheel_spins s LEFT JOIN users u ON u.telegram_id = s.user_id "
        "ORDER BY s.created_at DESC LIMIT ?",
        (limit,),
        "Не удалось получить журнал колеса",
    )


def get_wheel_stats() -> dict:
    row = _fetch_row(
        "SELECT COUNT(*) AS spins, COUNT(DISTINCT user_id) AS players, "
        "COALESCE(SUM(CASE WHEN prize_type='days' THEN amount ELSE 0 END), 0) AS days_given, "
        "COALESCE(SUM(CASE WHEN prize_type='balance' THEN amount ELSE 0 END), 0) AS rub_given "
        "FROM wheel_spins",
        (),
        "Не удалось посчитать статистику колеса",
    )
    return dict(row) if row else {"spins": 0, "players": 0, "days_given": 0, "rub_given": 0}


def get_wheel_tickets(user_id: int) -> int:
    row = _fetch_row("SELECT wheel_tickets FROM users WHERE telegram_id = ?", (user_id,))
    try:
        return max(0, int((row or {}).get("wheel_tickets") or 0))
    except (TypeError, ValueError):
        return 0


def add_wheel_tickets(user_id: int, amount: int, reason: str, note: str | None = None) -> bool:
    """Начисляет билеты и пишет причину в журнал."""
    amount = int(amount)
    if amount == 0:
        return True
    cursor = _exec(
        "UPDATE users SET wheel_tickets = MAX(0, COALESCE(wheel_tickets, 0) + ?) WHERE telegram_id = ?",
        (amount, user_id),
        f"Не удалось изменить билеты пользователя {user_id}",
    )
    if not (cursor and cursor.rowcount):
        return False
    _exec("INSERT INTO wheel_ticket_log (user_id, delta, reason, note) VALUES (?,?,?,?)",
          (user_id, amount, reason, note), "Не удалось записать движение билетов")
    return True


def spend_wheel_ticket(user_id: int, reason: str = "spin") -> bool:
    """Списывает один билет, если он есть.

    Проверка и списание одним UPDATE: иначе два быстрых нажатия успевали
    прочитать один и тот же остаток и прокрутить колесо дважды.
    """
    cursor = _exec(
        "UPDATE users SET wheel_tickets = wheel_tickets - 1 WHERE telegram_id = ? AND COALESCE(wheel_tickets, 0) > 0",
        (user_id,),
        f"Не удалось списать билет у {user_id}",
    )
    if not (cursor and cursor.rowcount):
        return False
    _exec("INSERT INTO wheel_ticket_log (user_id, delta, reason) VALUES (?,?,?)",
          (user_id, -1, reason), "Не удалось записать списание билета")
    return True


def get_wheel_ticket_log(limit: int = 30) -> list[dict]:
    return _fetch_list(
        "SELECT l.*, u.username FROM wheel_ticket_log l LEFT JOIN users u ON u.telegram_id = l.user_id "
        "ORDER BY l.created_at DESC, l.entry_id DESC LIMIT ?",
        (limit,), "Не удалось получить журнал билетов")


def get_wheel_notify(user_id: int) -> bool:
    row = _fetch_row("SELECT wheel_notify FROM users WHERE telegram_id = ?", (user_id,))
    if not row or row.get("wheel_notify") is None:
        return True
    return bool(int(row["wheel_notify"]))


def set_wheel_notify(user_id: int, enabled: bool) -> bool:
    cursor = _exec("UPDATE users SET wheel_notify = ? WHERE telegram_id = ?",
                   (1 if enabled else 0, user_id), f"Не удалось изменить напоминания колеса для {user_id}")
    return bool(cursor and cursor.rowcount)


def get_pending_wheel_prizes(user_id: int, now_iso: str) -> list[dict]:
    """Невыданные призы, у которых ещё не вышел срок."""
    return _fetch_list(
        "SELECT * FROM wheel_spins WHERE user_id = ? AND status = 'pending' "
        "AND (expires_at IS NULL OR expires_at > ?) ORDER BY spin_id DESC",
        (user_id, now_iso), "Не удалось получить невыданные призы")


def get_wheel_spin(spin_id: int) -> dict | None:
    return _fetch_row("SELECT * FROM wheel_spins WHERE spin_id = ?", (spin_id,))


_WHEEL_WON = ("SELECT {what} FROM wheel_spins WHERE user_id = ? "
              "AND COALESCE(prize_type, 'nothing') != 'nothing' AND COALESCE(amount, 0) > 0")


def get_user_wheel_prizes(user_id: int, limit: int | None = None, pending_only: bool = False) -> list[dict]:
    """Прокруты, в которых что-то выиграно: пустой сектор — не приз.

    limit=None отдаёт всё. Невыданные призы обрезать нельзя: пока приз не
    виден в списке, его не заберут, а срок у него идёт.
    """
    sql = _WHEEL_WON.format(what="*")
    sql += " AND status = 'pending'" if pending_only else " AND status != 'pending'"
    sql += " ORDER BY spin_id DESC"
    params = [user_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return _fetch_list(sql, tuple(params), "Не удалось получить призы пользователя")


def count_user_wheel_prizes(user_id: int) -> int:
    row = _fetch_row(_WHEEL_WON.format(what="COUNT(*) AS n"), (user_id,))
    return int((row or {}).get("n") or 0)


def expire_wheel_prizes(now_iso: str) -> int:
    """Гасит просроченные призы. Возвращает, сколько сгорело."""
    cursor = _exec(
        "UPDATE wheel_spins SET status = 'expired' WHERE status = 'pending' "
        "AND expires_at IS NOT NULL AND expires_at <= ?",
        (now_iso,), "Не удалось погасить просроченные призы")
    return cursor.rowcount if cursor else 0


def complete_wheel_spin(spin_id: int, key_id: int | None, detail: str | None) -> bool:
    cursor = _exec(
        "UPDATE wheel_spins SET status = 'done', key_id = ?, detail = ? WHERE spin_id = ? AND status = 'pending'",
        (key_id, detail, spin_id), f"Не удалось завершить выдачу приза {spin_id}")
    return bool(cursor and cursor.rowcount)


def log_wheel_spin_full(user_id: int, prize: dict, key_id: int | None, status: str,
                        detail: str | None, source: str, expires_at: str | None = None,
                        chance: float | None = None) -> int | None:
    cursor = _exec(
        "INSERT INTO wheel_spins (user_id, prize_id, label, prize_type, amount, key_id, status, detail, source, expires_at, chance) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, prize.get("prize_id"), prize.get("label"), prize.get("prize_type"),
         float(prize.get("amount") or 0), key_id, status, detail, source, expires_at, chance),
        "Не удалось записать прокрут колеса")
    return cursor.lastrowid if cursor else None


def get_wheel_fairness(limit_days: int | None = None) -> list[dict]:
    """Сколько раз сектор выпал против того, сколько должен был.

    Веса меняют на ходу, поэтому «ожидалось» считается не по нынешней
    настройке, а по шансу, записанному в момент каждого прокрута. Без этого
    любая правка секторов задним числом делала статистику бессмысленной.
    """
    where = "WHERE chance IS NOT NULL"
    params: tuple = ()
    if limit_days:
        where += " AND created_at >= datetime('now', ?)"
        params = (f"-{int(limit_days)} days",)
    return _fetch_list(
        "SELECT prize_id, label, prize_type, COUNT(*) AS hits, "
        "       SUM(chance) / 100.0 AS expected, AVG(chance) AS avg_chance "
        f"FROM wheel_spins {where} GROUP BY prize_id, label ORDER BY hits DESC",
        params, "Не удалось посчитать честность колеса")


def count_wheel_spins(limit_days: int | None = None, with_chance: bool = True) -> int:
    where = "WHERE chance IS NOT NULL" if with_chance else "WHERE 1=1"
    params: tuple = ()
    if limit_days:
        where += " AND created_at >= datetime('now', ?)"
        params = (f"-{int(limit_days)} days",)
    row = _fetch_row(f"SELECT COUNT(*) AS c FROM wheel_spins {where}", params, "")
    return int((row or {}).get("c") or 0)


def get_user_wheel_summary(user_id: int) -> dict:
    """Всё про рулетку одного пользователя — для карточки в панели."""
    row = _fetch_row(
        "SELECT COUNT(*) AS spins, MIN(created_at) AS first_spin, MAX(created_at) AS last_spin, "
        "COALESCE(SUM(CASE WHEN prize_type='days' THEN amount ELSE 0 END), 0) AS days_won, "
        "COALESCE(SUM(CASE WHEN prize_type='balance' THEN amount ELSE 0 END), 0) AS rub_won, "
        "COALESCE(SUM(CASE WHEN prize_type='nothing' OR amount<=0 THEN 1 ELSE 0 END), 0) AS misses, "
        "COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END), 0) AS pending "
        "FROM wheel_spins WHERE user_id = ?",
        (user_id,), f"Не удалось собрать сводку колеса для {user_id}")
    return dict(row) if row else {}


def get_user_wheel_spins(user_id: int, limit: int = 20) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM wheel_spins WHERE user_id = ? ORDER BY spin_id DESC LIMIT ?",
        (user_id, limit), f"Не удалось получить прокруты пользователя {user_id}")


def get_user_ticket_log(user_id: int, limit: int = 20) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM wheel_ticket_log WHERE user_id = ? ORDER BY entry_id DESC LIMIT ?",
        (user_id, limit), f"Не удалось получить журнал билетов {user_id}")


def get_wheel_notify_candidates(ready_before: str, quiet_since: str) -> list[dict]:
    """Кому пора напомнить про бесплатный прокрут.

    Берём только тех, кто уже крутил (иначе напоминание получат все 600
    зарегистрированных разом), у кого кулдаун истёк и кому давно не писали.
    """
    return _fetch_list(
        "SELECT telegram_id, username, last_wheel_spin FROM users "
        "WHERE COALESCE(wheel_notify, 1) = 1 AND COALESCE(is_banned, 0) = 0 "
        "AND last_wheel_spin IS NOT NULL AND last_wheel_spin <= ? "
        "AND (wheel_notified_at IS NULL OR wheel_notified_at <= ?) "
        "AND telegram_id > 0",
        (ready_before, quiet_since), "Не удалось получить список для напоминаний")


def mark_wheel_notified(user_id: int, when_iso: str) -> bool:
    cursor = _exec("UPDATE users SET wheel_notified_at = ? WHERE telegram_id = ?",
                   (when_iso, user_id), f"Не удалось отметить напоминание для {user_id}")
    return bool(cursor and cursor.rowcount)

# ===== Конец блока колеса удачи =====

# ===== _ENSURE_PLANS_COLUMNS =====
def _ensure_plans_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plans'")
    if not cursor.fetchone(): return
    extras = {
        "squad_uuid": "TEXT",
        "duration_days": "INTEGER",
        "traffic_limit_bytes": "INTEGER",
        "traffic_limit_strategy": "TEXT DEFAULT 'NO_RESET'",
        "is_active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "metadata": "TEXT",
        "hwid_limit": "INTEGER DEFAULT 0",
        "traffic_limit_gb": "INTEGER DEFAULT 0",
        "button_style": "TEXT DEFAULT NULL",
        "icon_emoji_id": "TEXT DEFAULT NULL",
    }
    for column, definition in extras.items():
        _ensure_table_column(cursor, "plans", column, definition)


# =================================


# ===== _ENSURE_SUPPORT_TICKETS_COLUMNS =====
def _ensure_support_tickets_columns(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='support_tickets'")
    if not cursor.fetchone(): return
    extras = {
        "forum_chat_id": "TEXT",
        "message_thread_id": "INTEGER",
    }
    for column, definition in extras.items():
        _ensure_table_column(cursor, "support_tickets", column, definition)


# ===========================================


# ===== _FINALIZE_VPN_KEY_INDEXES =====
def _finalize_vpn_key_indexes(cursor: sqlite3.Cursor) -> None:
    _ensure_unique_index(cursor, "uq_vpn_keys_email", "vpn_keys", "email")
    _ensure_unique_index(cursor, "uq_vpn_keys_key_email", "vpn_keys", "key_email")
    _ensure_index(cursor, "idx_vpn_keys_user_id", "vpn_keys", "user_id")
    _ensure_index(cursor, "idx_vpn_keys_rem_uuid", "vpn_keys", "remnawave_user_uuid")
    _ensure_index(cursor, "idx_vpn_keys_expire_at", "vpn_keys", "expire_at")


# =====================================


# ===== _REBUILD_VPN_KEYS_TABLE =====
def _rebuild_vpn_keys_table(cursor: sqlite3.Cursor) -> None:
    columns = _get_table_columns(cursor, "vpn_keys")
    legacy_markers = {"xui_client_uuid", "expiry_date", "created_date", "connection_string"}
    required = {"remnawave_user_uuid", "email", "expire_at", "created_at", "updated_at"}
    if required.issubset(columns) and not (columns & legacy_markers): _finalize_vpn_key_indexes(cursor); return

    cursor.execute("ALTER TABLE vpn_keys RENAME TO vpn_keys_legacy")
    cursor.execute('''
        CREATE TABLE vpn_keys (
            key_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            host_name TEXT,
            squad_uuid TEXT,
            remnawave_user_uuid TEXT,
            short_uuid TEXT,
            email TEXT UNIQUE,
            key_email TEXT UNIQUE,
            subscription_url TEXT,
            expire_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            traffic_limit_bytes INTEGER,
            traffic_limit_strategy TEXT DEFAULT 'NO_RESET',
            tag TEXT,
            description TEXT,
            comment_key TEXT,
            is_pinned BOOLEAN DEFAULT 0
        )
    ''')
    old_columns = _get_table_columns(cursor, "vpn_keys_legacy")

    def has(column: str) -> bool: return column in old_columns

    def col(column: str, default: str = "NULL") -> str: return column if has(column) else default

    rem_uuid_expr = "remnawave_user_uuid" if has("remnawave_user_uuid") else ("xui_client_uuid" if has("xui_client_uuid") else "NULL")
    email_expr = "LOWER(email)" if has("email") else ("LOWER(key_email)" if has("key_email") else "NULL")
    key_email_expr = "LOWER(key_email)" if has("key_email") else ("LOWER(email)" if has("email") else "NULL")
    subscription_expr = col("subscription_url", "connection_string" if has("connection_string") else "NULL")
    expire_expr = col("expire_at", "expiry_date" if has("expiry_date") else "NULL")
    created_expr = col("created_at", "created_date" if has("created_date") else "CURRENT_TIMESTAMP")
    updated_expr = col("updated_at", created_expr)
    traffic_strategy_expr = col("traffic_limit_strategy", "'NO_RESET'")

    select_clause = ",\n            ".join([
        f"{col('key_id')} AS key_id",
        f"{col('user_id')} AS user_id",
        f"{col('host_name')} AS host_name",
        f"{col('squad_uuid')} AS squad_uuid",
        f"{rem_uuid_expr} AS remnawave_user_uuid",
        f"{col('short_uuid')} AS short_uuid",
        f"{email_expr} AS email",
        f"{key_email_expr} AS key_email",
        f"{subscription_expr} AS subscription_url",
        f"{expire_expr} AS expire_at",
        f"{created_expr} AS created_at",
        f"{updated_expr} AS updated_at",
        f"{col('traffic_limit_bytes')} AS traffic_limit_bytes",
        f"{traffic_strategy_expr} AS traffic_limit_strategy",
        f"{col('tag')} AS tag",
        f"{col('description')} AS description",
        f"{col('comment_key')} AS comment_key",
        f"{col('is_pinned', '0')} AS is_pinned",
    ])

    cursor.execute(
        f"""
        INSERT INTO vpn_keys (
            key_id,
            user_id,
            host_name,
            squad_uuid,
            remnawave_user_uuid,
            short_uuid,
            email,
            key_email,
            subscription_url,
            expire_at,
            created_at,
            updated_at,
            traffic_limit_bytes,
            traffic_limit_strategy,
            tag,
            description,
            comment_key,
            is_pinned
        )
        SELECT
            {select_clause}
        FROM vpn_keys_legacy
        """
    )
    cursor.execute("DROP TABLE vpn_keys_legacy")
    cursor.execute("SELECT MAX(key_id) FROM vpn_keys")
    max_id = cursor.fetchone()[0]
    if max_id is not None:
        cursor.execute("INSERT OR REPLACE INTO sqlite_sequence(name, seq) VALUES('vpn_keys', ?)", (max_id,))
    _finalize_vpn_key_indexes(cursor)


# ===================================


# ===== _ENSURE_VPN_KEYS_SCHEMA =====
def _ensure_vpn_keys_schema(cursor: sqlite3.Cursor) -> None:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vpn_keys'")
    if cursor.fetchone() is None:
        cursor.execute('''
            CREATE TABLE vpn_keys (
                key_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                host_name TEXT,
                squad_uuid TEXT,
                remnawave_user_uuid TEXT,
                short_uuid TEXT,
                email TEXT UNIQUE,
                key_email TEXT UNIQUE,
                subscription_url TEXT,
                expire_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                traffic_limit_bytes INTEGER,
                traffic_limit_strategy TEXT DEFAULT 'NO_RESET',
                tag TEXT,
                description TEXT,
                comment_key TEXT,
                is_pinned BOOLEAN DEFAULT 0
            )
        ''')
        _finalize_vpn_key_indexes(cursor)
        return
    _rebuild_vpn_keys_table(cursor)
    _ensure_table_column(cursor, "vpn_keys", "is_pinned", "BOOLEAN DEFAULT 0")


# ===================================


# ===== RUN_MIGRATION =====
# ===========================================
# ===== _ENSURE_WEBAPP_SETTINGS_TABLE =====
def _ensure_webapp_settings_table(cursor: sqlite3.Cursor):
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS webapp_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                webapp_title TEXT DEFAULT 'VPN',
                webapp_domen TEXT DEFAULT '',
                webapp_enable INTEGER DEFAULT 0,
                webapp_logo TEXT DEFAULT '',
                webapp_icon TEXT DEFAULT '',
                tg_fullscreen INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute("PRAGMA table_info(webapp_settings)")
        columns = {row[1] for row in cursor.fetchall()}
        
        if "webapp_title" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN webapp_title TEXT DEFAULT 'VPN'")
        if "webapp_domen" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN webapp_domen TEXT DEFAULT ''")
        if "webapp_enable" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN webapp_enable INTEGER DEFAULT 0")
        if "webapp_logo" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN webapp_logo TEXT DEFAULT ''")
        if "webapp_icon" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN webapp_icon TEXT DEFAULT ''")
        if "tg_fullscreen" not in columns:
            cursor.execute("ALTER TABLE webapp_settings ADD COLUMN tg_fullscreen INTEGER DEFAULT 0")

        cursor.execute("INSERT OR IGNORE INTO webapp_settings (id, webapp_title, webapp_domen, webapp_enable, webapp_logo, webapp_icon) VALUES (1, 'VPN', '', 0, '', '')")
            
    except Exception as e:
        logging.error(f"Ошибка миграции webapp_settings: {e}")

# ===========================================


# ===== RUN_MIGRATION =====
def run_migration():
    if not DB_FILE.exists(): logging.error("Файл базы данных отсутствует, миграция пропущена."); return

    logging.info("Запуск миграций базы данных: %s", DB_FILE)

    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = OFF")
            _ensure_users_columns(cursor)
            _ensure_hosts_columns(cursor)
            _ensure_device_tiers_table(cursor)
            _ensure_wheel_tables(cursor)
            _ensure_plans_columns(cursor)
            _ensure_support_tickets_columns(cursor)
            _ensure_vpn_keys_schema(cursor)
            _ensure_table_column(cursor, "vpn_keys", "comment_key", "TEXT")
            _ensure_table_column(cursor, "vpn_keys", "is_pinned", "BOOLEAN DEFAULT 0")
            # общий для бота, вебаппа и админки момент последнего пересоздания подписки
            _ensure_table_column(cursor, "vpn_keys", "last_subscription_reset_at", "INTEGER")
            _ensure_ssh_targets_table(cursor)
            _ensure_host_speedtests_table(cursor)
            _ensure_resource_metrics_table(cursor)
            _ensure_gift_tokens_table(cursor)
            _ensure_username_history_table(cursor)
            _ensure_email_codes_table(cursor)
            _ensure_support_media_table(cursor)
            # Картинка из рассылки. Телеграму хватает file_id, а кабинету нужна
            # ссылка, по которой браузер сходит сам.
            _ensure_table_column(cursor, "user_notifications", "media_url", "TEXT")
            _ensure_table_column(cursor, "user_notifications", "media_type", "TEXT")
            _ensure_promo_tables(cursor)
            _ensure_webapp_settings_table(cursor)
            try:
                cursor.execute("ALTER TABLE seller_users RENAME COLUMN sellr_ref TO seller_ref")
                logging.info("Переименована колонка sellr_ref в seller_ref в таблице seller_users")
            except Exception:
                pass

            _ensure_seller_users_table(cursor)

            try:
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_support_tickets_thread ON support_tickets(forum_chat_id, message_thread_id)")
            except Exception:
                pass

            try:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pending_transactions (
                        payment_id TEXT PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        amount_rub REAL,
                        metadata TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
            except Exception:
                pass
            
            _ensure_default_values(cursor, "bot_settings", {
                "skip_email": "0",
                "enable_wal_mode": "0",
                "dashboard_layout": "sidebar",
                "demo_mode_enabled": "0"
            })
            
            _ensure_default_values(cursor, "other", {
                "theme_newsletter": json.dumps({}),
                "auto_start_bot": "0"
            })
            
            _ensure_pending_transactions_table(cursor)
            _ensure_default_button_configs(cursor)
            _ensure_reset_subscription_button(cursor)
            _ensure_addon_devices_button(cursor)
            _ensure_wheel_button(cursor)
            

            try:
                wide_buttons = [("trial", 2), ("referral", 2), ("admin", 2)]
                for button_id, width in wide_buttons:
                    cursor.execute("""
                        UPDATE button_configs 
                        SET button_width = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE menu_type = 'main_menu' AND button_id = ?
                    """, (width, button_id))
            except Exception:
                pass


            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()
    except sqlite3.Error as e:
        logging.error("Сбой миграции базы данных: %s", e)

# =========================


# ===== _ENSURE_PENDING_TRANSACTIONS_TABLE =====
def _ensure_pending_transactions_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_transactions (
            payment_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount_rub REAL,
            metadata TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

# ==============================================


# ===== _ENSURE_DEFAULT_BUTTON_CONFIGS =====
def _ensure_default_button_configs(cursor: sqlite3.Cursor) -> None:
    def menu_has_buttons(m_type):
        cursor.execute("SELECT 1 FROM button_configs WHERE menu_type = ? LIMIT 1", (m_type,))
        return cursor.fetchone() is not None

    ADMIN_MENU_LAYOUT_WITH_FINANCE = {
        "finance": (0, 0, 0, 2),
        "users": (1, 0, 1, 1),
        "host_keys": (1, 1, 2, 1),
        "gift_key": (2, 0, 3, 1),
        "promo": (2, 1, 4, 1),
        "speedtest": (3, 0, 5, 1),
        "monitor": (3, 1, 6, 1),
        "backup": (4, 0, 7, 1),
        "restore": (4, 1, 8, 1),
        "admins": (5, 0, 9, 1),
        "broadcast": (5, 1, 10, 1),
        "back_to_menu": (6, 0, 11, 3),
    }

    def normalize_admin_menu_default_layout():
        """Освобождает место под «Финансы» в админ-меню.

        Двигаем кнопки только если раскладка ровно такая, какой мы её создали:
        либо старая (без «Финансов»), либо та, что получалась при добавлении
        «Финансов» без сдвига остальных — там кнопка садилась на занятое место.
        Если владелец переставлял кнопки сам, не трогаем ничего.
        """
        layout_before_finance = {
            "users": (0, 0, 0, 1), "host_keys": (0, 1, 1, 1),
            "gift_key": (1, 0, 2, 1), "promo": (1, 1, 3, 1),
            "speedtest": (2, 0, 4, 1), "monitor": (2, 1, 5, 1),
            "backup": (3, 0, 6, 1), "restore": (3, 1, 7, 1),
            "admins": (4, 0, 8, 1), "broadcast": (4, 1, 9, 1),
            "back_to_menu": (5, 0, 10, 3),
        }
        overlapping_layout = dict(layout_before_finance, finance=(0, 0, 0, 2))

        cursor.execute(
            """
            SELECT button_id, row_position, column_position, sort_order, button_width
            FROM button_configs
            WHERE menu_type = 'admin_menu'
            """
        )
        layout = {
            row[0]: (row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
            if row[0] in ADMIN_MENU_LAYOUT_WITH_FINANCE
        }
        if layout == ADMIN_MENU_LAYOUT_WITH_FINANCE:
            return
        if layout not in (layout_before_finance, overlapping_layout):
            return
        for button_id, (row_pos, col_pos, sort_order, width) in ADMIN_MENU_LAYOUT_WITH_FINANCE.items():
            cursor.execute(
                """
                UPDATE button_configs
                SET row_position = ?, column_position = ?, sort_order = ?, button_width = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE menu_type = 'admin_menu' AND button_id = ?
                """,
                (row_pos, col_pos, sort_order, width, button_id),
            )

    if not menu_has_buttons("main_menu"):
        main_menu_buttons = [
            ("trial", "🎁 Попробовать бесплатно", "get_trial", 0, 0, 0, 2),
            ("profile", "👤 Мой профиль", "show_profile", 1, 0, 1, 1),
            ("my_keys", "🔑 Мои подписки ({len(user_keys)})", "manage_keys", 1, 1, 2, 1),
            ("buy_key", "🛒 Купить подписку", "buy_new_key", 2, 0, 3, 1),
            ("topup", "💳 Пополнить баланс", "top_up_start", 2, 1, 4, 1),
            ("referral", "🤝 Реферальная программа", "show_referral_program", 3, 0, 5, 2),
            ("wheel", "🎰 Колесо удачи", "wheel_open", 4, 0, 6, 2),
            ("support", "🆘 Поддержка", "show_help", 5, 0, 7, 1),
            ("about", "ℹ️ О проекте", "show_about", 5, 1, 8, 1),
            ("speed", "⚡ Скорость", "user_speedtest_last", 6, 0, 9, 1),
            ("howto", "❓ Как использовать", "howto_vless", 6, 1, 10, 1),
            ("admin", "⚙️ Админка", "admin_menu", 7, 0, 11, 2),
        ]
        
        for button_id, text, callback_data, row_pos, col_pos, sort_order, button_width in main_menu_buttons:
            cursor.execute("""
                INSERT INTO button_configs 
                (menu_type, button_id, text, callback_data, row_position, column_position, sort_order, button_width, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("main_menu", button_id, text, callback_data, row_pos, col_pos, sort_order, button_width))
    

    admin_menu_labels = {
        "finance": ("💸 Финансы", "admin_finance"),
        "users": ("👥 Пользователи", "admin_users"),
        "host_keys": ("🌍 Ключи на хосте", "admin_host_keys"),
        "gift_key": ("🎁 Выдать ключ", "admin_gift_key"),
        "promo": ("🎟 Промокоды", "admin_promo_menu"),
        "speedtest": ("⚡ Тест скорости", "admin_speedtest"),
        "monitor": ("📊 Мониторинг", "admin_monitor"),
        "backup": ("🗄 Бэкап БД", "admin_backup_db"),
        "restore": ("♻️ Восстановить БД", "admin_restore_db"),
        "admins": ("👮 Администраторы", "admin_admins_menu"),
        "broadcast": ("📢 Рассылка", "start_broadcast"),
        "back_to_menu": ("⬅️ Назад в меню", "back_to_main_menu"),
    }

    if not menu_has_buttons("admin_menu"):
        for button_id, (row_pos, col_pos, sort_order, width) in ADMIN_MENU_LAYOUT_WITH_FINANCE.items():
            text, callback_data = admin_menu_labels[button_id]
            cursor.execute("""
                INSERT INTO button_configs
                (menu_type, button_id, text, callback_data, row_position, column_position, sort_order, button_width, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("admin_menu", button_id, text, callback_data, row_pos, col_pos, sort_order, width))
    else:
        # Установка уже жила без «Финансов» — добавляем кнопку и, если раскладку
        # никто не менял руками, раздвигаем остальные.
        cursor.execute("""
            INSERT OR IGNORE INTO button_configs
            (menu_type, button_id, text, callback_data, row_position, column_position, sort_order, button_width, is_active)
            VALUES ('admin_menu', 'finance', '💸 Финансы', 'admin_finance', 0, 0, 0, 2, 1)
        """)
        normalize_admin_menu_default_layout()


    if not menu_has_buttons("profile_menu"):
        profile_menu_buttons = [
            ("topup", "💳 Пополнить баланс", "top_up_start", 0, 0, 0, 2),
            ("referral", "🤝 Реферальная программа", "show_referral_program", 1, 0, 1, 2),
            ("howto", "🛠 Подключиться", "howto_vless", 2, 0, 2, 1),
            ("promo_uni", "🎁 Ввести промокод", "promo_uni", 2, 1, 3, 1),
            ("back_to_menu", "⬅️ Назад в меню", "back_to_main_menu", 3, 0, 4, 3),
        ]
        
        for button_id, text, callback_data, row_pos, col_pos, sort_order, button_width in profile_menu_buttons:
            cursor.execute("""
                INSERT INTO button_configs 
                (menu_type, button_id, text, callback_data, row_position, column_position, sort_order, button_width, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("profile_menu", button_id, text, callback_data, row_pos, col_pos, sort_order, button_width))
    

    if not menu_has_buttons("support_menu"):
        support_menu_buttons = [
            ("new_ticket", "✍️ Новое обращение", "support_new_ticket", 0, 0, 0, 1),
            ("my_tickets", "📨 Мои обращения", "support_my_tickets", 0, 1, 1, 1),
            ("external", "🆘 Внешняя поддержка", "support_external", 1, 0, 2, 2),
            ("back_to_menu", "⬅️ Назад в меню", "back_to_main_menu", 2, 0, 3, 2),
        ]
        
        for button_id, text, callback_data, row_pos, col_pos, sort_order, button_width in support_menu_buttons:
            cursor.execute("""
                INSERT INTO button_configs 
                (menu_type, button_id, text, callback_data, row_position, column_position, sort_order, button_width, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("support_menu", button_id, text, callback_data, row_pos, col_pos, sort_order, button_width))

    if not menu_has_buttons("key_info_menu"):
        key_info_menu_buttons = [
            ("connect", "📲 Подключиться", None, "{connection_string}", 0, 0, 0, 2),
            ("extend", "➕ Продлить подписку", "extend_key_{key_id}", None, 1, 0, 1, 2),
            ("addon_devices", "📱 Докупить устройства", "addon_dev_{key_id}", None, 2, 0, 2, 2),
            ("key_devices", "📱 Устройства", "key_devices_{key_id}", None, 3, 0, 3, 1),
            ("qr", "📱 QR-код", "show_qr_{key_id}", None, 3, 1, 4, 1),
            ("howto", "📖 Инструкция", "howto_vless_{key_id}", None, 4, 0, 5, 1),
            ("comment_key", "📝 Комментарий", "key_comments_{key_id}", None, 4, 1, 6, 1),
            ("reset_sub", "🔄 Пересоздать подписку", "reset_sub_confirm_{key_id}", None, 5, 0, 7, 2),
            ("back", "⬅️ Назад к списку подписок", "manage_keys", None, 6, 0, 8, 2),
        ]

        for button_id, text, callback_data, url, row_pos, col_pos, sort_order, width in key_info_menu_buttons:
            cursor.execute("""
                INSERT INTO button_configs 
                (menu_type, button_id, text, callback_data, url, row_position, column_position, sort_order, button_width, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, ("key_info_menu", button_id, text, callback_data, url, row_pos, col_pos, sort_order, width))


# ==========================================


# ===== _ENSURE_RESET_SUBSCRIPTION_BUTTON =====
def _ensure_reset_subscription_button(cursor: sqlite3.Cursor) -> None:
    """
    Точечная миграция: добавляет кнопку "Пересоздать подписку" в key_info_menu
    для инсталляций, где это меню уже было засеяно раньше (до появления этой
    кнопки) и поэтому не попадает под _ensure_default_button_configs.
    Безопасна для повторного запуска.
    """
    try:
        cursor.execute(
            "SELECT 1 FROM button_configs WHERE menu_type = ? AND button_id = ? LIMIT 1",
            ("key_info_menu", "reset_sub"),
        )
        if cursor.fetchone():
            return

        cursor.execute(
            "SELECT COALESCE(MAX(row_position), -1), COALESCE(MAX(sort_order), -1) "
            "FROM button_configs WHERE menu_type = ?",
            ("key_info_menu",),
        )
        row = cursor.fetchone()
        next_row = (row[0] if row and row[0] is not None else -1) + 1
        next_sort = (row[1] if row and row[1] is not None else -1) + 1

        cursor.execute("""
            INSERT OR IGNORE INTO button_configs
            (menu_type, button_id, text, callback_data, url, row_position, column_position, sort_order, button_width, is_active)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1)
        """, ("key_info_menu", "reset_sub", "🔄 Пересоздать подписку", "reset_sub_confirm_{key_id}", next_row, 0, next_sort, 2))
        logging.info("Миграция: в key_info_menu добавлена кнопка 'reset_sub' (Пересоздать подписку)")
    except Exception as e:
        logging.warning(f"Миграция: не удалось добавить кнопку reset_sub в key_info_menu: {e}")

# ==============================================


# ===== _ENSURE_ADDON_DEVICES_BUTTON =====
def _ensure_addon_devices_button(cursor: sqlite3.Cursor) -> None:
    """
    Точечная миграция: добавляет кнопку "Докупить устройства" в key_info_menu
    для инсталляций, где меню уже засеяно и потому не попадает под
    _ensure_default_button_configs. Безопасна для повторного запуска.

    Место кнопки — сразу под "Продлить подписку": это соседнее действие, и
    искать его внизу меню никто не станет. Ради этого сдвигаем следующие
    строки на одну вниз, сохраняя их порядок.
    """
    try:
        cursor.execute(
            "SELECT 1 FROM button_configs WHERE menu_type = ? AND button_id = ? LIMIT 1",
            ("key_info_menu", "addon_devices"),
        )
        if cursor.fetchone():
            return

        def _anchor(condition: str, param) -> tuple | None:
            cursor.execute(
                "SELECT row_position, sort_order FROM button_configs "
                f"WHERE menu_type = ? AND ({condition}) AND is_active = 1 ORDER BY sort_order LIMIT 1",
                ("key_info_menu", param),
            )
            return cursor.fetchone()

        # Идентификаторы кнопок в конструкторе произвольные (админ мог
        # пересобрать меню), поэтому опознаём соседей по callback_data.
        after = _anchor("button_id = ? OR callback_data LIKE 'extend_key_%'", "extend")
        before = None if after else _anchor("button_id = ? OR callback_data = 'manage_keys'", "back")

        if after:
            row_pos, sort_order = (after[0] or 0) + 1, (after[1] or 0) + 1
        elif before:
            # Продления в меню нет — встаём хотя бы перед кнопкой «Назад»
            row_pos, sort_order = before[0] or 0, before[1] or 0
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(row_position), -1), COALESCE(MAX(sort_order), -1) "
                "FROM button_configs WHERE menu_type = ?",
                ("key_info_menu",),
            )
            row = cursor.fetchone()
            row_pos = (row[0] if row and row[0] is not None else -1) + 1
            sort_order = (row[1] if row and row[1] is not None else -1) + 1

        if after or before:
            cursor.execute(
                "UPDATE button_configs SET row_position = row_position + 1 WHERE menu_type = ? AND row_position >= ?",
                ("key_info_menu", row_pos),
            )
            cursor.execute(
                "UPDATE button_configs SET sort_order = sort_order + 1 WHERE menu_type = ? AND sort_order >= ?",
                ("key_info_menu", sort_order),
            )

        cursor.execute("""
            INSERT OR IGNORE INTO button_configs
            (menu_type, button_id, text, callback_data, url, row_position, column_position, sort_order, button_width, is_active)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1)
        """, ("key_info_menu", "addon_devices", "📱 Докупить устройства", "addon_dev_{key_id}", row_pos, 0, sort_order, 2))
        logging.info("Миграция: в key_info_menu добавлена кнопка 'addon_devices' (Докупить устройства)")
    except Exception as e:
        logging.warning(f"Миграция: не удалось добавить кнопку addon_devices в key_info_menu: {e}")

# ==============================================


# ===== _ENSURE_WHEEL_BUTTON =====
def _ensure_wheel_button(cursor: sqlite3.Cursor) -> None:
    """Кнопка колеса в главном меню для уже засеянных инсталляций.

    Ставим её перед входом в админку — там же, где остальные развлекательные
    пункты, а не последним пунктом после «Назад». Саму кнопку клавиатура
    показывает только когда колесо включено в настройках.
    """
    try:
        cursor.execute(
            "SELECT 1 FROM button_configs WHERE menu_type = ? AND button_id = ? LIMIT 1",
            ("main_menu", "wheel"),
        )
        if cursor.fetchone():
            return

        cursor.execute(
            "SELECT row_position, sort_order FROM button_configs "
            "WHERE menu_type = ? AND (button_id = ? OR callback_data = 'admin_menu') "
            "AND is_active = 1 ORDER BY sort_order LIMIT 1",
            ("main_menu", "admin"),
        )
        anchor = cursor.fetchone()

        if anchor:
            row_pos, sort_order = anchor[0] or 0, anchor[1] or 0
            cursor.execute(
                "UPDATE button_configs SET row_position = row_position + 1 WHERE menu_type = ? AND row_position >= ?",
                ("main_menu", row_pos),
            )
            cursor.execute(
                "UPDATE button_configs SET sort_order = sort_order + 1 WHERE menu_type = ? AND sort_order >= ?",
                ("main_menu", sort_order),
            )
        else:
            cursor.execute(
                "SELECT COALESCE(MAX(row_position), -1), COALESCE(MAX(sort_order), -1) "
                "FROM button_configs WHERE menu_type = ?",
                ("main_menu",),
            )
            row = cursor.fetchone()
            row_pos = (row[0] if row and row[0] is not None else -1) + 1
            sort_order = (row[1] if row and row[1] is not None else -1) + 1

        cursor.execute("""
            INSERT OR IGNORE INTO button_configs
            (menu_type, button_id, text, callback_data, url, row_position, column_position, sort_order, button_width, is_active)
            VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 1)
        """, ("main_menu", "wheel", "🎰 Колесо удачи", "wheel_open", row_pos, 0, sort_order, 2))
        logging.info("Миграция: в main_menu добавлена кнопка 'wheel' (Колесо удачи)")
    except Exception as e:
        logging.warning(f"Миграция: не удалось добавить кнопку колеса: {e}")

# ==============================================


# ===== _ENSURE_SSH_TARGETS_TABLE =====
def _ensure_ssh_targets_table(cursor: sqlite3.Cursor) -> None:
    """Миграция: создать таблицу speedtest_ssh_targets при необходимости и добавить недостающие столбцы."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS speedtest_ssh_targets (
            target_name TEXT PRIMARY KEY,
            ssh_host TEXT NOT NULL,
            ssh_port INTEGER DEFAULT 22,
            ssh_user TEXT,
            ssh_password TEXT,
            ssh_key_path TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            metadata TEXT,
            time_auto TEXT DEFAULT '{}'
        )
    """)

    extras = {
        "ssh_host": "TEXT",
        "ssh_port": "INTEGER",
        "ssh_user": "TEXT",
        "ssh_password": "TEXT",
        "ssh_key_path": "TEXT",
        "description": "TEXT",
        "is_active": "INTEGER DEFAULT 1",
        "sort_order": "INTEGER DEFAULT 0",
        "metadata": "TEXT",
        "time_auto": "TEXT DEFAULT '{}'",
    }
    for column, definition in extras.items():
        _ensure_table_column(cursor, "speedtest_ssh_targets", column, definition)


# =====================================


# ===== _ENSURE_GIFT_TOKENS_TABLE =====
def _ensure_support_media_table(cursor: sqlite3.Cursor) -> None:
    """
    Вложения в тикетах поддержки.

    Гибридное хранение: держим и file_id Telegram, и локальную копию.
    file_id позволяет мгновенно переслать файл обратно в Telegram без
    выгрузки, локальный файл — показать вложение в админ-панели и не
    потерять его при смене токена бота.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS support_media (
            media_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            message_id INTEGER,
            sender TEXT NOT NULL DEFAULT 'user',
            kind TEXT NOT NULL DEFAULT 'photo',
            file_id TEXT,
            file_unique_id TEXT,
            local_path TEXT,
            file_name TEXT,
            mime_type TEXT,
            file_size INTEGER DEFAULT 0,
            width INTEGER,
            height INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_index(cursor, "idx_support_media_ticket", "support_media", "ticket_id")
    _ensure_index(cursor, "idx_support_media_message", "support_media", "message_id")


def _ensure_email_codes_table(cursor: sqlite3.Cursor) -> None:
    """Коды подтверждения почты и сброса пароля.

    Раньше коды сброса жили в словаре в памяти процесса: перезапуск бота (в том
    числе автоматический после правки настроек) стирал их, и пользователь
    получал «Код не запрашивался» на верный код.
    """
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS email_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            purpose TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            attempts INTEGER DEFAULT 0,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )
        """
    )
    _ensure_index(cursor, "idx_email_codes_lookup", "email_codes", "email, purpose")


def _ensure_username_history_table(cursor: sqlite3.Cursor) -> None:
    """История имён пользователей: каждое обновление — новая запись."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS username_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            previous_username TEXT,
            source TEXT DEFAULT 'telegram',
            changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    _ensure_index(cursor, "idx_username_history_user", "username_history", "user_id")


def _ensure_gift_tokens_table(cursor: sqlite3.Cursor) -> None:
    """Миграция для таблиц подарочных токенов."""
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_tokens (
            token TEXT PRIMARY KEY,
            host_name TEXT NOT NULL,
            days INTEGER NOT NULL,
            activation_limit INTEGER DEFAULT 1,
            activations_used INTEGER DEFAULT 0,
            expires_at TIMESTAMP,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_claimed_at TIMESTAMP,
            comment TEXT
        )
        """
    )
    _ensure_index(cursor, "idx_gift_tokens_host", "gift_tokens", "host_name")
    _ensure_index(cursor, "idx_gift_tokens_expires", "gift_tokens", "expires_at")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS gift_token_claims (
            claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            key_id INTEGER,
            claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(token) REFERENCES gift_tokens(token) ON DELETE CASCADE
        )
        """
    )
    _ensure_index(cursor, "idx_gift_token_claims_token", "gift_token_claims", "token")
    _ensure_index(cursor, "idx_gift_token_claims_user", "gift_token_claims", "user_id")


# =====================================


# ===== GET_USER_ID_BY_GIFT_TOKEN =====
def get_user_id_by_gift_token(token: str) -> int | None:
    row = _fetch_row("SELECT user_id FROM gift_token_claims WHERE token = ? ORDER BY claimed_at DESC LIMIT 1", (token,), f"Ошибка поиска user_id по токену {token}")
    return row["user_id"] if row else None
# =====================================


# ===== _ENSURE_SELLER_USERS_TABLE =====
def _ensure_seller_users_table(cursor: sqlite3.Cursor) -> None:
    """Миграция для таблицы seller_users."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS seller_users (
            id_seller INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_sale REAL DEFAULT 0,
            seller_ref REAL DEFAULT 0,
            seller_uuid TEXT DEFAULT '0',
            user_id INTEGER UNIQUE
        )
    ''')
    
    mapping = {
        "seller_sale": "REAL DEFAULT 0",
        "seller_ref": "REAL DEFAULT 0",
        "seller_uuid": "TEXT DEFAULT '0'",
        "user_id": "INTEGER UNIQUE"
    }
    for column, definition in mapping.items():
        _ensure_table_column(cursor, "seller_users", column, definition)

    _ensure_unique_index(cursor, "idx_seller_users_user_id", "seller_users", "user_id")
# ====================================


# ===== _ENSURE_PROMO_TABLES =====
def _ensure_promo_tables(cursor: sqlite3.Cursor) -> None:
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            discount_percent REAL,
            discount_amount REAL,
            promo_type TEXT DEFAULT 'discount',
            reward_value INTEGER DEFAULT 0,
            usage_limit_total INTEGER,
            usage_limit_per_user INTEGER,
            used_total INTEGER DEFAULT 0,
            valid_from TIMESTAMP,
            valid_until TIMESTAMP,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        )
        """
    )
    
    mapping = {
        "promo_type": "TEXT DEFAULT 'discount'",
        "reward_value": "INTEGER DEFAULT 0"
    }
    for column, definition in mapping.items():
        _ensure_table_column(cursor, "promo_codes", column, definition)

    _ensure_index(cursor, "idx_promo_codes_valid", "promo_codes", "valid_until")
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_code_usages (
            usage_id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            applied_amount REAL,
            order_id TEXT,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(code) REFERENCES promo_codes(code) ON DELETE CASCADE
        )
        """
    )
    _ensure_index(cursor, "idx_promo_code_usages_code", "promo_code_usages", "code")
    _ensure_index(cursor, "idx_promo_code_usages_user", "promo_code_usages", "user_id")


# =================================


# ===== _ENSURE_HOST_SPEEDTESTS_TABLE =====
def _ensure_host_speedtests_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS host_speedtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_name TEXT NOT NULL,
            method TEXT NOT NULL,
            ping_ms REAL,
            jitter_ms REAL,
            download_mbps REAL,
            upload_mbps REAL,
            server_name TEXT,
            server_id TEXT,
            ok INTEGER NOT NULL DEFAULT 1,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_host_speedtests_host_time ON host_speedtests(host_name, created_at DESC)")


# =========================================


# ===== _ENSURE_RESOURCE_METRICS_TABLE =====
def _ensure_resource_metrics_table(cursor: sqlite3.Cursor) -> None:
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS resource_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,                -- 'local' | 'host' | 'target'
            object_name TEXT NOT NULL,          -- 'panel' | host_name | target_name
            cpu_percent REAL,
            mem_percent REAL,
            disk_percent REAL,
            load1 REAL,
            net_bytes_sent INTEGER,
            net_bytes_recv INTEGER,
            raw_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_resource_metrics_scope_time ON resource_metrics(scope, object_name, created_at DESC)")




# ==========================================


# ===== INSERT_RESOURCE_METRIC =====
def insert_resource_metric(
    scope: str,
    object_name: str,
    cpu_percent: float | None = None,
    mem_percent: float | None = None,
    disk_percent: float | None = None,
    load1: float | None = None,
    net_bytes_sent: int | None = None,
    net_bytes_recv: int | None = None,
    raw_json: str | None = None
) -> int | None:
    cursor = _exec(
        """
        INSERT INTO resource_metrics (
            scope, object_name, cpu_percent, mem_percent, disk_percent, load1, 
            net_bytes_sent, net_bytes_recv, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (scope or '').strip(), (object_name or '').strip(),
            cpu_percent, mem_percent, disk_percent, load1, 
            net_bytes_sent, net_bytes_recv, raw_json
        ),
        f"Не удалось сохранить метрики ресурсов scope={scope} object={object_name}"
    )
    return cursor.lastrowid if cursor else None


# ==================================


# ===== GET_LATEST_RESOURCE_METRIC =====
def get_latest_resource_metric(scope: str, object_name: str) -> dict | None:
    return _fetch_row(
        """
        SELECT * FROM resource_metrics
        WHERE scope = ? AND object_name = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        ((scope or '').strip(), (object_name or '').strip()),
        f"Не удалось получить последние метрики ресурсов scope={scope} object={object_name}"
    )


# ======================================


# ===== GET_RESOURCE_METRICS =====
def get_resource_metrics(
    scope: str,
    object_name: str,
    limit: int = 20
) -> list[dict]:
    return _fetch_list(
        """
        SELECT *
        FROM resource_metrics
        WHERE scope = ? AND object_name = ?
        ORDER BY datetime(created_at) DESC
        LIMIT ?
        """,
        ((scope or '').strip(), (object_name or '').strip(), limit),
        f"Не удалось получить метрики ресурсов scope={scope} object={object_name}"
    )


# ==============================


# ===== GET_METRICS_SERIES =====
def get_metrics_series(scope: str, object_name: str, *, since_hours: int = 24, limit: int = 500) -> list[dict]:
    if since_hours == 1:
        hours_filter = 2
    else:
        hours_filter = max(1, int(since_hours))
    
    rows = _fetch_list(
        f'''
        SELECT created_at, cpu_percent, mem_percent, disk_percent, load1
        FROM resource_metrics
        WHERE scope = ? AND object_name = ?
            AND created_at >= datetime('now', '+3 hours', ?)
        ORDER BY created_at ASC
        LIMIT ?
        ''',
        (
            (scope or '').strip(),
            (object_name or '').strip(),
            f'-{hours_filter} hours',
            max(10, int(limit)),
        ),
        f"Не удалось получить серию метрик для {scope}/{object_name}"
    )
    logging.debug(f"get_metrics_series: {scope}/{object_name}, since_hours={since_hours}, found {len(rows)} records")
    return rows




# ==============================


# ===== CREATE_HOST =====
def create_host(name: str, url: str, user: str, passwd: str, inbound: int, subscription_url: str | None = None):
    name = normalize_host_name(name)
    url = (url or "").strip()
    user = (user or "").strip()
    passwd = passwd or ""
    try:
        inbound = int(inbound)
    except Exception:
        pass
    subscription_url = (subscription_url or None)

    cursor = _exec(
         "INSERT INTO xui_hosts (host_name, host_url, host_username, host_pass, host_inbound_id, subscription_url) VALUES (?, ?, ?, ?, ?, ?)",
         (name, url, user, passwd, inbound, subscription_url),
         ""
    )
    if cursor:
        logging.info(f"Успешно создан новый хост: {name}")
        return

    cursor = _exec(
         "INSERT INTO xui_hosts (host_name, host_url, host_username, host_pass, host_inbound_id) VALUES (?, ?, ?, ?, ?)",
         (name, url, user, passwd, inbound),
         f"Ошибка при создании хоста '{name}'"
    )
    if cursor:
         logging.info(f"Успешно создан новый хост (fallback): {name}")

# =======================


# ===== UPDATE_HOST_SUBSCRIPTION_URL =====
def update_host_subscription_url(host_name: str, subscription_url: str | None) -> bool:
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET subscription_url = ? WHERE TRIM(host_name) = TRIM(?)",
        (subscription_url, host_name),
        f"Не удалось обновить subscription_url для хоста '{host_name}'"
    )
    return _check_rowcount(cursor, f"хост '{host_name}'", "update_host_subscription_url")
# ========================================

# ===== UPDATE_HOST_DESCRIPTION =====

# ===== UPDATE_HOST_DESCRIPTION =====
# Обновление описания хоста
def update_host_description(host_name: str, description: str | None) -> bool:
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET description = ? WHERE TRIM(host_name) = TRIM(?)",
        (description, host_name),
        f"Не удалось обновить описание для хоста '{host_name}'"
    )
    return _check_rowcount(cursor, f"хост '{host_name}'", "update_host_description")
# ===================================

# ===== UPDATE_HOST_TRAFFIC_SETTINGS =====

# ===== UPDATE_HOST_TRAFFIC_SETTINGS =====
# Обновление стратегии лимита трафика для хоста
# Default: 'NO_RESET'
def update_host_traffic_settings(host_name: str, traffic_strategy: str | None = 'NO_RESET') -> bool:
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET default_traffic_strategy = ? WHERE TRIM(host_name) = TRIM(?)",
        (traffic_strategy or 'NO_RESET', host_name),
        f"Не удалось обновить настройки трафика для хоста '{host_name}'"
    )
    return _check_rowcount(cursor, f"хост '{host_name}'", "update_host_traffic_settings")
# ========================================


# ===== SET_REFERRAL_START_BONUS_RECEIVED =====
def set_referral_start_bonus_received(user_id: int) -> bool:
    return _check_rowcount(_exec(
        "UPDATE users SET referral_start_bonus_received = 1 WHERE telegram_id = ?",
        (user_id,),
        f"Не удалось установить бонус реферала для пользователя {user_id}"
    ), f"пользователь {user_id}", "")
# =============================================


# ===== UPDATE_HOST_URL =====
# Обновление URL хоста
def update_host_url(host_name: str, new_url: str) -> bool:
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET host_url = ? WHERE TRIM(host_name) = TRIM(?)",
        (new_url, host_name),
        f"Не удалось обновить URL для хоста '{host_name}'"
    )
    return _check_rowcount(cursor, f"хост '{host_name}'", "update_host_url")
# ===========================


# ===== ADD_SELLER_USER =====
def add_seller_user(user_id: int, seller_sale: float = 0, seller_ref: float = 0, seller_uuid: str = "0") -> int | None:
    cursor = _exec(
        """
        INSERT OR REPLACE INTO seller_users (user_id, seller_sale, seller_ref, seller_uuid) 
        VALUES (?, ?, ?, ?)
        """,
        (user_id, seller_sale, seller_ref, str(seller_uuid)),
        "Не удалось добавить продавца"
    )
    return cursor.lastrowid if cursor else None

# =======================


# ===== GET_SELLER_USER =====
def get_seller_user(user_id: int) -> dict | None:
    row = _fetch_row("SELECT * FROM seller_users WHERE user_id = ?", (user_id,), f"Не удалось получить продавца {user_id}")
    if not row:
        return {
            "user_id": user_id,
            "seller_sale": 0.0,
            "seller_ref": 0.0,
            "seller_uuid": "0",
        }
    return row

# =======================


# ===== DELETE_SELLER_USER =====
def delete_seller_user(user_id: int) -> bool:
    cursor = _exec("DELETE FROM seller_users WHERE user_id = ?", (user_id,), f"Не удалось удалить продавца {user_id}")
    return cursor is not None

# ==========================


# ===== UPDATE_HOST_REMNAWAVE_SETTINGS =====
def update_host_remnawave_settings(
    host_name: str,
    *,
    remnawave_base_url: str | None = None,
    remnawave_api_token: str | None = None,
    squad_uuid: str | None = None,
) -> bool:
    host_name_n = normalize_host_name(host_name)
    row = _fetch_row("SELECT 1 FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (host_name_n,), "")
    if not row:
        logging.warning(f"update_host_remnawave_settings: хост не найден '{host_name_n}'")
        return False

    sets: list[str] = []
    params: list[Any] = []
    if remnawave_base_url is not None:
        value = (remnawave_base_url or '').strip() or None
        sets.append("remnawave_base_url = ?")
        params.append(value)
    if remnawave_api_token is not None:
        value = (remnawave_api_token or '').strip() or None
        sets.append("remnawave_api_token = ?")
        params.append(value)
    if squad_uuid is not None:
        value = (squad_uuid or '').strip() or None
        sets.append("squad_uuid = ?")
        params.append(value)
    
    if not sets:
        return True
    
    params.append(host_name_n)
    sql = f"UPDATE xui_hosts SET {', '.join(sets)} WHERE TRIM(host_name) = TRIM(?)"
    cursor = _exec(sql, params, f"Не удалось обновить Remnawave-настройки для хоста '{host_name}'")
    return cursor is not None

# ========================================


# ===== UPDATE_HOST_SSH_SETTINGS =====
def update_host_ssh_settings(
    host_name: str,
    ssh_host: str | None = None,
    ssh_port: int | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
) -> bool:
    host_name_n = normalize_host_name(host_name)
    row = _fetch_row("SELECT 1 FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (host_name_n,), "")
    if not row:
        logging.warning(f"update_host_ssh_settings: хост не найден '{host_name_n}'")
        return False

    cursor = _exec(
        """
        UPDATE xui_hosts
        SET ssh_host = ?, ssh_port = ?, ssh_user = ?, ssh_password = ?, ssh_key_path = ?
        WHERE TRIM(host_name) = TRIM(?)
        """,
        (
            (ssh_host or None),
            (int(ssh_port) if ssh_port is not None else None),
            (ssh_user or None),
            (ssh_password if ssh_password is not None else None),
            (ssh_key_path or None),
            host_name_n,
        ),
        f"Не удалось обновить SSH-параметры для хоста '{host_name}'"
    )
    return cursor is not None
# ====================================


# ===== UPDATE_HOST_NAME =====
def update_host_name(old_name: str, new_name: str) -> bool:
    old_n = normalize_host_name(old_name)
    new_n = normalize_host_name(new_name)
    if not old_n or not new_n:
        return False
    if old_n == new_n:
        return True

    row = _fetch_row("SELECT 1 FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (old_n,), "")
    if not row:
        logging.warning(f"update_host_name: исходный хост не найден '{old_n}'")
        return False

    row_new = _fetch_row("SELECT 1 FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (new_n,), "")
    if row_new:
        logging.warning(f"update_host_name: новое имя занято '{new_n}'")
        return False

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute(
                "UPDATE xui_hosts SET host_name = ? WHERE TRIM(host_name) = TRIM(?)",
                (new_n, old_n)
            )
            cursor.execute(
                "UPDATE plans SET host_name = ? WHERE TRIM(host_name) = TRIM(?)",
                (new_n, old_n)
            )
            cursor.execute(
                "UPDATE vpn_keys SET host_name = ? WHERE TRIM(host_name) = TRIM(?)",
                (new_n, old_n)
            )
            cursor.execute(
                "UPDATE host_speedtests SET host_name = ? WHERE TRIM(host_name) = TRIM(?)",
                (new_n, old_n)
            )
            conn.commit()
            cursor.execute("PRAGMA foreign_keys=ON")
            return True
    except sqlite3.Error as e: logging.error(f"Не удалось переименовать хост '{old_name}' -> '{new_name}': {e}"); return False

# ===== DELETE_HOST =====
# Удаление хоста и всех связанных тарифов
def delete_host(host_name: str):
    try:
        host_name = normalize_host_name(host_name)
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM plans WHERE TRIM(host_name) = TRIM(?)", (host_name,))
            cursor.execute("DELETE FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (host_name,))
            conn.commit()
            logging.info(f"Хост '{host_name}' и его тарифы успешно удалены.")
    except sqlite3.Error as e: logging.error(f"Ошибка удаления хоста '{host_name}': {e}")
# =========================


# ===== GET_HOST =====
# Получение информации о хосте по имени
# Fallback: None если хост не найден
def get_host(host_name: str) -> dict | None:
    try:
        host_name = normalize_host_name(host_name)
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (host_name,))
            result = cursor.fetchone(); return dict(result) if result else None
    except sqlite3.Error as e: logging.error(f"Ошибка получения хоста '{host_name}': {e}"); return None
# ==================


# ===== TOGGLE_HOST_VISIBILITY =====
# Переключение видимости хоста (поле see)
def toggle_host_visibility(host_name: str, visible: int) -> bool:
    host_name_n = normalize_host_name(host_name)
    visible_int = 1 if visible else 0
    row = _fetch_row("SELECT 1 FROM xui_hosts WHERE TRIM(host_name) = TRIM(?)", (host_name_n,), "")
    if not row: logging.warning(f"toggle_host_visibility: хост не найден '{host_name_n}'"); return False
    cursor = _exec(
        "UPDATE xui_hosts SET see = ? WHERE TRIM(host_name) = TRIM(?)",
        (visible_int, host_name_n),
        f"Не удалось обновить видимость для хоста '{host_name}'"
    )
    if cursor and cursor.rowcount > 0: logging.info(f"Видимость хоста '{host_name_n}' обновлена: see={visible_int}")
    return _check_rowcount(cursor, f"хост '{host_name_n}'", "")
# ==================================


def get_device_tiers(host_name: str) -> list[dict]:
    return _fetch_list("SELECT * FROM device_tiers WHERE TRIM(host_name)=TRIM(?) ORDER BY sort_order, device_count", (host_name,))

def add_device_tier(host_name: str, device_count: int, price: float) -> int | None:
    r = _exec("INSERT OR REPLACE INTO device_tiers (host_name, device_count, price) VALUES (?,?,?)", (host_name, device_count, price))
    return r.lastrowid if r else None

def update_device_tier(tier_id: int, device_count: int, price: float) -> bool:
    r = _exec("UPDATE device_tiers SET device_count=?, price=? WHERE tier_id=?", (device_count, price, tier_id))
    return r is not None and r.rowcount > 0

def delete_device_tier(tier_id: int) -> bool:
    r = _exec("DELETE FROM device_tiers WHERE tier_id=?", (tier_id,))
    return r is not None and r.rowcount > 0

def get_device_tier_by_id(tier_id: int) -> dict | None:
    return _fetch_row("SELECT * FROM device_tiers WHERE tier_id=?", (tier_id,))

def update_host_device_mode(host_name: str, mode: str) -> bool:
    r = _exec("UPDATE xui_hosts SET device_mode=? WHERE TRIM(host_name)=TRIM(?)", (mode, host_name))
    return r is not None and r.rowcount > 0


# ===== DELETE_KEY_BY_ID =====
# Удаление ключа по key_id
def delete_key_by_id(key_id: int) -> bool:
    return _check_rowcount(_exec("DELETE FROM vpn_keys WHERE key_id = ?", (key_id,), f"Не удалось удалить ключ по id {key_id}"), f"ключ {key_id}", "")
# ============================


# ===== UPDATE_KEY_COMMENT =====
# Обновление комментария (description) для ключа
def update_key_comment(key_id: int, comment: str) -> bool:
    return _check_rowcount(_exec("UPDATE vpn_keys SET description = ? WHERE key_id = ?", (comment, key_id), f"Не удалось обновить комментарий ключа для {key_id}"), f"ключ {key_id}", "")
# ==============================


# ===== GET_ALL_HOSTS =====
def get_all_hosts(visible_only: bool = False) -> list[dict]:
    # Сначала пытаемся выполнить запрос
    sql = "SELECT * FROM xui_hosts ORDER BY sort_order ASC, host_name ASC"
    if visible_only: sql = "SELECT * FROM xui_hosts WHERE see = 1 ORDER BY sort_order ASC, host_name ASC"
    
    rows = _fetch_list(sql, (), "")
    if not rows:
        # Если пусто или ошибка, возможно нет колонки see (хотя миграция должна была сработать)
        # Пробуем через старый механизм fallback только если реально была ошибка
        # Но у нас _fetch_list возвращает [], так что сложно отличить "пусто" от "ошибка".
        # Однако, раз мы строго следим за миграциями, колонка see должна быть.
        # Если ошибка была, она залогировалась в _fetch_list.
        pass

    result = []
    for row in rows:
        d = dict(row)
        d['host_name'] = normalize_host_name(d.get('host_name'))
        result.append(d)
    return result

# =========================


# ===== GET_SPEEDTESTS =====
def get_speedtests(host_name: str, limit: int = 20) -> list[dict]:
    host_name_n = normalize_host_name(host_name)
    try:
        limit_int = int(limit)
    except Exception: limit_int = 20
        
    return _fetch_list(
        """
        SELECT id, host_name, method, ping_ms, jitter_ms, download_mbps, upload_mbps,
               server_name, server_id, ok, error, created_at
        FROM host_speedtests
        WHERE TRIM(host_name) = TRIM(?)
        ORDER BY datetime(created_at) DESC
        LIMIT ?
        """,
        (host_name_n, limit_int),
        f"Не удалось получить speedtest-данные для хоста '{host_name}'"
    )

# ========================


# ===== GET_LATEST_SPEEDTEST =====
def get_latest_speedtest(host_name: str) -> dict | None:
    host_name_n = normalize_host_name(host_name)
    return _fetch_row(
        """
        SELECT id, host_name, method, ping_ms, jitter_ms, download_mbps, upload_mbps,
               server_name, server_id, ok, error, created_at
        FROM host_speedtests
        WHERE TRIM(host_name) = TRIM(?)
        ORDER BY datetime(created_at) DESC
        LIMIT 1
        """,
        (host_name_n,),
        f"Не удалось получить последний speedtest для хоста '{host_name}'"
    )

# ===== INSERT_HOST_SPEEDTEST =====
def insert_host_speedtest(
    host_name: str,
    method: str,
    ping_ms: float | None = None,
    jitter_ms: float | None = None,
    download_mbps: float | None = None,
    upload_mbps: float | None = None,
    server_name: str | None = None,
    server_id: str | None = None,
    ok: bool = True,
    error: str | None = None
) -> int | None:
    host_name_n = normalize_host_name(host_name)
    cursor = _exec(
        """
        INSERT INTO host_speedtests (host_name, method, ping_ms, jitter_ms, download_mbps, upload_mbps, server_name, server_id, ok, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (host_name_n, method, ping_ms, jitter_ms, download_mbps, upload_mbps, server_name, server_id, 1 if ok else 0, error),
        f"Не удалось сохранить запись speedtest для '{host_name}'"
    )
    return cursor.lastrowid if cursor else None






# ===== GET_ALL_SSH_TARGETS =====
def get_all_ssh_targets() -> list[dict]:
    return _fetch_list("SELECT * FROM speedtest_ssh_targets ORDER BY sort_order ASC, target_name ASC", (), "Не удалось получить список SSH-целей")


# ===========================


# ===== GET_SSH_TARGET =====
def get_ssh_target(target_name: str) -> dict | None:
    name = normalize_host_name(target_name)
    return _fetch_row("SELECT * FROM speedtest_ssh_targets WHERE TRIM(target_name) = TRIM(?)", (name,), f"Не удалось получить SSH-цель '{target_name}'")


# ========================


# ===== CREATE_SSH_TARGET =====
# Создание новой SSH-цели для speedtest
def create_ssh_target(
    target_name: str,
    ssh_host: str,
    ssh_port: int | None = 22,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    description: str | None = None,
    *,
    sort_order: int | None = 0,
    is_active: int | None = 1,
) -> bool:
    name = normalize_host_name(target_name)
    cursor = _exec(
        """
        INSERT INTO speedtest_ssh_targets
            (target_name, ssh_host, ssh_port, ssh_user, ssh_password, ssh_key_path, description, is_active, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            (ssh_host or '').strip(),
            int(ssh_port) if ssh_port is not None else None,
            (ssh_user or None),
            (ssh_password if ssh_password is not None else None),
            (ssh_key_path or None),
            (description or None),
            1 if (is_active is None or int(is_active) != 0) else 0,
            int(sort_order or 0),
        ),
        f"Не удалось создать SSH-цель '{target_name}'"
    )
    return cursor is not None
# ===========================


# ===== UPDATE_SSH_TARGET_FIELDS =====
# Обновление полей SSH-цели (выборочное обновление)
# Параметры с None не обновляются
def update_ssh_target_fields(
    target_name: str,
    *,
    ssh_host: str | None = None,
    ssh_port: int | None = None,
    ssh_user: str | None = None,
    ssh_password: str | None = None,
    ssh_key_path: str | None = None,
    description: str | None = None,
    sort_order: int | None = None,
    is_active: int | None = None,
) -> bool:
    name = normalize_host_name(target_name)
    row = _fetch_row("SELECT 1 FROM speedtest_ssh_targets WHERE TRIM(target_name) = TRIM(?)", (name,), "")
    if not row: logging.warning(f"update_ssh_target_fields: цель не найдена '{name}'"); return False
        
    sets: list[str] = []
    params: list[Any] = []
    if ssh_host is not None:
        sets.append("ssh_host = ?")
        params.append((ssh_host or '').strip())
    if ssh_port is not None:
        try:
            val = int(ssh_port)
        except Exception:
            val = None
        sets.append("ssh_port = ?")
        params.append(val)
    if ssh_user is not None:
        sets.append("ssh_user = ?")
        params.append(ssh_user or None)
    if ssh_password is not None:
        sets.append("ssh_password = ?")
        params.append(ssh_password)
    if ssh_key_path is not None:
        sets.append("ssh_key_path = ?")
        params.append(ssh_key_path or None)
    if description is not None:
        sets.append("description = ?")
        params.append(description or None)
    if sort_order is not None:
        try:
            so = int(sort_order)
        except Exception:
            so = 0
        sets.append("sort_order = ?")
        params.append(so)
    if is_active is not None:
        sets.append("is_active = ?")
        params.append(1 if int(is_active) != 0 else 0)
    
    if not sets: return True
    
    params.append(name)
    sql = f"UPDATE speedtest_ssh_targets SET {', '.join(sets)} WHERE TRIM(target_name) = TRIM(?)"
    cursor = _exec(sql, params, f"Не удалось обновить SSH-цель '{target_name}'")
    return cursor is not None








# ===== DELETE_SSH_TARGET =====
# Удаление SSH-цели по имени
def delete_ssh_target(target_name: str) -> bool:
    return _check_rowcount(_exec(
        "DELETE FROM speedtest_ssh_targets WHERE TRIM(target_name) = TRIM(?)",
        (normalize_host_name(target_name),),
        f"Не удалось удалить SSH-цель '{target_name}'"
    ), f"SSH-цель '{target_name}'", "")
# =============================


# ===== RENAME_SSH_TARGET =====
# Переименование SSH-цели с обновлением связанных speedtest-записей
def rename_ssh_target(old_target_name: str, new_target_name: str) -> bool:
    old_name = normalize_host_name(old_target_name)
    new_name = normalize_host_name(new_target_name)
    
    if old_name == new_name: return True
    
    row = _fetch_row("SELECT 1 FROM speedtest_ssh_targets WHERE TRIM(target_name) = TRIM(?)", (old_name,), "")
    if not row: logging.warning(f"rename_ssh_target: старая цель не найдена '{old_name}'"); return False
    
    row_new = _fetch_row("SELECT 1 FROM speedtest_ssh_targets WHERE TRIM(target_name) = TRIM(?)", (new_name,), "")
    if row_new: logging.warning(f"rename_ssh_target: новое имя уже занято '{new_name}'"); return False
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE speedtest_ssh_targets SET target_name = ? WHERE TRIM(target_name) = TRIM(?)",
                (new_name, old_name)
            )
            cursor.execute(
                "UPDATE host_speedtests SET host_name = ? WHERE TRIM(host_name) = TRIM(?)",
                (new_name, old_name)
            )
            conn.commit()
            logging.info(f"SSH-цель переименована: '{old_name}' → '{new_name}'")
            return True
    except sqlite3.Error as e: logging.error(f"Не удалось переименовать SSH-цель '{old_target_name}' → '{new_target_name}': {e}"); return False



# ===== GET_ADMIN_STATS =====
# Получение статистики для админ-панели
# Возвращает: total_users, total_keys, active_keys, total_income, today_new_users, today_income, today_issued_keys
def get_admin_stats() -> dict:
    stats = {}
    stats["total_users"] = _get_count_stat("SELECT COUNT(*) as c FROM users")
    stats["total_keys"] = _get_count_stat("SELECT COUNT(*) as c FROM vpn_keys")
    stats["active_keys"] = _get_count_stat("SELECT COUNT(*) as c FROM vpn_keys WHERE expire_at IS NOT NULL AND datetime(expire_at) > CURRENT_TIMESTAMP")
    stats["total_income"] = float(_get_count_stat("""
        SELECT COALESCE(SUM(amount_rub), 0) as s FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid','completed','success','succeeded')
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
    """))
    stats["today_new_users"] = _get_count_stat("SELECT COUNT(*) as c FROM users WHERE date(registration_date) = date('now', '+3 hours')")
    stats["today_income"] = float(_get_count_stat("""
        SELECT COALESCE(SUM(amount_rub), 0) as s FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid','completed','success','succeeded')
          AND date(created_date) = date('now', '+3 hours') 
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
    """))
    stats["today_topups"] = float(_get_count_stat("""
        SELECT COALESCE(SUM(amount_rub), 0) as s FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid','completed','success','succeeded')
          AND date(created_date) = date('now', '+3 hours')
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
          AND (
              LOWER(COALESCE(json_extract(metadata, '$.action'), '')) IN ('topup', 'top_up')
              OR LOWER(COALESCE(json_extract(metadata, '$.reason'), '')) = 'external_balance_top_up'
          )
    """))
    stats["today_subscription_purchases"] = float(_get_count_stat("""
        SELECT COALESCE(SUM(amount_rub), 0) as s FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid','completed','success','succeeded')
          AND date(created_date) = date('now', '+3 hours')
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
          AND (
              LOWER(COALESCE(json_extract(metadata, '$.action'), '')) IN ('new', 'extend')
              OR LOWER(COALESCE(json_extract(metadata, '$.reason'), '')) = 'subscription_purchase_or_extend'
          )
    """))
    stats["today_bought_keys"] = _get_count_stat("""
        SELECT COUNT(*) as c FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid','completed','success','succeeded')
          AND date(created_date) = date('now', '+3 hours')
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
          AND LOWER(COALESCE(json_extract(metadata, '$.action'), '')) = 'new'
    """)
    stats["today_trials"] = _get_count_stat("""
        SELECT COUNT(*) as c FROM vpn_keys
        WHERE COALESCE(key_email, '') LIKE 'trial_%'
          AND date(COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)) = date('now', '+3 hours')
    """)
    return stats
# =======================

# ===== GET_ALL_KEYS =====
# Получение всех ключей из БД с нормализацией
def get_all_keys() -> list[dict]:
    rows = _fetch_list("SELECT * FROM vpn_keys ORDER BY key_id DESC", (), "Не удалось получить все ключи")
    return [_normalize_key_row(row) for row in rows]
# =========================


# ===== GET_KEYS_FOR_USER =====
def get_keys_for_user(user_id: int) -> list[dict]:
    return get_user_keys(user_id)

# =============================


# ===== UPDATE_KEY_EMAIL =====
def update_key_email(key_id: int, new_email: str) -> bool:
    normalized = _normalize_email(new_email) or new_email.strip()
    return update_key_fields(key_id, email=normalized)

# ============================


# ===== UPDATE_KEY_HOST =====
def update_key_host(key_id: int, new_host_name: str) -> bool:
    return update_key_fields(key_id, host_name=new_host_name)

# ===========================


# ===== CREATE_GIFT_KEY =====
def create_gift_key(user_id: int, host_name: str, key_email: str, months: int, remnawave_user_uuid: str | None = None) -> int | None:
    try:
        from datetime import timedelta

        months_value = max(1, int(months or 1))
        expiry_dt = get_msk_time() + timedelta(days=30 * months_value)
        expiry_ms = int(expiry_dt.timestamp() * 1000)
        uuid_value = remnawave_user_uuid or f"GIFT-{user_id}-{int(get_msk_time().timestamp())}"
        return add_new_key(
            user_id=user_id,
            host_name=host_name,
            remnawave_user_uuid=uuid_value,
            key_email=key_email,
            expiry_timestamp_ms=expiry_ms,
        )
    except Exception as e:
        logging.error(f"Не удалось создать подарочный ключ для пользователя {user_id}: {e}")
        return None
# ===========================


# ===== GET_SETTING =====
def get_setting(key: str, default: str | None = None) -> str | None:
    row = _fetch_row("SELECT value FROM bot_settings WHERE key = ?", (key,), f"Не удалось получить настройку '{key}'")
    return row["value"] if row else default

# =======================


# ===== GET_ADMIN_IDS =====
def get_admin_ids() -> set[int]:
    ids: set[int] = set()
    try:
        single = get_setting("admin_telegram_id")
        if single:
            try:
                ids.add(int(single))
            except Exception:
                pass
        multi_raw = get_setting("admin_telegram_ids")
        if multi_raw:
            s = (multi_raw or "").strip()

            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    for v in arr:
                        try:
                            ids.add(int(v))
                        except Exception:
                            pass
                    return ids
            except Exception:
                pass

            parts = [p for p in re.split(r"[\s,]+", s) if p]
            for p in parts:
                try:
                    ids.add(int(p))
                except Exception:
                    pass
    except Exception as e:
        logging.warning(f"Ошибка get_admin_ids: {e}")
    return ids
# =========================


# ===== IS_ADMIN =====
def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in get_admin_ids()
    except Exception: return False


# ====================


# ===== CREATE_PAYLOAD_PENDING =====
def create_payload_pending(payment_id: str, user_id: int, amount_rub: float | None, metadata: dict | None) -> bool:
    print(f"[DEBUG] create_payload_pending called: payment_id={payment_id}, user_id={user_id}, amount_rub={amount_rub}, metadata={metadata}")
    cursor = _exec(
        """
        INSERT OR REPLACE INTO pending_transactions (payment_id, user_id, amount_rub, metadata, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, COALESCE((SELECT status FROM pending_transactions WHERE payment_id = ?), 'pending'),
                COALESCE((SELECT created_at FROM pending_transactions WHERE payment_id = ?), CURRENT_TIMESTAMP), CURRENT_TIMESTAMP)
        """,
        (payment_id, int(user_id), float(amount_rub) if amount_rub is not None else None, json.dumps(metadata or {}), payment_id, payment_id),
        f"Не удалось создать ожидающую транзакцию {payment_id}"
    )
    return cursor is not None
# ==============================


# ===== _GET_PENDING_METADATA =====
def _get_pending_metadata(payment_id: str) -> dict | None:
    row = _fetch_row("SELECT * FROM pending_transactions WHERE payment_id = ?", (payment_id,), f"Не удалось прочитать ожидающую транзакцию {payment_id}")
    if not row: return None
    try:
        meta = json.loads(row["metadata"] or "{}")
    except Exception: meta = {}

    meta.setdefault('payment_id', payment_id)
    return meta
# =================================


# ===== GET_PENDING_METADATA =====
def get_pending_metadata(payment_id: str) -> dict | None:
    return _get_pending_metadata(payment_id)


# ================================


# ===== GET_PENDING_STATUS =====
def get_pending_status(payment_id: str) -> str | None:
    row = _fetch_row("SELECT status FROM pending_transactions WHERE payment_id = ?", (payment_id,), f"Не удалось получить статус для ожидающей {payment_id}")
    return (row["status"] or '').strip() or None if row else None

# ==============================


# ===== _COMPLETE_PENDING =====
def _complete_pending(payment_id: str) -> bool:
    cursor = _exec(
        "UPDATE pending_transactions SET status = 'paid', updated_at = CURRENT_TIMESTAMP WHERE payment_id = ? AND status != 'paid'",
        (payment_id,),
        f"Не удалось завершить ожидающую транзакцию {payment_id}"
    )
    return cursor is not None and cursor.rowcount > 0
# ===========================


# ===== FIND_AND_COMPLETE_PENDING_TRANSACTION =====
def find_and_complete_pending_transaction(payment_id: str) -> dict | None:
    logging.info(f"🔍 Ищем ожидающую транзакцию: {payment_id}")
    meta = _get_pending_metadata(payment_id)
    if not meta: logging.warning(f"❌ Ожидающая транзакция не найдена: {payment_id}"); return None
    
    user_id = meta.get('user_id', 'неизвестно')
    amount = meta.get('price', 0)
    logging.info(f"✅ Найдена ожидающая транзакция: пользователь {user_id}, сумма {amount:.2f} RUB")
    
    success = _complete_pending(payment_id)
    if success:
        logging.info(f"✅ Транзакция отмечена как оплаченная: {payment_id}")
        return meta
    else:
        logging.warning(f"⚠️ Транзакция {payment_id} уже была оплачена или заблокирована (дубликат вебхука)")
        return None
# =================================================


# ===== GET_LATEST_PENDING_FOR_USER =====
def get_latest_pending_for_user(user_id: int) -> dict | None:
    row = _fetch_row(
        """
        SELECT payment_id, metadata FROM pending_transactions
        WHERE user_id = ? AND status = 'pending'
        ORDER BY datetime(created_at) DESC, datetime(updated_at) DESC
        LIMIT 1
        """,
        (int(user_id),),
        f"Не удалось получить последнюю ожидающую для пользователя {user_id}"
    )
    if not row:
        return None
    try:
        meta = json.loads(row["metadata"] or "{}")
    except Exception:
        meta = {}
    meta.setdefault('payment_id', row["payment_id"]) 
    return meta
# =======================================


# ===== GET_REFERRALS_FOR_USER =====
def get_referrals_for_user(user_id: int) -> list[dict]:
    rows = _fetch_list(
        """
        SELECT telegram_id, username, registration_date, total_spent, tg_linked
        FROM users
        WHERE referred_by = ?
        ORDER BY registration_date DESC
        """,
        (user_id,),
        f"Не удалось получить рефералов для пользователя {user_id}"
    )
    return [dict(r) for r in rows]
# ====================================


# ===== DETACH_REFERRALS_FROM_USER =====
def detach_referrals_from_user(user_id: int) -> int:
    """Снимает привязку рефералов к пользователю, не трогая сами аккаунты.
    Возвращает число отвязанных."""
    cursor = _exec(
        "UPDATE users SET referred_by = NULL WHERE referred_by = ?",
        (int(user_id),),
        f"Не удалось отвязать рефералов пользователя {user_id}",
    )
    return cursor.rowcount if cursor else 0
# ======================================


# ===== КОД ПРИГЛАШЕНИЯ ДЛЯ ВЕБ-ССЫЛКИ =====

# Ни 0/O, ни 1/l/I: код диктуют вслух и набирают руками, и пара, которую
# нельзя различить на слух или в шрифте, стоит дороже одного лишнего знака.
REF_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
REF_CODE_LENGTH = 7


def _new_ref_code() -> str:
    import secrets
    return "".join(secrets.choice(REF_CODE_ALPHABET) for _ in range(REF_CODE_LENGTH))


def get_or_create_ref_code(user_id: int) -> str | None:
    """Код приглашения владельца аккаунта; заводится при первом обращении.

    Уникальность держит индекс, а не проверка перед вставкой: между SELECT
    и UPDATE успевает вклиниться второй запрос, и два человека получают
    один код. Здесь вместо этого ловится нарушение индекса и берётся
    следующий код.
    """
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    row = _fetch_row("SELECT ref_code FROM users WHERE telegram_id = ?", (user_id,),
                     f"Не удалось прочитать код приглашения {user_id}")
    if row is None:
        return None
    if row.get("ref_code"):
        return row["ref_code"]

    for _ in range(12):
        code = _new_ref_code()
        try:
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                cursor = conn.cursor()
                # Условие на ref_code IS NULL — на случай, если параллельный
                # запрос уже успел выдать код этому же аккаунту.
                cursor.execute(
                    "UPDATE users SET ref_code = ? WHERE telegram_id = ? AND ref_code IS NULL",
                    (code, user_id))
                conn.commit()
                if cursor.rowcount:
                    return code
        except sqlite3.IntegrityError:
            continue
        except sqlite3.Error as e:
            logging.error(f"Не удалось выдать код приглашения {user_id}: {e}")
            return None
        # rowcount = 0 — код уже проставлен кем-то ещё, перечитываем
        row = _fetch_row("SELECT ref_code FROM users WHERE telegram_id = ?", (user_id,), "")
        if row and row.get("ref_code"):
            return row["ref_code"]

    logging.error(f"Не удалось подобрать свободный код приглашения для {user_id}")
    return None


def get_user_by_ref_code(code: str) -> dict | None:
    code = (code or "").strip().lower()
    if not code or not re.fullmatch(r"[a-z0-9]{4,16}", code):
        return None
    return _fetch_row("SELECT * FROM users WHERE ref_code = ?", (code,),
                      "Не удалось найти владельца кода приглашения")


def attach_referrer(user_id: int, referrer_id: int) -> bool:
    """Привязывает приглашённого к пригласившему. Только если связи ещё нет.

    Возвращает True, только когда привязка действительно случилась: на этом
    держится решение о билете и об уведомлении.
    """
    try:
        user_id, referrer_id = int(user_id), int(referrer_id)
    except (TypeError, ValueError):
        return False
    if user_id == referrer_id:
        return False

    referrer = get_user(referrer_id)
    if not referrer or referrer.get("is_banned"):
        return False

    cursor = _exec(
        "UPDATE users SET referred_by = ? WHERE telegram_id = ? "
        "AND (referred_by IS NULL OR referred_by = '')",
        (referrer_id, user_id),
        f"Не удалось привязать {user_id} к пригласившему {referrer_id}")
    return bool(cursor and cursor.rowcount)


def mark_referral_ticket_granted(user_id: int) -> bool:
    """Отмечает, что билет за этого приглашённого уже выдан.

    Возвращает True только первому вызову — на этом и держится «один билет
    на приглашённого», сколько бы раз ни сработали пути начисления.
    """
    cursor = _exec(
        "UPDATE users SET referral_ticket_granted = 1 WHERE telegram_id = ? "
        "AND COALESCE(referral_ticket_granted, 0) = 0",
        (int(user_id),),
        f"Не удалось отметить билет за реферала {user_id}")
    return bool(cursor and cursor.rowcount)
# ==========================================


# ===== GET_ALL_SETTINGS =====
def get_all_settings() -> dict:
    rows = _fetch_list("SELECT key, value FROM bot_settings", (), "Не удалось получить все настройки")
    return {row['key']: row['value'] for row in rows}

# ============================


# ===== UPDATE_SETTING =====
def update_setting(key: str, value: str):
    cursor = _exec(
        "INSERT OR REPLACE INTO bot_settings (key, value) VALUES (?, ?)",
        (key, value),
        f"Не удалось обновить настройку '{key}'"
    )
    if cursor: logging.info(f"Настройка '{key}' обновлена.")
# ==========================


# ===== GET_BUTTON_CONFIGS =====
def get_button_configs(menu_type: str, include_inactive: bool = False) -> list[dict]:
    query = """
        SELECT * FROM button_configs 
        WHERE menu_type = ? 
        ORDER BY sort_order, row_position, column_position
    """
    if not include_inactive:
        query = """
            SELECT * FROM button_configs 
            WHERE menu_type = ? AND is_active = 1 
            ORDER BY sort_order, row_position, column_position
        """
        
    rows = _fetch_list(query, (menu_type,), f"Не удалось получить конфиг кнопок для {menu_type}")
    
    if not rows and menu_type in ("main_menu", "admin_menu", "profile_menu", "support_menu", "key_info_menu"):
        try:
            count = _get_count_stat("SELECT COUNT(*) as c FROM button_configs")
            if count == 0:
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    cursor = conn.cursor()
                    _ensure_default_button_configs(cursor)
                    conn.commit()
                rows = _fetch_list(query, (menu_type,), f"Не удалось получить конфиг кнопок для {menu_type}")
        except Exception as e:
            logging.error(f"Не удалось инициализировать дефолтные кнопки: {e}")
            
    return [dict(r) for r in rows]
# ============================


# ===== GET_BUTTON_CONFIG =====
def get_button_config(menu_type: str, button_id: str) -> dict | None:
    row = _fetch_row(
        """
        SELECT * FROM button_configs 
        WHERE menu_type = ? AND button_id = ?
        """,
        (menu_type, button_id),
        f"Не удалось получить конфиг кнопки {menu_type}/{button_id}"
    )
    return dict(row) if row else None

# =============================


# ===== CREATE_BUTTON_CONFIG =====
def create_button_config(menu_type: str, button_id: str, text: str, callback_data: str = None, 
                        url: str = None, row_position: int = 0, column_position: int = 0, 
                        button_width: int = 1, metadata: str = None, 
                        button_color: str = None, emoji_id: str = None) -> bool:
    cursor = _exec(
        """
        INSERT OR REPLACE INTO button_configs 
        (menu_type, button_id, text, callback_data, url, row_position, column_position, button_width, metadata, button_color, emoji_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (menu_type, button_id, text, callback_data, url, row_position, column_position, button_width, metadata, button_color, emoji_id),
        "Не удалось создать конфиг кнопки"
    )
    if cursor: logging.info(f"Конфиг кнопки создан: {menu_type}/{button_id}"); return True
    return False
# ================================


# ===== UPDATE_BUTTON_CONFIG =====
def update_button_config(button_id: int, text: str = None, callback_data: str = None, 
                        url: str = None, row_position: int = None, column_position: int = None, 
                        button_width: int = None, is_active: bool = None, sort_order: int = None, 
                        metadata: str = None, button_color: str = None, emoji_id: str = None) -> bool:
    logging.info(f"update_button_config called for {button_id}: text={text}, callback_data={callback_data}, url={url}, row={row_position}, col={column_position}, active={is_active}, sort={sort_order}")
    
    updates = []
    params = []
    
    if text is not None:
        updates.append("text = ?")
        params.append(text)
    if callback_data is not None:
        updates.append("callback_data = ?")
        params.append(callback_data)
    if url is not None:
        updates.append("url = ?")
        params.append(url)
    if row_position is not None:
        updates.append("row_position = ?")
        params.append(row_position)
    if column_position is not None:
        updates.append("column_position = ?")
        params.append(column_position)
    if button_width is not None:
        updates.append("button_width = ?")
        params.append(button_width)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    if sort_order is not None:
        updates.append("sort_order = ?")
        params.append(sort_order)
    if metadata is not None:
        updates.append("metadata = ?")
        params.append(metadata)
    if button_color is not None:
        updates.append("button_color = ?")
        params.append(button_color if button_color else None)
    if emoji_id is not None:
        updates.append("emoji_id = ?")
        params.append(emoji_id if emoji_id else None)
    
    if not updates: return True
        
    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(button_id)
    
    query = f"UPDATE button_configs SET {', '.join(updates)} WHERE id = ?"
    cursor = _exec(query, params, f"Не удалось обновить конфиг кнопки {button_id}")
    
    if cursor and cursor.rowcount > 0: logging.info(f"Конфиг кнопки {button_id} успешно обновлён"); return True
    if cursor and cursor.rowcount == 0: logging.warning(f"Кнопка с id {button_id} не найдена")
    return False
# ================================


# ===== REORDER_BUTTON_CONFIGS =====
def reorder_button_configs(menu_type: str, button_orders: list[dict]) -> bool:
    try:
        logging.info(f"Reordering {len(button_orders)} buttons for {menu_type}")
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            for order_data in button_orders:
                button_id = order_data.get('button_id')
                sort_order = order_data.get('sort_order', 0)
                row_position = order_data.get('row_position', 0)
                column_position = order_data.get('column_position', 0)
                button_width = order_data.get('button_width', None)
                is_active = order_data.get('is_active')
                
                set_clauses = [
                    "sort_order = ?",
                    "row_position = ?",
                    "column_position = ?",
                    "updated_at = CURRENT_TIMESTAMP"
                ]
                query_params = [sort_order, row_position, column_position]

                if button_width is not None:
                    set_clauses.insert(3, "button_width = ?")
                    query_params.insert(3, int(button_width))
                
                if is_active is not None:
                    set_clauses.insert(len(set_clauses)-1, "is_active = ?")
                    query_params.insert(len(query_params), 1 if is_active else 0)

                query_params.append(menu_type)
                query_params.append(button_id)

                cursor.execute(
                    f"""
                    UPDATE button_configs 
                    SET {', '.join(set_clauses)}
                    WHERE menu_type = ? AND button_id = ?
                    """,
                    query_params,
                )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logging.error(f"Failed to reorder button configs for {menu_type}: {e}")
        return False
# ==================================


# ===== UPDATE_EXISTING_MY_KEYS_BUTTON =====
def update_existing_my_keys_button():
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE button_configs SET button_id = 'my_keys' WHERE button_id = 'keys'")
            conn.commit()
            return True
    except sqlite3.Error:
        return False
# ==========================================


# ===== DELETE_BUTTON_CONFIG =====
def delete_button_config(button_id: int) -> bool:
    cursor = _exec("DELETE FROM button_configs WHERE id = ?", (button_id,), f"Не удалось удалить конфиг кнопки {button_id}")
    if cursor: logging.info(f"Конфиг кнопки {button_id} удалён"); return True
    return False
# ================================



# ===== CREATE_PLAN =====
def create_plan(host_name: str, plan_name: str, months: int, price: float, hwid_limit: int = 0, traffic_limit_gb: int = 0, button_style: str = None, icon_emoji_id: str = None):
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "INSERT INTO plans (host_name, plan_name, months, price, hwid_limit, traffic_limit_gb, button_style, icon_emoji_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (host_name, plan_name, months, price, hwid_limit, traffic_limit_gb, button_style or None, icon_emoji_id or None),
        f"Не удалось создать тариф для хоста '{host_name}'"
    )
    if cursor: new_id = cursor.lastrowid; logging.info(f"Created new plan '{plan_name}' for host '{host_name}' with HWID={hwid_limit}, Traffic={traffic_limit_gb}GB."); return new_id
    return None
# =======================


# ===== GET_PLANS_FOR_HOST =====
def get_plans_for_host(host_name: str) -> list[dict]:
    host_name = normalize_host_name(host_name)
    rows = _fetch_list("SELECT * FROM plans WHERE TRIM(host_name) = TRIM(?) ORDER BY months", (host_name,), f"Не удалось получить тарифы для хоста '{host_name}'")
    return [dict(plan) for plan in rows]

# ==============================


# ===== GET_PLAN_BY_ID =====
def get_plan_by_id(plan_id: int) -> dict | None:
    row = _fetch_row("SELECT * FROM plans WHERE plan_id = ?", (plan_id,), f"Не удалось получить тариф по id '{plan_id}'")
    return dict(row) if row else None

# ==========================


# ===== DELETE_PLAN =====
def delete_plan(plan_id: int):
    cursor = _exec("DELETE FROM plans WHERE plan_id = ?", (plan_id,), f"Не удалось удалить тариф с id {plan_id}")
    if cursor: logging.info(f"Удалён тариф с id {plan_id}.")
# =======================


# ===== UPDATE_PLAN =====
def update_plan(plan_id: int, plan_name: str, months: int, price: float, hwid_limit: int = 0, traffic_limit_gb: int = 0, button_style: str = None, icon_emoji_id: str = None) -> bool:
    cursor = _exec(
        "UPDATE plans SET plan_name = ?, months = ?, price = ?, hwid_limit = ?, traffic_limit_gb = ?, button_style = ?, icon_emoji_id = ? WHERE plan_id = ?",
        (plan_name, months, price, hwid_limit, traffic_limit_gb, button_style or None, icon_emoji_id or None, plan_id),
        f"Не удалось обновить тариф {plan_id}"
    )
    if cursor and cursor.rowcount > 0: logging.info(f"Updated plan {plan_id}: name='{plan_name}', months={months}, price={price}, hwid={hwid_limit}, traffic={traffic_limit_gb}."); return True
    if cursor and cursor.rowcount == 0: logging.warning(f"No plan updated for id {plan_id} (not found).")
    return False


def update_host_button_style(host_name: str, button_style: str = None, icon_emoji_id: str = None) -> bool:
    host_name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET button_style = ?, icon_emoji_id = ? WHERE TRIM(host_name) = TRIM(?)",
        (button_style or None, icon_emoji_id or None, host_name),
        f"Не удалось обновить стиль кнопки для хоста '{host_name}'"
    )
    if cursor and cursor.rowcount > 0: logging.info(f"Updated button style for host '{host_name}': style={button_style}, emoji={icon_emoji_id}"); return True
    return False
# =======================


def register_user_if_not_exists(telegram_id: int, username: str, referrer_id):
    row = _fetch_row("SELECT referred_by FROM users WHERE telegram_id = ?", (telegram_id,), "")
    
    if not row:
        _exec(
            "INSERT INTO users (telegram_id, username, registration_date, referred_by, tg_linked) VALUES (?, ?, ?, ?, 1)",
            (telegram_id, username, get_msk_time().replace(tzinfo=None).replace(microsecond=0), referrer_id),
            f"Не удалось зарегистрировать пользователя {telegram_id}"
        )
    else:
        # Имя из Telegram подтягиваем на каждый /start, но не затираем то,
        # что администратор проставил вручную в панели.
        _exec(
            "UPDATE users SET username = ? WHERE telegram_id = ? AND NOT COALESCE(username_manually_set, 0)",
            (username, telegram_id),
            ""
        )

        current_ref = row['referred_by']
        if referrer_id and (current_ref is None or str(current_ref).strip() == "") and int(referrer_id) != int(telegram_id):
            _exec("UPDATE users SET referred_by = ? WHERE telegram_id = ?", (int(referrer_id), telegram_id), "")

def add_to_referral_balance(user_id: int, amount: float):
    _exec("UPDATE users SET referral_balance = referral_balance + ? WHERE telegram_id = ?", (amount, user_id), f"Не удалось добавить реферальный баланс для пользователя {user_id}")

def set_referral_balance(user_id: int, value: float):
    _exec("UPDATE users SET referral_balance = ? WHERE telegram_id = ?", (value, user_id), f"Не удалось установить реферальный баланс для пользователя {user_id}")

def set_referral_balance_all(user_id: int, value: float):
    _exec("UPDATE users SET referral_balance_all = ? WHERE telegram_id = ?", (value, user_id), f"Не удалось установить общий реф-баланс для пользователя {user_id}")

def add_to_referral_balance_all(user_id: int, amount: float):
    _exec(
        "UPDATE users SET referral_balance_all = referral_balance_all + ? WHERE telegram_id = ?",
        (amount, user_id),
        f"Не удалось добавить к общему реф-балансу для пользователя {user_id}"
    )

def get_referral_balance_all(user_id: int) -> float:
    row = _fetch_row("SELECT referral_balance_all FROM users WHERE telegram_id = ?", (user_id,), f"Не удалось получить общий реф-баланс для пользователя {user_id}")
    return row["referral_balance_all"] if row else 0.0

def get_referral_balance(user_id: int) -> float:
    row = _fetch_row("SELECT referral_balance FROM users WHERE telegram_id = ?", (user_id,), f"Не удалось получить реф-баланс для пользователя {user_id}")
    return row["referral_balance"] if row else 0.0

def get_balance(user_id: int) -> float:
    row = _fetch_row("SELECT balance FROM users WHERE telegram_id = ?", (user_id,), f"Не удалось получить баланс для пользователя {user_id}")
    return row["balance"] if row else 0.0

def adjust_user_balance(user_id: int, delta: float) -> bool:
    cursor = _exec(
        "UPDATE users SET balance = COALESCE(balance, 0) + ? WHERE telegram_id = ?",
        (float(delta), user_id),
        f"Не удалось изменить баланс для пользователя {user_id}"
    )
    return cursor is not None and cursor.rowcount > 0

def set_balance(user_id: int, value: float) -> bool:
    cursor = _exec(
        "UPDATE users SET balance = ? WHERE telegram_id = ?",
        (value, user_id),
        f"Не удалось установить баланс для пользователя {user_id}"
    )
    return cursor is not None and cursor.rowcount > 0

def add_to_balance(user_id: int, amount: float) -> bool:
    logging.info(f"💳 Добавляем {amount:.2f} RUB к балансу пользователя {user_id}")
    
    # Check if user exists first to match original logic logging
    row = _fetch_row("SELECT telegram_id, balance FROM users WHERE telegram_id = ?", (int(user_id),), "")
    if not row: logging.error(f"❌ Пользователь {user_id} не найден в базе данных"); return False

    old_balance = row["balance"] or 0.0
    
    cursor = _exec(
        "UPDATE users SET balance = COALESCE(balance, 0) + ? WHERE telegram_id = ?",
        (float(amount), int(user_id)),
        f"Ошибка базы данных при пополнении баланса для пользователя {user_id}"
    )
    
    if cursor and cursor.rowcount > 0:
        new_balance = old_balance + float(amount)
        logging.info(f"✅ Баланс обновлен: пользователь {user_id} | {old_balance:.2f} → {new_balance:.2f} RUB (+{amount:.2f})")
        return True
    
    logging.error(f"❌ Не удалось обновить баланс для пользователя {user_id}: строки не затронуты")
    return False

def deduct_from_balance(user_id: int, amount: float) -> bool:
    if amount <= 0: return True
        
    cursor = _exec(
        "UPDATE users SET balance = balance - ? WHERE telegram_id = ? AND balance >= ?",
        (amount, user_id, amount),
        f"Не удалось списать с баланса для пользователя {user_id}"
    )
    if cursor and cursor.rowcount > 0: return True
        
    return False
# ============================


# ===== DEDUCT_FROM_REFERRAL_BALANCE =====
def deduct_from_referral_balance(user_id: int, amount: float) -> bool:
    if amount <= 0: return True
    cursor = _exec(
        "UPDATE users SET referral_balance = referral_balance - ? WHERE telegram_id = ? AND referral_balance >= ?",
        (amount, user_id, amount),
        f"Не удалось списать с реферального баланса для пользователя {user_id}"
    )
    if cursor and cursor.rowcount > 0: return True
    return False
# ======================================


# ===== GET_REFERRAL_COUNT =====
def get_referral_count(user_id: int) -> int:
    row = _fetch_row("SELECT COUNT(*) as c FROM users WHERE referred_by = ?", (user_id,), f"Не удалось получить кол-во рефералов для пользователя {user_id}")
    return row["c"] if row else 0
# ==============================


# ===== GET_USER =====
def get_user(telegram_id: int):
    row = _fetch_row("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,), f"Не удалось получить пользователя {telegram_id}")
    return dict(row) if row else None
# ==================


# ===== APP_THEMES =====
# Палитры веб-аппа: имя -> набор CSS-переменных, см. app.html.
APP_THEMES = ("violet", "ocean", "forest", "ember", "rose", "gold")
DEFAULT_APP_THEME = "violet"


def update_user_app_theme(telegram_id: int, app_theme: str) -> bool:
    if app_theme not in APP_THEMES:
        return False
    cursor = _exec(
        "UPDATE users SET app_theme = ? WHERE telegram_id = ?",
        (app_theme, telegram_id),
        f"Не удалось обновить тему пользователя {telegram_id}",
    )
    return cursor is not None and cursor.rowcount > 0
# =======================


# ===== UPDATE_USER_USERNAME =====
def update_user_username(telegram_id: int, username: str) -> bool:
    """Задаёт имя вручную и помечает его, чтобы автосинк из Telegram не перетёр."""
    cursor = _exec(
        "UPDATE users SET username = ?, username_manually_set = 1 WHERE telegram_id = ?",
        (username, telegram_id),
        f"Не удалось обновить имя пользователя {telegram_id}"
    )
    return cursor is not None and cursor.rowcount > 0
# ================================


# ===== GET_USER_BY_EMAIL =====
def get_user_by_email(email: str):
    row = _fetch_row("SELECT * FROM users WHERE LOWER(auth_email) = ?", (email.lower().strip(),), f"Не удалось получить пользователя {email}")
    return dict(row) if row else None
# ==================

# ===== CREATE_USER_BY_EMAIL =====
def create_user_by_email(email: str, password_hash: str) -> dict | None:
    import random
    while True:
        telegram_id = int(f"999{random.randint(1000000, 9999999)}")
        if not get_user(telegram_id):
            break
            
    cursor = _exec(
        "INSERT INTO users (telegram_id, username, registration_date, auth_email, auth_pass, tg_linked) VALUES (?, ?, ?, ?, ?, 0)",
        (telegram_id, "", get_msk_time().replace(tzinfo=None).replace(microsecond=0), email.strip(), password_hash),
        f"Не удалось зарегистрировать пользователя {email}"
    )
    if cursor:
        return get_user(telegram_id)
    return None
# =================================

# ===== КОДЫ ПОДТВЕРЖДЕНИЯ ПОЧТЫ =====
EMAIL_CODE_TTL_SECONDS = 900        # 15 минут
EMAIL_CODE_RESEND_SECONDS = 60      # не чаще раза в минуту
EMAIL_CODE_MAX_ATTEMPTS = 5


def _hash_email_code(email: str, purpose: str, code: str) -> str:
    """Код в базе лежит хешем: дампа таблицы недостаточно, чтобы им воспользоваться."""
    import hashlib
    material = f"{email.lower().strip()}|{purpose}|{code}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def purge_expired_email_codes() -> None:
    _exec("DELETE FROM email_codes WHERE expires_at < ?", (int(time.time()),),
          "Не удалось убрать истёкшие коды")


def seconds_until_email_code_resend(email: str, purpose: str) -> int:
    """Сколько ещё ждать до повторной отправки; 0 — можно отправлять."""
    row = _fetch_row(
        "SELECT created_at FROM email_codes WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
        (email.lower().strip(), purpose),
        "Не удалось проверить частоту отправки кода",
    )
    if not row:
        return 0
    elapsed = int(time.time()) - int(row["created_at"])
    return max(0, EMAIL_CODE_RESEND_SECONDS - elapsed)


def issue_email_code(email: str, purpose: str) -> str:
    """Выдаёт новый код, гася предыдущие для этой пары адрес+назначение."""
    import secrets
    email_lower = email.lower().strip()
    code = f"{secrets.randbelow(1000000):06d}"
    now = int(time.time())
    _exec("DELETE FROM email_codes WHERE email = ? AND purpose = ?", (email_lower, purpose),
          "Не удалось убрать прежние коды")
    _exec(
        "INSERT INTO email_codes (email, purpose, code_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (email_lower, purpose, _hash_email_code(email_lower, purpose, code), now, now + EMAIL_CODE_TTL_SECONDS),
        "Не удалось сохранить код подтверждения",
    )
    return code


def check_email_code(email: str, purpose: str, code: str, *, consume: bool = False) -> tuple[bool, str]:
    """Проверяет код. Возвращает (успех, причина отказа).

    consume=True удаляет код — так проверка на последнем шаге не даёт
    переиспользовать один и тот же код дважды.
    """
    email_lower = email.lower().strip()
    row = _fetch_row(
        "SELECT id, code_hash, attempts, expires_at FROM email_codes WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
        (email_lower, purpose),
        "Не удалось получить код подтверждения",
    )
    if not row:
        return False, "Код не запрашивался"
    if int(row["expires_at"]) < int(time.time()):
        _exec("DELETE FROM email_codes WHERE id = ?", (row["id"],), "Не удалось убрать истёкший код")
        return False, "Код устарел — запросите новый"
    if int(row["attempts"] or 0) >= EMAIL_CODE_MAX_ATTEMPTS:
        _exec("DELETE FROM email_codes WHERE id = ?", (row["id"],), "Не удалось убрать исчерпанный код")
        return False, "Слишком много попыток — запросите новый код"

    if row["code_hash"] != _hash_email_code(email_lower, purpose, (code or "").strip()):
        _exec("UPDATE email_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],),
              "Не удалось учесть неверную попытку")
        return False, "Неверный код"

    if consume:
        _exec("DELETE FROM email_codes WHERE id = ?", (row["id"],), "Не удалось погасить код")
    return True, ""


def set_email_verified(email: str, verified: bool = True) -> bool:
    cursor = _exec(
        "UPDATE users SET email_verified = ? WHERE LOWER(auth_email) = ?",
        (1 if verified else 0, email.lower().strip()),
        f"Не удалось отметить почту {email} подтверждённой",
    )
    return cursor is not None and cursor.rowcount > 0
# ====================================


# ===== UPDATE_USER_PASSWORD =====
def update_user_password(email: str, new_password_hash: str) -> bool:
    cursor = _exec("UPDATE users SET auth_pass = ? WHERE LOWER(auth_email) = ?", (new_password_hash, email.lower().strip()), f"Не удалось обновить пароль для {email}")
    return cursor is not None and cursor.rowcount > 0
# =================================

# ===== UPDATE_USER_AUTH_TOKEN =====
def update_user_auth_token(telegram_id: int, token: str) -> bool:
    cursor = _exec("UPDATE users SET auth_token = ? WHERE telegram_id = ?", (token, telegram_id), f"Не удалось обновить токен {telegram_id}")
    return cursor is not None and cursor.rowcount > 0
# ==================================

# ===== LINK_TELEGRAM_TO_EMAIL_USER =====
def link_telegram_to_email_user(old_telegram_id: int, new_telegram_id: int, new_username: str):
    old_user = get_user(old_telegram_id)
    if not old_user:
        return "Ошибка: веб-аккаунт не найден."

    existing = get_user(new_telegram_id)
        
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            if existing:
                cursor.execute("UPDATE vpn_keys SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE transactions SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE pending_transactions SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE support_tickets SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE seller_users SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE users SET referred_by = ? WHERE referred_by = ?", (new_telegram_id, old_telegram_id))
                
                old_bal = old_user.get('balance', 0)
                old_ref_bal = old_user.get('referral_balance', 0)
                old_ref_all = old_user.get('referral_balance_all', 0)
                old_spent = old_user.get('total_spent', 0)
                old_months = old_user.get('total_months', 0)
                
                cursor.execute("""
                    UPDATE users 
                    SET balance = balance + ?, 
                        referral_balance = referral_balance + ?,
                        referral_balance_all = referral_balance_all + ?,
                        total_spent = total_spent + ?,
                        total_months = total_months + ?,
                        auth_email = ?,
                        auth_pass = ?,
                        auth_token = ?
                    WHERE telegram_id = ?
                """, (old_bal, old_ref_bal, old_ref_all, old_spent, old_months, 
                      old_user.get('auth_email'), old_user.get('auth_pass'), old_user.get('auth_token'),
                      new_telegram_id))
                
                # Кто привёл веб-аккаунт, при склейке терялось: строка с
                # referred_by удалялась, а телеграм-аккаунт оставался со
                # своим — то есть чаще всего ни с чьим. Переносим связь,
                # если на принимающей стороне её нет.
                if old_user.get('referred_by') and int(old_user['referred_by']) != int(new_telegram_id):
                    cursor.execute(
                        "UPDATE users SET referred_by = ? WHERE telegram_id = ? "
                        "AND (referred_by IS NULL OR referred_by = '')",
                        (old_user['referred_by'], new_telegram_id))

                cursor.execute("DELETE FROM users WHERE telegram_id = ?", (old_telegram_id,))
            else:
                # tg_linked обязательно взводим здесь: без него привязанный
                # аккаунт продолжал считаться веб-аккаунтом (нет пробного
                # периода, в кабинете значилось «Без Telegram»)
                cursor.execute("UPDATE users SET telegram_id = ?, username = ?, tg_linked = 1 WHERE telegram_id = ?", (new_telegram_id, new_username, old_telegram_id))
                cursor.execute("UPDATE vpn_keys SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE transactions SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE pending_transactions SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE support_tickets SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE seller_users SET user_id = ? WHERE user_id = ?", (new_telegram_id, old_telegram_id))
                cursor.execute("UPDATE users SET referred_by = ? WHERE referred_by = ?", (new_telegram_id, old_telegram_id))
            
            conn.commit()
            return True
    except sqlite3.Error as e:
        logging.error(f"Failed to link telegram {new_telegram_id} to {old_telegram_id}: {e}")
        return "Ошибка базы данных."
# =======================================


# ===== GET_TRANSACTION =====
def get_transaction(payment_id: str) -> dict | None:
    row = _fetch_row("SELECT * FROM transactions WHERE payment_id = ?", (payment_id,), f"Не удалось получить транзакцию {payment_id}")
    return dict(row) if row else None
# =========================


# ===== SET_TERMS_AGREED =====
def set_terms_agreed(telegram_id: int):
    cursor = _exec("UPDATE users SET agreed_to_terms = 1 WHERE telegram_id = ?", (telegram_id,), f"Не удалось установить согласие с условиями для пользователя {telegram_id}")
    if cursor: logging.info(f"Пользователь {telegram_id} согласился с условиями.")
# ==========================


# ===== UPDATE_USER_STATS =====
def update_user_stats(telegram_id: int, amount_spent: float, months_purchased: int):
    _exec("UPDATE users SET total_spent = total_spent + ?, total_months = total_months + ? WHERE telegram_id = ?", (amount_spent, months_purchased, telegram_id), f"Не удалось обновить статистику пользователя {telegram_id}")
# ===========================


# ===== GET_USER_COUNT =====
def get_user_count() -> int:
    row = _fetch_row("SELECT COUNT(*) as c FROM users", (), "Не удалось получить кол-во пользователей")
    return row["c"] if row else 0
# ========================


# ===== GET_TOTAL_KEYS_COUNT =====
def get_total_keys_count() -> int:
    row = _fetch_row("SELECT COUNT(*) as c FROM vpn_keys", (), "Не удалось получить кол-во ключей")
    return row["c"] if row else 0
# ==============================


# ===== GET_TOTAL_SPENT_SUM =====
def get_total_spent_sum() -> float:
    row = _fetch_row(
        """
        SELECT COALESCE(SUM(amount_rub), 0.0) as s
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success', 'succeeded')
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
        """,
        (),
        "Не удалось получить общую сумму расходов"
    )
    return row["s"] if row else 0.0
# =============================


# ===== GET_TOTAL_SPENT_BY_METHOD =====
def get_total_spent_by_method(payment_method: str) -> float:
    method_norm = (payment_method or '').strip().lower()
    method_aliases = {
        'platega': ('platega', 'platega payform', 'platega crypto'),
        'ton connect': ('ton connect', 'ton'),
    }
    methods = method_aliases.get(method_norm, (method_norm,))
    placeholders = ','.join('?' for _ in methods)
    val = _fetch_val(
        f"""
        SELECT COALESCE(SUM(amount_rub), 0.0)
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success', 'succeeded')
          AND LOWER(COALESCE(payment_method, '')) IN ({placeholders})
          AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')
        """,
        methods,
        0.0,
        f"Не удалось получить доход по методу {payment_method}"
    )
    return float(val) if val is not None else 0.0
# ===================================


# ===== GET_TODAY_INCOME_BY_CURRENCY =====
def get_today_income_by_currency() -> dict:
    rub_methods = ('yookassa', 'platega', 'platega payform')
    crypto_methods = ('telegram stars', 'cryptobot', 'heleket', 'ton connect', 'platega crypto')
    income_filter = """
          AND (
              LOWER(COALESCE(json_extract(metadata, '$.action'), '')) IN ('new', 'extend', 'topup', 'top_up')
              OR LOWER(COALESCE(json_extract(metadata, '$.reason'), '')) IN ('subscription_purchase_or_extend', 'external_balance_top_up')
          )
    """
    rub = _fetch_val(
        f"""
        SELECT COALESCE(SUM(amount_rub), 0.0)
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success', 'succeeded')
          AND date(created_date) = date('now', '+3 hours')
          AND LOWER(COALESCE(payment_method, '')) IN ({','.join('?' for _ in rub_methods)})
          {income_filter}
        """,
        rub_methods, 0.0, "Не удалось получить рублёвый доход за сегодня"
    )
    yesterday_rub = _fetch_val(
        f"""
        SELECT COALESCE(SUM(amount_rub), 0.0)
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success', 'succeeded')
          AND date(created_date) = date('now', '+3 hours', '-1 day')
          AND LOWER(COALESCE(payment_method, '')) IN ({','.join('?' for _ in rub_methods)})
          {income_filter}
        """,
        rub_methods, 0.0, "Не удалось получить рублёвый доход за вчера"
    )
    crypto = _fetch_val(
        f"""
        SELECT COALESCE(SUM(amount_rub), 0.0)
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success', 'succeeded')
          AND date(created_date) = date('now', '+3 hours')
          AND LOWER(COALESCE(payment_method, '')) IN ({','.join('?' for _ in crypto_methods)})
          {income_filter}
        """,
        crypto_methods, 0.0, "Не удалось получить крипто доход за сегодня"
    )
    return {"rub": float(rub or 0), "yesterday_rub": float(yesterday_rub or 0), "crypto": float(crypto or 0)}
# ========================================


# ===== GET_ADMIN_FINANCIAL_STATS =====
def get_admin_financial_stats() -> dict:
    """Сводка для раздела «Финансы» в админ-меню бота."""
    paid_statuses = "('paid', 'completed', 'success', 'succeeded')"
    excluded_methods = "('balance', 'admin', 'referral')"
    # json_extract падает на битом JSON и роняет весь запрос, а вместе с ним
    # обнуляет цифру в отчёте. Разбираем метаданные только если это валидный JSON.
    meta = "CASE WHEN json_valid(COALESCE(metadata, '{}')) THEN COALESCE(metadata, '{}') ELSE '{}' END"
    income_action_filter = f"""
          AND (
              LOWER(COALESCE(json_extract({meta}, '$.action'), '')) IN ('new', 'extend', 'topup', 'top_up')
              OR LOWER(COALESCE(json_extract({meta}, '$.reason'), '')) IN ('subscription_purchase_or_extend', 'external_balance_top_up')
          )
    """

    admin_stats = get_admin_stats()
    user_groups = get_dashboard_user_groups()

    def income_sum(date_filter: str = "") -> float:
        return float(_fetch_val(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0.0)
            FROM transactions
            WHERE LOWER(COALESCE(status, '')) IN {paid_statuses}
              AND LOWER(COALESCE(payment_method, '')) NOT IN {excluded_methods}
              {date_filter}
              {income_action_filter}
            """,
            (), 0.0, "Не удалось получить финансовую сумму для админской сводки",
        ) or 0)

    def referral_income_sum(date_filter: str = "") -> float:
        return float(_fetch_val(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0.0)
            FROM transactions
            WHERE LOWER(COALESCE(status, '')) IN {paid_statuses}
              AND LOWER(COALESCE(payment_method, '')) = 'referral'
              {date_filter}
            """,
            (), 0.0, "Не удалось получить доход партнёров для админской сводки",
        ) or 0)

    def today_sum(actions: str, reason: str) -> float:
        return float(_fetch_val(
            f"""
            SELECT COALESCE(SUM(amount_rub), 0.0)
            FROM transactions
            WHERE LOWER(COALESCE(status, '')) IN {paid_statuses}
              AND date(created_date) = date('now', '+3 hours')
              AND LOWER(COALESCE(payment_method, '')) NOT IN {excluded_methods}
              AND (
                  LOWER(COALESCE(json_extract({meta}, '$.action'), '')) IN ({actions})
                  OR LOWER(COALESCE(json_extract({meta}, '$.reason'), '')) = '{reason}'
              )
            """,
            (), 0.0, "Не удалось получить сумму за сегодня для финансовой сводки",
        ) or 0)

    total_income = income_sum()
    today_topups = today_sum("'topup', 'top_up'", "external_balance_top_up")
    today_subscriptions = today_sum("'new', 'extend'", "subscription_purchase_or_extend")

    pending_amount = _fetch_val(
        f"SELECT COALESCE(SUM(amount_rub), 0.0) FROM transactions WHERE LOWER(COALESCE(status, '')) = 'pending'",
        (), 0.0, "Не удалось получить сумму ожидающих платежей",
    )
    pending_count = _fetch_val(
        "SELECT COUNT(*) FROM transactions WHERE LOWER(COALESCE(status, '')) = 'pending'",
        (), 0, "Не удалось получить количество ожидающих платежей",
    )
    user_balance_total = _fetch_val(
        "SELECT COALESCE(SUM(balance), 0.0) FROM users",
        (), 0.0, "Не удалось получить суммарный баланс пользователей",
    )
    trial_used_total = _fetch_val(
        """
        SELECT COUNT(DISTINCT telegram_id)
        FROM users
        WHERE COALESCE(trial_used, 0) = 1
           OR EXISTS (
                SELECT 1 FROM vpn_keys k
                WHERE k.user_id = users.telegram_id AND COALESCE(k.key_email, '') LIKE 'trial_%'
           )
        """,
        (), 0, "Не удалось получить количество пользователей с триалом",
    )
    partners_with_referrals = _fetch_val(
        """
        SELECT COUNT(*) FROM (
            SELECT referred_by FROM users WHERE referred_by IS NOT NULL GROUP BY referred_by
        ) q
        """,
        (), 0, "Не удалось получить количество партнёров с рефералами",
    )
    total_referred = _fetch_val(
        "SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL",
        (), 0, "Не удалось получить количество приглашённых пользователей",
    )
    partner_balance = _fetch_val(
        "SELECT COALESCE(SUM(referral_balance), 0.0) FROM users",
        (), 0.0, "Не удалось получить партнёрский баланс",
    )
    partners_earned_total = _fetch_val(
        "SELECT COALESCE(SUM(referral_balance_all), 0.0) FROM users",
        (), 0.0, "Не удалось получить общий заработок партнёров",
    )
    top_partner = _fetch_row(
        """
        SELECT u.telegram_id, u.username, COUNT(*) AS referrals_count
        FROM users r
        JOIN users u ON u.telegram_id = r.referred_by
        WHERE r.referred_by IS NOT NULL
        GROUP BY u.telegram_id, u.username
        ORDER BY referrals_count DESC, u.telegram_id ASC
        LIMIT 1
        """,
        (), "Не удалось получить топ партнёра",
    ) or {}
    top_user = _fetch_row(
        f"""
        SELECT u.telegram_id, u.username,
               COALESCE(SUM(COALESCE(
                   CAST(json_extract(t_meta.m, '$.months') AS INTEGER),
                   (SELECT p.months FROM plans p WHERE p.plan_id = CAST(json_extract(t_meta.m, '$.plan_id') AS INTEGER)),
                   0
               )), 0) AS months_total
        FROM users u
        JOIN (
            SELECT t.user_id, t.status, t.payment_method,
                   CASE WHEN json_valid(COALESCE(t.metadata, '{{}}')) THEN COALESCE(t.metadata, '{{}}') ELSE '{{}}' END AS m
            FROM transactions t
        ) t_meta ON t_meta.user_id = u.telegram_id
        WHERE LOWER(COALESCE(t_meta.status, '')) IN {paid_statuses}
          AND LOWER(COALESCE(t_meta.payment_method, '')) NOT IN ('admin', 'referral')
          AND (
              LOWER(COALESCE(json_extract(t_meta.m, '$.action'), '')) IN ('new', 'extend')
              OR LOWER(COALESCE(json_extract(t_meta.m, '$.reason'), '')) = 'subscription_purchase_or_extend'
              OR json_extract(t_meta.m, '$.plan_id') IS NOT NULL
              OR json_extract(t_meta.m, '$.key_id') IS NOT NULL
          )
        GROUP BY u.telegram_id, u.username
        ORDER BY months_total DESC, u.telegram_id ASC
        LIMIT 1
        """,
        (), "Не удалось получить топ пользователя по месяцам",
    ) or {}
    payment_rows = _fetch_list(
        f"""
        SELECT LOWER(COALESCE(payment_method, '')) AS method, COALESCE(SUM(amount_rub), 0.0) AS total
        FROM transactions
        WHERE LOWER(COALESCE(status, '')) IN {paid_statuses}
          AND LOWER(COALESCE(payment_method, '')) NOT IN {excluded_methods}
          {income_action_filter}
        GROUP BY LOWER(COALESCE(payment_method, ''))
        ORDER BY total DESC, method ASC
        """,
        (), "Не удалось получить разбивку дохода по методам",
    )
    payment_totals = {
        "yookassa": 0.0, "yoomoney": 0.0, "platega_all": 0.0, "cryptobot": 0.0,
        "heleket": 0.0, "ton_connect": 0.0, "telegram_stars": 0.0,
    }
    method_map = {
        "yookassa": "yookassa",
        "yoomoney": "yoomoney",
        "platega": "platega_all",
        "platega payform": "platega_all",
        "platega crypto": "platega_all",
        "cryptobot": "cryptobot",
        "heleket": "heleket",
        "ton connect": "ton_connect",
        "telegram stars": "telegram_stars",
    }
    for row in payment_rows:
        bucket = method_map.get((row.get("method") or "").strip().lower())
        if bucket:
            payment_totals[bucket] += float(row.get("total") or 0)

    return {
        "total_users": int(admin_stats.get("total_users", 0) or 0),
        "total_keys": int(admin_stats.get("total_keys", 0) or 0),
        "active_keys": int(admin_stats.get("active_keys", 0) or 0),
        "total_income": float(total_income or 0),
        "no_purchases": len(user_groups.get("no_purchases", [])),
        "inactive_buyers": len(user_groups.get("inactive_buyers", [])),
        "trials": len(user_groups.get("trials", [])),
        "active_buyers": len(user_groups.get("active_buyers", [])),
        "active_keys_total": len(user_groups.get("active_keys", [])),
        "trial_used_total": int(trial_used_total or 0),
        "today_income": income_sum("AND date(created_date) = date('now', '+3 hours')"),
        "yesterday_income": income_sum("AND date(created_date) = date('now', '+3 hours', '-1 day')"),
        "week_income": income_sum("AND date(created_date) >= date('now', '+3 hours', '-6 day')"),
        "month_income": income_sum("AND strftime('%Y-%m', created_date) = strftime('%Y-%m', datetime('now', '+3 hours'))"),
        "last_month_income": income_sum("AND strftime('%Y-%m', created_date) = strftime('%Y-%m', datetime('now', '+3 hours', '-1 month'))"),
        "year_income": income_sum("AND strftime('%Y', created_date) = strftime('%Y', datetime('now', '+3 hours'))"),
        "today_topups": today_topups,
        "today_subscriptions": today_subscriptions,
        "today_new_users": int(admin_stats.get("today_new_users", 0) or 0),
        "today_bought_keys": int(admin_stats.get("today_bought_keys", 0) or 0),
        "today_trials": int(admin_stats.get("today_trials", 0) or 0),
        "pending_amount": float(pending_amount or 0),
        "pending_count": int(pending_count or 0),
        "user_balance_total": float(user_balance_total or 0),
        "partners_with_referrals": int(partners_with_referrals or 0),
        "total_referred": int(total_referred or 0),
        "partner_balance": float(partner_balance or 0),
        "partners_earned_total": float(partners_earned_total or 0),
        "partners_earned_month": referral_income_sum(
            "AND strftime('%Y-%m', created_date) = strftime('%Y-%m', datetime('now', '+3 hours'))"
        ),
        "top_partner": {
            "telegram_id": int(top_partner.get("telegram_id") or 0),
            "username": top_partner.get("username"),
            "referrals_count": int(top_partner.get("referrals_count") or 0),
        },
        "top_user": {
            "telegram_id": int(top_user.get("telegram_id") or 0),
            "username": top_user.get("username"),
            "months_total": int(top_user.get("months_total") or 0),
        },
        "payment_totals": payment_totals,
    }
# ====================================


# ===== CREATE_PENDING_TRANSACTION =====
def create_pending_transaction(payment_id: str, user_id: int, amount_rub: float, metadata: dict) -> int:
    cursor = _exec(
        "INSERT INTO transactions (payment_id, user_id, status, amount_rub, metadata) VALUES (?, ?, ?, ?, ?)",
        (payment_id, user_id, 'pending', amount_rub, json.dumps(metadata)),
        f"Не удалось создать ожидающую транзакцию для пользователя {user_id}"
    )
    return cursor.lastrowid if cursor else 0
# ====================================


# ===== LOG_TRANSACTION_SIMPLE =====
def log_transaction_simple(user_id: int, amount: float, method: str, description: str) -> bool:
    logging.info(f"📝 Логирование транзакции: user={user_id}, amount={amount}, method={method}")
    cursor = _exec(
        """
        INSERT INTO transactions (user_id, amount_rub, payment_method, status, description, created_date)
        VALUES (?, ?, ?, 'paid', ?, ?)
        """,
        (user_id, amount, method, description, get_msk_time().replace(tzinfo=None).replace(microsecond=0)),
        f"Не удалось залогировать транзакцию для пользователя {user_id}"
    )
    if cursor: logging.info(f"✅ Транзакция успешно сохранена для пользователя {user_id}"); return True
    return False
# ==================================

# ===== FIND_AND_COMPLETE_TON_TRANSACTION =====
def find_and_complete_ton_transaction(payment_id: str, amount_ton: float) -> dict | None:
    row = _fetch_row("SELECT * FROM transactions WHERE payment_id = ? AND status = 'pending'", (payment_id,), "")
    if not row: logging.warning(f"TON Webhook: Получен платеж для неизвестного или уже обработанного payment_id: {payment_id}"); return None
        
    cursor = _exec(
        "UPDATE transactions SET status = 'paid', amount_currency = ?, currency_name = 'TON', payment_method = 'TON' WHERE payment_id = ?",
        (amount_ton, payment_id),
        f"Не удалось завершить TON-транзакцию {payment_id}"
    )
    
    if cursor and cursor.rowcount > 0:
        try: return json.loads(row['metadata'])
        except Exception: return {}

    return None
# ===============================================


# ===== LOG_TRANSACTION =====
def log_transaction(username: str, transaction_id: str | None, payment_id: str | None, user_id: int, status: str, amount_rub: float, amount_currency: float | None, currency_name: str | None, payment_method: str, metadata: str):
    _exec(
        """INSERT INTO transactions
           (username, transaction_id, payment_id, user_id, status, amount_rub, amount_currency, currency_name, payment_method, metadata, created_date)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (username, transaction_id, payment_id, user_id, status, amount_rub, amount_currency, currency_name, payment_method, metadata, get_msk_time().replace(tzinfo=None).replace(microsecond=0)),
        f"Не удалось залогировать транзакцию для пользователя {user_id}"
    )
# ===========================

# ===== CHECK_TRANSACTION_EXISTS =====
def check_transaction_exists(payment_id: str) -> bool:
    row = _fetch_row("SELECT 1 as ex FROM transactions WHERE payment_id = ? LIMIT 1", (payment_id,), f"Не удалось проверить транзакцию {payment_id}")
    return bool(row)

def get_paginated_transactions(page: int = 1, per_page: int = 15) -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    transactions = []
    total = 0

    r_count = _fetch_row("SELECT COUNT(*) as c FROM transactions", (), "Не удалось получить кол-во транзакций")
    total = r_count["c"] if r_count else 0

    query = "SELECT * FROM transactions ORDER BY created_date DESC LIMIT ? OFFSET ?"
    rows = _fetch_list(query, (per_page, offset), "Не удалось получить страницу транзакций")

    for row in rows:
        transaction_dict = dict(row)
        
        metadata_str = transaction_dict.get('metadata')
        if metadata_str:
            try:
                metadata = json.loads(metadata_str)
                transaction_dict['action'] = metadata.get('action')
                transaction_dict['host_name'] = metadata.get('host_name', 'N/A')
                transaction_dict['plan_name'] = metadata.get('plan_name', 'N/A')
            except json.JSONDecodeError:
                transaction_dict['action'] = None
                transaction_dict['host_name'] = 'Error'
                transaction_dict['plan_name'] = 'Error'
        else:
            transaction_dict['host_name'] = 'N/A'
            transaction_dict['plan_name'] = 'N/A'
        
        transactions.append(transaction_dict)
    
    return transactions, total
# ==========================================


# ===== SET_TRIAL_USED =====
def set_trial_used(telegram_id: int):
    cursor = _exec("UPDATE users SET trial_used = 1 WHERE telegram_id = ?", (telegram_id,), f"Не удалось установить trial_used для пользователя {telegram_id}")
    if cursor: logging.info(f"Пробный период отмечен как использованный для пользователя {telegram_id}.")
# ========================


# ===== ADD_NEW_KEY =====
def add_new_key(
    user_id: int,
    host_name: str | None,
    remnawave_user_uuid: str,
    key_email: str,
    expiry_timestamp_ms: int,
    *,
    squad_uuid: str | None = None,
    short_uuid: str | None = None,
    subscription_url: str | None = None,
    traffic_limit_bytes: int | None = None,
    traffic_limit_strategy: str | None = None,
    description: str | None = None,
    tag: str | None = None,
    comment_key: str | None = None,
    created_at_ms: int | None = None,
) -> int | None:
    host_name_norm = normalize_host_name(host_name) if host_name else None
    email_normalized = _normalize_email(key_email) or key_email.strip()
    expire_str = _to_datetime_str(expiry_timestamp_ms) or _now_str()
    created_str = _to_datetime_str(created_at_ms) or _now_str() if created_at_ms is not None else _now_str()
    strategy_value = traffic_limit_strategy or "NO_RESET"
    
    cursor = _exec(
        """
        INSERT INTO vpn_keys (
            user_id, host_name, squad_uuid, remnawave_user_uuid, short_uuid, email, key_email,
            subscription_url, expire_at, created_at, updated_at, traffic_limit_bytes,
            traffic_limit_strategy, tag, description, comment_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id, host_name_norm, squad_uuid, remnawave_user_uuid, short_uuid, email_normalized,
            email_normalized, subscription_url, expire_str, created_str, created_str,
            traffic_limit_bytes, strategy_value, tag, description, comment_key
        ),
        f"Не удалось добавить новый ключ для пользователя {user_id}"
    )
    return cursor.lastrowid if cursor else None
# =======================


# ===== _APPLY_KEY_UPDATES =====
def _apply_key_updates(key_id: int, updates: dict[str, Any]) -> bool:
    if not updates: return False
    updates = dict(updates)
    updates["updated_at"] = _now_str()
    columns = ", ".join(f"{column} = ?" for column in updates)
    values = list(updates.values())
    values.append(key_id)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE vpn_keys SET {columns} WHERE key_id = ?",
                tuple(values),
            )
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e: logging.error("Не удалось обновить ключ %s: %s", key_id, e); return False
# ==============================


# ===== UPDATE_KEY_FIELDS =====
def update_key_fields(
    key_id: int,
    *,
    user_id: int | None = None,
    host_name: str | None = None,
    squad_uuid: str | None = None,
    remnawave_user_uuid: str | None = None,
    short_uuid: str | None = None,
    email: str | None = None,
    subscription_url: str | None = None,
    expire_at_ms: int | None = None,
    traffic_limit_bytes: int | None = None,
    traffic_limit_strategy: str | None = None,
    tag: str | None = None,
    description: str | None = None,
    comment_key: str | None = None,
    is_pinned: bool | None = None,
) -> bool:
    updates: dict[str, Any] = {}
    if user_id is not None:
        updates["user_id"] = user_id
    if host_name is not None:
        updates["host_name"] = normalize_host_name(host_name)
    if squad_uuid is not None:
        updates["squad_uuid"] = squad_uuid
    if remnawave_user_uuid is not None:
        updates["remnawave_user_uuid"] = remnawave_user_uuid
    if short_uuid is not None:
        updates["short_uuid"] = short_uuid
    if email is not None:
        normalized = _normalize_email(email) or email.strip()
        updates["email"] = normalized
        updates["key_email"] = normalized
    if subscription_url is not None:
        updates["subscription_url"] = subscription_url
    if expire_at_ms is not None:
        expire_str = _to_datetime_str(expire_at_ms) or _now_str()
        updates["expire_at"] = expire_str
    if traffic_limit_bytes is not None:
        updates["traffic_limit_bytes"] = traffic_limit_bytes
    if traffic_limit_strategy is not None:
        updates["traffic_limit_strategy"] = traffic_limit_strategy or "NO_RESET"
    if tag is not None:
        updates["tag"] = tag
    if description is not None:
        updates["description"] = description
    if comment_key is not None:
        updates["comment_key"] = comment_key
    if is_pinned is not None:
        updates["is_pinned"] = 1 if is_pinned else 0
    return _apply_key_updates(key_id, updates)
# ===========================


# ===== DELETE_KEY_BY_EMAIL =====
def delete_key_by_email(email: str) -> bool:
    lookup = _normalize_email(email) or email.strip()
    cursor = _exec(
        "DELETE FROM vpn_keys WHERE email = ? OR key_email = ?",
        (lookup, lookup),
        "Не удалось удалить ключ"
    )
    if cursor: logger.debug("delete_key_by_email('%s') affected=%s", email, cursor.rowcount); return cursor.rowcount > 0
    return False
# ===========================


# ===== GET_USER_KEYS =====
def get_user_keys(user_id: int) -> list[dict]:
    rows = _fetch_list(
        "SELECT * FROM vpn_keys WHERE user_id = ? ORDER BY datetime(created_at) DESC, key_id DESC",
        (user_id,),
        f"Не удалось получить ключи для пользователя {user_id}"
    )
    return [_normalize_key_row(row) for row in rows]
# ===========================


# ===== GET_KEY_BY_ID =====
def get_key_by_id(key_id: int) -> dict | None:
    row = _fetch_row(
        "SELECT * FROM vpn_keys WHERE key_id = ?",
        (key_id,),
        f"Не удалось получить ключ по ID {key_id}"
    )
    return _normalize_key_row(row)
# =========================


# ===== GET_KEY_BY_EMAIL =====
def get_key_by_email(key_email: str) -> dict | None:
    lookup = _normalize_email(key_email) or key_email.strip()
    row = _fetch_row(
        "SELECT * FROM vpn_keys WHERE email = ? OR key_email = ?",
        (lookup, lookup),
        f"Не удалось получить ключ по email {key_email}"
    )
    return _normalize_key_row(row)
# =================================


# ===== GET_KEY_BY_REMNAWAVE_UUID =====
def get_key_by_remnawave_uuid(remnawave_uuid: str) -> dict | None:
    if not remnawave_uuid: return None
    normalized_uuid = remnawave_uuid.strip()
    row = _fetch_row(
        "SELECT * FROM vpn_keys WHERE remnawave_user_uuid = ? LIMIT 1",
        (normalized_uuid,),
        f"Не удалось получить ключ по remnawave uuid {remnawave_uuid}"
    )
    return _normalize_key_row(row)
# ===========================


# ===== USERNAME / ИСТОРИЯ ИМЁН =====
# Подпись для пользователей без телеграм-username: их может не быть
# у зарегистрировавшихся через мини-апп либо у скрывших имя.
NO_USERNAME_LABEL = "Безымянный пользователь"


def normalize_username(username: str | None) -> str | None:
    """Приводит имя к каноничному виду: без @, пустое -> None."""
    if username is None:
        return None
    value = str(username).strip().lstrip("@").strip()
    return value or None


def format_username(username: str | None) -> str:
    """Готовая к показу подпись пользователя."""
    value = normalize_username(username)
    return f"@{value}" if value else NO_USERNAME_LABEL


def add_username_history(
    user_id: int,
    username: str | None,
    previous_username: str | None = None,
    source: str = "telegram",
) -> bool:
    """Добавляет запись в историю имён."""
    return _exec(
        "INSERT INTO username_history (user_id, username, previous_username, source) "
        "VALUES (?, ?, ?, ?)",
        (user_id, normalize_username(username), normalize_username(previous_username), source),
        f"Не удалось записать историю имени пользователя {user_id}"
    ) is not None


def get_username_history(user_id: int, limit: int = 50) -> list[dict]:
    """История имён пользователя, новые записи первыми."""
    return _fetch_list(
        "SELECT id, username, previous_username, source, changed_at "
        "FROM username_history WHERE user_id = ? "
        "ORDER BY datetime(changed_at) DESC, id DESC LIMIT ?",
        (user_id, limit),
        f"Не удалось получить историю имён пользователя {user_id}"
    )


def set_username(user_id: int, username: str | None, source: str = "telegram") -> dict:
    """
    Обновляет имя пользователя и, если оно изменилось, пишет запись
    в историю. Возвращает {changed, previous, current}.
    """
    row = _fetch_row(
        "SELECT username FROM users WHERE telegram_id = ?",
        (user_id,),
        f"Не удалось получить текущее имя пользователя {user_id}"
    )
    if row is None:
        return {"changed": False, "previous": None, "current": None, "found": False}

    previous = normalize_username(row.get("username"))
    current = normalize_username(username)

    if previous == current:
        return {"changed": False, "previous": previous, "current": current, "found": True}

    _exec(
        "UPDATE users SET username = ? WHERE telegram_id = ?",
        (current, user_id),
        f"Не удалось обновить имя пользователя {user_id}"
    )
    add_username_history(user_id, current, previous, source)
    return {"changed": True, "previous": previous, "current": current, "found": True}


def get_matching_user_ids(q: str | None = None) -> list[int]:
    """
    ID всех пользователей, подходящих под тот же фильтр, что и на странице
    списка. Нужен для действия «выбрать всех», чтобы выбор не ограничивался
    текущей страницей, но и не игнорировал поиск.
    """
    if q and q.strip():
        q_like = f"%{q.strip()}%"
        rows = _fetch_list(
            "SELECT telegram_id FROM users "
            "WHERE (username LIKE ?) OR (CAST(telegram_id AS TEXT) LIKE ?) OR (auth_email LIKE ?) "
            "ORDER BY telegram_id",
            (q_like, q_like, q_like),
            "Не удалось получить ID пользователей по фильтру"
        )
    else:
        rows = _fetch_list(
            "SELECT telegram_id FROM users ORDER BY telegram_id",
            (),
            "Не удалось получить ID пользователей"
        )
    return [int(r["telegram_id"]) for r in (rows or []) if r.get("telegram_id") is not None]


def get_all_user_ids() -> list[int]:
    """Список telegram_id всех пользователей."""
    rows = _fetch_list(
        "SELECT telegram_id FROM users ORDER BY telegram_id",
        (),
        "Не удалось получить список пользователей"
    )
    return [int(r["telegram_id"]) for r in rows if r.get("telegram_id") is not None]
# ===================================


# ===== SUBSCRIPTION RESET COOLDOWN =====
# Единый на весь проект интервал между пересозданиями подписки.
# Хранится в БД, поэтому ограничение общее для бота, веб-приложения
# и переживает перезапуск процессов.
RESET_SUBSCRIPTION_COOLDOWN_SECONDS = 3600


def get_last_subscription_reset(key_id: int) -> int | None:
    """Unix-время последнего пересоздания подписки или None."""
    row = _fetch_row(
        "SELECT last_subscription_reset_at FROM vpn_keys WHERE key_id = ?",
        (key_id,),
        f"Не удалось получить время последнего сброса подписки {key_id}"
    )
    if not row:
        return None
    value = row.get("last_subscription_reset_at")
    return int(value) if value else None


def get_subscription_reset_wait(key_id: int, *, cooldown: int | None = None) -> int:
    """
    Сколько секунд осталось ждать до следующего пересоздания.
    0 — можно сбрасывать прямо сейчас.
    """
    import time as _time
    limit = RESET_SUBSCRIPTION_COOLDOWN_SECONDS if cooldown is None else cooldown
    if limit <= 0:
        return 0
    last = get_last_subscription_reset(key_id)
    if not last:
        return 0
    elapsed = int(_time.time()) - last
    remaining = limit - elapsed
    return remaining if remaining > 0 else 0


def clear_subscription_reset(key_id: int) -> bool:
    """Снимает ограничение по частоте для одной подписки."""
    result = _exec(
        "UPDATE vpn_keys SET last_subscription_reset_at = NULL WHERE key_id = ?",
        (key_id,),
        f"Не удалось снять кулдаун сброса подписки {key_id}"
    )
    return result is not None


def clear_subscription_reset_for_user(user_id: int) -> int:
    """
    Снимает ограничение по частоте для всех подписок пользователя.
    Возвращает количество затронутых записей.
    """
    result = _exec(
        "UPDATE vpn_keys SET last_subscription_reset_at = NULL "
        "WHERE user_id = ? AND last_subscription_reset_at IS NOT NULL",
        (user_id,),
        f"Не удалось снять кулдаун сброса подписок пользователя {user_id}"
    )
    return result.rowcount if result else 0


def reset_trial_for_user(user_id: int) -> bool:
    """Возвращает пользователю право на пробный период."""
    result = _exec(
        "UPDATE users SET trial_used = 0 WHERE telegram_id = ?",
        (user_id,),
        f"Не удалось сбросить пробный период пользователя {user_id}"
    )
    return result is not None


def mark_subscription_reset(key_id: int, ts: int | None = None) -> bool:
    """Отмечает момент пересоздания подписки."""
    import time as _time
    stamp = int(ts if ts is not None else _time.time())
    result = _exec(
        "UPDATE vpn_keys SET last_subscription_reset_at = ? WHERE key_id = ?",
        (stamp, key_id),
        f"Не удалось отметить сброс подписки {key_id}"
    )
    return result is not None
# =======================================


# ===== GET_KEY_BY_SHORT_UUID =====
def get_key_by_short_uuid(short_uuid: str) -> dict | None:
    """Поиск подписки по короткому идентификатору из ссылки подписки."""
    if not short_uuid:
        return None
    normalized = short_uuid.strip()
    if not normalized:
        return None
    row = _fetch_row(
        "SELECT * FROM vpn_keys WHERE short_uuid = ? LIMIT 1",
        (normalized,),
        f"Не удалось получить подписку по short_uuid {short_uuid}"
    )
    return _normalize_key_row(row)
# =================================


# ===== GET_KEY_BY_SUBSCRIPTION_URL =====
def get_key_by_subscription_url(subscription_url: str) -> dict | None:
    """
    Поиск подписки по полной ссылке. Сравнение без учёта регистра и
    завершающего слэша, чтобы пользователь мог вставить ссылку как есть.
    """
    if not subscription_url:
        return None
    normalized = subscription_url.strip().rstrip('/')
    if not normalized:
        return None
    row = _fetch_row(
        "SELECT * FROM vpn_keys "
        "WHERE LOWER(TRIM(RTRIM(subscription_url, '/'))) = LOWER(?) LIMIT 1",
        (normalized,),
        "Не удалось получить подписку по ссылке"
    )
    return _normalize_key_row(row)
# =======================================


# ===== UPDATE_KEY_INFO =====
def update_key_info(key_id: int, new_remnawave_uuid: str, new_expiry_ms: int, **kwargs) -> bool:
    return update_key_fields(
        key_id,
        remnawave_user_uuid=new_remnawave_uuid,
        expire_at_ms=new_expiry_ms,
        **kwargs,
    )


# ===== UPDATE_KEY_HOST_AND_INFO =====
def update_key_host_and_info(
    key_id: int,
    new_host_name: str,
    new_remnawave_uuid: str,
    new_expiry_ms: int,
    **kwargs,
) -> bool:
    return update_key_fields(
        key_id,
        host_name=new_host_name,
        remnawave_user_uuid=new_remnawave_uuid,
        expire_at_ms=new_expiry_ms,
        **kwargs,
    )


# ===== GET_NEXT_KEY_NUMBER =====
def get_next_key_number(user_id: int) -> int:
    count = _fetch_val("SELECT COUNT(*) FROM vpn_keys WHERE user_id = ?", (user_id,), 0)
    return int(count) + 1
# ===========================


# ===== GET_KEYS_FOR_HOST =====
def get_keys_for_host(host_name: str) -> list[dict]:
    host_name_normalized = normalize_host_name(host_name)
    rows = _fetch_list(
        "SELECT * FROM vpn_keys WHERE TRIM(host_name) = TRIM(?)",
        (host_name_normalized,),
        f"Не удалось получить ключи для хоста '{host_name}'"
    )
    return [_normalize_key_row(row) for row in rows]
# =============================


# ===== GET_ALL_VPN_USERS =====
def get_all_vpn_users() -> list[dict]:
    return _fetch_list("SELECT DISTINCT user_id FROM vpn_keys", (), "Не удалось получить всех VPN пользователей")
# ===========================


# ===== UPDATE_KEY_STATUS_FROM_SERVER =====
def update_key_status_from_server(key_email: str, client_data) -> bool:
    try:
        normalized_email = _normalize_email(key_email) or key_email.strip()
        existing = get_key_by_email(normalized_email)
        if client_data:
            if isinstance(client_data, dict):
                remote_uuid = client_data.get('uuid') or client_data.get('id')
                expire_value = client_data.get('expireAt') or client_data.get('expiryDate')
                subscription_url = client_data.get('subscriptionUrl') or client_data.get('subscription_url')
                expiry_ms = None
                if expire_value:
                    try:
                        remote_dt = datetime.fromisoformat(str(expire_value).replace('Z', '+00:00'))
                        expiry_ms = int(remote_dt.timestamp() * 1000)
                    except Exception: expiry_ms = None
            else:
                remote_uuid = getattr(client_data, 'id', None) or getattr(client_data, 'uuid', None)
                expiry_ms = getattr(client_data, 'expiry_time', None)
                subscription_url = getattr(client_data, 'subscription_url', None)
            if not existing: return False
            return update_key_fields(
                existing['key_id'],
                remnawave_user_uuid=remote_uuid,
                expire_at_ms=expiry_ms,
                subscription_url=subscription_url,
            )
        if existing: return delete_key_by_email(normalized_email)
        return True
    except sqlite3.Error as e: logging.error("Не удалось обновить статус ключа для %s: %s", key_email, e); return False
# ===========================


# ===== GET_DAILY_STATS_FOR_CHARTS =====
def get_daily_stats_for_charts(days: int = 30) -> dict:
    stats = {'users': {}, 'keys': {}, 'income': {}, 'finance': {'topups': {'amount': 0.0, 'count': 0}, 'subscriptions': {'amount': 0.0, 'count': 0}, 'total': {'amount': 0.0, 'count': 0}}}
    time_filter = ""
    params = []
    group_fmt = "%Y-%m-%d"
    
    if days > 0:
        time_filter = " >= datetime('now', '+3 hours', ?)"
        params.append(f'-{days} days')
        if days == 1: group_fmt = "%Y-%m-%d %H:00"
    
    def get_data(table, date_col, is_count=True):
        nonlocal group_fmt
        where_clause = f"WHERE {date_col} {time_filter}" if time_filter else ""
        
        if is_count:
            query = f"SELECT STRFTIME('{group_fmt}', {date_col}) AS period, COUNT(*) as cnt FROM {table} {where_clause} GROUP BY period ORDER BY period"
        else:
            income_filter = "LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success') AND LOWER(COALESCE(payment_method, '')) NOT IN ('balance', 'admin', 'referral')"
            if where_clause:
                where_clause += f" AND {income_filter}"
            else:
                where_clause = f"WHERE {income_filter}"
            query = f"SELECT STRFTIME('{group_fmt}', {date_col}) AS period, payment_method, SUM(amount_rub) as total FROM {table} {where_clause} GROUP BY period, payment_method ORDER BY period"
        
        return _fetch_list(query, tuple(params), "Не удалось получить данные статистики по дням")

    for row in get_data("users", "registration_date"):
        stats['users'][row['period']] = row['cnt']

    for row in get_data("vpn_keys", "COALESCE(created_at, updated_at, CURRENT_TIMESTAMP)"):
        stats['keys'][row['period']] = row['cnt']

    for row in get_data("transactions", "created_date", is_count=False):
        period = row['period']
        method = row['payment_method']
        amount = row['total']
        if period not in stats['income']:
            stats['income'][period] = {}
        stats['income'][period][method or 'Other'] = float(amount) if amount else 0.0
    
    tx_where = "WHERE LOWER(COALESCE(status, '')) IN ('paid', 'completed', 'success')"
    tx_params = []
    if days > 0:
        tx_where += " AND created_date >= datetime('now', '+3 hours', ?)"
        tx_params.append(f'-{days} days')
    rows = _fetch_list(
        f"""
        SELECT amount_rub, payment_method, metadata
        FROM transactions
        {tx_where}
        """,
        tuple(tx_params),
        "Не удалось получить финансовую статистику"
    )
    for row in rows:
        amount = float(row['amount_rub'] or 0.0)
        payment_method = str(row['payment_method'] or '').strip().lower()
        try:
            metadata = json.loads(row['metadata'] or '{}')
            if not isinstance(metadata, dict):
                metadata = {}
        except Exception:
            metadata = {}
        action = str(metadata.get('action') or '').strip().lower()
        reason = str(metadata.get('reason') or '').strip().lower()
        is_income_method = payment_method not in ('balance', 'admin', 'referral')
        is_topup = action in ('topup', 'top_up') or reason == 'external_balance_top_up'
        is_subscription = action in ('new', 'extend') or reason == 'subscription_purchase_or_extend' or any(metadata.get(k) for k in ('plan_id', 'key_id', 'host_name', 'host', 'customer_email')) or is_income_method
        if is_topup and is_income_method:
            stats['finance']['topups']['amount'] += abs(amount)
            stats['finance']['topups']['count'] += 1
        elif is_subscription and is_income_method:
            stats['finance']['subscriptions']['amount'] += abs(amount)
            stats['finance']['subscriptions']['count'] += 1
    stats['finance']['total']['amount'] = stats['finance']['topups']['amount'] + stats['finance']['subscriptions']['amount']
    stats['finance']['total']['count'] = stats['finance']['topups']['count'] + stats['finance']['subscriptions']['count']
    return stats
# ==========================


# ===== GET_RECENT_TRANSACTIONS =====
def get_recent_transactions(limit: int = 15) -> list[dict]:
    query = """
        SELECT
            k.key_id,
            k.host_name,
            k.created_at,
            u.telegram_id,
            u.username
        FROM vpn_keys k
        JOIN users u ON k.user_id = u.telegram_id
        ORDER BY datetime(k.created_at) DESC, k.key_id DESC
        LIMIT ?
    """
    rows = _fetch_list(query, (limit,), "Не удалось получить последние транзакции")
    return rows


# ===== GET_ALL_USERS =====
# Получение всех пользователей с сортировкой по дате регистрации
def get_all_users() -> list[dict]:
    return _fetch_list("SELECT * FROM users ORDER BY registration_date DESC", (), "Не удалось получить всех пользователей")
# ===================================


# ===== GET_USERS_PAGINATED =====
def get_users_paginated(page: int = 1, per_page: int = 30, q: str | None = None) -> tuple[list[dict], int]:
    """Вернуть пользователей постранично и общее количество (с учётом фильтра).

    Фильтр q ищет по username (LIKE) и по текстовому представлению telegram_id.
    """
    page = max(1, int(page or 1))
    per_page = max(1, int(per_page or 30))
    offset = (page - 1) * per_page
    
    if q:
        q_like = f"%{q.strip()}%"
        
        # Веб-аккаунты часто не имеют username вовсе — без поиска по почте
        # найти такого человека в панели было нечем
        where = ("WHERE (username LIKE ?) OR (CAST(telegram_id AS TEXT) LIKE ?) "
                 "OR (auth_email LIKE ?)")
        args = (q_like, q_like, q_like)
        total = _fetch_val(f"SELECT COUNT(*) FROM users {where}", args, 0,
                           "Не удалось подсчитать пользователей с фильтром") or 0
        users = _fetch_list(
            f"SELECT * FROM users {where} ORDER BY is_pinned DESC, registration_date DESC LIMIT ? OFFSET ?",
            args + (per_page, offset), "Не удалось получить страницу пользователей с фильтром")
    else:
        total = _fetch_val("SELECT COUNT(*) FROM users", (), 0, "Не удалось подсчитать пользователей") or 0
        
        data_query = "SELECT * FROM users ORDER BY is_pinned DESC, registration_date DESC LIMIT ? OFFSET ?"
        users = _fetch_list(data_query, (per_page, offset), "Не удалось получить страницу пользователей")

    return users, total


    return users, total
# ========================


# ===== TOGGLE_USER_PIN =====
def toggle_user_pin(user_id: int) -> bool:
    cursor = _exec(
        "UPDATE users SET is_pinned = NOT COALESCE(is_pinned, 0) WHERE telegram_id = ?",
        (user_id,),
        f"Не удалось переключить закреп для пользователя {user_id}"
    )
    return cursor is not None and cursor.rowcount > 0

    return cursor is not None and cursor.rowcount > 0
# ===========================


# ===== GET_KEYS_COUNTS_FOR_USERS =====
def get_keys_counts_for_users(user_ids: list[int]) -> dict[int, int]:
    result: dict[int, int] = {}
    if not user_ids: return result

    placeholders = ",".join(["?"] * len(user_ids))
    query = f"SELECT user_id, COUNT(*) AS cnt FROM vpn_keys WHERE user_id IN ({placeholders}) GROUP BY user_id"
    
    rows = _fetch_list(query, tuple(int(x) for x in user_ids), "Не удалось получить кол-во ключей для пользователей")
    
    for row in rows: result[int(row['user_id'])] = int(row['cnt'] or 0)
        
    return result

# ===== BAN_USER =====
# Установка флага is_banned=1 для пользователя
def ban_user(telegram_id: int):
    _exec("UPDATE users SET is_banned = 1 WHERE telegram_id = ?", (telegram_id,), f"Не удалось забанить пользователя {telegram_id}")

# ===== UNBAN_USER =====
# Снятие бана (is_banned=0) для пользователя
def unban_user(telegram_id: int):
    _exec("UPDATE users SET is_banned = 0 WHERE telegram_id = ?", (telegram_id,), f"Не удалось разбанить пользователя {telegram_id}")

# ===== DELETE_USER_KEYS =====
# Удаление всех ключей пользователя
def delete_user_keys(user_id: int):
    _exec("DELETE FROM vpn_keys WHERE user_id = ?", (user_id,), f"Не удалось удалить ключи пользователя {user_id}")

# ===== CREATE_SUPPORT_TICKET =====
def create_support_ticket(user_id: int, subject: str | None = None) -> int | None:
    row = _fetch_row(
        "SELECT ticket_id FROM support_tickets WHERE user_id = ? AND status = 'open' ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
        ""
    )
    if row and row['ticket_id']: return int(row['ticket_id'])

    cursor = _exec(
        "INSERT INTO support_tickets (user_id, subject) VALUES (?, ?)",
        (user_id, subject),
        f"Не удалось создать тикет поддержки для пользователя {user_id}"
    )
    return cursor.lastrowid if cursor else None

    return cursor.lastrowid if cursor else None
# ===========================


# ===== GET_OR_CREATE_OPEN_TICKET =====
def get_or_create_open_ticket(user_id: int, subject: str | None = None) -> tuple[int | None, bool]:
    row = _fetch_row(
        "SELECT ticket_id FROM support_tickets WHERE user_id = ? AND status = 'open' ORDER BY updated_at DESC LIMIT 1",
        (user_id,),
        f"Не удалось получить тикет для пользователя {user_id}"
    )
    if row and row['ticket_id']: return int(row['ticket_id']), False
    cursor = _exec(
        "INSERT INTO support_tickets (user_id, subject) VALUES (?, ?)",
        (user_id, subject),
        f"Не удалось создать/получить тикет для пользователя {user_id}"
    )
    if cursor and cursor.lastrowid: return int(cursor.lastrowid), True
    return None, False

    return None, False
# ===================================


# ===== ADD_SUPPORT_MESSAGE =====
def add_support_message(ticket_id: int, sender: str, content: str, media: str | None = None) -> int | None:
    cursor = _exec(
        "INSERT INTO support_messages (ticket_id, sender, content, media) VALUES (?, ?, ?, ?)",
        (ticket_id, sender, content, media),
        f"Не удалось добавить сообщение в тикет {ticket_id}"
    )
    if cursor and cursor.lastrowid: mid = cursor.lastrowid; _exec("UPDATE support_tickets SET updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?", (ticket_id,), "Не удалось обновить время тикета"); return mid
    return None
# =============================


# ===== ВЛОЖЕНИЯ ПОДДЕРЖКИ =====
SUPPORT_MEDIA_DEFAULT_MAX_MB = 10
SUPPORT_MEDIA_DEFAULT_ALLOWED = "jpg,jpeg,png,webp,gif,mp4,mov,pdf"


def get_support_media_settings() -> dict:
    """Настройки вложений: включены ли, лимит размера, разрешённые форматы."""
    def _flag(name: str, default: bool) -> bool:
        raw = (get_setting(name) or "").strip().lower()
        if not raw:
            return default
        return raw in ("1", "true", "on", "yes", "да")

    try:
        max_mb = float((get_setting("support_media_max_mb") or SUPPORT_MEDIA_DEFAULT_MAX_MB))
    except Exception:
        max_mb = SUPPORT_MEDIA_DEFAULT_MAX_MB
    max_mb = max(0.1, min(max_mb, 50.0))  # Bot API не отдаёт файлы больше 50 МБ

    raw_allowed = (get_setting("support_media_allowed") or SUPPORT_MEDIA_DEFAULT_ALLOWED)
    allowed = sorted({
        e.strip().lower().lstrip(".")
        for e in re.split(r"[\s,;]+", raw_allowed) if e.strip()
    })

    try:
        keep_days = int(get_setting("support_media_keep_days") or 0)
    except Exception:
        keep_days = 0

    return {
        "enabled": _flag("support_media_enabled", True),
        "max_mb": max_mb,
        "max_bytes": int(max_mb * 1024 * 1024),
        "allowed": allowed or SUPPORT_MEDIA_DEFAULT_ALLOWED.split(","),
        "keep_days": max(0, keep_days),
    }


def add_support_media(
    ticket_id: int,
    *,
    message_id: int | None = None,
    sender: str = "user",
    kind: str = "photo",
    file_id: str | None = None,
    file_unique_id: str | None = None,
    local_path: str | None = None,
    file_name: str | None = None,
    mime_type: str | None = None,
    file_size: int = 0,
    width: int | None = None,
    height: int | None = None,
) -> int | None:
    cursor = _exec(
        "INSERT INTO support_media (ticket_id, message_id, sender, kind, file_id, "
        "file_unique_id, local_path, file_name, mime_type, file_size, width, height) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, message_id, sender, kind, file_id, file_unique_id, local_path,
         file_name, mime_type, int(file_size or 0), width, height),
        f"Не удалось сохранить вложение тикета {ticket_id}"
    )
    return cursor.lastrowid if cursor and cursor.lastrowid else None


def update_support_media_path(media_id: int, local_path: str, file_size: int = 0) -> bool:
    """Проставляет локальный путь после дозагрузки файла из Telegram."""
    cursor = _exec(
        "UPDATE support_media SET local_path = ?, file_size = CASE WHEN ? > 0 THEN ? ELSE file_size END "
        "WHERE media_id = ?",
        (local_path, int(file_size or 0), int(file_size or 0), media_id),
        f"Не удалось обновить путь вложения {media_id}"
    )
    return cursor is not None


def get_support_media(media_id: int) -> dict | None:
    return _fetch_row(
        "SELECT * FROM support_media WHERE media_id = ?",
        (media_id,),
        f"Не удалось получить вложение {media_id}"
    )


def get_media_for_ticket(ticket_id: int) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM support_media WHERE ticket_id = ? ORDER BY media_id",
        (ticket_id,),
        f"Не удалось получить вложения тикета {ticket_id}"
    )


def get_media_for_messages(message_ids: list[int]) -> dict[int, list[dict]]:
    """Вложения, сгруппированные по id сообщения (одним запросом)."""
    ids = [int(m) for m in (message_ids or []) if m]
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    rows = _fetch_list(
        f"SELECT * FROM support_media WHERE message_id IN ({placeholders}) ORDER BY media_id",
        tuple(ids),
        "Не удалось получить вложения сообщений"
    )
    grouped: dict[int, list[dict]] = {}
    for r in rows or []:
        grouped.setdefault(int(r["message_id"]), []).append(r)
    return grouped


def get_support_media_stats() -> dict:
    """Сводка по хранилищу вложений для страницы обслуживания."""
    row = _fetch_row(
        "SELECT COUNT(*) AS cnt, COALESCE(SUM(file_size), 0) AS bytes FROM support_media",
        (), "Не удалось получить статистику вложений"
    ) or {}
    orphan = _fetch_val(
        "SELECT COUNT(*) FROM support_media m "
        "LEFT JOIN support_tickets t ON t.ticket_id = m.ticket_id "
        "WHERE t.ticket_id IS NULL",
        (), 0, "Не удалось посчитать осиротевшие вложения"
    ) or 0
    return {
        "count": int(row.get("cnt") or 0),
        "bytes": int(row.get("bytes") or 0),
        "orphan": int(orphan),
    }


def list_support_media(limit: int = 200, offset: int = 0) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM support_media ORDER BY media_id DESC LIMIT ? OFFSET ?",
        (int(limit), int(offset)),
        "Не удалось получить список вложений"
    )


def delete_support_media(media_id: int) -> dict | None:
    """Удаляет запись и возвращает её, чтобы вызывающий убрал файл с диска."""
    row = get_support_media(media_id)
    if not row:
        return None
    _exec("DELETE FROM support_media WHERE media_id = ?", (media_id,),
          f"Не удалось удалить вложение {media_id}")
    return row


def get_media_to_cleanup(older_than_days: int = 0, orphan_only: bool = False) -> list[dict]:
    """Вложения под очистку: осиротевшие и/или старше N дней."""
    if orphan_only:
        return _fetch_list(
            "SELECT m.* FROM support_media m "
            "LEFT JOIN support_tickets t ON t.ticket_id = m.ticket_id "
            "WHERE t.ticket_id IS NULL",
            (), "Не удалось получить осиротевшие вложения"
        )
    if older_than_days and older_than_days > 0:
        return _fetch_list(
            "SELECT * FROM support_media "
            "WHERE datetime(created_at) < datetime('now', ?)",
            (f"-{int(older_than_days)} days",),
            "Не удалось получить старые вложения"
        )
    return []
# ==============================


# ===== UPDATE_TICKET_THREAD_INFO =====
def update_ticket_thread_info(ticket_id: int, forum_chat_id: str | None, message_thread_id: int | None) -> bool:
    cursor = _exec(
        "UPDATE support_tickets SET forum_chat_id = ?, message_thread_id = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
        (forum_chat_id, message_thread_id, ticket_id),
        f"Не удалось обновить инфо о треде для тикета {ticket_id}"
    )
    return cursor is not None and cursor.rowcount > 0

    return cursor is not None and cursor.rowcount > 0
# =================================


# ===== GET_TICKET =====
def get_ticket(ticket_id: int) -> dict | None:
    return _fetch_row("SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,), f"Не удалось получить тикет {ticket_id}")

    return _fetch_row("SELECT * FROM support_tickets WHERE ticket_id = ?", (ticket_id,), f"Не удалось получить тикет {ticket_id}")
# ==================


# ===== GET_TICKET_BY_THREAD =====
def get_ticket_by_thread(forum_chat_id: str, message_thread_id: int) -> dict | None:
    return _fetch_row(
        "SELECT * FROM support_tickets WHERE forum_chat_id = ? AND message_thread_id = ?",
        (str(forum_chat_id), int(message_thread_id)),
        f"Не удалось получить тикет по треду {forum_chat_id}/{message_thread_id}"
    )

    return _fetch_row(
        "SELECT * FROM support_tickets WHERE forum_chat_id = ? AND message_thread_id = ?",
        (str(forum_chat_id), int(message_thread_id)),
        f"Не удалось получить тикет по треду {forum_chat_id}/{message_thread_id}"
    )
# ============================


# ===== GET_USER_TICKETS =====
def get_user_tickets(user_id: int, status: str | None = None) -> list[dict]:
    if status:
        return _fetch_list(
            "SELECT * FROM support_tickets WHERE user_id = ? AND status = ? ORDER BY updated_at DESC",
            (user_id, status),
            f"Не удалось получить тикеты для пользователя {user_id}"
        )
    return _fetch_list(
        "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
        f"Не удалось получить тикеты для пользователя {user_id}"
    )

    return _fetch_list(
        "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
        f"Не удалось получить тикеты для пользователя {user_id}"
    )
# ============================


# ===== GET_TICKET_MESSAGES =====
def get_ticket_messages(ticket_id: int) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY created_at ASC",
        (ticket_id,),
        f"Не удалось получить сообщения для тикета {ticket_id}"
    )
# ===============================


# ===== SET_TICKET_STATUS =====
def set_ticket_status(ticket_id: int, status: str) -> bool:
    cursor = _exec(
        "UPDATE support_tickets SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
        (status, ticket_id),
        f"Не удалось установить статус '{status}' для тикета {ticket_id}"
    )
    return cursor is not None and cursor.rowcount > 0

    return cursor is not None and cursor.rowcount > 0
# ===========================


# ===== UPDATE_TICKET_SUBJECT =====
def update_ticket_subject(ticket_id: int, subject: str) -> bool:
    cursor = _exec(
        "UPDATE support_tickets SET subject = ?, updated_at = CURRENT_TIMESTAMP WHERE ticket_id = ?",
        (subject, ticket_id),
        f"Не удалось обновить тему для тикета {ticket_id}"
    )
    return cursor is not None and cursor.rowcount > 0

    return cursor is not None and cursor.rowcount > 0
# ===============================


# ===== DELETE_TICKET =====
def delete_ticket(ticket_id: int) -> bool:
    _exec("DELETE FROM support_messages WHERE ticket_id = ?", (ticket_id,), "Не удалось удалить сообщения тикета")
    cursor = _exec("DELETE FROM support_tickets WHERE ticket_id = ?", (ticket_id,), f"Не удалось удалить тикет {ticket_id}")
    return cursor is not None and cursor.rowcount > 0

    return cursor is not None and cursor.rowcount > 0
# ===========================


# ===== GET_TICKETS_PAGINATED =====
def get_tickets_paginated(page: int = 1, per_page: int = 20, status: str | None = None) -> tuple[list[dict], int]:
    offset = (page - 1) * per_page
    
    if status:
        total = _fetch_val("SELECT COUNT(*) FROM support_tickets WHERE status = ?", (status,), 0) or 0
        where_clause = " WHERE t.status = ?"
        params = [status]
    else:
        total = _fetch_val("SELECT COUNT(*) FROM support_tickets", (), 0) or 0
        where_clause = ""
        params = []
    
    base_query = """
        SELECT t.*, 
               u.username,
               (SELECT sender FROM support_messages 
                WHERE ticket_id = t.ticket_id 
                ORDER BY created_at DESC LIMIT 1) as last_sender
        FROM support_tickets t
        LEFT JOIN users u ON t.user_id = u.telegram_id
    """
    
    order_clause = """
        ORDER BY 
        CASE 
            WHEN t.status = 'open' AND (
                SELECT sender FROM support_messages 
                WHERE ticket_id = t.ticket_id 
                ORDER BY created_at DESC LIMIT 1
            ) != 'admin' THEN 1
            WHEN t.status = 'open' THEN 2
            ELSE 3
        END ASC,
        t.updated_at DESC
    """
    
    full_query = base_query + where_clause + order_clause + " LIMIT ? OFFSET ?"
    params.extend([per_page, offset])
    
    rows = _fetch_list(full_query, tuple(params), "Не удалось получить страницу тикетов поддержки")
    return rows, total
# ===========================


# ===== GET_OPEN_TICKETS_COUNT =====
def get_open_tickets_count() -> int:
    return _fetch_val("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'", (), 0) or 0
# ==============================


# ===== GET_WAITING_TICKETS_COUNT =====
def get_waiting_tickets_count() -> int:
    query = """
        SELECT COUNT(*) FROM support_tickets t
        WHERE t.status = 'open' AND (
            SELECT sender FROM support_messages 
            WHERE ticket_id = t.ticket_id 
            ORDER BY created_at DESC LIMIT 1
        ) != 'admin'
    """
    return _fetch_val(query, (), 0, "Не удалось получить кол-во ожидающих тикетов")
# ===================================


# ===== GET_SUPPORT_BADGE_COUNTS =====
def get_support_badge_counts() -> dict:
    """Универсальная функция для получения всех счетчиков бейджей в один запрос."""
    try:
        # Получаем общее количество открытых тикетов
        open_count = _fetch_val("SELECT COUNT(*) FROM support_tickets WHERE status = 'open'", (), 0) or 0
        
        # Получаем количество тикетов, ожидающих ответа админа (последнее сообщение не от админа)
        waiting_count = _fetch_val("""
            SELECT COUNT(*) FROM support_tickets t
            WHERE t.status = 'open' AND (
                SELECT sender FROM support_messages 
                WHERE ticket_id = t.ticket_id 
                ORDER BY created_at DESC LIMIT 1
            ) != 'admin'
        """, (), 0) or 0
        
        return {
            "ok": True,
            "open_count": open_count,
            "waiting_tickets_count": waiting_count
        }
    except Exception as e:
        logger.error(f"Ошибка при получении счетчиков бейджей: {e}")
        return {"ok": False, "error": str(e), "open_count": 0, "waiting_tickets_count": 0}


# ===== GET_CLOSED_TICKETS_COUNT =====
def get_closed_tickets_count() -> int:
    return _fetch_val("SELECT COUNT(*) FROM support_tickets WHERE status = 'closed'", (), 0) or 0
# ==================================


# ===== GET_ALL_TICKETS_COUNT =====
def get_all_tickets_count() -> int:
    return _fetch_val("SELECT COUNT(*) FROM support_tickets", (), 0) or 0
# ===============================


# ===== GET_OTHER_VALUE =====
def get_other_value(key: str) -> str | None:
    return _fetch_val("SELECT value FROM other WHERE key = ?", (key,), None, f"Не удалось получить other-значение для {key}")


    return _fetch_val("SELECT value FROM other WHERE key = ?", (key,), None, f"Не удалось получить other-значение для {key}")
# =========================


# ===== SET_OTHER_VALUE =====
def set_other_value(key: str, value: str) -> bool:
    cursor = _exec(
        "INSERT OR REPLACE INTO other (key, value) VALUES (?, ?)",
        (key, value),
        f"Не удалось установить other-значение для {key}"
    )
    return cursor is not None




    return cursor is not None
# =======================


# ===== UPDATE_SSH_TARGET_SCHEDULER =====
def update_ssh_target_scheduler(target_name: str, time_auto: str) -> bool:
    name = normalize_host_name(target_name)
    cursor = _exec(
        "UPDATE speedtest_ssh_targets SET time_auto = ? WHERE TRIM(target_name) = TRIM(?)",
        (time_auto, name),
        f"Не удалось обновить планировщик для '{target_name}'"
    )
    return cursor is not None and cursor.rowcount > 0
# ===================================


# ===== UPDATE_HOST_SORT_ORDER =====
def update_host_sort_order(host_name: str, sort_order: int) -> bool:
    name = normalize_host_name(host_name)
    cursor = _exec(
        "UPDATE xui_hosts SET sort_order = ? WHERE TRIM(host_name) = TRIM(?)",
        (sort_order, name),
        "Не удалось обновить sort_order хоста"
    )
    if cursor and cursor.rowcount > 0: logging.info(f"Обновлён sort_order хоста '{name}': {sort_order}"); return True
    logging.warning(f"Хост '{name}' не найден для обновления sort_order"); return False
# ==============================


# ===== UPDATE_SSH_TARGET_SORT_ORDER =====
def update_ssh_target_sort_order(target_name: str, sort_order: int) -> bool:
    name = normalize_host_name(target_name)
    cursor = _exec(
        "UPDATE speedtest_ssh_targets SET sort_order = ? WHERE TRIM(target_name) = TRIM(?)",
        (sort_order, name),
        "Не удалось обновить sort_order SSH-цели"
    )
    if cursor and cursor.rowcount > 0: logging.info(f"Обновлён sort_order SSH-цели '{name}': {sort_order}"); return True
    logging.warning(f"SSH-цель '{name}' не найдена для обновления sort_order"); return False
# ====================================


# ===== GET_OTHER_SETTING =====
def get_other_setting(key: str, default: Any = None) -> Any:
    val = get_other_value(key)
    return val if val is not None else default
# =========================


# ===== UPDATE_OTHER_SETTING =====
def update_other_setting(key: str, value: Any) -> bool:
    return set_other_value(key, str(value))


def get_all_other_settings() -> dict:
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM other")
        return {row['key']: row['value'] for row in cursor.fetchall()}

# ===========================================
# ===== WEBAPP SETTINGS =====
# Проверка и получение настроек веб-приложения
def get_webapp_settings() -> dict:
    row = _fetch_row("SELECT * FROM webapp_settings WHERE id = 1")
    if not row:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            _ensure_webapp_settings_table(conn.cursor())
            conn.commit()
        row = _fetch_row("SELECT * FROM webapp_settings WHERE id = 1")
    # Преобразуем sqlite3.Row в обычный словарь
    return dict(row) if row else {}

# Обновление настроек веб-приложения
def update_webapp_settings(webapp_title: str = None, webapp_domen: str = None, webapp_enable: int = None, webapp_logo: str = None, webapp_icon: str = None, tg_fullscreen: int = None) -> bool:
    try:
        updates = []
        params = []
        if webapp_title is not None:
            updates.append("webapp_title = ?")
            params.append(webapp_title)
        if webapp_domen is not None:
            updates.append("webapp_domen = ?")
            params.append(webapp_domen)
        if webapp_enable is not None:
            updates.append("webapp_enable = ?")
            params.append(int(webapp_enable))
        if webapp_logo is not None:
            updates.append("webapp_logo = ?")
            params.append(webapp_logo)
        if webapp_icon is not None:
            updates.append("webapp_icon = ?")
            params.append(webapp_icon)
        if tg_fullscreen is not None:
            updates.append("tg_fullscreen = ?")
            params.append(int(tg_fullscreen))
        
        if not updates:
            return False
        
        # Строим SQL запрос
        sql = f"UPDATE webapp_settings SET {', '.join(updates)} WHERE id = 1"
        return _exec(sql, tuple(params))
    except Exception as e:
        logging.error(f"Ошибка при обновлении настроек webapp: {e}")
        return False
def update_user_auth_token(user_id: int, token: str | None) -> bool:
    return _exec("UPDATE users SET auth_token = ? WHERE telegram_id = ?", (token, user_id), "Failed to update auth_token") is not None

def get_user_by_auth_token(token: str) -> dict | None:
    if not token: return None
    return _fetch_row("SELECT * FROM users WHERE auth_token = ?", (token,), "Failed to get user by auth_token")

def get_auth_token_by_user_id(user_id: int) -> str | None:
    row = _fetch_row("SELECT auth_token FROM users WHERE telegram_id = ?", (user_id,), "Failed to get auth_token by user_id")
    return row["auth_token"] if row else None

# ===== ДАШБОРД: СТАТИСТИКА ГРУПП ПОЛЬЗОВАТЕЛЕЙ =====
def get_dashboard_user_groups() -> dict:
    groups = {
        "no_purchases": [],
        "inactive_buyers": [],
        "trials": [],
        "active_buyers": [],
        "active_keys": []
    }
    
    def purchase_condition(alias: str) -> str:
        meta_expr = f"CASE WHEN json_valid(COALESCE({alias}.metadata, '{{}}')) THEN COALESCE({alias}.metadata, '{{}}') ELSE '{{}}' END"
        return f"""
        LOWER(COALESCE({alias}.status, '')) IN ('paid', 'completed', 'success', 'succeeded')
        AND LOWER(COALESCE({alias}.payment_method, '')) NOT IN ('admin', 'referral')
        AND (
            LOWER(COALESCE(json_extract({meta_expr}, '$.action'), '')) IN ('new', 'extend')
            OR LOWER(COALESCE(json_extract({meta_expr}, '$.reason'), '')) = 'subscription_purchase_or_extend'
            OR json_extract({meta_expr}, '$.plan_id') IS NOT NULL
            OR json_extract({meta_expr}, '$.key_id') IS NOT NULL
            OR json_extract({meta_expr}, '$.host_name') IS NOT NULL
            OR json_extract({meta_expr}, '$.host') IS NOT NULL
            OR json_extract({meta_expr}, '$.customer_email') IS NOT NULL
        )
        """
    
    # 1. Не купил ключ (нет транзакций 'paid' и нет ключей)
    q_no = f"""
    SELECT u.telegram_id, u.username, u.balance,
           (SELECT COALESCE(SUM(t2.amount_rub), 0) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as total_spent
    FROM users u
    WHERE NOT EXISTS (SELECT 1 FROM vpn_keys k WHERE k.user_id = u.telegram_id AND COALESCE(k.key_email, '') NOT LIKE 'trial_%')
      AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.user_id = u.telegram_id AND {purchase_condition('t')})
    """
    groups["no_purchases"] = _fetch_list(q_no, (), "Ошибка получения no_purchases")
    
    # 2. Покупали, но сейчас нет активных (истекли или нет ключей, но есть транзакции)
    q_inactive = f"""
    SELECT u.telegram_id, u.username, u.balance,
           (SELECT SUM(COALESCE(
               CAST(json_extract(t2.metadata, '$.months') AS INTEGER),
               (SELECT p.months FROM plans p WHERE p.plan_id = CAST(json_extract(t2.metadata, '$.plan_id') AS INTEGER)),
               0
           )) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as months_bought,
           (SELECT COALESCE(SUM(t2.amount_rub), 0) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as total_spent
    FROM users u
    WHERE EXISTS (SELECT 1 FROM transactions t WHERE t.user_id = u.telegram_id AND {purchase_condition('t')})
      AND NOT EXISTS (
          SELECT 1 FROM vpn_keys k 
          WHERE k.user_id = u.telegram_id 
            AND COALESCE(k.key_email, '') NOT LIKE 'trial_%'
            AND (k.expire_at IS NULL OR k.expire_at > datetime('now', '+3 hours'))
      )
    """
    groups["inactive_buyers"] = _fetch_list(q_inactive, (), "Ошибка получения inactive_buyers")
    
    # 3. Используют триал (есть активный триальный ключ)
    q_trials = """
    SELECT u.telegram_id, u.username, u.balance, k.key_id, k.expire_at,
           (SELECT SUM(COALESCE(
               CAST(json_extract(t2.metadata, '$.months') AS INTEGER),
               (SELECT p.months FROM plans p WHERE p.plan_id = CAST(json_extract(t2.metadata, '$.plan_id') AS INTEGER)),
               0
           )) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND """ + purchase_condition('t2') + """) as months_bought,
           (SELECT COALESCE(SUM(t2.amount_rub), 0) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND """ + purchase_condition('t2') + """) as total_spent
    FROM users u
    JOIN vpn_keys k ON k.user_id = u.telegram_id
    WHERE COALESCE(k.key_email, '') LIKE 'trial_%' 
      AND (k.expire_at IS NULL OR k.expire_at > datetime('now', '+3 hours'))
    GROUP BY u.telegram_id
    """
    groups["trials"] = _fetch_list(q_trials, (), "Ошибка получения trials")
    
    # 4. Купили ключ (есть активный нетриальный ключ)
    q_active_buyers = f"""
    SELECT u.telegram_id, u.username, u.balance, k.key_id, k.expire_at,
           (SELECT SUM(COALESCE(
               CAST(json_extract(t2.metadata, '$.months') AS INTEGER),
               (SELECT p.months FROM plans p WHERE p.plan_id = CAST(json_extract(t2.metadata, '$.plan_id') AS INTEGER)),
               0
           )) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as months_bought,
           (SELECT COALESCE(SUM(t2.amount_rub), 0) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as total_spent
    FROM users u
    JOIN vpn_keys k ON k.user_id = u.telegram_id
    WHERE COALESCE(k.key_email, '') NOT LIKE 'trial_%' 
      AND (k.expire_at IS NULL OR k.expire_at > datetime('now', '+3 hours'))
    GROUP BY u.telegram_id
    """
    groups["active_buyers"] = _fetch_list(q_active_buyers, (), "Ошибка получения active_buyers")
    
    # 5. Всего активных ключей (действующих)
    q_active_keys = f"""
    SELECT k.key_id, k.user_id as telegram_id, k.host_name, k.expire_at, u.username, u.balance,
           (SELECT SUM(COALESCE(
               CAST(json_extract(t2.metadata, '$.months') AS INTEGER),
               (SELECT p.months FROM plans p WHERE p.plan_id = CAST(json_extract(t2.metadata, '$.plan_id') AS INTEGER)),
               0
           )) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as months_bought,
           (SELECT COALESCE(SUM(t2.amount_rub), 0) FROM transactions t2 WHERE t2.user_id = u.telegram_id AND {purchase_condition('t2')}) as total_spent
    FROM vpn_keys k
    LEFT JOIN users u ON k.user_id = u.telegram_id
    WHERE (k.expire_at IS NULL OR k.expire_at > datetime('now', '+3 hours'))
      AND COALESCE(k.key_email, '') NOT LIKE 'trial_%'
    """
    groups["active_keys"] = _fetch_list(q_active_keys, (), "Ошибка получения active_keys")
    
    return groups
# ===================================================


# ===== ПЕРЕНЕСЁННЫЕ РЕФЕРАЛЬНЫЕ СВЯЗИ =====
# Старый бот знал, кто кого привёл. Новый узнаёт об этом только в момент, когда
# приглашённый нажмёт /start — а это может случиться через месяц. Поэтому связи
# лежат заранее, и применяются, когда человек наконец дойдёт.

def get_imported_referrer(telegram_id: int) -> int | None:
    """Кто привёл этого человека по данным старого бота."""
    row = _fetch_row(
        "SELECT referrer_id FROM referral_imports WHERE telegram_id = ?",
        (int(telegram_id),), "")
    if not row:
        return None
    try:
        referrer_id = int(row["referrer_id"])
    except (TypeError, ValueError):
        return None
    return referrer_id if referrer_id != int(telegram_id) else None


def mark_referral_import_applied(telegram_id: int) -> None:
    _exec(
        "UPDATE referral_imports SET applied_at = ? WHERE telegram_id = ? AND applied_at IS NULL",
        (get_msk_time().replace(tzinfo=None).replace(microsecond=0), int(telegram_id)), "")


def add_pending_referral_bonus(referrer_id: int, amount: float,
                               source_user_id: int | None = None,
                               reason: str = "") -> bool:
    """Откладывает начисление до появления пригласившего в боте."""
    if float(amount) <= 0:
        return False
    cursor = _exec(
        "INSERT INTO referral_pending_bonuses (referrer_id, amount, source_user_id, reason) "
        "VALUES (?, ?, ?, ?)",
        (int(referrer_id), float(amount), source_user_id, reason),
        f"Не удалось отложить реферальный бонус для {referrer_id}")
    if cursor is not None:
        logging.info(
            "Реферальный бонус %.2f для %s отложен до его регистрации (%s)",
            float(amount), referrer_id, reason or "без причины")
    return cursor is not None


def get_pending_referral_total(referrer_id: int) -> float:
    row = _fetch_row(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM referral_pending_bonuses "
        "WHERE referrer_id = ? AND paid_at IS NULL",
        (int(referrer_id),), "")
    return float(row["total"]) if row else 0.0


def settle_pending_referral_bonuses(referrer_id: int) -> tuple[float, int]:
    """Выплачивает всё, что накопилось, пока человека не было в боте.

    Возвращает (сумма, количество начислений). Помечаем выплаченными только
    после успешного пополнения баланса — иначе при сбое деньги пропадут молча.
    """
    referrer_id = int(referrer_id)
    rows = _fetch_list(
        "SELECT entry_id, amount FROM referral_pending_bonuses "
        "WHERE referrer_id = ? AND paid_at IS NULL",
        (referrer_id,), "")
    if not rows:
        return 0.0, 0

    total = round(sum(float(r["amount"]) for r in rows), 2)
    if total <= 0:
        return 0.0, 0
    if not add_to_balance(referrer_id, total):
        logging.warning("Отложенные бонусы для %s остались неоплаченными: нет пользователя", referrer_id)
        return 0.0, 0

    add_to_referral_balance_all(referrer_id, total)
    now = get_msk_time().replace(tzinfo=None).replace(microsecond=0)
    placeholders = ",".join("?" for _ in rows)
    _exec(
        f"UPDATE referral_pending_bonuses SET paid_at = ? WHERE entry_id IN ({placeholders})",
        [now] + [r["entry_id"] for r in rows], "")
    logging.info("Выплачено отложенных реферальных бонусов: %.2f для %s (%d начислений)",
                 total, referrer_id, len(rows))
    return total, len(rows)


def credit_referrer(referrer_id: int, amount: float, source_user_id: int | None = None,
                    reason: str = "") -> str:
    """Начисляет бонус пригласившему либо откладывает его до регистрации.

    Возвращает 'paid', 'held' или 'skipped'. Забаненным не начисляем и не
    копим: бан — это решение, а не временное состояние.
    """
    try:
        referrer_id = int(referrer_id)
    except (TypeError, ValueError):
        return "skipped"
    if float(amount) <= 0:
        return "skipped"

    referrer = get_user(referrer_id)
    if referrer and referrer.get("is_banned"):
        return "skipped"
    if not referrer:
        return "held" if add_pending_referral_bonus(referrer_id, amount, source_user_id, reason) else "skipped"
    if add_to_balance(referrer_id, float(amount)):
        add_to_referral_balance_all(referrer_id, float(amount))
        return "paid"
    return "skipped"


# ===== ПЕРЕНЕСЁННЫЕ БАЛАНСЫ =====

def get_pending_balance_import(telegram_id: int) -> float:
    """Сколько денег из старого бота ждёт этого человека."""
    row = _fetch_row(
        "SELECT amount FROM balance_imports WHERE telegram_id = ? AND applied_at IS NULL",
        (int(telegram_id),), "")
    return float(row["amount"]) if row else 0.0


def settle_balance_import(telegram_id: int) -> float:
    """Зачисляет перенесённый баланс. Возвращает зачисленную сумму.

    Помечаем выданным только после успешного пополнения: иначе при сбое деньги
    исчезнут молча, а повторить будет нечем — запись уже закрыта.
    """
    telegram_id = int(telegram_id)
    amount = get_pending_balance_import(telegram_id)
    if amount <= 0:
        return 0.0
    if not add_to_balance(telegram_id, amount):
        logging.warning("Перенесённый баланс %.2f для %s не зачислен: нет пользователя",
                        amount, telegram_id)
        return 0.0
    _exec(
        "UPDATE balance_imports SET applied_at = ? WHERE telegram_id = ? AND applied_at IS NULL",
        (get_msk_time().replace(tzinfo=None).replace(microsecond=0), telegram_id), "")
    logging.info("Зачислен перенесённый баланс %.2f пользователю %s", amount, telegram_id)
    return amount


# ===== РАССЫЛКИ И УВЕДОМЛЕНИЯ =====

def start_broadcast(admin_id: int | None, admin_name: str, preview: str,
                    has_media: bool, button_text: str | None, button_url: str | None,
                    total: int) -> int | None:
    """Открывает запись о рассылке. Итоги допишет finish_broadcast."""
    cursor = _exec(
        "INSERT INTO broadcasts (admin_id, admin_name, preview, has_media, "
        "button_text, button_url, total) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (admin_id, admin_name, (preview or "")[:2000], 1 if has_media else 0,
         button_text, button_url, int(total)),
        "Не удалось начать запись о рассылке")
    return cursor.lastrowid if cursor else None


def finish_broadcast(broadcast_id: int, sent: int, in_app: int, failed: int,
                     skipped: int, status: str = "done") -> None:
    _exec(
        "UPDATE broadcasts SET sent = ?, in_app = ?, failed = ?, skipped = ?, "
        "status = ?, finished_at = ? WHERE broadcast_id = ?",
        (sent, in_app, failed, skipped, status,
         get_msk_time().replace(tzinfo=None).replace(microsecond=0), int(broadcast_id)),
        "Не удалось записать итоги рассылки")


def get_broadcasts(limit: int = 50) -> list[dict]:
    return _fetch_list(
        "SELECT * FROM broadcasts ORDER BY broadcast_id DESC LIMIT ?",
        (int(limit),), "Не удалось получить историю рассылок")


def add_notification(user_id: int, title: str, body: str,
                     url: str | None = None, url_text: str | None = None,
                     broadcast_id: int | None = None,
                     media_url: str | None = None,
                     media_type: str | None = None) -> bool:
    cursor = _exec(
        "INSERT INTO user_notifications "
        "(user_id, broadcast_id, title, body, url, url_text, media_url, media_type) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (int(user_id), broadcast_id, title, body, url, url_text, media_url, media_type),
        f"Не удалось создать уведомление для {user_id}")
    return cursor is not None


def get_notifications(user_id: int, limit: int = 50) -> list[dict]:
    return _fetch_list(
        "SELECT notification_id, title, body, url, url_text, media_url, media_type, "
        "created_at, read_at "
        "FROM user_notifications WHERE user_id = ? ORDER BY notification_id DESC LIMIT ?",
        (int(user_id), int(limit)), "")


def count_unread_notifications(user_id: int) -> int:
    row = _fetch_row(
        "SELECT COUNT(*) AS c FROM user_notifications WHERE user_id = ? AND read_at IS NULL",
        (int(user_id),), "")
    return int(row["c"]) if row else 0


def mark_notifications_read(user_id: int, notification_id: int | None = None) -> int:
    now = get_msk_time().replace(tzinfo=None).replace(microsecond=0)
    if notification_id is None:
        cursor = _exec(
            "UPDATE user_notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
            (now, int(user_id)), "")
    else:
        cursor = _exec(
            "UPDATE user_notifications SET read_at = ? "
            "WHERE user_id = ? AND notification_id = ? AND read_at IS NULL",
            (now, int(user_id), int(notification_id)), "")
    return cursor.rowcount if cursor else 0


def user_has_telegram(user: dict) -> bool:
    """Есть ли смысл вообще пытаться писать этому человеку в Telegram.

    Аккаунты, заведённые только через сайт, получают синтетический id вида
    999…: чата с ботом у них нет, и попытка отправки всегда кончалась ошибкой,
    из-за чего рассылка отчитывалась о несуществующих сбоях.
    """
    try:
        uid = int(user.get("telegram_id"))
    except (TypeError, ValueError):
        return False
    if str(uid).startswith("999") and len(str(uid)) >= 10:
        return False
    linked = user.get("tg_linked")
    return linked is None or bool(linked)


# ===== ПРИТОК =====

def _month_bounds(offset: int = 0) -> tuple[str, str]:
    """Начало и конец месяца со смещением: 0 — текущий, -1 — прошлый."""
    now = get_msk_time().replace(tzinfo=None)
    year, month = now.year, now.month + offset
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def _idle_users_at(moment: str) -> int:
    """Сколько зарегистрированных не имели действующей подписки в этот момент."""
    ms = int(datetime.strptime(moment, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    row = _fetch_row(
        "SELECT COUNT(*) AS c FROM users u WHERE u.registration_date <= ? "
        "AND NOT EXISTS (SELECT 1 FROM vpn_keys k WHERE k.user_id = u.telegram_id "
        "AND COALESCE(k.created_at, '') <= ? AND COALESCE(k.expire_at, 0) > ?)",
        (moment, moment, ms), "")
    return int(row["c"]) if row else 0


def get_growth_stats(days: int = 60) -> dict:
    """Приток по дням и сравнение текущего месяца с прошлым.

    «Без подписки» за прошлый месяц считается на его конец, а не «сейчас»:
    иначе прошлый месяц сравнивался бы с сегодняшним днём и разница всегда
    выходила бы в его пользу.
    """
    now = get_msk_time().replace(tzinfo=None)
    since = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    rows = _fetch_list(
        "SELECT substr(registration_date, 1, 10) AS d, COUNT(*) AS n FROM users "
        "WHERE substr(registration_date, 1, 10) >= ? GROUP BY d", (since,), "")
    by_day = {r["d"]: int(r["n"]) for r in rows}

    series = []
    for i in range(days):
        day = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        series.append({"date": day, "users": by_day.get(day, 0)})

    this_start, this_end = _month_bounds(0)
    prev_start, prev_end = _month_bounds(-1)

    def paid_in(start: str, end: str) -> int:
        row = _fetch_row(
            "SELECT COUNT(*) AS c FROM transactions WHERE status = 'paid' "
            "AND created_date >= ? AND created_date < ?", (start, end), "")
        return int(row["c"]) if row else 0

    def joined_in(start: str, end: str) -> int:
        row = _fetch_row(
            "SELECT COUNT(*) AS c FROM users WHERE registration_date >= ? AND registration_date < ?",
            (start, end), "")
        return int(row["c"]) if row else 0

    purchases_now, purchases_prev = paid_in(this_start, this_end), paid_in(prev_start, prev_end)
    joined_now, joined_prev = joined_in(this_start, this_end), joined_in(prev_start, prev_end)

    idle_now = _idle_users_at(now.strftime("%Y-%m-%d %H:%M:%S"))
    idle_prev = _idle_users_at(prev_end)

    def growth(now_v: int, prev_v: int) -> float | None:
        if not prev_v:
            return None            # делить не на что — покажем «сравнить не с чем»
        return round((now_v - prev_v) / prev_v * 100, 1)

    return {
        "series": series,
        "purchases": {"now": purchases_now, "prev": purchases_prev,
                      "growth": growth(purchases_now, purchases_prev)},
        "joined": {"now": joined_now, "prev": joined_prev,
                   "growth": growth(joined_now, joined_prev)},
        "idle": {"now": idle_now, "prev": idle_prev, "delta": idle_now - idle_prev},
        "has_prev": bool(purchases_prev or joined_prev or idle_prev),
    }
