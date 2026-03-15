# main.py — aiogram 2.x
import asyncio, logging
from aiogram import Bot, Dispatcher, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from config import config, load_group_chat_id
from handlers.flash_sale import register
from scheduler import on_startup, on_shutdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

bot     = Bot(token=config.bot_token, parse_mode="HTML")
storage = MemoryStorage()
dp      = Dispatcher(bot, storage=storage)

register(dp)

async def on_start(dp: Dispatcher):
    await on_startup(bot)
    await load_group_chat_id()
    if config.group_chat_id:
        logger.info("✅ Guruh yuklandi: %d", config.group_chat_id)
    else:
        logger.warning("⚠️  Guruh sozlanmagan! Botni guruhga admin qilib qo'shing.")
        try:
            await bot.send_message(
                config.admin_id,
                "⚠️ <b>Guruh sozlanmagan!</b>\nBotni guruhga admin qilib qo'shing — tugma avtomatik keladi."
            )
        except Exception:
            pass

async def on_stop(dp: Dispatcher):
    await on_shutdown()

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_start, on_shutdown=on_stop)
