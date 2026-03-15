# scheduler.py — aiogram 2.x uchun
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from aiogram.utils.exceptions import MessageNotModified, MessageToEditNotFound
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from config import build_expired_caption, config

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None

def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            timezone="Asia/Tashkent",
            job_defaults={"misfire_grace_time": 120, "coalesce": True},
        )
    return _scheduler

async def expire_flash_post(bot, post_id: int):
    from database import get_flash_post, get_product, mark_post_expired
    post = await get_flash_post(post_id)
    if not post or post["is_expired"]:
        return
    product = await get_product(post["product_id"])
    if not product:
        return

    expired_text = build_expired_caption(product["id"], product["name"], product["original_price"])
    try:
        await bot.edit_message_text(
            chat_id=post["chat_id"],
            message_id=post["text_message_id"],
            text=expired_text,
            parse_mode="HTML",
            reply_markup=None,
        )
    except (MessageNotModified, MessageToEditNotFound):
        pass
    except Exception as e:
        logger.error("Xabar yangilashda xato: %s", e)

    await mark_post_expired(post_id)
    logger.info("✅ Post #%d yakunlandi", post_id)

    try:
        await bot.send_message(
            config.admin_id,
            f"⏱ <b>Flash Sale yakunlandi!</b>\n"
            f"📦 <b>{product['name']}</b>\n"
            f"🏷 <code>{product['id']}</code>",
            parse_mode="HTML",
        )
    except Exception:
        pass

def _job_id(post_id: int) -> str:
    return f"expire_post_{post_id}"

async def schedule_post_expiry(bot, post_id: int, delay_seconds: int):
    scheduler = get_scheduler()
    run_at = datetime.now() + timedelta(seconds=delay_seconds)
    job_id = _job_id(post_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    scheduler.add_job(
        func=expire_flash_post,
        trigger=DateTrigger(run_date=run_at),
        id=job_id,
        kwargs={"bot": bot, "post_id": post_id},
        replace_existing=True,
    )
    logger.info("Job qo'shildi: post_id=%d delay=%ds", post_id, delay_seconds)

async def restore_pending_jobs(bot):
    from database import get_active_flash_posts
    posts = await get_active_flash_posts()
    now = datetime.now()
    for post in posts:
        expires_at = datetime.fromisoformat(post["expires_at"])
        remaining = (expires_at - now).total_seconds()
        if remaining <= 0:
            await expire_flash_post(bot, post["id"])
        else:
            await schedule_post_expiry(bot, post["id"], int(remaining))

async def on_startup(bot):
    from database import init_db
    await init_db()
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("✅ Scheduler ishga tushdi")
    await restore_pending_jobs(bot)

async def on_shutdown():
    scheduler = get_scheduler()
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
