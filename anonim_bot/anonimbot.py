import asyncio
import logging
import aiosqlite
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# ==================== SOZLAMALAR ====================
BOT_TOKEN = "8900317787:AAFBrjtee_AvOFwb5pqfXUL9f1hSGXjsXdU"  # BotFather'dan olingan token
ADMIN_ID = 7353338920  # Telegram ID ingiz (int ko'rinishida)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Bot global sozlamalari
IS_BOT_ACTIVE = True
SHOW_SENDER_NAME = False  # False = Anonim, True = Ism ko'rinadi

# ==================== FSM HOLATLAR ====================
class Form(StatesGroup):
    waiting_for_anon_message = State()
    waiting_for_reply = State()
    waiting_for_report_reason = State()
    waiting_for_auto_reply_text = State()
    waiting_for_unblock_id = State()
    waiting_for_admin_report_reply = State()
    waiting_for_broadcast_message = State()

# ==================== BAZA BILAN ISHLASH ====================
async def init_db():
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                auto_reply TEXT DEFAULT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_blocks (
                owner_id INTEGER,
                blocked_id INTEGER,
                PRIMARY KEY (owner_id, blocked_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id INTEGER,
                reported_id INTEGER,
                reason TEXT
            )
        """)
        await db.commit()

# ==================== KEYBOARDLAR ====================
def main_keyboard(user_id: int):
    kb = [
        [types.KeyboardButton(text="🔗 Shaxsiy havola"), types.KeyboardButton(text="📊 Profil")],
        [types.KeyboardButton(text="⚙️ Avto-javob sozlash"), types.KeyboardButton(text="ℹ️ Yordam")]
    ]
    if user_id == ADMIN_ID:
        kb.append([types.KeyboardButton(text="👑 Admin Panel")])
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_keyboard():
    anon_status = "O'chirilgan (Ism ko'rinadi)" if SHOW_SENDER_NAME else "Yoqilgan (Anonim)"
    bot_status = "Yoqilgan" if IS_BOT_ACTIVE else "To'xtatilgan"
    kb = [
        [types.KeyboardButton(text="📈 Statistika"), types.KeyboardButton(text="👥 Foydalanuvchilar ro'yxati")],
        [types.KeyboardButton(text="🚨 Shikoyatlar"), types.KeyboardButton(text="🔓 Blokdan chiqarish")],
        [types.KeyboardButton(text="📢 Xabar tarqatish")],
        [types.KeyboardButton(text=f"👁 Anonimlik: {anon_status}")],
        [types.KeyboardButton(text=f"⏯ Bot: {bot_status}")],
        [types.KeyboardButton(text="🔙 Bosh menyu")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def anon_msg_inline(sender_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Javob berish", callback_data=f"reply_{sender_id}"),
            InlineKeyboardButton(text="🚨 Shikoyat", callback_data=f"report_{sender_id}")
        ],
        [
            InlineKeyboardButton(text="🚫 Taqiqlash", callback_data=f"block_{sender_id}")
        ]
    ])

def send_again_inline(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍️ Yana xabar yuborish", callback_data=f"sendagain_{target_id}")
        ]
    ])

# ==================== HANDLERLAR ====================

@dp.message(CommandStart())
async def start_handler(message: types.Message, command: CommandObject, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    first_name = message.from_user.first_name or "Foydalanuvchi"
    username = message.from_user.username or "Mavjud emas"

    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute(
            "INSERT INTO users (user_id, first_name, username) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET first_name=?, username=?",
            (user_id, first_name, username, first_name, username)
        )
        await db.commit()

    args = command.args

    # Havola orqali kirilganda (o'ziniki bo'lsa ham o'taveradi)
    if args and args.isdigit():
        target_id = int(args)
        
        # Bloklanganini tekshirish
        async with aiosqlite.connect("bot_database.db") as db:
            async with db.execute("SELECT 1 FROM user_blocks WHERE owner_id = ? AND blocked_id = ?", (target_id, user_id)) as cursor:
                if await cursor.fetchone():
                    await message.answer("Ushbu foydalanuvchi sizdan xabarlar qabul qilmaydi.")
                    return

        await state.update_data(target_id=target_id)
        await state.set_state(Form.waiting_for_anon_message)
        
        msg_text = "✍️ O'zingizga xabar yozing:" if target_id == user_id else "✍️ Anonim xabaringizni yozing (Matn, rasm, stiker yoki audio yuborishingiz mumkin):"
        await message.answer(msg_text)
        return

    await message.answer(
        "Xush kelibsiz! Shaxsiy havolangizni oling va do'stlaringizga ulashing.",
        reply_markup=main_keyboard(user_id)
    )

# --- Anonim xabar yuborish ---
@dp.message(Form.waiting_for_anon_message)
async def process_anon_message(message: types.Message, state: FSMContext):
    if not IS_BOT_ACTIVE and message.from_user.id != ADMIN_ID:
        await message.answer("Bot vaqtincha to'xtatilgan.")
        await state.clear()
        return

    data = await state.get_data()
    target_id = data.get("target_id")
    sender = message.from_user

    # Ism ko'rsatish global nastroykaga bog'liq
    if SHOW_SENDER_NAME:
        header = f"📥 **Sizga yangi xabar keldi:**\n👤 **Yuboruvchi:** {sender.first_name} (@{sender.username or 'yoq'})\n\n"
    else:
        header = "📥 **Sizga yangi anonim xabar keldi:**\n\n"

    try:
        # Xabar turini birga (bitta xat qilib) yetkazish
        if message.text:
            await bot.send_message(
                chat_id=target_id,
                text=f"{header}{message.text}",
                reply_markup=anon_msg_inline(sender.id),
                parse_mode="Markdown"
            )
        else:
            caption_text = f"{header}{message.caption or ''}"
            await message.copy_to(
                chat_id=target_id,
                caption=caption_text,
                reply_markup=anon_msg_inline(sender.id),
                parse_mode="Markdown"
            )
        
        await message.answer(
            "✅ Xabaringiz yetkazildi!",
            reply_markup=send_again_inline(target_id)
        )
        
        # Avto-javob mavjud bo'lsa
        async with aiosqlite.connect("bot_database.db") as db:
            async with db.execute("SELECT auto_reply FROM users WHERE user_id = ?", (target_id,)) as cursor:
                res = await cursor.fetchone()
                if res and res[0]:
                    await message.answer(f"🤖 **Avto-javob:**\n{res[0]}", parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Xabar yuborishda xatolik: {e}")
        await message.answer("Xabarni yetkazishda xatolik yuz berdi. Foydalanuvchi botni bloklagan bo'lishi mumkin.")
    
    await state.clear()

# --- Yana xabar yuborish tugmasi ---
@dp.callback_query(F.data.startswith("sendagain_"))
async def cb_send_again(call: CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[1])
    user_id = call.from_user.id

    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT 1 FROM user_blocks WHERE owner_id = ? AND blocked_id = ?", (target_id, user_id)) as cursor:
            if await cursor.fetchone():
                await call.message.answer("Ushbu foydalanuvchi sizdan xabarlar qabul qilmaydi.")
                await call.answer()
                return

    await state.update_data(target_id=target_id)
    await state.set_state(Form.waiting_for_anon_message)
    await call.message.answer("✍️ Anonim xabaringizni yozing:")
    await call.answer()

# --- Inline javob berish va bloklash ---
@dp.callback_query(F.data.startswith("reply_"))
async def cb_reply(call: CallbackQuery, state: FSMContext):
    target_id = int(call.data.split("_")[1])
    await state.update_data(reply_target_id=target_id)
    await state.set_state(Form.waiting_for_reply)
    await call.message.answer("💬 Javob xabaringizni yozing:")
    await call.answer()

@dp.message(Form.waiting_for_reply)
async def process_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("reply_target_id")
    sender_id = message.from_user.id
    
    try:
        # Bitta xabarda javobni yetkazish
        if message.text:
            await bot.send_message(
                chat_id=target_id,
                text=f"📩 **Sizga javob keldi:**\n\n{message.text}",
                reply_markup=send_again_inline(sender_id),
                parse_mode="Markdown"
            )
        else:
            caption_text = f"📩 **Sizga javob keldi:**\n\n{message.caption or ''}"
            await message.copy_to(
                chat_id=target_id,
                caption=caption_text,
                reply_markup=send_again_inline(sender_id),
                parse_mode="Markdown"
            )
        await message.answer("Javobingiz yetkazildi!")
    except Exception:
        await message.answer("Javobni yetkazib bo'lmadi.")
    
    await state.clear()

@dp.callback_query(F.data.startswith("block_"))
async def cb_block(call: CallbackQuery):
    blocked_id = int(call.data.split("_")[1])
    owner_id = call.from_user.id

    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute("INSERT OR IGNORE INTO user_blocks VALUES (?, ?)", (owner_id, blocked_id))
        await db.commit()

    await call.message.answer("Foydalanuvchi bloklandi. Endi u sizga xabar yubora olmaydi.")
    await call.answer()

# --- Shikoyatlar bo'limi ---
@dp.callback_query(F.data.startswith("report_"))
async def cb_report(call: CallbackQuery, state: FSMContext):
    reported_id = int(call.data.split("_")[1])
    await state.update_data(reported_id=reported_id)
    await state.set_state(Form.waiting_for_report_reason)
    await call.message.answer("Shikoyat sababini yozib qoldiring:")
    await call.answer()

@dp.message(Form.waiting_for_report_reason)
async def process_report(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reported_id = data.get("reported_id")
    reporter_id = message.from_user.id
    reason = message.text or "Sabab ko'rsatilmadi"

    async with aiosqlite.connect("bot_database.db") as db:
        cursor = await db.execute("INSERT INTO reports (reporter_id, reported_id, reason) VALUES (?, ?, ?)",
                                 (reporter_id, reported_id, reason))
        report_id = cursor.lastrowid
        await db.commit()

    await message.answer("Shikoyatingiz adminga yetkazildi.")
    
    # Adminga xabar yuborish
    try:
        admin_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Shikoyatga javob berish", callback_data=f"repans_{reporter_id}")
        ]])
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🚨 **Yangi shikoyat!** (#ID_{report_id})\n\n"
                 f"👤 **Kimdan:** `{reporter_id}`\n"
                 f"🚫 **Kim ustidan:** `{reported_id}`\n"
                 f"📝 **Sabab:** {reason}",
            reply_markup=admin_kb,
            parse_mode="Markdown"
        )
    except Exception:
        pass

    await state.clear()

# --- Admin shikoyatga javob berishi ---
@dp.callback_query(F.data.startswith("repans_"))
async def cb_report_answer(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return
    reporter_id = int(call.data.split("_")[1])
    await state.update_data(report_user_id=reporter_id)
    await state.set_state(Form.waiting_for_admin_report_reply)
    await call.message.answer("Foydalanuvchiga yuboriladigan javobingizni yozing:")
    await call.answer()

@dp.message(Form.waiting_for_admin_report_reply)
async def process_admin_report_reply(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    data = await state.get_data()
    reporter_id = data.get("report_user_id")

    try:
        await bot.send_message(
            chat_id=reporter_id,
            text=f"👨‍💻 **Admin sizning shikoyatingizga javob berdi:**\n\n{message.text}"
        )
        await message.answer("Javob foydalanuvchiga yetkazildi!")
    except Exception:
        await message.answer("Javobni yetkazib bo'lmadi.")

    await state.clear()

# --- Menyular ---
@dp.message(F.text == "🔗 Shaxsiy havola")
async def get_link(message: types.Message):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    
    link_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Havolaga o'tish", url=link)]
    ])
    
    await message.answer(
        f"Sizning shaxsiy havolangiz:\n\n{link}\n\nUshbu havolani nusxalab do'stlaringizga yoki ijtimoiy tarmoqlarga ulashing!",
        reply_markup=link_kb
    )

@dp.message(F.text == "📊 Profil")
async def get_profile(message: types.Message):
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT auto_reply FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor:
            res = await cursor.fetchone()
            auto_reply_status = res[0] if res and res[0] else "O'chirilgan"

    await message.answer(
        f"👤 **Profil ma'lumotlari:**\n\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"⚙️ Avto-javob: **{auto_reply_status}**",
        parse_mode="Markdown"
    )

@dp.message(F.text == "⚙️ Avto-javob sozlash")
async def set_auto_reply_start(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_auto_reply_text)
    await message.answer("Anonim xabar tushganda avtomatik yuboriladigan matnni kiriting (O'chirish uchun '-' deb yozing):")

@dp.message(Form.waiting_for_auto_reply_text)
async def set_auto_reply_finish(message: types.Message, state: FSMContext):
    text = None if message.text == "-" else message.text
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute("UPDATE users SET auto_reply = ? WHERE user_id = ?", (text, message.from_user.id))
        await db.commit()
    
    await message.answer("Avto-javob saqlandi!" if text else "Avto-javob o'chirildi!")
    await state.clear()

@dp.message(F.text == "ℹ️ Yordam")
async def help_cmd(message: types.Message):
    await message.answer(
        "💡 **Yordam bo'limi:**\n\n"
        "1. '🔗 Shaxsiy havola' tugmasini bosing va havolangizni oling.\n"
        "2. Ushbu havolani Telegram-kanal, Instagram sto'ris yoki do'stlaringizga yuboring.\n"
        "3. Ular havola orqali sizga shaxsini oshkor qilmagan holda xabar, rasm yoki ovozli xabarlar yuborishlari mumkin!"
    )

# ==================== ADMIN PANEL ====================
@dp.message(F.text == "👑 Admin Panel")
async def admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Admin panelga xush kelibsiz:", reply_markup=admin_keyboard())

@dp.message(F.text.startswith("👁 Anonimlik:"))
async def toggle_anon(message: types.Message):
    global SHOW_SENDER_NAME
    if message.from_user.id != ADMIN_ID:
        return
    SHOW_SENDER_NAME = not SHOW_SENDER_NAME
    await message.answer("Anonimlik rejimi o'zgardi!", reply_markup=admin_keyboard())

@dp.message(F.text.startswith("⏯ Bot:"))
async def toggle_bot_status(message: types.Message):
    global IS_BOT_ACTIVE
    if message.from_user.id != ADMIN_ID:
        return
    IS_BOT_ACTIVE = not IS_BOT_ACTIVE
    await message.answer("Bot holati o'zgardi!", reply_markup=admin_keyboard())

@dp.message(F.text == "👥 Foydalanuvchilar ro'yxati")
async def admin_users_list(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT user_id, first_name, username FROM users LIMIT 30") as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        await message.answer("Foydalanuvchilar topilmadi.")
        return

    msg = "👥 **Foydalanuvchilar ro'yxati (Oxirgi 30 ta):**\n\n"
    for row in rows:
        msg += f"• `{row[0]}` | {row[1]} (@{row[2]})\n"
    await message.answer(msg, parse_mode="Markdown")

@dp.message(F.text == "📈 Statistika")
async def admin_stats(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            count = (await cursor.fetchone())[0]
    await message.answer(f"📊 Jami foydalanuvchilar soni: **{count}** ta", parse_mode="Markdown")

# --- BROADCASTING (XABAR TARQATISH) ---
@dp.message(F.text == "📢 Xabar tarqatish")
async def broadcast_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(Form.waiting_for_broadcast_message)
    await message.answer("Barcha foydalanuvchilarga yuboriladigan xabarni (matn, rasm, stiker) yuboring:")

@dp.message(Form.waiting_for_broadcast_message)
async def broadcast_finish(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            users = await cursor.fetchall()

    success, failed = 0, 0
    await message.answer("📢 Xabar tarqatish boshlandi...")

    for user in users:
        u_id = user[0]
        try:
            await message.copy_to(chat_id=u_id)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await message.answer(
        f"✅ **Xabar tarqatish yakunlandi!**\n\n"
        f"🟢 Muvaffaqiyatli: {success} ta\n"
        f"🔴 Yetib bormadi (bloklagan): {failed} ta",
        parse_mode="Markdown"
    )
    await state.clear()

@dp.message(F.text == "🚨 Shikoyatlar")
async def admin_reports(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    async with aiosqlite.connect("bot_database.db") as db:
        async with db.execute("SELECT id, reporter_id, reported_id, reason FROM reports ORDER BY id DESC LIMIT 10") as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        await message.answer("Hozircha shikoyatlar yo'q.")
        return
    
    for row in rows:
        reply_btn = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="💬 Javob berish", callback_data=f"repans_{row[1]}")
        ]])
        msg = f"🚨 **Shikoyat #ID_{row[0]}**\nKimdan: `{row[1]}`\nKim ustidan: `{row[2]}`\nSabab: {row[3]}"
        await message.answer(msg, reply_markup=reply_btn, parse_mode="Markdown")

@dp.message(F.text == "🔓 Blokdan chiqarish")
async def unblock_start(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.set_state(Form.waiting_for_unblock_id)
    await message.answer("Blokdan chiqariladigan foydalanuvchining ID sini kiriting:")

@dp.message(Form.waiting_for_unblock_id)
async def unblock_finish(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Raqam kiriting.")
        return
    uid = int(message.text)
    async with aiosqlite.connect("bot_database.db") as db:
        await db.execute("DELETE FROM user_blocks WHERE blocked_id = ?", (uid,))
        await db.commit()
    await message.answer(f"Foydalanuvchi `{uid}` blokdan chiqarildi.", parse_mode="Markdown")
    await state.clear()

@dp.message(F.text == "🔙 Bosh menyu")
async def back_to_main(message: types.Message):
    await message.answer("Bosh menyu", reply_markup=main_keyboard(message.from_user.id))

# ==================== MAIN ====================
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())