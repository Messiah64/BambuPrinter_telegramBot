import os
import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple storage
printer_busy = False
printer_user = ""
printer_end_time = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "3D Printer Bot\n\n"
        "/current - Check availability\n"
        "/use NAME HOURS - Reserve (e.g. /use John 2.5)"
    )

async def current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global printer_busy, printer_user, printer_end_time
    
    if not printer_busy:
        await update.message.reply_text("✅ Printer is available!")
        return
    
    if printer_end_time and datetime.now() > printer_end_time:
        printer_busy = False
        printer_user = ""
        printer_end_time = None
        await update.message.reply_text("✅ Printer is available!")
        return
    
    remaining = (printer_end_time - datetime.now()).total_seconds() / 3600
    await update.message.reply_text(
        f"🔴 In use by: {printer_user}\n"
        f"Available in: {remaining:.1f} hours"
    )

async def use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global printer_busy, printer_user, printer_end_time
    
    if printer_busy and printer_end_time and datetime.now() < printer_end_time:
        remaining = (printer_end_time - datetime.now()).total_seconds() / 3600
        await update.message.reply_text(f"❌ Busy! Available in {remaining:.1f} hours")
        return
    
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /use NAME HOURS\nExample: /use John 2.5")
            return
        
        name = args[0]
        hours = float(args[1])
        
        if hours <= 0 or hours > 24:
            await update.message.reply_text("Hours must be between 0 and 24")
            return
        
        printer_busy = True
        printer_user = name
        printer_end_time = datetime.now() + timedelta(hours=hours)
        
        await update.message.reply_text(
            f"✅ Reserved!\n"
            f"User: {name}\n"
            f"Duration: {hours} hours"
        )
    except (ValueError, IndexError):
        await update.message.reply_text("Usage: /use NAME HOURS\nExample: /use John 2.5")

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("ERROR: Set BOT_TOKEN environment variable")
        return
    
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("current", current))
    app.add_handler(CommandHandler("use", use))
    
    print("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
