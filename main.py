# main.py — aiogram 2.x (Render uchun to'g'rilangan varianti)
import asyncio, logging, os
from threading import Thread
from flask import Flask
from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from config import config, load_group_chat_id
from handlers.flash_sale import register
from scheduler import on_startup, on_shutdown

# 1. Logging sozlamalari
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 2. Bot va Dispatcher
bot = Bot(token=config.bot_token, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

register(dp)

# 3. Render uchun Flask (DUMMY SERVER)
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running..."

def run_web():
    # Render bergan portni olamiz
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# 4. Bot ishga tushganda bajariladigan funksiyalar
async def on_start(dp: Dispatcher):
    # Orqa fondagi scheduler va guruhni yuklash
    await on_startup(bot)
    await load_group_chat_id()
    logger.info("✅ Bot muvaffaqiyatli ishga tushdi!")

async def on_stop(dp: Dispatcher):
    await on_shutdown()

# 5. ASOSIY ISHGA TUSHIRISH QISMI
if __name__ == "__main__":
    # DIQQAT: Avval Flask'ni alohida oqimda (Thread) yoqamiz
    logger.info("🌐 Flask server ishga tushmoqda...")
    web_thread = Thread(target=run_web)
    web_thread.daemon = True  # Asosiy dastur bilan birga yopilishi uchun
    web_thread.start()
    
    # Keyin botni polling rejimida yoqamiz
    logger.info("🤖 Bot polling rejimida boshlanmoqda...")
    executor.start_polling(dp, skip_updates=True, on_startup=on_start, on_shutdown=on_stop)