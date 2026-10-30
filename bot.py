import os
from dotenv import load_dotenv
load_dotenv()

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
APP_URL = os.getenv("APP_URL", "https://example.com/app")
SHOP_NAME = os.getenv("SHOP_NAME", "HAWK STRIKE")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("📅 Onlayn yozilish", web_app=WebAppInfo(url=APP_URL))]]
    await update.message.reply_text(
        f"Assalomu alaykum! {SHOP_NAME} onlayn yozilish xizmatiga xush kelibsiz.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN .env faylida ko‘rsatilmagan.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    print("Telegram bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
