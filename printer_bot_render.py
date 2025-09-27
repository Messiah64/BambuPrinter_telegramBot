import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from aiohttp import web
import logging

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states for /use_now command
NAME, DURATION = range(2)

# Global variable to store printer status
printer_status = {
    "in_use": False,
    "user_name": None,
    "start_time": None,
    "duration_hours": None,
    "chat_id": None
}

# Web server for health checks
async def health_check(request):
    return web.Response(text="OK", status=200)

async def home(request):
    return web.Response(text="Bot is running!", status=200)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Welcome to the 3D Printer Bot! 🖨️\n\n"
        "Available commands:\n"
        "/current - Check if the printer is available\n"
        "/use_now - Reserve the printer for use\n"
        "/cancel_use - Cancel your current reservation"
    )

async def current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check current printer status."""
    if not printer_status["in_use"]:
        await update.message.reply_text("✅ Printer is available right now!")
    else:
        # Calculate when printer will be available
        end_time = printer_status["start_time"] + timedelta(hours=printer_status["duration_hours"])
        remaining_time = end_time - datetime.now()
        
        if remaining_time.total_seconds() <= 0:
            # Time has elapsed, mark printer as available
            printer_status["in_use"] = False
            printer_status["user_name"] = None
            printer_status["start_time"] = None
            printer_status["duration_hours"] = None
            printer_status["chat_id"] = None
            await update.message.reply_text("✅ Printer is available right now!")
        else:
            hours_remaining = remaining_time.total_seconds() / 3600
            if hours_remaining >= 1:
                time_str = f"{hours_remaining:.1f} hours"
            else:
                minutes_remaining = remaining_time.total_seconds() / 60
                time_str = f"{minutes_remaining:.0f} minutes"
            
            await update.message.reply_text(
                f"🔴 Printer is currently in use\n"
                f"User: {printer_status['user_name']}\n"
                f"Available in approximately: {time_str}"
            )

async def use_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the reservation process."""
    if printer_status["in_use"]:
        # Check if time has elapsed
        end_time = printer_status["start_time"] + timedelta(hours=printer_status["duration_hours"])
        remaining_time = end_time - datetime.now()
        
        if remaining_time.total_seconds() <= 0:
            # Time has elapsed, allow new reservation
            printer_status["in_use"] = False
        else:
            hours_remaining = remaining_time.total_seconds() / 3600
            if hours_remaining >= 1:
                time_str = f"{hours_remaining:.1f} hours"
            else:
                minutes_remaining = remaining_time.total_seconds() / 60
                time_str = f"{minutes_remaining:.0f} minutes"
            
            await update.message.reply_text(
                f"❌ Printer is currently in use by {printer_status['user_name']}\n"
                f"It will be available in approximately {time_str}"
            )
            return ConversationHandler.END
    
    await update.message.reply_text(
        "Please enter your name:",
        reply_markup=ForceReply(selective=True)
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store the user's name and ask for duration."""
    context.user_data["name"] = update.message.text
    
    await update.message.reply_text(
        "How many hours will you be using the printer? (e.g., 2.5 for 2.5 hours)",
        reply_markup=ForceReply(selective=True)
    )
    return DURATION

async def get_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store the duration and set up the printer reservation."""
    try:
        duration = float(update.message.text)
        if duration <= 0 or duration > 24:
            await update.message.reply_text("Please enter a valid duration between 0 and 24 hours.")
            return DURATION
        
        # Set printer as in use
        printer_status["in_use"] = True
        printer_status["user_name"] = context.user_data["name"]
        printer_status["start_time"] = datetime.now()
        printer_status["duration_hours"] = duration
        printer_status["chat_id"] = update.effective_chat.id
        
        # Schedule notification
        context.job_queue.run_once(
            notify_completion,
            duration * 3600,  # Convert hours to seconds
            chat_id=update.effective_chat.id,
            name=f"printer_timer_{update.effective_chat.id}",
            data={
                "user_name": context.user_data["name"],
                "chat_id": update.effective_chat.id
            }
        )
        
        await update.message.reply_text(
            f"✅ Printer reserved!\n"
            f"User: {context.user_data['name']}\n"
            f"Duration: {duration} hours\n"
            f"Started at: {datetime.now().strftime('%H:%M')}\n\n"
            f"You'll be notified when your time is up!"
        )
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("Please enter a valid number (e.g., 2 or 2.5)")
        return DURATION

async def notify_completion(context: ContextTypes.DEFAULT_TYPE):
    """Notify the user when their printing time is complete."""
    job = context.job
    user_name = job.data["user_name"]
    chat_id = job.data["chat_id"]
    
    # Mark printer as available
    printer_status["in_use"] = False
    printer_status["user_name"] = None
    printer_status["start_time"] = None
    printer_status["duration_hours"] = None
    printer_status["chat_id"] = None
    
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ Hey {user_name}! Your printing time is up!\n"
             f"The printer is now available for others to use."
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

async def cancel_use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current printer reservation."""
    if not printer_status["in_use"]:
        await update.message.reply_text("The printer is not currently reserved.")
        return
    
    # Check if the user canceling is the one who reserved it
    if printer_status["chat_id"] != update.effective_chat.id:
        await update.message.reply_text(
            f"Only {printer_status['user_name']} can cancel their reservation.\n"
            f"If they're done, they should use /cancel_use from their chat."
        )
        return
    
    # Cancel the timer job
    current_jobs = context.job_queue.get_jobs_by_name(f"printer_timer_{update.effective_chat.id}")
    for job in current_jobs:
        job.schedule_removal()
    
    # Clear printer status
    user_name = printer_status["user_name"]
    printer_status["in_use"] = False
    printer_status["user_name"] = None
    printer_status["start_time"] = None
    printer_status["duration_hours"] = None
    printer_status["chat_id"] = None
    
    await update.message.reply_text(f"✅ {user_name}'s reservation has been cancelled. Printer is now available!")

async def main():
    """Start the bot."""
    # Get token from environment variable
    TOKEN = os.environ.get("BOT_TOKEN")
    
    if not TOKEN:
        logger.error("Error: BOT_TOKEN environment variable not set!")
        return
    
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("current", current))
    application.add_handler(CommandHandler("cancel_use", cancel_use))
    
    # Add conversation handler for /use_now command
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("use_now", use_now)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_duration)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # Initialize the bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Set up web server for health checks
    app = web.Application()
    app.router.add_get('/', home)
    app.router.add_get('/health', health_check)
    
    # Get port from environment
    port = int(os.environ.get("PORT", 10000))
    
    logger.info(f"Starting web server on port {port}")
    logger.info("Bot is running...")
    
    # Start web server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # Keep the bot running
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot is shutting down...")
    finally:
        await application.stop()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
