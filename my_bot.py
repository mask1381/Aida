import os
import re
import io
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# ---------- ۱. خواندن تنظیمات از متغیرهای محیطی (روش امن) ----------
try:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID"))
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    CHANNEL_ID = os.getenv("CHANNEL_ID")
    if not all([BOT_TOKEN, ADMIN_USER_ID, GEMINI_API_KEY, CHANNEL_ID]):
        raise ValueError("یکی از متغیرهای محیطی تنظیم نشده است.")
except (ValueError, TypeError) as e:
    print(f"خطای حیاتی: لطفا متغیرهای محیطی را در هاست خود (مثلا Render) تنظیم کنید. خطا: {e}")
    exit()


# ---------- ۲. تنظیمات واترمارک و فونت ----------
WATERMARK_TEXT = f"{CHANNEL_ID} ©"
FONT_FILE = "Vazirmatn-Regular.ttf" 
FONT_SIZE = 30

# ---------- ۳. پیکربندی هوش مصنوعی Gemini ----------
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')
    print("هوش مصنوعی Gemini با موفقیت پیکربندی شد.")
except Exception as e:
    print(f"خطا در پیکربندی Gemini: {e}")
    exit()

# ---------- ۴. توابع کمکی ربات ----------

def generate_hashtags(text: str) -> str:
    """با استفاده از هوش مصنوعی، برای متن ورودی هشتگ تولید می‌کند"""
    if not text or not text.strip(): return ""
    try:
        prompt = f"بر اساس متن زیر، بین ۳ تا ۵ هشتگ مناسب و مرتبط به زبان فارسی تولید کن. فقط هشتگ‌ها را بنویس.\n\nمتن: \"{text}\""
        response = model.generate_content(prompt)
        hashtags = " ".join([f"#{tag.strip()}" for tag in response.text.replace("#", "").split()])
        return hashtags
    except Exception as e:
        print(f"خطا در تولید هشتگ: {e}")
        return ""

def apply_watermark(file_bytes: bytes) -> bytes:
    """لوگو یا متن را به عنوان واترمارک به عکس اضافه می‌کند"""
    try:
        with Image.open(io.BytesIO(file_bytes)).convert("RGBA") as base:
            txt = Image.new("RGBA", base.size, (255, 255, 255, 0))
            try:
                font = ImageFont.truetype(FONT_FILE, FONT_SIZE)
            except IOError:
                print("فایل فونت پیدا نشد! از فونت پیش‌فرض استفاده می‌شود.")
                font = ImageFont.load_default()
            
            draw = ImageDraw.Draw(txt)
            bbox = font.getbbox(WATERMARK_TEXT)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            margin = 20
            x = base.size[0] - text_width - margin
            y = base.size[1] - text_height - margin
            
            draw.text((x, y), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 128))
            
            out = Image.alpha_composite(base, txt)
            buffer = io.BytesIO()
            out.convert("RGB").save(buffer, "JPEG")
            buffer.seek(0)
            return buffer.getvalue()
    except Exception as e:
        print(f"خطا در اعمال واترمارک: {e}")
        return file_bytes

def escape_markdown(text: str) -> str:
    """کاراکترهای خاص مارک‌داون را برای جلوگیری از خطا در تلگرام اصلاح می‌کند"""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def process_and_send(context: CallbackContext, chat_id: int, text: str = None, photo_id: str = None, video_id: str = None, document_id: str = None):
    """تابع اصلی برای پردازش و ارسال نهایی محتوا به کانال"""
    bot = context.bot
    original_caption = text or ""
    
    buttons = []
    final_caption = original_caption
    pattern = r'\[(.*?)\]\((.*?)\)'
    matches = re.findall(pattern, original_caption)
    if matches:
        for button_text, url in matches:
            buttons.append([InlineKeyboardButton(button_text, url=url)])
        final_caption = re.sub(pattern, '', final_caption).strip()

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    hashtags = generate_hashtags(final_caption)
    user = await bot.get_chat(ADMIN_USER_ID)
    
    # اصلاح کاراکترهای خاص در تمام بخش‌های متنی
    escaped_caption = escape_markdown(final_caption)
    escaped_hashtags = escape_markdown(hashtags)
    user_signature = f"👤 ارسال توسط: [{escape_markdown(user.first_name)}](tg://user?id={user.id})"
    
    full_caption = f"{escaped_caption}\n\n{escaped_hashtags}\n\n{user_signature}".strip()
    
    sent_message = None
    try:
        if photo_id:
            file = await bot.get_file(photo_id)
            photo_bytes = await file.download_as_bytearray()
            watermarked_photo_bytes = apply_watermark(photo_bytes)
            sent_message = await bot.send_photo(chat_id=CHANNEL_ID, photo=watermarked_photo_bytes, caption=full_caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        elif video_id:
            sent_message = await bot.send_video(chat_id=CHANNEL_ID, video=video_id, caption=full_caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        elif document_id:
            sent_message = await bot.send_document(chat_id=CHANNEL_ID, document=document_id, caption=full_caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)
        elif text:
            sent_message = await bot.send_message(chat_id=CHANNEL_ID, text=full_caption, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=reply_markup)

        if sent_message:
            delete_button = InlineKeyboardButton("🗑️ حذف از کانال", callback_data=f"delete_{sent_message.message_id}")
            confirmation_markup = InlineKeyboardMarkup([[delete_button]])
            await bot.send_message(chat_id=ADMIN_USER_ID, text="✅ پیام شما با موفقیت به کانال ارسال شد.", reply_markup=confirmation_markup)

    except Exception as e:
        print(f"خطا در ارسال به کانال: {e}")
        await bot.send_message(chat_id=ADMIN_USER_ID, text=f"❌ خطایی در هنگام ارسال به کانال رخ داد:\n`{escape_markdown(str(e))}`", parse_mode=ParseMode.MARKDOWN_V2)


# ---------- ۵. تعریف Handlers (توابع پاسخ‌گو) ----------

async def message_handler(update: Update, context: CallbackContext):
    if update.message.from_user.id != ADMIN_USER_ID: return
    
    processing_msg = await update.message.reply_text("⏳ در حال پردازش...")
    
    await process_and_send(
        context,
        chat_id=ADMIN_USER_ID,
        text=update.message.text or update.message.caption,
        photo_id=update.message.photo[-1].file_id if update.message.photo else None,
        video_id=update.message.video.file_id if update.message.video else None,
        document_id=update.message.document.file_id if update.message.document else None
    )
    await processing_msg.delete()

async def schedule_command(update: Update, context: CallbackContext):
    if update.message.from_user.id != ADMIN_USER_ID: return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("لطفا روی یک پیام برای زمان‌بندی ریپلای کنید.")
        return
        
    try:
        time_str = context.args[0]
        delay = 0
        if 'd' in time_str: delay += int(time_str.split('d')[0]) * 86400
        if 'h' in time_str: delay += int(re.search(r'(\d+)h', time_str).group(1)) * 3600
        if 'm' in time_str: delay += int(re.search(r'(\d+)m', time_str).group(1)) * 60

        job_context = {
            'chat_id': update.message.chat_id,
            'text': update.message.reply_to_message.text or update.message.reply_to_message.caption,
            'photo_id': update.message.reply_to_message.photo[-1].file_id if update.message.reply_to_message.photo else None,
            'video_id': update.message.reply_to_message.video.file_id if update.message.reply_to_message.video else None,
            'document_id': update.message.reply_to_message.document.file_id if update.message.reply_to_message.document else None
        }
        
        context.job_queue.run_once(scheduled_post_callback, delay, context=job_context, name=str(update.message.message_id))
        await update.message.reply_text(f"✅ پیام شما برای ارسال در {time_str} دیگر زمان‌بندی شد.")
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت زمان اشتباه است. مثال: /schedule 1h30m")

async def scheduled_post_callback(context: CallbackContext):
    job = context.job
    await process_and_send(context, **job.context)

async def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("delete_"):
        message_id_to_delete = int(query.data.split('_')[1])
        try:
            await context.bot.delete_message(chat_id=CHANNEL_ID, message_id=message_id_to_delete)
            await query.edit_message_text(text="🗑️ پیام با موفقیت از کانال حذف شد.")
        except Exception as e:
            await query.edit_message_text(text=f"❌ خطایی در حذف پیام رخ داد:\n`{escape_markdown(str(e))}`", parse_mode=ParseMode.MARKDOWN_V2)


# ---------- ۶. بخش اصلی برنامه (برای اجرا) ----------
def main():
    """تابع اصلی برای شروع به کار ربات"""
    print("در حال شروع به کار ربات...")
    application = Application.builder().token(BOT_TOKEN).build()

    # ثبت کردن Handler ها
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    print("ربات مدیر حرفه‌ای کانال شروع به کار کرد و آماده دریافت پیام است...")
    
    # اجرای ربات
    application.run_polling()

if __name__ == '__main__':
    main()

