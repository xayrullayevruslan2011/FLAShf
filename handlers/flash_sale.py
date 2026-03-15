# handlers/flash_sale.py — aiogram 2.x
from __future__ import annotations
import logging, random
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
    list_active_products, set_setting
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
    dp.register_message_handler(cmd_set_group, commands=["setgroup"]) # <-- YANGI QO'SHILDI
    
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
    if event.new_chat_member.status not in ("administrator", "member"):
        return
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"✅ '{chat.title}' ni tanlash",
        callback_data=f"select_group:{chat.id}:{chat.title[:40]}"
    ))
    try:
        await bot.send_message(
            config.admin_id,
            f"🔔 <b>Bot guruhga qo'shildi!</b>\n\n"
            f"📣 <b>{chat.title}</b>\n"
            f"🆔 <code>{chat.id}</code>\n\n"
            "Flash Sale uchun shu guruhni tanlaysizmi?",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception as e:
        logger.warning("Admin xabari yuborilmadi: %s", e)

async def cb_select_group(call: types.CallbackQuery):
    parts     = call.data.split(":", 2)
    chat_id   = int(parts[1])
    chat_name = parts[2]
    await save_group_chat_id(chat_id)
    await call.message.edit_text(
        f"✅ <b>Guruh sozlandi!</b>\n\n"
        f"📣 {chat_name}\n🆔 <code>{chat_id}</code>\n\n"
        "Admin panel: /flash",
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
        f"⚡️ <b>Flash Sale Admin Paneli</b>\n\n"
        f"⏱ Post muddati: <b>{duration} daqiqa</b>\n"
        f"📦 Aktiv mahsulotlar: <b>{len(products)} ta</b>",
        parse_mode="HTML", reply_markup=kb_admin_panel()
    )

async def cmd_status(message: types.Message, bot: Bot):
    if message.from_user.id != config.admin_id:
        return
    if config.group_chat_id == 0:
        g = "❌ Guruh sozlanmagan"
    else:
        try:
            chat = await bot.get_chat(config.group_chat_id)
            g = f"✅ {chat.title} (<code>{config.group_chat_id}</code>)"
        except Exception:
            g = f"✅ <code>{config.group_chat_id}</code>"
    await message.answer(
        f"⚙️ <b>Bot holati</b>\n\nAdmin: <code>{config.admin_id}</code>\nGuruh: {g}",
        parse_mode="HTML"
    )

# ── YANGI: Guruhni buyruq orqali sozlash ──────────────────

async def cmd_set_group(message: types.Message):
    if message.from_user.id != config.admin_id:
        return
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("❌ Bu buyruqni faqat guruh ichida yozish kerak!"); return

    chat_id = message.chat.id
    await save_group_chat_id(chat_id)
    
    await message.answer(
        f"✅ <b>Guruh muvaffaqiyatli tanlandi!</b>\n\n"
        f"📌 Nomi: <b>{message.chat.title}</b>\n"
        f"🆔 ID: <code>{chat_id}</code>\n\n"
        f"Endi bot xabarlarni aynan shu yerga yuboradi.",
        parse_mode="HTML"
    )

# ── Qolgan handlerlar ─────────────────────────────────────

async def cb_panel_add(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer(
        "📸 <b>Rasmlar yoki videolarni yuboring.</b>\n"
        "Hammasini yuborganingizdan so'ng ✅ Tayyor bosing.",
        parse_mode="HTML", reply_markup=kb_ready()
    )
    await state.update_data(media_items=[])
    await AddProduct.collect_media.set()
    await call.answer()

async def cb_panel_list(call: types.CallbackQuery):
    products = await list_active_products()
    if not products:
        await call.message.answer("📭 Aktiv mahsulot yo'q.")
        await call.answer(); return
    lines = ["📋 <b>Mahsulotlar:</b>\n"]
    kb = InlineKeyboardMarkup()
    for p in products:
        lines.append(f"• <code>{p['id']}</code> — <b>{p['name']}</b> ({fmt_price(p['sale_price'])} so'm)")
        kb.add(InlineKeyboardButton(f"🗑 {p['id']}", callback_data=f"del_product:{p['id']}"))
    kb.add(InlineKeyboardButton("🔙 Orqaga", callback_data="panel_back"))
    await call.message.answer("\n".join(lines), parse_mode="HTML", reply_markup=kb)
    await call.answer()

async def cb_del_product(call: types.CallbackQuery):
    pid = call.data.split(":", 1)[1]
    await deactivate_product(pid)
    await call.message.answer(f"🗑 <code>{pid}</code> o'chirildi.", parse_mode="HTML")
    await call.answer("O'chirildi ✅")

async def cb_panel_interval(call: types.CallbackQuery):
    current = await get_flash_duration()
    await call.message.answer(
        f"⏱ Hozirgi muddat: <b>{current} daqiqa</b>\nYangi vaqtni kiriting (1–1440):",
        parse_mode="HTML"
    )
    await ChangeInterval.waiting.set()
    await call.answer()

async def cb_panel_interval_prompt(call: types.CallbackQuery, state: FSMContext):
    pass

async def cb_panel_send_now(call: types.CallbackQuery, bot: Bot):
    products = await list_active_products()
    if not products:
        await call.answer("❌ Aktiv mahsulot yo'q!", show_alert=True); return
    product = dict(random.choice(products))
    await _send_flash_post(bot, product)
    await call.answer("📤 Yuborildi!")

async def cb_panel_back(call: types.CallbackQuery):
    duration = await get_flash_duration()
    products = await list_active_products()
    await call.message.answer(
        f"⚡️ <b>Flash Sale Admin Paneli</b>\n\n"
        f"⏱ Post muddati: <b>{duration} daqiqa</b>\n"
        f"📦 Aktiv mahsulotlar: <b>{len(products)} ta</b>",
        parse_mode="HTML", reply_markup=kb_admin_panel()
    )
    await call.answer()

# ── FSM — Media ───────────────────────────────────────────

async def fsm_collect_media(message: types.Message, state: FSMContext):
    data  = await state.get_data()
    items = data.get("media_items", [])
    if message.photo:
        file_id, mtype = message.photo[-1].file_id, "photo"
    elif message.video:
        file_id, mtype = message.video.file_id, "video"
    else:
        return
    if file_id in {i["file_id"] for i in items}:
        return
    items.append({"file_id": file_id, "media_type": mtype, "sort_order": len(items)})
    await state.update_data(media_items=items)
    if len(items) == 1:
        await message.answer(
            "✅ <b>1 ta media qabul qilindi.</b>\nDavom eting yoki ✅ Tayyor bosing.",
            parse_mode="HTML", reply_markup=kb_ready()
        )
    elif len(items) % 5 == 0:
        await message.answer(f"📦 Jami <b>{len(items)} ta</b> media.", parse_mode="HTML", reply_markup=kb_ready())

async def cb_media_ready(call: types.CallbackQuery, state: FSMContext):
    data  = await state.get_data()
    items = data.get("media_items", [])
    if not items:
        await call.answer("❌ Hech qanday media yo'q!", show_alert=True); return
    await call.message.answer(
        f"✅ <b>{len(items)} ta media saqlandi.</b>\n\nMahsulot nomini kiriting:",
        parse_mode="HTML"
    )
    await AddProduct.wait_name.set()
    await call.answer()

async def fsm_got_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Nom juda qisqa."); return
    await state.update_data(name=name)
    await message.answer("📝 Ta'rifini kiriting:", parse_mode="HTML")
    await AddProduct.wait_description.set()

async def fsm_got_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await message.answer(
        "💰 <b>Chegirmadagi narxni kiriting</b> (so'm):\n<i>Bot +15% qo'shib eski narxni hisoblaydi.</i>",
        parse_mode="HTML"
    )
    await AddProduct.wait_price.set()

async def fsm_got_price(message: types.Message, state: FSMContext):
    raw = message.text.strip().replace(" ","").replace(",","")
    if not raw.replace(".","",1).isdigit():
        await message.answer("❌ Faqat raqam: <code>85000</code>", parse_mode="HTML"); return
    sale_price     = float(raw)
    original_price = calc_original_price(sale_price)
    await state.update_data(sale_price=sale_price, original_price=original_price)
    data = await state.get_data()
    await message.answer(
        f"📋 <b>Tekshiring:</b>\n\n"
        f"📦 {data['name']}\n📝 {data['description']}\n\n"
        f"🔴 <s>{fmt_price(original_price)} so'm</s>\n"
        f"🟢 <b>{fmt_price(sale_price)} so'm</b>\n"
        f"📸 {len(data['media_items'])} ta media\n\nTasdiqlaysizmi?",
        parse_mode="HTML", reply_markup=kb_confirm()
    )
    await AddProduct.confirm.set()

async def cb_confirm(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.finish()
    pid   = generate_product_id()
    media = [{"file_id":m["file_id"],"media_type":m["media_type"],"sort_order":m["sort_order"]} for m in data["media_items"]]
    await create_product(pid, data["name"], data["description"], data["sale_price"], data["original_price"], media)
    await call.message.answer(
        f"✅ <b>Mahsulot saqlandi!</b>\n🏷 <code>{pid}</code>\n\n"
        "Guruhga yuborish uchun '📤 Hozir yuborish' bosing.",
        parse_mode="HTML", reply_markup=kb_admin_panel()
    )
    await call.answer("Saqlandi ✅")

async def cb_cancel(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await call.message.answer("❌ Bekor qilindi.", reply_markup=kb_admin_panel())
    await call.answer()

async def fsm_set_interval(message: types.Message, state: FSMContext):
    if message.from_user.id != config.admin_id:
        return
    raw = message.text.strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 1440):
        await message.answer("❌ 1–1440 orasida raqam kiriting."); return
    await set_setting("flash_duration_minutes", raw)
    await state.finish()
    await message.answer(f"✅ Muddat <b>{raw} daqiqa</b> qilindi.", parse_mode="HTML", reply_markup=kb_admin_panel())

# ── Guruhga yuborish ──────────────────────────────────────

async def _send_flash_post(bot: Bot, product: dict):
    from datetime import datetime, timedelta
    from scheduler import schedule_post_expiry
    pid      = product["id"]
    duration = await get_flash_duration()
    media_rows = await get_product_media(pid)
    if not media_rows:
        await bot.send_message(config.admin_id, f"⚠️ <code>{pid}</code> uchun media yo'q!", parse_mode="HTML"); return

    input_media = []
    for row in media_rows:
        if row["media_type"] == "photo":
            input_media.append(InputMediaPhoto(media=row["file_id"]))
        else:
            input_media.append(InputMediaVideo(media=row["file_id"]))

    sent_album = await bot.send_media_group(config.group_chat_id, media=input_media)
    album_ids  = [m.message_id for m in sent_album]

    expires_at = datetime.now() + timedelta(minutes=duration)
    post_id    = await create_flash_post(pid, config.group_chat_id, album_ids, 0, expires_at)

    caption  = build_group_caption(product["id"], product["name"], product["description"],
                                    product["sale_price"], product["original_price"], duration)
    text_msg = await bot.send_message(
        config.group_chat_id, caption,
        parse_mode="HTML",
        reply_to_message_id=sent_album[0].message_id,
        reply_markup=kb_buy(post_id, pid)
    )

    async with get_db() as db:
        await db.execute("UPDATE flash_posts SET text_message_id=? WHERE id=?", (text_msg.message_id, post_id))
        await db.commit()

    await schedule_post_expiry(bot, post_id, duration * 60)
    logger.info("✅ Flash post yuborildi: %s post_id=%d", pid, post_id)

# ── Sotib olaman ──────────────────────────────────────────

async def cb_buy(call: types.CallbackQuery, bot: Bot):
    parts      = call.data.split(":", 2)
    post_id    = int(parts[1])
    product_id = parts[2]

    post = await get_flash_post(post_id)
    if not post or post["is_expired"]:
        await call.answer("⛔️ Aksiya yakunlangan!", show_alert=True); return

    buyer = call.from_user
    if await has_already_requested(post_id, buyer.id):
        await call.answer("ℹ️ Allaqachon so'rov yuborgansiz!", show_alert=True); return

    product = await get_product(product_id)
    if not product:
        await call.answer("❌ Mahsulot topilmadi.", show_alert=True); return

    await create_purchase_request(post_id, product_id, buyer.id, buyer.username, buyer.full_name)

    uname = f"@{buyer.username}" if buyer.username else f"<b>{buyer.full_name}</b>"
    await bot.send_message(
        config.group_chat_id,
        f"🎉 {uname} ushbu mahsulotni (<code>{product_id}</code>) xarid qilmoqchi!\n"
        "👥 <i>Adminlar tez orada aloqaga chiqadi.</i>",
        parse_mode="HTML",
        reply_to_message_id=post["text_message_id"]
    )
    await bot.send_message(
        config.admin_id,
        build_admin_notify(buyer.full_name, buyer.username, buyer.id, product_id, product["name"], product["sale_price"]),
        parse_mode="HTML"
    )
    await call.answer("✅ So'rovingiz qabul qilindi! Admin tez orada bog'lanadi.", show_alert=True)