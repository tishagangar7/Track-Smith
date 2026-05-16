"""
Telegram Bot — interface between the producer and the agent.
Handles incoming commands and sends autonomous notifications.
"""

import asyncio
import os
import logging
import threading
from pathlib import Path

from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from agent.config import (
    TELEGRAM_TOKEN,
    TELEGRAM_CHAT_ID,
    WATCHED_FOLDER,
    OUTPUT_FOLDER,
)

logger = logging.getLogger(__name__)

# global bot instance and event loop used for autonomous notifications
_bot: Bot = None
_notify_loop: asyncio.AbstractEventLoop = None

# artist's preferred pipeline mode — overridden per-message by keyword detection
_default_mode: str = "full"

# ── Mode detection ────────────────────────────────────────────────────────────

_SUGGEST_KEYWORDS = {
    "suggest", "ideas", "what should", "help me",
    "thoughts", "what would", "recommend",
}
_FULL_KEYWORDS = {
    "full", "generate", "make it", "write it",
    "create", "produce", "all instruments", "everything",
}


def _detect_mode(text: str) -> str:
    """
    Infer pipeline mode from the artist's text.
    Suggest keywords win over full keywords when both match.
    Falls back to _default_mode if no keyword matches.
    """
    t = text.lower()
    if any(kw in t for kw in _SUGGEST_KEYWORDS):
        return "suggest"
    if any(kw in t for kw in _FULL_KEYWORDS):
        return "full"
    return _default_mode


# ── Autonomous notifications ──────────────────────────────────────────────────

def notify(message: str):
    """
    Send a text message from the agent to the producer.
    Safe to call from any sync thread.
    """
    global _bot, _notify_loop
    if not _bot or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram not configured. Message: {message}")
        return
    if _notify_loop is None or not _notify_loop.is_running():
        logger.warning(f"Notify loop not ready. Message: {message}")
        return
    try:
        future = asyncio.run_coroutine_threadsafe(
            _bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="Markdown",
            ),
            _notify_loop,
        )
        future.result(timeout=10)
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")


def notify_document(filepath: str, filename: str = None, caption: str = None):
    """
    Send a file as a document to the producer's chat.
    Safe to call from any sync thread. filename controls what the artist sees in Telegram.
    """
    global _bot, _notify_loop
    if not _bot or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram not configured. Document: {filepath}")
        return
    if _notify_loop is None or not _notify_loop.is_running():
        logger.warning(f"Notify loop not ready. Document: {filepath}")
        return
    try:
        async def _send():
            with open(filepath, "rb") as f:
                await _bot.send_document(
                    chat_id=TELEGRAM_CHAT_ID,
                    document=f,
                    filename=filename,
                    caption=caption,
                    parse_mode="Markdown" if caption else None,
                )

        future = asyncio.run_coroutine_threadsafe(_send(), _notify_loop)
        future.result(timeout=30)
    except Exception as e:
        logger.error(f"Telegram send_document failed: {e}")


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎛 *Aux is online.*\n\n"
        "Drop a `.mid` file into the watched folder and I'll handle it automatically.\n\n"
        "*Commands:*\n"
        "`/compose <vibe>` — compose original track from description\n"
        "`/mode full` — generate MIDI continuations (default)\n"
        "`/mode suggest` — get text ideas, no files\n"
        "`/dj on` — start autonomous DJ mode\n"
        "`/dj off` — stop DJ mode\n"
        "`/status` — agent status\n"
        "`/library` — list all tracks\n"
        "`/help` — show this message",
        parse_mode="Markdown"
    )


async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set or query the default pipeline mode."""
    global _default_mode
    arg = context.args[0].lower() if context.args else None

    if arg == "full":
        _default_mode = "full"
        await update.message.reply_text(
            "🎛 Mode set to *full*\n\n"
            "Drop a MIDI → I'll generate continuations with drums and send the `.mid` files.",
            parse_mode="Markdown"
        )
    elif arg == "suggest":
        _default_mode = "suggest"
        await update.message.reply_text(
            "💡 Mode set to *suggest*\n\n"
            "Drop a MIDI → I'll think through where the track could go and tell you. No files.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"🎛 Current mode: *{_default_mode}*\n\n"
            f"`/mode full` — generate MIDI + drums\n"
            f"`/mode suggest` — text ideas only\n\n"
            f"You can also override per-message:\n"
            f"Say _\"suggest some ideas\"_ or _\"generate it\"_ and I'll pick up the intent.",
            parse_mode="Markdown"
        )


async def cmd_compose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Compose an original track from a vibe description."""
    vibe = " ".join(context.args).strip()

    if not vibe:
        await update.message.reply_text(
            "Give me a vibe to work with.\n\n"
            "Example:\n"
            "`/compose dark rainy 3am Tokyo lo-fi 85 BPM`",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"🎼 *Composing...*\n\n"
        f"Vibe: _{vibe}_\n\n"
        f"Nemotron is translating your sound...",
        parse_mode="Markdown"
    )

    def _run():
        try:
            from agent.skills.composer import compose_from_vibe
            results = compose_from_vibe(vibe, OUTPUT_FOLDER)

            if not results:
                notify("❌ Composition failed — no results returned.")
                return

            first = results[0]
            lines = [
                f"✅ *Composition complete*\n",
                f"🎵 Vibe: _{vibe}_",
                f"🎼 Key: {first.get('key', '?')}",
                f"🥁 Tempo: {first.get('tempo', '?')} BPM",
                f"🎸 Style: {first.get('production_style', '?')}",
                f"🎤 References: {', '.join(first.get('reference_artists', []))}",
                f"🎵 Chords: {' → '.join(first.get('chord_progression', []))}",
                "",
                "*3 Variations:*",
            ]

            for r in results:
                lines.append(
                    f"\n*Variation {r['variation']}* — {r.get('energy_direction', '').title()} energy\n"
                    f"  _{r.get('description', '')}_\n"
                    f"  File: `{r['filename']}`"
                )

            lines.append("\n📁 All files saved to `/output`")
            notify("\n".join(lines))

        except Exception as e:
            logger.error(f"Compose command failed: {e}")
            notify(f"❌ Composition error: {str(e)}")

    threading.Thread(target=_run, daemon=True).start()


async def cmd_dj(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle DJ mode on or off."""
    action = context.args[0].lower() if context.args else "status"

    if action == "on":
        os.environ["DJ_MODE"] = "true"
        await update.message.reply_text(
            "🎛 *DJ Mode: ON*\n\n"
            "Drop tracks into the watched folder.\n"
            "I'll build and run the set autonomously.",
            parse_mode="Markdown"
        )

    elif action == "off":
        os.environ["DJ_MODE"] = "false"
        await update.message.reply_text(
            "⏹ *DJ Mode: OFF*",
            parse_mode="Markdown"
        )

    else:
        dj_on = os.getenv("DJ_MODE", "false") == "true"
        await update.message.reply_text(
            f"🎛 DJ Mode is currently: *{'ON' if dj_on else 'OFF'}*",
            parse_mode="Markdown"
        )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current agent status."""
    watched = list(Path(WATCHED_FOLDER).glob("*.mid"))
    output = list(Path(OUTPUT_FOLDER).glob("*.mid"))
    dj_mode = os.getenv("DJ_MODE", "false") == "true"

    await update.message.reply_text(
        f"📊 *Agent Status*\n\n"
        f"🟢 Online\n"
        f"🎛 DJ Mode: {'ON' if dj_mode else 'OFF'}\n"
        f"🎚 Pipeline mode: *{_default_mode}*\n"
        f"📂 Watched folder: `{Path(WATCHED_FOLDER).resolve()}`\n"
        f"🎵 Tracks in watched: {len(watched)}\n"
        f"🎹 Files in output: {len(output)}\n"
        f"🔒 NemoClaw sandbox: active",
        parse_mode="Markdown"
    )


async def cmd_library(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all MIDI files in watched and output folders."""
    watched = list(Path(WATCHED_FOLDER).glob("*.mid"))
    output = list(Path(OUTPUT_FOLDER).glob("*.mid"))

    lines = ["📚 *Track Library*\n"]

    if watched:
        lines.append("*📂 Watched:*")
        for f in watched:
            lines.append(f"  • `{f.name}`")
    else:
        lines.append("*📂 Watched:* empty — drop `.mid` files here")

    lines.append("")

    if output:
        lines.append("*🎹 Generated:*")
        for f in output:
            lines.append(f"  • `{f.name}`")
    else:
        lines.append("*🎹 Generated:* none yet")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Plain text messages try to pair with a recently dropped MIDI.
    Mode is detected from the text before the pipeline fires.
    """
    # lazy imports — avoids circular dependency (watcher imports bot, bot imports watcher)
    from agent.pairing import consume_latest, peek_latest, reset_timer
    from agent.watcher import get_handler

    text = update.message.text.strip()

    # Debounce: any artist message resets the fallback timer so it doesn't fire mid-thought
    pending_fp = peek_latest()
    if pending_fp:
        reset_timer(pending_fp)

    filepath = consume_latest()

    if filepath:
        mode = _detect_mode(text)
        filename = Path(filepath).name
        working_msg = "Generating MIDI continuations..." if mode == "full" else "Thinking up ideas..."

        await update.message.reply_text(
            f"🔗 *Paired* `{filename}` with:\n_{text}_\n\n{working_msg}",
            parse_mode="Markdown"
        )

        handler = get_handler()
        if handler:
            handler.run_pipeline(filepath, prompt=text, mode=mode)
        else:
            logger.error("Pairing succeeded but handler not available — pipeline skipped")
    else:
        await update.message.reply_text(
            f"💬 No MIDI waiting right now.\n\n"
            f"Drop a `.mid` file into the watched folder, then send your vibe within 60s.\n\n"
            f"Or: `/compose {text}`",
            parse_mode="Markdown"
        )


# ── Bot startup ───────────────────────────────────────────────────────────────

def start_bot():
    """Start the Telegram bot. Blocks until stopped."""
    global _bot, _notify_loop

    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set — bot disabled")
        return

    _bot = Bot(token=TELEGRAM_TOKEN)

    # Dedicated event loop for async notifications from sync threads.
    # PTB's app.run_polling() creates its own internal loop; this is separate.
    _notify_loop = asyncio.new_event_loop()
    threading.Thread(target=_notify_loop.run_forever, daemon=True, name="notify-loop").start()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("mode",    cmd_mode))
    app.add_handler(CommandHandler("compose", cmd_compose))
    app.add_handler(CommandHandler("dj",      cmd_dj))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("library", cmd_library))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Telegram bot polling...")
    app.run_polling()
