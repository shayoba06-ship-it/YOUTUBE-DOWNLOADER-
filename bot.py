# bot.py
import os
import aiohttp
import asyncio
import tempfile
import shutil
import logging
import urllib.parse
from aiohttp import ClientTimeout
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from flask import Flask
from threading import Thread

# ---------------- CONFIG ----------------
BOT_TOKEN = "8282905908:AAFCqaLfBYqQNgPpIHUAy816kjQ4KzVThNI"
API_KEY_RAW = "anshapi=WT6WGGGHJW7WT53YYHWHHWH"  # full param as given
CHANNEL = "@backuphaiyaarh"
PORT = 8080
MAX_TELEGRAM_BYTES = 50*1024*1024  # 50 MB
# ----------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ytbot")

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ---------------- Keep-alive Flask ----------------
app = Flask("keepalive")
@app.route("/")
def home():
    return "Bot is alive!"
Thread(target=lambda: app.run(host="0.0.0.0", port=PORT), daemon=True).start()

# ---------------- Helpers ----------------
async def is_member(user_id):
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return m.status in ["member","administrator","creator"]
    except:
        return False

async def get_head_size(session, url):
    try:
        async with session.head(url, timeout=ClientTimeout(total=30)) as r:
            size = r.headers.get("Content-Length")
            return int(size) if size and size.isdigit() else None
    except:
        return None

async def download_file(session, url, path):
    async with session.get(url, timeout=ClientTimeout(total=600)) as r:
        r.raise_for_status()
        with open(path,"wb") as f:
            async for chunk in r.content.iter_chunked(1024*64):
                f.write(chunk)

# ---------------- Handlers ----------------
@dp.message(Command(commands=["start","help"]))
async def start(message: types.Message):
    await message.reply(f"Hi! Mujhe YouTube link bhejo aur mai download kar ke dunga.\n⚠️ Pehle {CHANNEL} join karna hoga!")

@dp.message()
async def handle_msg(message: types.Message):
    text = (message.text or "").strip()
    if not text:
        await message.reply("Koi URL bhejo pehle.")
        return

    if not await is_member(message.from_user.id):
        await message.reply(f"⚠️ Pehle {CHANNEL} join karo!\nJoin link: https://t.me/{CHANNEL.lstrip('@')}")
        return

    if "youtube.com/watch" not in text and "youtu.be/" not in text:
        await message.reply("Valid YouTube URL bhejo.")
        return

    await message.reply("Processing...")

    api_url = f"https://ytdownloder.anshapi.workers.dev/ytdown/v1?{API_KEY_RAW}&url={urllib.parse.quote(text)}"
    logger.info(f"Calling API: {api_url}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                body = await resp.text()
                if resp.status != 200:
                    await message.reply(f"API error: HTTP {resp.status}\nPreview:\n{body[:500]}")
                    return
                try:
                    data = await resp.json()
                except:
                    await message.reply(f"API returned non-JSON response. Preview:\n{body[:800]}")
                    return

            # get download URL
            file_url = data.get("download") or data.get("url") or data.get("link")
            if not file_url:
                await message.reply("Download link nahi mila. Response preview:\n"+str(data)[:800])
                return

            size = await get_head_size(session, file_url)
            if size and size>MAX_TELEGRAM_BYTES:
                await message.reply("File bahut badi hai. Direct link:\n"+file_url)
                return

            tmp_dir = tempfile.mkdtemp()
            tmp_file = tmp_dir+"/video.mp4"
            await message.reply("File download kar raha hoon...")
            await download_file(session,file_url,tmp_file)

            with open(tmp_file,"rb") as f:
                await bot.send_document(chat_id=message.chat.id, document=f, caption="Yeh lo — downloaded video")
            await message.reply("Done ✅")

            shutil.rmtree(tmp_dir)
    except Exception as e:
        await message.reply(f"Kuch error hua: {e}")
        logger.exception("Error")

# ---------------- Run ----------------
if __name__=="__main__":
    from aiogram import Runner
    runner = Runner(dispatcher=dp, bot=bot)
    try:
        asyncio.run(runner.start_polling())
    except (KeyboardInterrupt,SystemExit):
        print("Bot stopped")
