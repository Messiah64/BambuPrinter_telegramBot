import os
import json
import logging
from datetime import datetime, timedelta

from flask import Flask, request, Response
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

STATE_WAITING_NAME, STATE_WAITING_DURATION = range(2)
STATE_FILE = "printer_state.json"
printer_usage = {
    "user_name": None,
    "start_time": None,
    "finish_time": None,
    "chat_id": None,
}

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
            printer_usage.update(data)
        except Exception as e:
            logging.warning("Failed to load state: %s", e)

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(printer_usage, f)
    except Exception as e:
        logging.error("Failed to save state: %s", e)

def clear_usage():
    printer_usage["user_name"] = None
    printer_usage["start_time"] = None
    printer_usage["finish_time"] = None
    printer_usage["chat_id"] = None
    save_state()

def is_in_use():
    if printer_usage["user_name"] is None or printer_usage["finish_time"] is None:
        return False, None, None
    try:
        finish = datetime.fromisoformat(printer_usage["finish_time"])
    except Exception:
        return False, None, None
    now = datetime.utcnow()
    if now >= finish:
        return False, None, None
    remaining = finish - now
    return True, printer_usage["user_name"], remaining

async def cmd_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_use, name, remaining = is_in_use()
    if not in_use:
        clear_usage()
        await update.message.reply_text("🟢 Printer is available right now.")
    else:
        total_secs = int(remaining.total_seconds())
        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        finish = datetime.fromisoformat(printer_usage["finish_time"])
        await update.message.reply_text(
            f"🔴 Printer is currently in use by *{name}*.\n"
            f"Expected free in about {hrs}h {mins}m (at {finish.isoformat()} UTC).",
            parse_mode="Markdown"
        )

async def cmd_use_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    in_use, _, _ = is_in_use()
    if in_use:
        await update.message.reply_text("⚠️ Printer is already in use. Try /current.")
        return ConversationHandler.END
    await update.message.reply_text("What is your name?")
    return STATE_WAITING_NAME

async def received_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    context.user_data["printer_name"] = name
    await update.message.reply_text("How many hours (e.g. 1, 1.5)?")
    return STATE_WAITING_DURATION

async def received_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    try:
        hours = float(txt)
        if hours <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("Please send a positive number (e.g. 1.5).")
        return STATE_WAITING_DURATION

    name = context.user_data.get("printer_name")
    if not name:
        await update.message.reply_text("Internal error; please /use_now again.")
        return ConversationHandler.END

    now = datetime.utcnow()
    finish = now + timedelta(hours=hours)

    printer_usage["user_name"] = name
    printer_usage["start_time"] = now.isoformat()
    printer_usage["finish_time"] = finish.isoformat()
    printer_usage["chat_id"] = update.effective_chat.id
    save_state()

    delay = (finish - now).total_seconds()
    context.job_queue.run_once(notify_finished, delay, chat_id=update.effective_chat.id)

    await update.message.reply_text(
        f"✅ Noted: *{name}* using printer for ~{hours:.2f}h. I'll notify you at {finish.isoformat()} UTC.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def notify_finished(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    name = printer_usage.get("user_name")

    clear_usage()

    if name:
        await context.bot.send_message(chat_id=chat_id, text=f"✅ Hey *{name}*, your printer time is up. Printer is now free.", parse_mode="Markdown")

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

def create_app():
    load_state()

    telegram_token = os.environ.get("TELEGRAM_TOKEN")
    if not telegram_token:
        raise RuntimeError("TELEGRAM_TOKEN environment variable is not set")

    app = Flask(__name__)
    application = ApplicationBuilder().token(telegram_token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("use_now", cmd_use_now)],
        states={
            STATE_WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_name)],
            STATE_WAITING_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_duration)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )
    application.add_handler(conv)
    application.add_handler(CommandHandler("current", cmd_current))

    @app.route("/", methods=["GET"])
    def health():
        return "OK", 200

    @app.route("/webhook", methods=["POST"])
    def webhook_receiver():
        payload = request.get_json()
        update = Update.de_json(payload, application.bot)
        # Use create_task so as not to block
        application.create_task(application.process_update(update))
        return Response("ok", status=200)

    # Save both objects for external use if needed
    app.telegram_app = application
    return app

if __name__ == "__main__":
    app = create_app()
    # For production, use gunicorn or similar
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
