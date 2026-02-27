"""
═══════════════════════════════════════════════════════════
                    FLASH-UCBOT - MAIN.PY
          Magical Command Loader - No Built-in Commands
          + FastAPI SMS Receiver + Transaction Commands
═══════════════════════════════════════════════════════════
"""

import asyncio
import time
import os
import importlib
import sys
import logging
import threading
from datetime import datetime
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError, AuthKeyError, SessionPasswordNeededError
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
import uvicorn

from firestoredb import save_transaction, get_transaction, delete_transaction, execute_query, init_database

# ═══════════════════════════════════════════════════════════
#                    LOAD ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════

load_dotenv()

# ═══════════════════════════════════════════════════════════
#                    CONFIGURATION
# ═══════════════════════════════════════════════════════════

API_ID          = os.getenv('API_ID')
API_HASH        = os.getenv('API_HASH')
SESSION_STRING  = os.getenv('SESSION_STRING')
COMMAND_PREFIX  = os.getenv('COMMAND_PREFIX', '.')
MAIN_AUTH       = os.getenv('MAIN_AUTH')

# Validate required variables
if not all([API_ID, API_HASH, SESSION_STRING]):
    print("\n" + "═" * 60)
    print("❌ ERROR: Missing Required Environment Variables!")
    print("═" * 60)
    print("\n📋 Required variables:")
    print("   • API_ID")
    print("   • API_HASH")
    print("   • SESSION_STRING")
    print("\n💡 Set these in your .env file or environment variables")
    print("═" * 60 + "\n")
    sys.exit(1)

if not MAIN_AUTH:
    print("❌ ERROR: MAIN_AUTH not set in environment variables!")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
#                    LOGGING SETUP
# ═══════════════════════════════════════════════════════════

log_dir = 'logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(
            f'{log_dir}/bot_{datetime.now().strftime("%Y%m%d")}.log',
            encoding='utf-8'
        ),
        logging.StreamHandler()
    ]
)

logging.getLogger('telethon').setLevel(logging.WARNING)
logging.getLogger('uvicorn').setLevel(logging.WARNING)
logging.getLogger('fastapi').setLevel(logging.WARNING)

logger = logging.getLogger('FlashBot')

# ═══════════════════════════════════════════════════════════
#                    INITIALIZE CLIENT
# ═══════════════════════════════════════════════════════════

client = TelegramClient(
    StringSession(SESSION_STRING),
    API_ID,
    API_HASH,
    system_version="4.16.30-vxCUSTOM"
)

start_time = time.time()

# ═══════════════════════════════════════════════════════════
#                    FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(title="Flash-UCBot SMS Receiver", docs_url=None, redoc_url=None)

class SMSPayload(BaseModel):
    trxid:   str
    amount:  float
    gateway: str


@app.post("/sendsms")
async def receive_sms(payload: SMSPayload, request: Request):
    """
    Receive transaction data and store it.

    Authorization: Pass MAIN_AUTH value in the 'Authorization' header.

    Body:
        {
            "trxid":   "DBR3IBG8W3",
            "amount":  1785,
            "gateway": "bKash"
        }
    """
    # ── Auth check ──────────────────────────────────────────
    auth_header = request.headers.get("Authorization", "")
    if auth_header != MAIN_AUTH:
        logger.warning(f"⛔ Unauthorized /sendsms attempt from {request.client.host}")
        raise HTTPException(status_code=401, detail="Unauthorized")

    # ── Store transaction ────────────────────────────────────
    success = save_transaction(
        trxid   = payload.trxid,
        amount  = payload.amount,
        gateway = payload.gateway
    )

    if not success:
        logger.error(f"❌ Failed to save transaction: {payload.trxid}")
        raise HTTPException(status_code=500, detail="Failed to save transaction")

    logger.info(f"💾 Transaction saved via API: {payload.trxid} | {payload.amount} | {payload.gateway}")

    return {
        "status":  "success",
        "message": "Transaction saved",
        "trxid":   payload.trxid
    }


def run_api():
    """Run FastAPI in a separate thread"""
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")

# ═══════════════════════════════════════════════════════════
#              CASE-INSENSITIVE PREFIX HELPER
# ═══════════════════════════════════════════════════════════

def make_prefix_case_insensitive(prefix):
    import re
    return ''.join(
        f'[{c.upper()}{c.lower()}]' if c.isalpha() else re.escape(c)
        for c in prefix
    )

# ═══════════════════════════════════════════════════════════
#              BUILT-IN TRANSACTION COMMANDS
# ═══════════════════════════════════════════════════════════

def register_transaction_commands():
    """
    Register /check and /clean commands directly on the Telethon client.

    /check <trxid>  — Look up a transaction
    /clean          — Wipe all transactions from the database
    """

    @client.on(events.NewMessage(pattern=r'^/check\s+(\S+)$', incoming=True, outgoing=True))
    async def cmd_check(event):
        trxid = event.pattern_match.group(1).strip()
        trx   = get_transaction(trxid)

        if not trx:
            await event.reply(
                f"❌ **Transaction Not Found**\n\n"
                f"No record for TRX ID: `{trxid}`"
            )
            return

        await event.reply(
            f"✅ **Transaction Found**\n\n"
            f"🆔 **TRX ID  :** `{trx['trxid']}`\n"
            f"💰 **Amount  :** `{trx['amount']}`\n"
            f"🏦 **Gateway :** `{trx['gateway']}`\n"
            f"🕐 **Time    :** `{trx.get('created_at', 'N/A')}`"
        )
        logger.info(f"✅ /check {trxid} — found")

    @client.on(events.NewMessage(pattern=r'^/clean$', incoming=True, outgoing=True))
    async def cmd_clean(event):
        try:
            execute_query('DELETE FROM transactions')
            await event.reply("🧹 **All transactions have been cleared.**")
            logger.info("🧹 /clean — all transactions deleted")
        except Exception as e:
            await event.reply(f"❌ Failed to clear transactions: {e}")
            logger.error(f"❌ /clean error: {e}")

    logger.info("✅ Built-in commands registered: /check, /clean")

# ═══════════════════════════════════════════════════════════
#              MAGICAL COMMAND LOADING SYSTEM
# ═══════════════════════════════════════════════════════════

def load_all_commands():
    commands_dir = 'commands'

    if not os.path.exists(commands_dir):
        logger.warning(f"Commands directory not found!")
        os.makedirs(commands_dir)

        init_file = os.path.join(commands_dir, '__init__.py')
        with open(init_file, 'w', encoding='utf-8') as f:
            f.write('"""Commands Package - Auto-generated"""\n')

        logger.info(f"Created '{commands_dir}/' directory")
        return 0

    command_files = [
        f[:-3] for f in os.listdir(commands_dir)
        if f.endswith('.py') and not f.startswith('_')
    ]

    if not command_files:
        logger.warning(f"No command files found in '{commands_dir}/'")
        return 0

    command_files.sort()
    case_insensitive_prefix = make_prefix_case_insensitive(COMMAND_PREFIX)

    loaded_count  = 0
    failed_count  = 0

    print("\n" + "═" * 60)
    print(f"📦 LOADING COMMAND MODULES (Case-Insensitive Mode)")
    print("═" * 60 + "\n")

    for command_file in command_files:
        try:
            module_name = f'{commands_dir}.{command_file}'

            if module_name in sys.modules:
                module = importlib.reload(sys.modules[module_name])
            else:
                module = importlib.import_module(module_name)

            if hasattr(module, 'register'):
                module.register(client, case_insensitive_prefix)
                loaded_count += 1
                print(f"  ✅ {command_file:30s} → Loaded (Case-Insensitive)")
            else:
                failed_count += 1
                print(f"  ⚠️  {command_file:30s} → No register() function")

        except Exception as e:
            failed_count += 1
            print(f"  ❌ {command_file:30s} → Error")
            logger.error(f"Failed to load '{command_file}': {str(e)}")

    print("\n" + "═" * 60)
    print(f"📊 LOADED: {loaded_count} | FAILED: {failed_count} | TOTAL: {loaded_count + failed_count}")
    print("═" * 60 + "\n")

    return loaded_count

# ═══════════════════════════════════════════════════════════
#                    MAIN BOT RUNNER
# ═══════════════════════════════════════════════════════════

async def main():
    retry_count = 0
    max_retries = 5

    while retry_count < max_retries:
        try:
            os.system('clear' if os.name != 'nt' else 'cls')

            print("\n")
            print("╔═══════════════════════════════════════════════════════════╗")
            print("║                                                           ║")
            print("║              ⚡ FLASH-UCBOT INITIALIZING ⚡              ║")
            print("║                                                           ║")
            print("╚═══════════════════════════════════════════════════════════╝")
            print("\n")

            logger.info("🔌 Connecting to Telegram...")
            await client.start()

            me = await client.get_me()

            print("═" * 60)
            print("✅ TELEGRAM CONNECTION SUCCESSFUL")
            print("═" * 60)
            print(f"👤 Name      : {me.first_name}" + (f" {me.last_name}" if me.last_name else ""))
            print(f"📱 Username  : @{me.username}" if me.username else "📱 Username  : Not Set")
            print(f"🆔 User ID   : {me.id}")
            print(f"📞 Phone     : {me.phone}" if me.phone else "📞 Phone     : Hidden")
            print(f"🔑 Prefix    : '{COMMAND_PREFIX}'")
            print("═" * 60)

            # Register built-in transaction commands
            register_transaction_commands()

            # Load external command modules
            loaded_commands = load_all_commands()

            if loaded_commands == 0:
                logger.warning("⚠️  No external commands loaded.")

            # Start FastAPI in background thread
            api_thread = threading.Thread(target=run_api, daemon=True)
            api_thread.start()
            logger.info("🌐 FastAPI running on http://0.0.0.0:8000 | Endpoint: POST /sendsms")

            print("\n" + "╔" + "═" * 58 + "╗")
            print("║" + " " * 58 + "║")
            print("║" + "✨ BOT IS NOW ONLINE AND READY! ✨".center(58) + "║")
            print("║" + " " * 58 + "║")
            print("╚" + "═" * 58 + "╝" + "\n")

            logger.info(f"🎯 Monitoring messages with prefix '{COMMAND_PREFIX}'")
            logger.info("⏸️  Press Ctrl+C to stop the bot")

            print("\n" + "─" * 60)
            print("📝 BOT ACTIVITY LOG")
            print("─" * 60 + "\n")

            retry_count = 0
            await client.run_until_disconnected()
            break

        except FloodWaitError as e:
            retry_count += 1
            wait_time = e.seconds
            logger.error(f"⚠️  Flood Wait Error! Must wait {wait_time} seconds")
            logger.info(f"🔄 Retry {retry_count}/{max_retries}")
            if retry_count < max_retries:
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"❌ Max retries ({max_retries}) reached. Exiting...")
                break

        except AuthKeyError:
            logger.error("❌ Authentication Error! SESSION_STRING is invalid or expired.")
            break

        except SessionPasswordNeededError:
            logger.error("❌ 2FA Password Required!")
            break

        except KeyboardInterrupt:
            logger.info("⏹️  Bot stopped by user (Ctrl+C)")
            break

        except Exception as e:
            retry_count += 1
            logger.error(f"❌ Unexpected Error: {str(e)}")
            if retry_count < max_retries:
                logger.info("⏳ Waiting 5 seconds before retry...")
                await asyncio.sleep(5)
            else:
                logger.error(f"❌ Max retries ({max_retries}) reached. Exiting...")
                break

    logger.info("🧹 Cleaning up...")
    if client.is_connected():
        await client.disconnect()
    logger.info("✅ Client disconnected")

    print("\n" + "═" * 60)
    print("👋 FLASH-UCBOT SHUTDOWN COMPLETE")
    print("═" * 60 + "\n")

# ═══════════════════════════════════════════════════════════
#                    ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user\n")
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {str(e)}\n")
        logger.critical(f"Fatal error: {str(e)}", exc_info=True)
    finally:
        print("👋 Goodbye!\n")
