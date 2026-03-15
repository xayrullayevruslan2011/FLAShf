from __future__ import annotations
import os, random, string
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self):
        self.bot_token     = os.environ.get("BOT_TOKEN")
        self.admin_id      = int(os.environ.get("ADMIN_ID"))
        self.group_chat_id = int(os.environ.get("GROUP_CHAT_ID"))
        if not self.bot_token:
            raise ValueError("BOT_TOKEN topilmadi!")

config = Config()
MARKUP_PERCENT = 15.0

async def load_group_chat_id():
    from database import get_setting
    value = await get_setting("group_chat_id")
    if value and value != "0":
        config.group_chat_id = int(value)

async def save_group_chat_id(chat_id: int):
    from database import set_setting
    config.group_chat_id = chat_id
    await set_setting("group_chat_id", str(chat_id))

def generate_product_id():
    digits = "".join(random.choices(string.digits, k=4))
    return f"#FL-{digits}"

def calc_original_price(sale_price: float) -> float:
    return round(sale_price * (1 + MARKUP_PERCENT / 100))

def fmt_price(amount: float) -> str:
    return f"{int(amount):,}".replace(",", " ")

def build_group_caption(product_id, name, description, sale_price, original_price, expires_minutes):
    return (
        f"⚡️ <b>FLASH SALE</b>  •  <code>{product_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛍 <b>{name}</b>\n\n"
        f"📝 {description}\n\n"
        "💸 <b>Narxlar:</b>\n"
        f"   🔴 <s>{fmt_price(original_price)} so'm</s>\n"
        f"   🟢 <b>{fmt_price(sale_price)} so'm</b> ✅\n\n"
        f"⏳ <i>Aksiya faqat {expires_minutes} daqiqa davom etadi!</i>\n"
        "🔥 <i>Ulguring — miqdor cheklangan!</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 Xarid qilish uchun quyidagi tugmani bosing:"
    )

def build_expired_caption(product_id, name, original_price):
    return (
        f"❌ <b>BU AKSIYA YAKUNLANDI</b>  •  <code>{product_id}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🛍 <b>{name}</b>\n\n"
        f"💰 Narx o'z holiga qaytdi: <b>{fmt_price(original_price)} so'm</b>\n\n"
        "📢 <i>Yangi aksiyalar uchun guruhimizni kuzatib boring!</i>"
    )

def build_admin_notify(buyer_fullname, buyer_username, buyer_id, product_id, product_name, sale_price):
    uname = f"@{buyer_username}" if buyer_username else "<i>yo'q</i>"
    return (
        "🛒 <b>YANGI XARID SO'ROVI!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Xaridor:</b> {buyer_fullname}\n"
        f"📱 <b>Username:</b> {uname}\n"
        f"🆔 <b>ID:</b> <code>{buyer_id}</code>\n\n"
        f"📦 <b>Mahsulot:</b> {product_name}\n"
        f"🏷 <b>ID:</b> <code>{product_id}</code>\n"
        f"💰 <b>Narx:</b> {fmt_price(sale_price)} so'm\n\n"
        f"<a href='tg://user?id={buyer_id}'>👉 Xaridorga yozish</a>"
    )