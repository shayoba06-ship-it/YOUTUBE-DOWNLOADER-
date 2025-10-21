import os
import asyncio
import aiohttp
import logging
import tempfile
import shutil
import urllib.parse
from aiohttp import ClientTimeout
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

# --- Load environment variables ---
load_dotenv()
BOT_TOKEN = os.environ.get("BOT_TOKEN")
API_KEY = os.environ.get("API_KEY")  # Just the key, no extra symbols
PORT = int(os.environ.get("PORT", "8080"))

if not BOT_TOKEN or not API_KEY:
    raise RuntimeError("Please set BOT_TOKEN and API_KEY environment variables correctly")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# Force join channel
CHANNEL = "@backuphaiyaarh"

async def is_member(chat_id: int, user_id: int, channel_username: str, bot):
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ["creator", "administrator", "member"]
    except Exception:
        return False

# Flask keep-alive
app = Flask("keepalive")
@app.route("/")
def home():
    return "Bot is alive!"
Thread(target=lambda: app.run(host="0.0.0.0", port=PORT), daemon=True).start()

# Helper functions
async def head_url(session, url):
    try:
        async with session.head(url, timeout=ClientTimeout(total=30)) as r:
            size = r.headers.get("Content-Length")
            return int(size) if size and size.isdigit() else None
    except Exception:
        return None

async def stream_download(session, url, dest_path):
    async with session.get(url, timeout=ClientTimeout(total=600)) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            async for chunk in r.content.iter_chunked(1024*64):
                f.write(chunk)

# Command handlers
@dp.message(Command(commands=["start", "help"]))
async def cmd_start(message: Message):
    await message.reply(
        f"Hi! Mujhe YouTube link bhejo aur mai video download kar ke dunga.\n\n"
        f"⚠️ Pehle aapko {CHANNEL} join karna hoga!\n"
        "Agar file bahut badi hui toh mai direct download link bhej dunga."
    )

@dp.message()
async def handle_message(message: Message):
    text = (message.text or "").strip()
    if not text:
        await message.reply("Koi URL bhejo pehle.")
        return

    # Force join check
    if not await is_member(message.chat.id, message.from_user.id, CHANNEL, bot):
        await message.reply(f"⚠️ Pehle {CHANNEL} join karo tabhi video download kar paoge!\nJoin link: https://t.me/backuphaiyaarh")
        return

    if "youtube.com/watch" not in text and "youtu.be/" not in text:
        await message.reply("Ye YouTube link nahi lag raha. Ek valid YouTube URL bhejo.")
        return

    await message.reply("Link mila — processing kar raha hoon... thoda intezar karo.")

    # Build API request with correct API key
    api_url = f"https://ytdownloder.anshapi.workers.dev/ytdown/v1?key={API_KEY}&url={urllib.parse.quote(text)}"
    logger.info(f"Calling downloader API: {api_url}")

    try:
        timeout = ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url) as resp:
                if resp.status != 200:
                    text_body = await resp.text()
                    await message.reply(f"API error: HTTP {resp.status}\nResponse: {text_body[:500]}")
                    return
                try:
                    data = await resp.json()
                except Exception:
                    text_body = await resp.text()
                    await message.reply(f"API returned non-JSON. Preview:\n{text_body[:800]}")
                    return

            # Extract download URL
            file_url = None
            for key in ("download", "url", "link", "file", "video_url", "download_url"):
                if key in data and data[key]:
                    file_url = data[key]
                    break

            if not file_url and isinstance(data.get("formats"), list):
                formats = data["formats"]
                formats_sorted = sorted(formats, key=lambda f: int(f.get("filesize", 0) or 0), reverse=True)
                for f in formats_sorted:
                    candidate = f.get("url") or f.get("download")
                    if candidate:
                        file_url = candidate
                        break

            if not file_url:
                await message.reply("API response me download link nahi mila. Response (short):\n" + str(data)[:800])
                return

            await message.reply("Download link mil gaya. File size check kar raha hoon...")
            size = await head_url(session, file_url)
            MAX_TELEGRAM_BYTES = 50 * 1024 * 1024  # 50MB approx
            if size is not None and size > MAX_TELEGRAM_BYTES:
                await message.reply(
                    "Ye file Telegram ke liye bahut badi hai. Direct download link: " + file_url
                )
                return

            tmp_dir = tempfile.mkdtemp(prefix="tgvid_")
            tmp_path = os.path.join(tmp_dir, "video.mp4")
            try:
                await message.reply("File download kar raha hoon... (phir bhej dunga)")
                await stream_download(session, file_url, tmp_path)
                with open(tmp_path, "rb") as f:
                    await bot.send_document(chat_id=message.chat.id, document=f, caption="Yeh lo — downloaded video")
                await message.reply("File bhej di gayi ✅")
            finally:
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

    except Exception as e:
        logger.exception("Error processing download")
        await message.reply(f"Kuch error hua: {e}")

# Run bot
if __name__ == "__main__":
    import asyncio
    from aiogram import Runner
    runner = Runner(dispatcher=dp, bot=bot)
    try:
        asyncio.run(runner.start_polling())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")
