import os
from pyrogram import Client, filters
from pyrogram.types import Message
from yt_dlp import YoutubeDL

# 🔐 Bot Token
BOT_TOKEN = "7735683292:AAGVbm3MrB7vLD9Qf5yQcxj2uYULCwNqk-0"  # ← Replace this

# ✅ Create download folder
os.makedirs("downloads", exist_ok=True)

# 🎥 YouTube downloader function
def download_video(url: str, cookies_path: str = "cookies.txt") -> str:
    output_path = "downloads/%(title)s.%(ext)s"
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    ydl_opts = {
        "outtmpl": output_path,
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "cookies": cookies_path if os.path.exists(cookies_path) else None,
        "quiet": True,
        "noplaylist": True,
        "http_headers": {"User-Agent": user_agent},
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace(".webm", ".mp4")
        return filename

# 🤖 Telegram bot instance
app = Client("yt_downloader_bot", bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text(
        "**👋 Welcome to YouTube Downloader Bot!**\n\n"
        "📥 Send a YouTube link to download the video.\n"
        "📤 To enable age-restricted/private download, send your `cookies.txt` with caption `/uploadcookies`."
    )

@app.on_message(filters.document & filters.caption.regex("^/uploadcookies$"))
async def upload_cookies(client, message: Message):
    if message.document.file_name != "cookies.txt":
        await message.reply_text("❌ Please upload a file named `cookies.txt`.")
        return
    await message.download(file_name="cookies.txt")
    await message.reply_text("✅ `cookies.txt` uploaded and saved!")

@app.on_message(filters.text & ~filters.command(["start"]))
async def handle_download(client, message: Message):
    url = message.text.strip()
    if "youtube.com" not in url and "youtu.be" not in url:
        await message.reply_text("❌ Invalid YouTube URL.")
        return

    status = await message.reply_text("⏬ Downloading... Please wait.")
    try:
        file_path = download_video(url)
        await status.edit_text("📤 Uploading to Telegram...")
        await message.reply_video(file_path, caption="✅ Downloaded via @yt_downloader_bot")
        os.remove(file_path)
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ Failed: {e}")

# ▶️ Run bot
app.run()
