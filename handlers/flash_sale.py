# handlers/flash_sale.py — aiogram 2.x
from __future__ import annotations
import logging, random, json
from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    InputMediaPhoto, InputMediaVideo
)
from config import (
    build_admin_notify, build_group_caption,
    calc_original_price, config, fmt_price, generate_product_id,
    save_group_chat_id, load_group_chat_id
)
from database import (
    create_flash_post, create_product, create_purchase_request,
    deactivate_product, get_db, get_flash_duration, get_flash_post,
    get_product, get_product_media, has_already_requested,
    list_active_products, set_setting, get_setting
)

logger = logging.getLogger(__name__)

# ── FSM ──────────────────────────────────────────────────

class AddProduct(StatesGroup):
    collect_media    = State()
    wait_name        = State()
    wait_description = State()
    wait_price       = State()
    confirm          = State()

class ChangeInterval(StatesGroup):
    waiting = State()

# ── Klaviaturalar ─────────────────────────────────────────

def kb_ready():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✅ Tayyor", callback_data="media_ready"))
    return kb

def kb_confirm():
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("✅ Tasdiqlash",   callback_data="product_confirm"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="product_cancel"),
    )
    return kb

def kb_buy(post_id: int, product_id: str):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Sotib olaman 🛒", callback_data=f"buy:{post_id}:{product_id}"))
    return kb

def kb_admin_panel():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Yangi mahsulot",    callback_data="panel_add"),
        InlineKeyboardButton("📋 Mahsulotlar",       callback_data="panel_list"),
        InlineKeyboardButton("⏱ Muddatni sozlash",  callback_data="panel_interval"),
        InlineKeyboardButton("📤 Hozir yuborish",    callback_data="panel_send_now"),
    )
    return kb

# ── Handlerlarni ro'yxatdan o'tkazish ────────────────────

def register(dp: Dispatcher):
    # Setup
    dp.register_my_chat_member_handler(on_bot_added)
    dp.register_callback_query_handler(cb_select_group, lambda c: c.data.startswith("select_group:"))

    # Admin panel
    dp.register_message_handler(cmd_flash,  commands=["flash"])
    dp.register_message_handler(cmd_status, commands=["status"])
    dp.register_message_handler(cmd_set_group, commands=["setgroup"])
    
    dp.register_callback_query_handler(cb_panel_add,      lambda c: c.data == "panel_add")
    dp.register_callback_query_handler(cb_panel_list,     lambda c: c.data == "panel_list")
    dp.register_callback_query_handler(cb_panel_interval, lambda c: c.data == "panel_interval")
    dp.register_callback_query_handler(cb_panel_send_now, lambda c: c.data == "panel_send_now")
    dp.register_callback_query_handler(cb_panel_back,     lambda c: c.data == "panel_back")
    dp.register_callback_query_handler(cb_del_product,    lambda c: c.data.startswith("del_product:"))

    # FSM — media
    dp.register_message_handler(fsm_collect_media, content_types=["photo","video"], state=AddProduct.collect_media)
    dp.register_callback_query_handler(cb_media_ready, lambda c: c.data == "media_ready", state=AddProduct.collect_media)
    dp.register_message_handler(fsm_got_name,        content_types=["text"], state=AddProduct.wait_name)
    dp.register_message_handler(fsm_got_description, content_types=["text"], state=AddProduct.wait_description)
    dp.register_message_handler(fsm_got_price,       content_types=["text"], state=AddProduct.wait_price)
    dp.register_callback_query_handler(cb_confirm, lambda c: c.data == "product_confirm", state=AddProduct.confirm)
    dp.register_callback_query_handler(cb_cancel,  lambda c: c.data == "product_cancel",  state=AddProduct.confirm)

    # FSM — interval
    dp.register_callback_query_handler(cb_panel_interval_prompt, lambda c: c.data == "panel_interval")
    dp.register_message_handler(fsm_set_interval, content_types=["text"], state=ChangeInterval.waiting)

    # Buy
    dp.register_callback_query_handler(cb_buy, lambda c: c.data.startswith("buy:"))

# ── Bot guruhga qo'shildi ─────────────────────────────────

async def on_bot_added(event: types.ChatMemberUpdated, bot: Bot):
    chat = event.chat
    if chat.type not in ("group", "supergroup"):
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"✅ '{chat.title}' ni tanlash",
        callback_data=f"select_group:{chat.id}:{chat.title[:40]}"
    ))
    try:
        await bot.send_message(
            config.admin_id,
            f"🔔 <b>Bot guruhga qo'shildi!</b>\n\n🆔 <code>{chat.id}</code>",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception as e:
        logger.warning("Xabarda xato: %s", e)

async def cb_select_group(call: types.CallbackQuery):
    parts     = call.data.split(":", 2)
    chat_id   = int(parts[1])
    await save_group_chat_id(chat_id)
    await call.message.edit_text(
        f"✅ <b>Guruh sozlandi!</b>\n🆔 <code>{chat_id}</code>",
        parse_mode="HTML"
    )
    await call.answer("✅ Saqlandi!")

# ── Admin panel ───────────────────────────────────────────

async def cmd_flash(message: types.Message):
    if message.from_user.id != config.admin_id:
        return
    duration = await get_flash_duration()
    products = await list_active_products()
    await message.answer(
        f"⚡️ <b>Flash Sale Admin Paneli</b>\n\n⏱ Muddat: {duration} min",
        parse_mode="HTML", reply_markup=kb_admin_panel()
    )

async def cmd_status(message: types.Message, bot: Bot):
    if message.from_user.id != config.admin_id:
        return
    db_id = await get_setting("group_chat_id")
    try:
        current_id = int(db_id) if db_id and db_id != "0" else config.group_chat_id
    except: current_id = config.group_chat_id
    await message.answer(f"⚙️ <b>Holat</b>\nGuruh ID: <code>{current_id}</code>", parse_mode="HTML")

async def cmd_set_group(message: types.Message):
    if message.from_user.id != config.admin_id:
        return
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("❌ Bu buyruqni faqat guruh ichida yozish kerak!"); return
    chat_id = message.chat.id
    await save_group_chat_id(chat_id)
    await message.answer(f"✅ <b>Guruh muvaffaqiyatli tanlandi!</b>\n🆔 <code>{chat_id}</code>", parse_mode="HTML")

async def cb_panel_send_now(call: types.CallbackQuery, bot: Bot):
    products = await list_active_products()
    if not products:
        await call.answer("❌ Aktiv mahsulot yo'q!", show_alert=True); return
    product = dict(random.choice(products))
    await _send_flash_post(bot, product)
    await call.answer("📤 Yuborilmoqda...")

# ── MAJBURAN YUBORISH FUNKSIYASI ──────────────────────────

async def _send_flash_post(bot: Bot, product: dict):
    from datetime import datetime, timedelta
    from scheduler import schedule_post_expiry
    
    # 1. Guruh ID raqamini ANIQ butun son sifatida olish
    db_id = await get_setting("group_chat_id")
    try:
        if db_id and db_id != "0":
            target_chat_id = int(db_id)
        else:
            target_chat_id = int(config.group_chat_id)
    except:
        await bot.send_message(config.admin_id, "❌ XATO: Guruh ID raqami noto'g'ri!"); return

    if not target_chat_id or target_chat_id == 0:
        await bot.send_message(config.admin_id, "❌ XATO: Guruh tanlanmagan!"); return

    pid = product["id"]
    media_rows = await get_product_media(pid)
    input_media = []
    for row in media_rows:
        m_type = InputMediaPhoto if row["media_type"] == "photo" else InputMediaVideo
        input_media.append(m_type(media=row["file_id"]))

    try:
        # 2. MAJBURAN YUBORISH
        sent_album = await bot.send_media_group(chat_id=target_chat_id, media=input_media)
        duration = await get_flash_duration()
        expires_at = datetime.now() + timedelta(minutes=duration)
        
        post_id = await create_flash_post(pid, target_chat_id, [m.message_id for m in sent_album], 0, expires_at)
        
        caption = build_group_caption(pid, product["name"], product["description"], product["sale_price"], product["original_price"], duration)
        text_msg = await bot.send_message(
            chat_id=target_chat_id, 
            text=caption, 
            parse_mode="HTML", 
            reply_to_message_id=sent_album[0].message_id, 
            reply_markup=kb_buy(post_id, pid)
        )
        
        async with get_db() as db:
            await db.execute("UPDATE flash_posts SET text_message_id=? WHERE id=?", (text_msg.message_id, post_id))
            await db.commit()
        await schedule_post_expiry(bot, post_id, duration * 60)
        await bot.send_message(config.admin_id, "✅ Mahsulot guruhga muvaffaqiyatli yuborildi!")
    except Exception as e:
        await bot.send_message(config.admin_id, f"❌ MAJBURIY YUBORISHDA XATOLIK: {e}")

# ── FSM handlerlari va boshqalar ──────────────────────────

async def fsm_collect_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    items = data.get("media_items", [])
    file_id = message.photo[-1].file_id if message.photo else message.video.file_id
    m_type = "photo" if message.photo else "video"
    if any(i["file_id"] == file_id for i in items): return
    items.append({"file_id": file_id, "media_type": m_type, "sort_order": len(items)})
    await state.update_data(media_items=items)
    await message.answer(f"📦 Jami {len(items)} ta media qabul qilindi.", reply_markup=kb_ready())

async def cb_media_ready(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("📦 Mahsulot nomini kiriting:")
    await AddProduct.wait_name.set()
    await call.answer()

async def fsm_got_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📝 Ta'rifini kiriting:")
    await AddProduct.wait_description.set()

async def fsm_got_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer("💰 Chegirmadagi narxni kiriting (faqat raqam):")
    await AddProduct.wait_price.set()

async def fsm_got_price(message: types.Message, state: FSMContext):
    raw = message.text.replace(" ","").replace(",","")
    if not raw.isdigit():
        await message.answer("❌ Faqat raqam kiriting!"); return
    price = float(raw)
    await state.update_data(sale_price=price, original_price=calc_original_price(price))
    data = await state.get_data()
    await message.answer(f"📋 <b>Tekshiring:</b>\n\n📦 {data['name']}\n💰 {fmt_price(price)} so'm\n\nTasdiqlaysizmi?", parse_mode="HTML", reply_markup=kb_confirm())
    await AddProduct.confirm.set()

async def cb_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    pid = generate_product_id()
    await create_product(pid, data["name"], data["description"], data["sale_price"], data["original_price"], data["media_items"])
    await state.finish()
    await call.message.answer("✅ Mahsulot bazaga saqlandi!", reply_markup=kb_admin_panel())
    await call.answer()

async def cb_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_panel())
    await call.answer()

async def fsm_set_interval(message: types.Message, state: FSMContext):
    if message.text.isdigit():
        await set_setting("flash_duration_minutes", message.text)
        await state.finish()
        await message.answer(f"✅ Yangilandi: {message.text} daqiqa", reply_markup=kb_admin_panel())
    else: await message.answer("❌ Faqat raqam kiriting!")

async def cb_panel_back(call: types.CallbackQuery):
    await cmd_flash(call.message)
    await call.answer()

async def cb_del_product(call: types.CallbackQuery):
    pid = call.data.split(":")[1]
    await deactivate_product(pid)
    await call.message.answer(f"🗑 {pid} o'chirildi.")
    await call.answer()

async def cb_panel_interval_prompt(call: types.CallbackQuery):
    await call.message.answer("⏱ Yangi muddatni kiriting (daqiqa):")
    await ChangeInterval.waiting.set()
    await call.answer()

async def cb_buy(call: types.CallbackQuery, bot: Bot):
    parts = call.data.split(":")
    post_id, product_id = int(parts[1]), parts[2]
    post = await get_flash_post(post_id)
    if not post or post["is_expired"]:
        await call.answer("❌ Aksiya yakunlangan!", show_alert=True); return
    buyer = call.from_user
    if await has_already_requested(post_id, buyer.id):
        await call.answer("⚠️ Allaqachon so'rov bergansiz!", show_alert=True); return
    product = await get_product(product_id)
    await create_purchase_request(post_id, product_id, buyer.id, buyer.username, buyer.full_name)
    db_id = await get_setting("group_chat_id")
    try:
        t_id = int(db_id) if db_id and db_id != "0" else config.group_chat_id
    except: t_id = config.group_chat_id
    if t_id:
        try: await bot.send_message(t_id, f"🎉 {buyer.full_name} ushbu mahsulotni sotib olmoqchi!", reply_to_message_id=post["text_message_id"])
        except: pass
    await bot.send_message(config.admin_id, build_admin_notify(buyer.full_name, buyer.username, buyer.id, product_id, product["name"], product["sale_price"]), parse_mode="HTML")
    await call.answer("✅ So'rovingiz qabul qilindi!", show_alert=True)