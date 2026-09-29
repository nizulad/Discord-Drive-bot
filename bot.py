import os
import re
import base64
import asyncio
import requests
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
from pypdf import PdfReader
import io

# ---------------- CONFIG ----------------
DISCORD_TOKEN = os.getenv("DT")
GAS_WEBAPP_URL = os.getenv("GAS_WEBAPP_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
HISTORY_SCAN_LIMIT = 500  # how many messages to look back when doc_count is set

# ---------------- FLASK ----------------
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# ---------------- DISCORD ----------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot successfully connected as {bot.user}")

# ---------------- GROQ FUNCTION ----------------
def ask_groq(prompt, model="llama-3.3-70b-versatile"):
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    r = requests.post(url, headers=headers, json=data, timeout=60)

    if r.status_code != 200:
        raise Exception(r.text)

    return r.json()["choices"][0]["message"]["content"]

# extract text from pdf
def extract_pdf_text(file_bytes, max_pages=3):
    reader = PdfReader(io.BytesIO(file_bytes))

    total_pages = len(reader.pages)

    text_parts = []

    # First pages
    for i in range(min(max_pages, total_pages)):
        page_text = reader.pages[i].extract_text()
        if page_text:
            text_parts.append(page_text)

    # Last pages
    for i in range(max(total_pages - max_pages, 0), total_pages):
        page_text = reader.pages[i].extract_text()
        if page_text:
            text_parts.append(page_text)

    return "\n".join(text_parts)

# ---------------- PDF ANALYSIS ----------------
def analyze_pdf_with_llm(file_bytes, original_filename):
    try:
        text = extract_pdf_text(file_bytes, max_pages=3)

        prompt = f"""
You are an academic document classifier.

You will receive extracted text from a PDF (first and last pages).

Your job:
- Identify professor name
- Identify document type:
  - COURSE (cours, td, tp, lecture, chapter)
  - EXAM (exam, test, controle, rattrapage)

OUTPUT RULES:
- If COURSE:
  Format: Professor Name | Chapter Name.pdf
- If EXAM:
  Format: Professor Name | Year.pdf

STRICT RULES:
- Return ONLY filename
- No explanations
- No markdown
- Always end with .pdf

EXTRACTED PDF TEXT:
{text}
"""

        result = ask_groq(prompt)

        cleaned = result.strip().replace("`", "").replace('"', "").replace("'", "")

        if not cleaned.endswith(".pdf"):
            cleaned += ".pdf"

        return cleaned

    except Exception as e:
        print("PDF Groq error:", e)
        return original_filename

# ---------------- HELPERS ----------------
def get_extension(filename):
    return os.path.splitext(filename.lower())[1]

def is_supported(attachment):
    ext = get_extension(attachment.filename)
    return ext == ".pdf" or ext in IMAGE_EXTENSIONS

def upload_to_drive(file_name, file_bytes, mime_type):
    payload = {
        "fileName": file_name,
        "fileData": base64.b64encode(file_bytes).decode("utf-8"),
        "mimeType": mime_type,
    }
    response = requests.post(GAS_WEBAPP_URL, json=payload, timeout=60)
    return response.json()

# ---------------- CHAT FEATURE ----------------
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    match = re.search(r'!(.+?)!', message.content)
    if match:
        question = match.group(1).strip()
        try:
            reply = ask_groq(question)
            await message.reply(reply)
        except Exception as e:
            await message.reply(f"Error: {str(e)}")
        return

    await bot.process_commands(message)

# ---------------- CORE FETCH LOGIC ----------------
async def run_fetch(ctx, target_channel_id: int, doc_count: int, rename: bool):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.author.send("Error: Use this command in DM only.")
        return

    if doc_count == 0 or doc_count < -1:
        await ctx.send("Count must be a positive number, or -1 for everything.")
        return

    target_channel = bot.get_channel(target_channel_id)
    if not target_channel:
        try:
            target_channel = await bot.fetch_channel(target_channel_id)
        except Exception:
            await ctx.send("Could not access channel.")
            return

    fetch_all = doc_count == -1
    scan_limit = None if fetch_all else HISTORY_SCAN_LIMIT

    await ctx.send(f"Scanning #{target_channel.name}...")

    # History is newest -> oldest, so we collect the most recent files first
    queue = []
    async for message in target_channel.history(limit=scan_limit):
        for attachment in message.attachments:
            if is_supported(attachment):
                queue.append(attachment)
                if not fetch_all and len(queue) >= doc_count:
                    break
        if not fetch_all and len(queue) >= doc_count:
            break  # stop scanning entirely, not just the inner loop

    # Upload oldest -> newest so Drive order matches channel order
    queue.reverse()

    mode = "with AI rename" if rename else "no rename"
    await ctx.send(f"Found {len(queue)} file(s) ({mode}). Processing...")

    loop = asyncio.get_running_loop()
    success = 0

    for attachment in queue:
        try:
            file_bytes = await attachment.read()
            original_name = attachment.filename
            ext = get_extension(original_name)
            mime_type = MIME_TYPES.get(ext, "application/octet-stream")
            final_name = original_name

            # AI rename: PDFs only, and only for /fetch2
            if rename and ext == ".pdf":
                await ctx.send(f"Analyzing `{original_name}`...")
                final_name = await loop.run_in_executor(
                    None, analyze_pdf_with_llm, file_bytes, original_name
                )
                await ctx.send(f"Renamed → `{final_name}`")
            else:
                await ctx.send(f"Uploading `{original_name}`...")

            result = await loop.run_in_executor(
                None, upload_to_drive, final_name, file_bytes, mime_type
            )

            if result.get("status") == "success":
                success += 1
                await ctx.send(f"Uploaded {success}/{len(queue)}")
            else:
                await ctx.send(f"Upload failed: {result.get('message')}")

            await asyncio.sleep(1.5)

        except Exception as e:
            await ctx.send(f"Error: {str(e)}")

    await ctx.send(f"Done. {success}/{len(queue)} uploaded.")

# ---------------- COMMANDS ----------------
# /fetch  <channel_id> [count]  -> download + reupload as-is (PDFs and images)
# /fetch2 <channel_id> [count]  -> same, but PDFs are renamed with Groq
# count defaults to 1 (latest file). Use -1 for everything.
@bot.command(name="fetch")
async def fetch_plain(ctx, target_channel_id: int, doc_count: int = 1):
    await run_fetch(ctx, target_channel_id, doc_count, rename=False)

@bot.command(name="fetch2")
async def fetch_renamed(ctx, target_channel_id: int, doc_count: int = 1):
    await run_fetch(ctx, target_channel_id, doc_count, rename=True)

# ---------------- START ----------------
Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
