import os
import asyncio
import json
import base64
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
ANTHROPIC_AUTH_TOKEN = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "anthropic/claude-sonnet-4.6")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")


def log_entry(session_name: str, event: str, detail: str = ""):
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] [{session_name}] {event}"
    if detail:
        line += f": {detail}"
    with open(os.path.join(LOG_DIR, f"{today}.log"), "a") as f:
        f.write(line + "\n")

# sessions[user_id][name] = {"session_id": str | None, "cwd": str}
sessions: dict[int, dict[str, dict]] = {}
# active_session[user_id] = current session name
active_session: dict[int, str] = {}
active_tasks: dict[int, asyncio.Task] = {}


def load_state():
    if not os.path.exists(STATE_FILE):
        return
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        for uid_str, named_sessions in data.get("sessions", {}).items():
            sessions[int(uid_str)] = named_sessions
        for uid_str, name in data.get("active_session", {}).items():
            active_session[int(uid_str)] = name
    except Exception:
        pass


def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "sessions": {str(k): v for k, v in sessions.items()},
                "active_session": {str(k): v for k, v in active_session.items()},
            }, f, indent=2)
    except Exception:
        pass


def get_current_session(user_id: int) -> dict:
    """Return the active session data dict, creating default if needed."""
    name = active_session.setdefault(user_id, "default")
    user_sessions = sessions.setdefault(user_id, {})
    if name not in user_sessions:
        user_sessions[name] = {"session_id": None, "cwd": os.path.expanduser("~")}
    return user_sessions[name]


def session_file_path(session_id: str, cwd: str) -> str:
    """Return the .jsonl file path Claude Code uses for a session."""
    dir_name = os.path.expanduser(cwd).replace("/", "-")
    return os.path.expanduser(f"~/.claude/projects/{dir_name}/{session_id}.jsonl")


def delete_session_file(session_id: str | None, cwd: str):
    if not session_id:
        return
    path = session_file_path(session_id, cwd)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


async def send_long_message(update: Update, text: str):
    for i in range(0, len(text), 4096):
        await update.message.reply_text(text[i:i+4096])


async def call_claude(
    content: list,
    session_id: str | None,
    cwd: str,
    session_name: str = "default",
    on_tool_use=None,
) -> tuple[str, str | None]:
    cmd = [
        "claude",
        "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--allowedTools", "Bash,Read,Write,Edit,Glob,Grep",
        "--permission-mode", "bypassPermissions",
        "--name", session_name,
    ]
    if session_id:
        cmd.extend(["--resume", session_id])

    env = {**os.environ}
    if ANTHROPIC_AUTH_TOKEN:
        env["ANTHROPIC_AUTH_TOKEN"] = ANTHROPIC_AUTH_TOKEN
    if ANTHROPIC_BASE_URL:
        env["ANTHROPIC_BASE_URL"] = ANTHROPIC_BASE_URL
    if ANTHROPIC_MODEL:
        env["ANTHROPIC_MODEL"] = ANTHROPIC_MODEL
    if ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY
    elif not ANTHROPIC_AUTH_TOKEN:
        env["ANTHROPIC_API_KEY"] = ""
    env.pop("CLAUDECODE", None)

    stdin_msg = json.dumps({
        "type": "user",
        "message": {"role": "user", "content": content}
    }).encode() + b"\n"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=env,
        cwd=cwd,
    )

    proc.stdin.write(stdin_msg)
    proc.stdin.close()

    result = ""
    new_session_id = None

    async def read_lines():
        nonlocal result, new_session_id
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "system" and msg.get("subtype") == "init":
                    new_session_id = msg.get("session_id")
                elif msg.get("type") == "assistant" and on_tool_use:
                    for block in msg.get("message", {}).get("content", []):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            await on_tool_use(block.get("name", "unknown"), block.get("input", {}))
                elif msg.get("type") == "result":
                    result = msg.get("result", "")
            except json.JSONDecodeError:
                pass

    try:
        await asyncio.wait_for(read_lines(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "Error: timed out after 120s", None
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise

    await proc.wait()
    return result, new_session_id


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return

    if user_id in active_tasks and not active_tasks[user_id].done():
        await update.message.reply_text("Already processing. Please wait or /cancel.")
        return

    user_message = update.message.text
    status_msg = await update.message.reply_text("Thinking...")
    await _run_task(update, status_msg, user_id, [{"type": "text", "text": user_message}])


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    if user_id in active_tasks and not active_tasks[user_id].done():
        await update.message.reply_text("Already processing. Please wait or /cancel.")
        return

    status_msg = await update.message.reply_text("Downloading image...")
    try:
        photo = update.message.photo[-1]  # highest resolution
        tg_file = await context.bot.get_file(photo.file_id)
        data = await tg_file.download_as_bytearray()
        b64 = base64.standard_b64encode(bytes(data)).decode()
        caption = update.message.caption or "Please analyze this image."
        content = [
            {"type": "text", "text": caption},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
        ]
    except Exception as e:
        await status_msg.edit_text(f"Failed to download image: {e}")
        return

    await _run_task(update, status_msg, user_id, content)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        await update.message.reply_text("Unauthorized.")
        return
    if user_id in active_tasks and not active_tasks[user_id].done():
        await update.message.reply_text("Already processing. Please wait or /cancel.")
        return

    status_msg = await update.message.reply_text("Downloading file...")
    try:
        doc = update.message.document
        tg_file = await context.bot.get_file(doc.file_id)
        sess = get_current_session(user_id)
        save_path = os.path.join(sess["cwd"], doc.file_name)
        await tg_file.download_to_drive(save_path)
        caption = update.message.caption or ""
        text = f"User uploaded file: `{doc.file_name}` (saved to `{save_path}`)"
        if caption:
            text += f"\n{caption}"
        content = [{"type": "text", "text": text}]
    except Exception as e:
        await status_msg.edit_text(f"Failed to download file: {e}")
        return

    await _run_task(update, status_msg, user_id, content)


async def _run_task(update: Update, status_msg, user_id: int, content: list):
    sess = get_current_session(user_id)
    session_name = active_session.get(user_id, "default")

    # log user input
    text_blocks = [b["text"] for b in content if b.get("type") == "text"]
    has_image = any(b.get("type") == "image" for b in content)
    input_summary = " ".join(text_blocks)
    if has_image:
        input_summary += " [image]"
    log_entry(session_name, "USER", input_summary)

    async def on_tool_use(tool_name: str, tool_input: dict):
        if tool_name == "Bash":
            detail = tool_input.get("command", "")
        elif tool_name in ("Read", "Write", "Edit"):
            detail = tool_input.get("file_path", "")
        elif tool_name == "Glob":
            detail = tool_input.get("pattern", "")
        elif tool_name == "Grep":
            detail = tool_input.get("pattern", "")
        else:
            detail = ""
        log_entry(session_name, f"TOOL {tool_name}", detail)
        if len(detail) > 60:
            detail = detail[:57] + "..."
        text = f"{tool_name}: `{detail}`" if detail else f"Using {tool_name}..."
        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    task = asyncio.create_task(call_claude(
        content=content,
        session_id=sess["session_id"],
        cwd=sess["cwd"],
        session_name=session_name,
        on_tool_use=on_tool_use,
    ))
    active_tasks[user_id] = task

    try:
        result, new_session_id = await task
        if new_session_id:
            sess["session_id"] = new_session_id
            save_state()
        reply = result or "Done."
        log_entry(session_name, "RESULT", reply[:200] + ("..." if len(reply) > 200 else ""))
        if len(reply) <= 4096:
            await status_msg.edit_text(reply)
        else:
            await status_msg.delete()
            await send_long_message(update, reply)
    except asyncio.CancelledError:
        log_entry(session_name, "CANCELLED")
        await status_msg.edit_text("Cancelled.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        log_entry(session_name, "ERROR", f"{type(e).__name__}: {e}")
        try:
            await status_msg.edit_text(f"Error: {type(e).__name__}: {str(e)}")
        except Exception:
            await update.message.reply_text(f"Error: {type(e).__name__}: {str(e)}")
    finally:
        active_tasks.pop(user_id, None)


async def handle_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    user_sessions = sessions.get(user_id, {})
    if not user_sessions:
        await update.message.reply_text("No sessions saved.")
        return
    current = active_session.get(user_id, "default")
    lines = []
    for name, data in user_sessions.items():
        marker = "▶" if name == current else "  "
        sid = data.get("session_id")
        sid_short = sid[:8] if sid else "new"
        cwd = data.get("cwd", "~")
        lines.append(f"{marker} {name}  [{sid_short}]  {cwd}")
    await update.message.reply_text("Sessions:\n" + "\n".join(lines))


async def handle_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /session <name>")
        return
    name = context.args[0]
    user_sessions = sessions.setdefault(user_id, {})
    if name not in user_sessions:
        current_cwd = get_current_session(user_id)["cwd"]
        user_sessions[name] = {"session_id": None, "cwd": current_cwd}
        msg = f"Created new session: *{name}*"
    else:
        msg = f"Switched to session: *{name}*"
    active_session[user_id] = name
    save_state()
    cwd = user_sessions[name]["cwd"]
    await update.message.reply_text(f"{msg}\nDirectory: `{cwd}`", parse_mode="Markdown")


async def handle_session_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    if not context.args:
        await update.message.reply_text("Usage: /session\\_delete <name>", parse_mode="Markdown")
        return
    name = context.args[0]
    user_sessions = sessions.get(user_id, {})
    if name not in user_sessions:
        await update.message.reply_text(f"Session not found: {name}")
        return
    if active_session.get(user_id) == name:
        await update.message.reply_text("Cannot delete the active session. Switch to another session first.")
        return
    sess = user_sessions.pop(name)
    delete_session_file(sess.get("session_id"), sess.get("cwd", "~"))
    save_state()
    await update.message.reply_text(f"Deleted session: {name}")


async def handle_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    sess = get_current_session(user_id)
    delete_session_file(sess.get("session_id"), sess["cwd"])
    sess["session_id"] = None
    save_state()
    await update.message.reply_text("Session cleared.")


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    task = active_tasks.get(user_id)
    if task and not task.done():
        task.cancel()
    else:
        await update.message.reply_text("No active task.")


async def handle_setdir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ALLOWED_USER_ID:
        return
    sess = get_current_session(user_id)
    if not context.args:
        await update.message.reply_text(f"Current directory: `{sess['cwd']}`", parse_mode="Markdown")
        return
    path = os.path.expanduser(" ".join(context.args))
    if not os.path.isdir(path):
        await update.message.reply_text(f"Directory not found: `{path}`", parse_mode="Markdown")
        return
    sess["cwd"] = path
    save_state()
    await update.message.reply_text(f"Working directory set to: `{path}`", parse_mode="Markdown")


async def post_init(app):
    await app.bot.set_my_commands([
        ("sessions",       "List all sessions"),
        ("session",        "Switch or create a named session"),
        ("session_delete", "Delete a session"),
        ("clear",          "Clear current session history"),
        ("cancel",         "Cancel the running task"),
        ("setdir",         "Set working directory for current session"),
    ])


def main():
    load_state()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).concurrent_updates(True).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CommandHandler("sessions", handle_sessions))
    app.add_handler(CommandHandler("session", handle_session))
    app.add_handler(CommandHandler("session_delete", handle_session_delete))
    app.add_handler(CommandHandler("clear", handle_clear))
    app.add_handler(CommandHandler("cancel", handle_cancel))
    app.add_handler(CommandHandler("setdir", handle_setdir))
    print("Bot started. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
