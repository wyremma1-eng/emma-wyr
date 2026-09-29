import os
import datetime
import logging
import sqlite3

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ==========================================
# 🔑 CONFIGURATION EMMA-WYR
# ==========================================

TOKEN = "8553645204:AAEXdlx5JFIyFLKe7fknHEFaWNFzfeYnnoc"
ADMIN_ID = 8200593285

DB_FILE = "emma_wyr_v2ray.db"

WHATSAPP_LINK = "https://wa.me/243831278772"


admin_states = {}


# ==========================================
# 💾 GESTION BASE DE DONNÉES SQLITE
# ==========================================

def init_db():

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Table des serveurs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS v2ray_servers (
            protocol TEXT PRIMARY KEY,
            link TEXT NOT NULL
        )
    """)

    # Table des abonnements utilisateurs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            user_id INTEGER PRIMARY KEY,
            expiration_date TEXT NOT NULL
        )
    """)

    # Table des temporisations 5h
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_cooldowns (
            user_id INTEGER,
            protocol TEXT,
            next_access_time TEXT,
            PRIMARY KEY (user_id, protocol)
        )
    """)

    default_servers = [
        ("vless", "Aucun serveur VLESS configuré."),
        ("trojan", "Aucun serveur TROJAN configuré."),
        ("vmess", "Aucun serveur VMESS configuré."),
        ("ssh", "Aucun serveur SSH configuré.")
    ]

    for protocol, link in default_servers:

        cursor.execute(
            """
            INSERT OR IGNORE INTO v2ray_servers
            (protocol, link)
            VALUES (?, ?)
            """,
            (protocol, link)
        )

    conn.commit()
    conn.close()


# ==========================================
# 🌐 SERVEURS
# ==========================================

def get_server_from_db(protocol: str) -> str:

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT link FROM v2ray_servers WHERE protocol = ?",
        (protocol,)
    )

    row = cursor.fetchone()

    conn.close()

    return row[0] if row else "Aucun serveur configuré."


def update_server_in_db(protocol: str, new_link: str):

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO v2ray_servers
        (protocol, link)
        VALUES (?, ?)
        """,
        (protocol, new_link)
    )

    conn.commit()
    conn.close()


# ==========================================
# 👤 ABONNEMENTS
# ==========================================

def set_user_subscription(user_id: int, days: int):

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    exp_date = (
        datetime.datetime.now()
        + datetime.timedelta(days=days)
    )

    exp_str = exp_date.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        INSERT OR REPLACE INTO user_subscriptions
        (user_id, expiration_date)
        VALUES (?, ?)
        """,
        (user_id, exp_str)
    )

    conn.commit()
    conn.close()


def remove_user_subscription(user_id: int):

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM user_subscriptions WHERE user_id = ?",
        (user_id,)
    )

    cursor.execute(
        "DELETE FROM user_cooldowns WHERE user_id = ?",
        (user_id,)
    )

    conn.commit()
    conn.close()


def check_user_access(user_id: int) -> tuple[bool, str]:

    # Administrateur = accès illimité
    if user_id == ADMIN_ID:
        return True, "ACCÈS ADMINISTRATEUR (ILLIMITÉ)"

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT expiration_date
        FROM user_subscriptions
        WHERE user_id = ?
        """,
        (user_id,)
    )

    row = cursor.fetchone()

    conn.close()

    if not row:

        return False, "AUCUN ABONNEMENT ACTIF"

    exp_date = datetime.datetime.strptime(
        row[0],
        "%Y-%m-%d %H:%M:%S"
    )

    if datetime.datetime.now() > exp_date:

        return False, (
            f"ABONNEMENT EXPIRÉ LE "
            f"{exp_date.strftime('%d/%m/%Y')}"
        )

    return True, (
        f"VALIDE JUSQU'AU "
        f"{exp_date.strftime('%d/%m/%Y à %H:%M')}"
    )


# ==========================================
# ⏳ DÉLAI DE 5 HEURES
# ==========================================

def check_and_update_cooldown(
    user_id: int,
    protocol: str
) -> tuple[bool, str]:

    # Administrateur sans limitation
    if user_id == ADMIN_ID:
        return True, ""

    now = datetime.datetime.now()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT next_access_time
        FROM user_cooldowns
        WHERE user_id = ?
        AND protocol = ?
        """,
        (user_id, protocol)
    )

    row = cursor.fetchone()

    if row:

        next_time = datetime.datetime.strptime(
            row[0],
            "%Y-%m-%d %H:%M:%S"
        )

        if now < next_time:

            remaining = next_time - now

            hours, remainder = divmod(
                int(remaining.total_seconds()),
                3600
            )

            minutes, _ = divmod(
                remainder,
                60
            )

            conn.close()

            return False, (
                f"{hours}h {minutes}min"
            )

    # Nouveau délai de 5 heures
    next_access = (
        now + datetime.timedelta(hours=5)
    )

    next_str = next_access.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        INSERT OR REPLACE INTO user_cooldowns
        (user_id, protocol, next_access_time)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            protocol,
            next_str
        )
    )

    conn.commit()
    conn.close()

    return True, ""


# ==========================================
# 🤖 CLAVIER PRINCIPAL
# ==========================================

def get_main_keyboard(user_id: int):

    buttons = [

        [
            KeyboardButton("⚡ Menu Serveurs"),
            KeyboardButton("👤 Mon Statut")
        ],

        [
            KeyboardButton(
                "📩 Contacter l'administrateur"
            )
        ]

    ]

    if user_id == ADMIN_ID:

        buttons.append(
            [
                KeyboardButton(
                    "👑 Panneau Admin"
                )
            ]
  )
