import os
import asyncio
import logging
import aiofiles
import json
import time
import subprocess
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime

import yt_dlp
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, 
    InputMediaAnimation, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    CallbackQueryHandler, ContextTypes, filters
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import RetryAfter, TimedOut

# ================================
# CONFIGURATION
# ================================

class Config:
    # Bot Configuration
    BOT_TOKEN: str = "8037389280:AAG5WfzHcheszs-RHWL8WXszWPkrWjyulp8"  # Get from @BotFather
    
    # Admin Configuration
    ADMIN_IDS: list = [7910994767]  # Add your Telegram user IDs
    
    # Download Configuration
    DOWNLOAD_PATH: str = "downloads"
    TEMP_PATH: str = "temp"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB (Telegram limit)
    MAX_CONCURRENT_DOWNLOADS: int = 3
    
    # Cookies Configuration
    COOKIES_FILE: str = "cookies.txt"
    
    # FFmpeg Configuration
    FFMPEG_PATH: str = "ffmpeg"  # System PATH or direct path
    
    # User Agents for different scenarios
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
    ]
    
    @classmethod
    def get_ytdl_opts(cls, quality: str = "best", user_agent: str = None) -> dict:
        """Get yt-dlp options with various configurations"""
        opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': f'{cls.TEMP_PATH}/%(title)s_%(id)s.%(ext)s',
            'noplaylist': True,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'ignoreerrors': False,
            'no_warnings': False,
            'extractaudio': False,
            'user_agent': user_agent or cls.USER_AGENTS[0],
            'http_headers': {
                'User-Agent': user_agent or cls.USER_AGENTS[0],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        }
        
        # Add cookies if available
        if os.path.exists(cls.COOKIES_FILE):
            opts['cookiefile'] = cls.COOKIES_FILE
        
        # Quality-specific settings
        if quality == "best":
            opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
        elif quality == "medium":
            opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
        elif quality == "low":
            opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]'
        elif quality == "audio":
            opts['format'] = 'bestaudio/best'
            opts['extractaudio'] = True
        
        return opts

# Validate configuration
if not Config.BOT_TOKEN or Config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    raise ValueError("Please set your BOT_TOKEN in the script")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================================
# ANIMATIONS AND EFFECTS
# ================================

class AnimatedMessages:
    @staticmethod
    def get_loading_frames():
        """Get loading animation frames"""
        return [
            "🔍 Analyzing video.",
            "🔍 Analyzing video..",
            "🔍 Analyzing video...",
            "🔍 Analyzing video",
        ]
    
    @staticmethod
    def get_download_frames():
        """Get download progress frames"""
        return [
            "⬇️ Downloading video ▱▱▱▱▱",
            "⬇️ Downloading video █▱▱▱▱", 
            "⬇️ Downloading video ██▱▱▱",
            "⬇️ Downloading video ███▱▱",
            "⬇️ Downloading video ████▱",
            "⬇️ Downloading video █████",
        ]
    
    @staticmethod
    def get_processing_frames():
        """Get processing animation frames"""
        return [
            "🎬 Processing video 🔄",
            "🎬 Merging audio & video 🔄",
            "🎬 Optimizing quality 🔄",
            "🎬 Finalizing 🔄",
        ]
    
    @staticmethod
    def get_upload_frames():
        """Get upload animation frames"""
        return [
            "📤 Uploading ▱▱▱▱▱",
            "📤 Uploading █▱▱▱▱",
            "📤 Uploading ██▱▱▱", 
            "📤 Uploading ███▱▱",
            "📤 Uploading ████▱",
            "📤 Uploading █████",
        ]

# ================================
# UTILITY FUNCTIONS
# ================================

class Utils:
    @staticmethod
    def format_duration(seconds):
        """Format duration in seconds to readable format"""
        if not seconds:
            return "Unknown"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    @staticmethod
    def format_filesize(bytes_size):
        """Format file size in bytes to readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} TB"
    
    @staticmethod
    def sanitize_filename(filename):
        """Sanitize filename for cross-platform compatibility"""
        import re
        # Remove or replace problematic characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', filename)
        return filename[:200]  # Limit length

# ================================
# YOUTUBE DOWNLOADER CLASS
# ================================

class YouTubeDownloader:
    def __init__(self):
        self.download_path = Path(Config.DOWNLOAD_PATH)
        self.temp_path = Path(Config.TEMP_PATH)
        self.download_path.mkdir(exist_ok=True)
        self.temp_path.mkdir(exist_ok=True)
        
        # Statistics
        self.stats = {
            'total_downloads': 0,
            'successful_downloads': 0,
            'failed_downloads': 0,
            'total_size_downloaded': 0
        }
        
        # Load stats
        self.load_stats()
    
    def load_stats(self):
        """Load statistics from file"""
        stats_file = Path("bot_stats.json")
        if stats_file.exists():
            try:
                with open(stats_file, 'r') as f:
                    self.stats.update(json.load(f))
            except:
                pass
    
    def save_stats(self):
        """Save statistics to file"""
        try:
            with open("bot_stats.json", 'w') as f:
                json.dump(self.stats, f, indent=2)
        except:
            pass
    
    async def get_video_info(self, url: str, user_agent: str = None) -> Optional[Dict[str, Any]]:
        """Extract video information without downloading"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'user_agent': user_agent or Config.USER_AGENTS[0],
            }
            
            # Add cookies if available
            if os.path.exists(Config.COOKIES_FILE):
                ydl_opts['cookiefile'] = Config.COOKIES_FILE
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                return info
        except Exception as e:
            logger.error(f"Error extracting video info: {e}")
            # Try with different user agent
            if user_agent != Config.USER_AGENTS[-1]:
                next_ua = Config.USER_AGENTS[(Config.USER_AGENTS.index(user_agent or Config.USER_AGENTS[0]) + 1) % len(Config.USER_AGENTS)]
                return await self.get_video_info(url, next_ua)
            return None
    
    async def download_video(self, url: str, quality: str = "best", progress_callback=None) -> Optional[str]:
        """Download video with FFmpeg merging support"""
        try:
            self.stats['total_downloads'] += 1
            
            # Get video info first
            info = await self.get_video_info(url)
            if not info:
                self.stats['failed_downloads'] += 1
                self.save_stats()
                return None
            
            video_title = Utils.sanitize_filename(info.get('title', 'video'))
            video_id = info.get('id', 'unknown')
            
            # Configure download options
            ydl_opts = Config.get_ytdl_opts(quality)
            
            # Custom progress hook
            def progress_hook(d):
                if progress_callback and d['status'] == 'downloading':
                    percent = d.get('_percent_str', '0%')
                    speed = d.get('_speed_str', 'N/A')
                    asyncio.create_task(progress_callback(f"⬇️ {percent} | {speed}"))
            
            ydl_opts['progress_hooks'] = [progress_hook]
            
            downloaded_files = []
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download video
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ydl.download([url])
                )
                
                # Find downloaded files
                for file in self.temp_path.glob(f"*{video_id}*"):
                    downloaded_files.append(str(file))
            
            if not downloaded_files:
                self.stats['failed_downloads'] += 1
                self.save_stats()
                return None
            
            # Process files based on quality and format
            if quality == "audio":
                # For audio only, convert to MP3
                audio_file = downloaded_files[0]
                output_file = self.download_path / f"{video_title}.mp3"
                
                if progress_callback:
                    await progress_callback("🎵 Converting to MP3...")
                
                # Convert to MP3 using FFmpeg
                cmd = [
                    Config.FFMPEG_PATH, '-i', audio_file,
                    '-codec:a', 'libmp3lame', '-b:a', '192k',
                    '-y', str(output_file)
                ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                
                # Clean up temp files
                for file in downloaded_files:
                    try:
                        os.remove(file)
                    except:
                        pass
                
                if output_file.exists():
                    self.stats['successful_downloads'] += 1
                    self.stats['total_size_downloaded'] += output_file.stat().st_size
                    self.save_stats()
                    return str(output_file)
            
            else:
                # For video, merge audio and video if separate
                video_files = [f for f in downloaded_files if any(ext in f for ext in ['.mp4', '.webm', '.mkv'])]
                audio_files = [f for f in downloaded_files if any(ext in f for ext in ['.m4a', '.webm', '.opus'])]
                
                output_file = self.download_path / f"{video_title}.mp4"
                
                if len(downloaded_files) == 1:
                    # Single file, just move it
                    os.rename(downloaded_files[0], output_file)
                elif len(video_files) == 1 and len(audio_files) == 1:
                    # Separate video and audio, merge with FFmpeg
                    if progress_callback:
                        await progress_callback("🎬 Merging video and audio...")
                    
                    cmd = [
                        Config.FFMPEG_PATH,
                        '-i', video_files[0],
                        '-i', audio_files[0],
                        '-c:v', 'copy',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-y', str(output_file)
                    ]
                    
                    process = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    # Clean up temp files
                    for file in downloaded_files:
                        try:
                            os.remove(file)
                        except:
                            pass
                else:
                    # Fallback: use the largest file
                    largest_file = max(downloaded_files, key=lambda x: os.path.getsize(x))
                    os.rename(largest_file, output_file)
                    
                    # Clean up other files
                    for file in downloaded_files:
                        if file != largest_file:
                            try:
                                os.remove(file)
                            except:
                                pass
                
                if output_file.exists():
                    self.stats['successful_downloads'] += 1
                    self.stats['total_size_downloaded'] += output_file.stat().st_size
                    self.save_stats()
                    return str(output_file)
            
            self.stats['failed_downloads'] += 1
            self.save_stats()
            return None
            
        except Exception as e:
            logger.error(f"Error downloading video: {e}")
            self.stats['failed_downloads'] += 1
            self.save_stats()
            return None

# ================================
# TELEGRAM BOT CLASS
# ================================

class TelegramBot:
    def __init__(self):
        self.downloader = YouTubeDownloader()
        self.active_downloads = {}  # Track active downloads per user
        self.user_preferences = {}  # Store user preferences
        
        # Rate limiting
        self.user_last_request = {}
        self.rate_limit_seconds = 3
    
    async def animate_message(self, message, frames, delay=1.0):
        """Animate message with given frames"""
        for frame in frames:
            try:
                await message.edit_text(frame, parse_mode=ParseMode.MARKDOWN)
                await asyncio.sleep(delay)
            except (RetryAfter, TimedOut):
                await asyncio.sleep(2)
            except:
                break
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Send chat action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        welcome_text = f"""
🎬 **YouTube Downloader Pro** 🚀

Hello {user.first_name}! Welcome to the most advanced YouTube downloader bot.

✨ **Features:**
• 🔥 High-quality video downloads (up to 1080p)
• 🎵 Audio extraction (MP3, 192kbps)
• 🔗 FFmpeg merging for perfect quality
• 🍪 Cookies support for restricted content
• 🎭 Animated progress indicators
• 📊 Download statistics

**📱 Commands:**
/start - Show this message
/help - Detailed help guide
/quality - Set default quality
/stats - Your download statistics
/admin - Admin panel (Admins only)

**🎯 Quick Start:**
Just send me any YouTube URL and I'll handle the rest!

**Supported formats:** youtube.com, youtu.be, youtube shorts, and more!
        """
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        help_text = """
📖 **Detailed Help Guide**

**🔗 Supported URLs:**
• youtube.com/watch?v=...
• youtu.be/...
• youtube.com/shorts/...
• m.youtube.com/...
• music.youtube.com/...

**🎯 Quality Options:**
• **Best Quality**: 1080p video + high-quality audio
• **Medium Quality**: 720p video + good audio
• **Low Quality**: 480p video + standard audio  
• **Audio Only**: MP3 format, 192kbps

**⚡ Advanced Features:**
• **FFmpeg Merging**: Combines separate video/audio streams for best quality
• **Smart User Agents**: Bypasses restrictions automatically
• **Cookies Support**: Access age-restricted content
• **Progress Animations**: Real-time download progress
• **Error Recovery**: Automatic retry with different settings

**📊 File Limits:**
• Maximum size: 50MB (Telegram limitation)
• For larger files, try lower quality

**🛠️ Troubleshooting:**
• Video unavailable? Try again with different quality
• Age-restricted? Admin has cookies configured
• Still issues? Use /admin to contact support

**💡 Tips:**
• Use /quality to set your preferred default quality
• Check /stats to see your download history
• The bot automatically chooses best settings for each video
        """
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def create_quality_keyboard(self, user_id: int = None) -> InlineKeyboardMarkup:
        """Create inline keyboard for quality selection"""
        # Get user's preferred quality
        default_quality = self.user_preferences.get(user_id, {}).get('quality', 'best')
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"🔥 Best Quality {'✅' if default_quality == 'best' else ''}",
                    callback_data="quality_best"
                ),
                InlineKeyboardButton(
                    f"📱 Medium Quality {'✅' if default_quality == 'medium' else ''}",
                    callback_data="quality_medium"
                )
            ],
            [
                InlineKeyboardButton(
                    f"⚡ Low Quality {'✅' if default_quality == 'low' else ''}",
                    callback_data="quality_low"
                ),
                InlineKeyboardButton(
                    f"🎵 Audio Only {'✅' if default_quality == 'audio' else ''}",
                    callback_data="quality_audio"
                )
            ],
            [
                InlineKeyboardButton("ℹ️ Video Info", callback_data="show_info"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def quality_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /quality command to set user preferences"""
        user_id = update.effective_user.id
        
        keyboard = [
            [
                InlineKeyboardButton("🔥 Best Quality (Default)", callback_data="set_quality_best"),
                InlineKeyboardButton("📱 Medium Quality", callback_data="set_quality_medium")
            ],
            [
                InlineKeyboardButton("⚡ Low Quality", callback_data="set_quality_low"),
                InlineKeyboardButton("🎵 Audio Only", callback_data="set_quality_audio")
            ]
        ]
        
        current_quality = self.user_preferences.get(user_id, {}).get('quality', 'best')
        
        await update.message.reply_text(
            f"🎯 **Quality Preferences**\n\n"
            f"Current default: **{current_quality.title()}**\n\n"
            f"Choose your preferred default quality:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        user_id = update.effective_user.id
        
        # User stats (you can implement user-specific tracking)
        user_downloads = self.user_preferences.get(user_id, {}).get('downloads', 0)
        
        stats_text = f"""
📊 **Your Statistics**

**🎬 Downloads:** {user_downloads}
**🎯 Preferred Quality:** {self.user_preferences.get(user_id, {}).get('quality', 'best').title()}

**🤖 Bot Global Stats:**
• Total Downloads: {self.downloader.stats['total_downloads']}
• Successful: {self.downloader.stats['successful_downloads']}
• Failed: {self.downloader.stats['failed_downloads']}
• Success Rate: {(self.downloader.stats['successful_downloads']/max(1,self.downloader.stats['total_downloads'])*100):.1f}%
• Data Processed: {Utils.format_filesize(self.downloader.stats['total_size_downloaded'])}

**⚡ Active Downloads:** {len(self.active_downloads)}
        """
        
        await update.message.reply_text(
            stats_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /admin command"""
        if update.effective_user.id not in Config.ADMIN_IDS:
            await update.message.reply_text("❌ This command is only available for admins.")
            return
        
        # Get system stats
        download_path = Path(Config.DOWNLOAD_PATH)
        temp_path = Path(Config.TEMP_PATH)
        
        download_files = list(download_path.glob("*")) if download_path.exists() else []
        temp_files = list(temp_path.glob("*")) if temp_path.exists() else []
        
        download_size = sum(f.stat().st_size for f in download_files if f.is_file())
        temp_size = sum(f.stat().st_size for f in temp_files if f.is_file())
        
        # Check FFmpeg
        try:
            result = subprocess.run([Config.FFMPEG_PATH, '-version'], capture_output=True, text=True)
            ffmpeg_status = "✅ Available" if result.returncode == 0 else "❌ Error"
        except:
            ffmpeg_status = "❌ Not found"
        
        admin_text = f"""
🛠️ **Admin Panel**

**📁 Storage:**
• Download folder: {len(download_files)} files ({Utils.format_filesize(download_size)})
• Temp folder: {len(temp_files)} files ({Utils.format_filesize(temp_size)})

**🔧 System:**
• FFmpeg: {ffmpeg_status}
• Cookies: {'✅ Available' if os.path.exists(Config.COOKIES_FILE) else '❌ Not found'}
• Active Downloads: {len(self.active_downloads)}
• Max Concurrent: {Config.MAX_CONCURRENT_DOWNLOADS}

**👥 Users:**
• Total Users: {len(self.user_preferences)}
• Rate Limited Users: {len([u for u, t in self.user_last_request.items() if time.time() - t < self.rate_limit_seconds])}

**📊 Statistics:**
{json.dumps(self.downloader.stats, indent=2)}
        """
        
        keyboard = [
            [
                InlineKeyboardButton("🧹 Clear Downloads", callback_data="admin_clear_downloads"),
                InlineKeyboardButton("🗑️ Clear Temp", callback_data="admin_clear_temp")
            ],
            [
                InlineKeyboardButton("📊 Export Stats", callback_data="admin_export_stats"),
                InlineKeyboardButton("🔄 Restart Bot", callback_data="admin_restart")
            ]
        ]
        
        await update.message.reply_text(
            admin_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    def is_youtube_url(self, url: str) -> bool:
        """Check if URL is a valid YouTube URL"""
        youtube_patterns = [
            'youtube.com', 'youtu.be', 'www.youtube.com',
            'm.youtube.com', 'music.youtube.com'
        ]
        return any(pattern in url.lower() for pattern in youtube_patterns)
    
    def check_rate_limit(self, user_id: int) -> bool:
        """Check if user is rate limited"""
        now = time.time()
        last_request = self.user_last_request.get(user_id, 0)
        
        if now - last_request < self.rate_limit_seconds:
            return False
        
        self.user_last_request[user_id] = now
        return True
    
    async def handle_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle YouTube URL messages"""
        url = update.message.text.strip()
        user_id = update.effective_user.id
        
        # Rate limiting
        if not self.check_rate_limit(user_id):
            await update.message.reply_text(
                f"⏳ Please wait {self.rate_limit_seconds} seconds between requests."
            )
            return
        
        # Check if user already has an active download
        if user_id in self.active_downloads:
            await update.message.reply_text(
                "⏳ You already have an active download. Please wait for it to complete.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ Cancel Current Download", callback_data="cancel_download")
                ]])
            )
            return
        
        # Check concurrent download limit
        if len(self.active_downloads) >= Config.MAX_CONCURRENT_DOWNLOADS:
            await update.message.reply_text(
                f"🚫 Server busy! Maximum {Config.MAX_CONCURRENT_DOWNLOADS} concurrent downloads. "
                f"Please try again in a moment."
            )
            return
        
        # Validate YouTube URL
        if not self.is_youtube_url(url):
            await update.message.reply_text(
                "❌ **Invalid URL**\n\n"
                "Please send a valid YouTube URL.\n\n"
                "**Supported formats:**\n"
                "• youtube.com/watch?v=...\n"
                "• youtu.be/...\n"
                "• youtube.com/shorts/...\n"
                "• m.youtube.com/...",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Send chat action
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        
        # Show animated loading message
        loading_msg = await update.message.reply_text("🔍 Analyzing video...")
        
        # Animate loading
        asyncio.create_task(self.animate_message(
            loading_msg, 
            AnimatedMessages.get_loading_frames(),
            delay=0.8
        ))
        
        await asyncio.sleep(3)  # Let animation play
        
        # Get video information
        video_info = await self.downloader.get_video_info(url)
        
        if not video_info:
            await loading_msg.edit_text(
                "❌ **Failed to analyze video**\n\n"
                "Possible reasons:\n"
                "• Video is private or deleted\n"
                "• Geographic restrictions\n"
                "• Invalid URL\n\n"
                "Please check the URL and try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Store data for later use
        context.user_data['pending_url'] = url
        context.user_data['video_info'] = video_info
        
        # Extract video information
        title = video_info.get('title', 'Unknown Title')[:60]
        duration = video_info.get('duration', 0)
        uploader = video_info.get('uploader', 'Unknown')
        view_count = video_info.get('view_count', 0)
        upload_date = video_info.get('upload_date', '')
        
        # Format upload date
        if upload_date:
            try:
                upload_date = datetime.strptime(upload_date, '%Y%m%d').strftime('%B %d, %Y')
            except:
                upload_date = 'Unknown'
        
        # Show video info with quality options
        info_text = f"""
🎬 **Video Found!**

**📺 Title:** {title}{"..." if len(video_info.get('title', '')) > 60 else ""}
**⏱️ Duration:** {Utils.format_duration(duration)}
**👤 Channel:** {uploader}
**👀 Views:** {view_count:,} views
**📅 Upload Date:** {upload_date}

**Choose your preferred quality:**
        """
        
        await loading_msg.edit_text(
            info_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self.create_quality_keyboard(user_id)
        )
    
    async def handle_quality_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle quality selection and download process"""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        
        # Handle different callback types
        if query.data == "cancel":
            await query.edit_message_text("❌ **Download cancelled.**", parse_mode=ParseMode.MARKDOWN)
            context.user_data.clear()
            return
        
        elif query.data == "cancel_download":
            if user_id in self.active_downloads:
                self.active_downloads.pop(user_id, None)
                await query.edit_message_text("❌ **Download cancelled.**", parse_mode=ParseMode.MARKDOWN)
            else:
                await query.edit_message_text("ℹ️ **No active download to cancel.**", parse_mode=ParseMode.MARKDOWN)
            return
        
        elif query.data == "show_info":
            video_info = context.user_data.get('video_info')
            if not video_info:
                await query.edit_message_text("❌ **No video information available.**", parse_mode=ParseMode.MARKDOWN)
                return
            
            # Show detailed info
            formats = video_info.get('formats', [])
            video_formats = [f for f in formats if f.get('vcodec') != 'none']
            audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
            
            detail_text = f"""
📊 **Detailed Video Information**

**📺 Title:** {video_info.get('title', 'Unknown')}
**🆔 Video ID:** {video_info.get('id', 'Unknown')}
**⏱️ Duration:** {Utils.format_duration(video_info.get('duration', 0))}
**👤 Uploader:** {video_info.get('uploader', 'Unknown')}
**📝 Description:** {(video_info.get('description', 'No description')[:100] + '...') if video_info.get('description') else 'No description'}

**🎥 Available Video Qualities:**
{chr(10).join([f"• {f.get('height', 'Unknown')}p ({f.get('ext', 'Unknown')}) - {Utils.format_filesize(f.get('filesize', 0)) if f.get('filesize') else 'Unknown size'}" for f in video_formats[:5]])}

**🎵 Available Audio Qualities:**
{chr(10).join([f"• {f.get('abr', 'Unknown')}kbps ({f.get('ext', 'Unknown')})" for f in audio_formats[:3]])}
            """
            
            back_keyboard = [[InlineKeyboardButton("🔙 Back to Download", callback_data="back_to_download")]]
            
            await query.edit_message_text(
                detail_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(back_keyboard)
            )
            return
        
        elif query.data == "back_to_download":
            # Go back to quality selection
            video_info = context.user_data.get('video_info')
            if not video_info:
                await query.edit_message_text("❌ **Session expired. Please send the URL again.**", parse_mode=ParseMode.MARKDOWN)
                return
            
            title = video_info.get('title', 'Unknown Title')[:60]
            duration = video_info.get('duration', 0)
            
            info_text = f"""
🎬 **Video Ready for Download**

**📺 Title:** {title}
**⏱️ Duration:** {Utils.format_duration(duration)}

**Choose your preferred quality:**
            """
            
            await query.edit_message_text(
                info_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self.create_quality_keyboard(user_id)
            )
            return
        
        # Handle quality preference setting
        elif query.data.startswith("set_quality_"):
            quality = query.data.replace('set_quality_', '')
            
            if user_id not in self.user_preferences:
                self.user_preferences[user_id] = {}
            
            self.user_preferences[user_id]['quality'] = quality
            
            await query.edit_message_text(
                f"✅ **Default quality set to: {quality.title()}**\n\n"
                f"Future downloads will use this quality by default.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Handle admin commands
        elif query.data.startswith("admin_"):
            if user_id not in Config.ADMIN_IDS:
                await query.answer("❌ Admin access required!", show_alert=True)
                return
            
            action = query.data.replace('admin_', '')
            
            if action == "clear_downloads":
                try:
                    count = 0
                    for file in Path(Config.DOWNLOAD_PATH).glob("*"):
                        if file.is_file():
                            file.unlink()
                            count += 1
                    await query.edit_message_text(f"✅ **Cleared {count} files from downloads folder.**", parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    await query.edit_message_text(f"❌ **Error clearing downloads:** {str(e)}", parse_mode=ParseMode.MARKDOWN)
                return
            
            elif action == "clear_temp":
                try:
                    count = 0
                    for file in Path(Config.TEMP_PATH).glob("*"):
                        if file.is_file():
                            file.unlink()
                            count += 1
                    await query.edit_message_text(f"✅ **Cleared {count} files from temp folder.**", parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    await query.edit_message_text(f"❌ **Error clearing temp:** {str(e)}", parse_mode=ParseMode.MARKDOWN)
                return
            
            elif action == "export_stats":
                stats_json = json.dumps(self.downloader.stats, indent=2)
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=stats_json.encode(),
                    filename=f"bot_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    caption="📊 **Bot Statistics Export**"
                )
                return
            
            elif action == "restart":
                await query.edit_message_text("🔄 **Restarting bot...** (Feature not implemented in this demo)", parse_mode=ParseMode.MARKDOWN)
                return
        
        # Handle download quality selection
        elif query.data.startswith("quality_"):
            # Check if user has pending URL
            url = context.user_data.get('pending_url')
            if not url:
                await query.edit_message_text("❌ **No pending download found. Please send a new URL.**", parse_mode=ParseMode.MARKDOWN)
                return
            
            # Extract quality from callback data
            quality = query.data.replace('quality_', '')
            
            # Check if user already has active download
            if user_id in self.active_downloads:
                await query.answer("⏳ You already have an active download!", show_alert=True)
                return
            
            # Mark user as having active download
            self.active_downloads[user_id] = True
            
            # Update user download count
            if user_id not in self.user_preferences:
                self.user_preferences[user_id] = {}
            self.user_preferences[user_id]['downloads'] = self.user_preferences[user_id].get('downloads', 0) + 1
            
            # Quality display names
            quality_names = {
                'best': '🔥 Best Quality (1080p)',
                'medium': '📱 Medium Quality (720p)', 
                'low': '⚡ Low Quality (480p)',
                'audio': '🎵 Audio Only (MP3)'
            }
            
            # Start download process with animations
            progress_msg = await query.edit_message_text(
                f"🚀 **Starting Download**\n\n"
                f"**Quality:** {quality_names.get(quality, quality.title())}\n"
                f"**Status:** Initializing...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            try:
                # Progress callback for real-time updates
                async def progress_callback(status):
                    try:
                        await progress_msg.edit_text(
                            f"🚀 **Downloading Video**\n\n"
                            f"**Quality:** {quality_names.get(quality, quality.title())}\n"
                            f"**Status:** {status}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except:
                        pass
                
                # Start download with progress animation
                asyncio.create_task(self.animate_message(
                    progress_msg,
                    [f"🚀 **Downloading Video**\n\n**Quality:** {quality_names.get(quality, quality.title())}\n**Status:** {frame}" for frame in AnimatedMessages.get_download_frames()],
                    delay=1.0
                ))
                
                # Download the video
                file_path = await self.downloader.download_video(url, quality, progress_callback)
                
                if not file_path or not os.path.exists(file_path):
                    await progress_msg.edit_text(
                        "❌ **Download Failed**\n\n"
                        "The video might be:\n"
                        "• Unavailable or private\n"
                        "• Too large for the selected quality\n"
                        "• Geo-restricted\n\n"
                        "Try a different quality or check the URL.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    return
                
                # Check file size
                file_size = os.path.getsize(file_path)
                if file_size > Config.MAX_FILE_SIZE:
                    await progress_msg.edit_text(
                        f"❌ **File Too Large**\n\n"
                        f"**File size:** {Utils.format_filesize(file_size)}\n"
                        f"**Maximum allowed:** {Utils.format_filesize(Config.MAX_FILE_SIZE)}\n\n"
                        f"Please try downloading with **lower quality**.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    os.remove(file_path)  # Clean up
                    return
                
                # Upload process with animation
                await progress_msg.edit_text(
                    f"📤 **Uploading File**\n\n"
                    f"**Quality:** {quality_names.get(quality, quality.title())}\n"
                    f"**Size:** {Utils.format_filesize(file_size)}\n"
                    f"**Status:** Preparing upload...",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Animate upload process
                asyncio.create_task(self.animate_message(
                    progress_msg,
                    [f"📤 **Uploading File**\n\n**Quality:** {quality_names.get(quality, quality.title())}\n**Size:** {Utils.format_filesize(file_size)}\n**Status:** {frame}" for frame in AnimatedMessages.get_upload_frames()],
                    delay=0.8
                ))
                
                await asyncio.sleep(3)  # Let animation play
                
                # Send chat action
                if quality == "audio":
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_AUDIO)
                else:
                    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)
                
                # Upload file to Telegram
                async with aiofiles.open(file_path, 'rb') as file:
                    file_content = await file.read()
                    
                    caption = f"✅ **Download Complete!**\n\n📱 **Quality:** {quality_names.get(quality, quality.title())}\n📊 **Size:** {Utils.format_filesize(file_size)}"
                    
                    if quality == "audio":
                        await context.bot.send_audio(
                            chat_id=update.effective_chat.id,
                            audio=file_content,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN,
                            filename=os.path.basename(file_path)
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=update.effective_chat.id,
                            video=file_content,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN,
                            filename=os.path.basename(file_path)
                        )
                
                await progress_msg.edit_text(
                    f"🎉 **Upload Successful!**\n\n"
                    f"Your video has been processed and sent.\n\n"
                    f"Thanks for using YouTube Downloader Pro! 🚀",
                    parse_mode=ParseMode.MARKDOWN
                )
                
                # Clean up downloaded file
                try:
                    os.remove(file_path)
                except:
                    pass
                
            except Exception as e:
                logger.error(f"Error in download process: {e}")
                await progress_msg.edit_text(
                    f"❌ **Download Error**\n\n"
                    f"An unexpected error occurred:\n"
                    f"`{str(e)[:100]}...`\n\n"
                    f"Please try again or contact support.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
            finally:
                # Remove user from active downloads
                self.active_downloads.pop(user_id, None)
                context.user_data.clear()
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all text messages"""
        text = update.message.text
        
        # Check if it's a URL
        if self.is_youtube_url(text):
            await self.handle_url(update, context)
        else:
            await update.message.reply_text(
                "🤔 **I only understand YouTube URLs!**\n\n"
                "Please send me a YouTube link and I'll download it for you.\n\n"
                "**Example URLs:**\n"
                "• https://youtube.com/watch?v=...\n"
                "• https://youtu.be/...\n"
                "• https://youtube.com/shorts/...",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ **An error occurred**\n\n"
                "The bot encountered an unexpected error. Please try again.\n\n"
                "If the problem persists, contact the administrator.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    def run(self):
        """Run the bot"""
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("quality", self.quality_command))
        application.add_handler(CommandHandler("stats", self.stats_command))
        application.add_handler(CommandHandler("admin", self.admin_command))
        
        # Callback query handler for all buttons
        application.add_handler(CallbackQueryHandler(self.handle_quality_selection))
        
        # Message handlers
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        
        # Error handler
        application.add_error_handler(self.error_handler)
        
        print("🤖 YouTube Downloader Bot is starting...")
        print(f"📁 Download path: {Config.DOWNLOAD_PATH}")
        print(f"📁 Temp path: {Config.TEMP_PATH}")
        print(f"🔧 FFmpeg: {'✅' if self.check_ffmpeg() else '❌'}")
        print(f"🍪 Cookies: {'✅' if os.path.exists(Config.COOKIES_FILE) else '❌'}")
        print("🚀 Bot is ready! Send /start to begin.")
        
        # Run the bot
        application.run_polling()
    
    def check_ffmpeg(self):
        """Check if FFmpeg is available"""
        try:
            result = subprocess.run([Config.FFMPEG_PATH, '-version'], 
                                  capture_output=True, text=True, timeout=5)
            return result.returncode == 0
        except:
            return False

# ================================
# MAIN EXECUTION
# ================================

if __name__ == "__main__":
    # Create required directories
    Path(Config.DOWNLOAD_PATH).mkdir(exist_ok=True)
    Path(Config.TEMP_PATH).mkdir(exist_ok=True)
    
    # Initialize and run bot
    bot = TelegramBot()
    bot.run()

