import asyncio, logging, os
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from config import config, load_group_chat_id
from handlers.flash_sale import register
from scheduler import on_startup, on_shutdown

# 1. Flask server (Render porti uchun)
app = Flask(__name__)

@app.route('/')
def health_check():
    return "OK", 200

def run_flask():
    # Render bergan portni aniq ko'rsatib yoqamiz
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# 2. Bot sozlamalari
logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.bot_token, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
register(dp)

async def on_start(dp: Dispatcher):
    await on_startup(bot)
    await load_group_chat_id()

if __name__ == "__main__":
    # DIQQAT: Flaskni alohida thread'da botdan OLDIN yoqamiz
    Thread(target=run_flask, daemon=True).start()
    
    # Keyin botni boshlaymiz
    executor.start_polling(dp, skip_updates=True, on_startup=on_start)