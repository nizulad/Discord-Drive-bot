import os
<<<<<<< HEAD
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

#extract text from pdf
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

# ---------------- FETCH COMMAND ----------------
@bot.command(name="fetch")
async def fetch_resources(ctx, target_channel_id: int, doc_count: int):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.author.send("Error: Use this command in DM only.")
        return

    target_channel = bot.get_channel(target_channel_id)
    if not target_channel:
        await ctx.send("Could not access channel.")
        return

    await ctx.send(f"Scanning #{target_channel.name}...")

    pdf_queue = []
    scan_limit = None if doc_count == -1 else 500

    async for message in target_channel.history(limit=scan_limit):
        for attachment in message.attachments:
            if attachment.filename.lower().endswith(".pdf"):
                pdf_queue.append(attachment)

                if doc_count != -1 and len(pdf_queue) >= doc_count:
                    break

    await ctx.send(f"Found {len(pdf_queue)} PDFs. Processing...")

    success = 0

    for attachment in pdf_queue:
        try:
            file_bytes = await attachment.read()
            original_name = attachment.filename

            await ctx.send(f"Analyzing `{original_name}`...")
            final_name = analyze_pdf_with_llm(file_bytes, original_name)

            await ctx.send(f"Renamed → `{final_name}`")

            base64_data = base64.b64encode(file_bytes).decode("utf-8")

            payload = {
                "fileName": final_name,
                "fileData": base64_data
            }

            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(GAS_WEBAPP_URL, json=payload, timeout=60)
            )

            result = response.json()

            if result.get("status") == "success":
                success += 1
                await ctx.send(f"Uploaded {success}/{len(pdf_queue)}")
            else:
                await ctx.send(f"Upload failed: {result.get('message')}")

            await asyncio.sleep(1.5)

        except Exception as e:
            await ctx.send(f"Error: {str(e)}")

    await ctx.send(f"Done. {success}/{len(pdf_queue)} uploaded.")

# ---------------- START ----------------
Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
=======
import asyncio
from datetime import datetime

import discord
import aiohttp
from PIL import Image

TRIGGER_PREFIX = "!scrape anoun 1.0!"
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
# Optional: restrict who can DM the bot this command. Leave unset to allow anyone
# who can reach the bot's DMs (only safe if you keep the bot private/unlisted).
OWNER_ID = os.environ.get("DISCORD_OWNER_ID", "")

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True

client = discord.Client(intents=intents)


def fmt_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


async def download_image(session: aiohttp.ClientSession, url: str, dest: str):
    async with session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.read()
        with open(dest, "wb") as f:
            f.write(data)
def load_as_rgb(path: str) -> Image.Image:
    """Open an image and flatten it to RGB so it can go into a PDF page."""
    im = Image.open(path)
    if im.mode != "RGB":
        im = im.convert("RGB")
    return im


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # Only respond in DMs with the bot
    if not isinstance(message.channel, discord.DMChannel):
        return

    content = message.content.strip()
    if not content.startswith(TRIGGER_PREFIX):
        return

    reply_channel = message.channel  # the DM — this is where results get sent

    if OWNER_ID and str(message.author.id) != OWNER_ID:
        await reply_channel.send("Not authorized to run this command.")
        return

    arg = content[len(TRIGGER_PREFIX):].strip()
    if not arg.isdigit():
        await reply_channel.send(
            f"Usage: `{TRIGGER_PREFIX} <channel_id>` — send me the ID of the channel to scrape."
        )
        return

    target_channel_id = int(arg)
    channel = client.get_channel(target_channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(target_channel_id)
        except discord.Forbidden:
            await reply_channel.send("I don't have access to that channel.")
            return
        except discord.NotFound:
            await reply_channel.send("No channel found with that ID.")
            return
        except Exception as e:
            await reply_channel.send(f"Couldn't fetch that channel: {e}")
            return

    status = await reply_channel.send(f"Scraping <#{channel.id}>, this may take a while…")

    work_dir = f"scrape_{channel.id}_{int(datetime.utcnow().timestamp())}"
    img_dir = os.path.join(work_dir, "images")
    os.makedirs(img_dir, exist_ok=True)

    text_lines = []
    image_entries = []  # (index, date_str, local_path)
    img_index = 0

    async with aiohttp.ClientSession() as session:
        async for msg in channel.history(limit=None, oldest_first=True):
            if msg.author.bot:
                continue

            date_str = fmt_date(msg.created_at)

            if msg.content and msg.content.strip():
                text_lines.append(f"[{date_str}] {msg.author.display_name}: {msg.content.strip()}")

            for att in msg.attachments:
                is_image = (att.content_type or "").startswith("image/") or \
                    att.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
                if not is_image:
                    continue
                img_index += 1
                ext = os.path.splitext(att.filename)[1] or ".png"
                local_path = os.path.join(img_dir, f"{img_index:04d}{ext}")
                try:
                    await download_image(session, att.url, local_path)
                    image_entries.append((img_index, date_str, local_path))
                except Exception as e:
                    print(f"Failed to download {att.url}: {e}")

    # messages.txt
    messages_path = os.path.join(work_dir, "messages.txt")
    with open(messages_path, "w", encoding="utf-8") as f:
        f.write("\n".join(text_lines))

    # images.txt (index -> date, matches page order in the PDF)
    images_txt_path = os.path.join(work_dir, "images.txt")
    with open(images_txt_path, "w", encoding="utf-8") as f:
        for idx, date_str, _ in image_entries:
            f.write(f"{idx}: {date_str}\n")

    # images.pdf (one image per page, scrollable, in send order)
    pdf_path = os.path.join(work_dir, "images.pdf")
    if image_entries:
        pages = [load_as_rgb(p) for _, _, p in image_entries]
        pages[0].save(pdf_path, "PDF", save_all=True, append_images=pages[1:])
        for p in pages:
            p.close()
    else:
        with open(pdf_path, "wb") as f:
            f.write(b"")

    await status.edit(content="Done. Sending files…")

    await reply_channel.send(file=discord.File(messages_path))
    await reply_channel.send(file=discord.File(pdf_path))
    await reply_channel.send(file=discord.File(images_txt_path))


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set the DISCORD_BOT_TOKEN environment variable before running.")
    client.run(TOKEN)
>>>>>>> af9e5ae (save local files)
