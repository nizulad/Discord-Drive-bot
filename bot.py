import os
import re
import base64
import asyncio
import json
import requests
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands, tasks
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

# --- Sheet -> announcement feature (PFE project sheet) ---
SHEET_WEBAPP_URL = os.getenv("SHEET_WEBAPP_URL")  # URL of the NEW, separate Apps Script deployment
SHEET_ID = os.getenv("SHEET_ID", "1E6DVFetxlMStgiiCKFA5v8l8cW25_WoVJEYPgDph5WE")
SHEET_NAME = os.getenv("SHEET_NAME", "Form Responses 1")
ANNOUNCE_CHANNEL_ID = os.getenv("ANNOUNCE_CHANNEL_ID", "1399062753028608100")
SHEET_POLL_SECONDS = int(os.getenv("SHEET_POLL_SECONDS", "60"))
SHEET_STATE_FILE = "sheet_state.json"

PFE_ANALYSIS_PROMPT = (
    "these are the details of projet fin d'etude of a university professor "
    "give details about the project, propose critical and essential questions "
    "that must be asked to the professor about the project before proceeding to start"
)
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
    if not check_sheet.is_running():
        check_sheet.start()

# ---------------- GROQ FUNCTION ----------------
def ask_groq(prompt, model="openai/gpt-oss-120b"):
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

# ---------------- OPTION PARSING ----------------
# /fetch [ID] [option1] [option2]
#   option1 positive N  -> download the latest N files, no skip
#   option1 = "N"       -> download everything (until an error occurs)
#   option1 negative -N -> skip the first N files found, then use option2:
#       option2 positive M -> download M files after the skip
#       option2 = "N"      -> download everything after the skip (until an error occurs)
# Returns (skip: int, count: int|None). count=None means "unlimited, stop only on error".
def parse_fetch_options(option1: str, option2: str):
    o1 = option1.strip()

    if o1.upper() == "N":
        return 0, None

    try:
        v1 = int(o1)
    except ValueError:
        raise ValueError(f"`{option1}` isn't a valid number. Use a whole number, or `N`.")

    if v1 == 0:
        raise ValueError("The count can't be 0.")

    if v1 > 0:
        return 0, v1

    # v1 is negative -> it's a skip count, option2 says how many to download after
    skip = abs(v1)

    if option2 is None:
        raise ValueError(
            f"You asked to skip {skip}, but didn't say how many to download after. "
            f"Add a second number, e.g. `{option1} 5`, or `{option1} N` for everything."
        )

    o2 = option2.strip()

    if o2.upper() == "N":
        return skip, None

    try:
        v2 = int(o2)
    except ValueError:
        raise ValueError(f"`{option2}` isn't a valid number. Use a whole number, or `N`.")

    if v2 <= 0:
        raise ValueError("The second number (how many to download) must be positive, or `N`.")

    return skip, v2

# ---------------- SHEET -> ANNOUNCEMENT ----------------
def load_sheet_state():
    if os.path.exists(SHEET_STATE_FILE):
        try:
            with open(SHEET_STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_row_count": None}

def save_sheet_state(state):
    with open(SHEET_STATE_FILE, "w") as f:
        json.dump(state, f)

def fetch_sheet_rows():
    params = {"sheetId": SHEET_ID, "sheetName": SHEET_NAME}
    r = requests.get(SHEET_WEBAPP_URL, params=params, timeout=30)
    data = r.json()
    if data.get("status") != "success":
        raise Exception(data.get("message", "Unknown sheet error"))
    return data["rows"]

def build_project_prompt(row: dict) -> str:
    def g(*keys):
        for k in keys:
            v = row.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    supervisor = g("Nom et Prénom encadreur")
    co_supervisor = g("Nom et Prénom Co-encadreur")
    domain = g("Domaine")
    title = g("Titre du sujet")
    description = g("Description du sujet")
    plan = g("Plan du travail")

    details = f"Supervisor: {supervisor}\n"
    if co_supervisor:
        details += f"Co-supervisor: {co_supervisor}\n"
    details += f"Domain: {domain}\nTitle: {title}\n"
    if description:
        details += f"Description: {description}\n"
    if plan:
        details += f"Work plan: {plan}\n"

    return f"{PFE_ANALYSIS_PROMPT}\n\n{details}"

async def send_long_message(channel, text, prefix=""):
    if prefix:
        text = f"{prefix}\n\n{text}"
    chunk_size = 1900
    for i in range(0, len(text), chunk_size):
        await channel.send(text[i:i + chunk_size])

@tasks.loop(seconds=SHEET_POLL_SECONDS)
async def check_sheet():
    if not (SHEET_ID and ANNOUNCE_CHANNEL_ID and SHEET_WEBAPP_URL):
        return  # feature not configured, skip silently

    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(None, fetch_sheet_rows)
    except Exception as e:
        print("Sheet check failed:", e)
        return

    state = load_sheet_state()
    last_count = state.get("last_row_count")

    if last_count is None:
        # First run ever: set the baseline without announcing existing rows.
        state["last_row_count"] = len(rows)
        save_sheet_state(state)
        print(f"Sheet baseline set at {len(rows)} row(s). Future additions will be announced.")
        return

    if len(rows) > last_count:
        new_rows = rows[last_count:]
        channel = bot.get_channel(int(ANNOUNCE_CHANNEL_ID))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(ANNOUNCE_CHANNEL_ID))
            except Exception as e:
                print("Could not reach announce channel:", e)
                return

        for row in new_rows:
            title = row.get("Titre du sujet") or "Untitled project"
            try:
                prompt = build_project_prompt(row)
                analysis = await loop.run_in_executor(None, ask_groq, prompt)
            except Exception as e:
                analysis = f"(AI analysis failed: {e})"

            header = f"📢 **New PFE project posted:** {title}"
            try:
                await send_long_message(channel, analysis, prefix=header)
            except Exception as e:
                print("Failed to send announcement:", e)

        state["last_row_count"] = len(rows)
        save_sheet_state(state)

    elif len(rows) < last_count:
        # Rows were deleted/cleared — reset baseline so we don't misfire later.
        state["last_row_count"] = len(rows)
        save_sheet_state(state)

@check_sheet.before_loop
async def before_check_sheet():
    await bot.wait_until_ready()

# Manual trigger for testing, usable anywhere (not DM-restricted like /fetch)
@bot.command(name="checksheet")
async def checksheet_command(ctx):
    if not (SHEET_ID and ANNOUNCE_CHANNEL_ID and SHEET_WEBAPP_URL):
        await ctx.send("Sheet announcements aren't configured (missing SHEET_WEBAPP_URL / SHEET_ID / ANNOUNCE_CHANNEL_ID).")
        return
    await ctx.send("Checking sheet now...")
    await check_sheet()
    await ctx.send("Check complete.")

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
async def run_fetch(ctx, target_channel_id: int, option1: str, option2: str, rename: bool):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.author.send("Error: Use this command in DM only.")
        return

    try:
        skip, count = parse_fetch_options(option1, option2)
    except ValueError as e:
        await ctx.send(str(e))
        return

    unlimited = count is None

    target_channel = bot.get_channel(target_channel_id)
    if not target_channel:
        try:
            target_channel = await bot.fetch_channel(target_channel_id)
        except Exception:
            await ctx.send("Could not access channel.")
            return

    await ctx.send(f"Scanning #{target_channel.name}...")

    # History is newest -> oldest, so index 1 = most recent matching file.
    # We scan the full history so skipping is always accurate; if a count is
    # given we stop early once we've collected enough to cover skip+count.
    target_needed = None if unlimited else skip + count
    queue = []
    async for message in target_channel.history(limit=None):
        for attachment in message.attachments:
            if is_supported(attachment):
                queue.append(attachment)
                if target_needed is not None and len(queue) >= target_needed:
                    break
        if target_needed is not None and len(queue) >= target_needed:
            break

    total_found = len(queue)

    if skip >= total_found:
        await ctx.send(
            f"Found {total_found} file(s), but that's not enough to skip {skip}. Nothing to download."
        )
        return

    selected = queue[skip:] if unlimited else queue[skip:skip + count]

    # Keep newest-first order: the first upload is the most recent file
    # after the skip, and it works backward in time from there.

    mode = "with AI rename" if rename else "no rename"
    limit_desc = "until an error occurs" if unlimited else f"{len(selected)} file(s)"
    await ctx.send(f"Skipping {skip}, downloading {limit_desc} ({mode}). Processing...")

    loop = asyncio.get_running_loop()
    success = 0
    stopped_early = False

    for attachment in selected:
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
                await ctx.send(f"Uploaded {success}/{len(selected)}")
            else:
                await ctx.send(f"Upload failed: {result.get('message')}")
                if unlimited:
                    stopped_early = True
                    break

            await asyncio.sleep(1.5)

        except Exception as e:
            await ctx.send(f"Error: {str(e)}")
            if unlimited:
                stopped_early = True
                break

    last_index = skip + success  # resume point: use this as next skip value
    summary = f"Done. Skipped {skip}, uploaded {success}."
    if stopped_early:
        summary += " Stopped early due to an error."
    summary += f" Last uploaded file index: {last_index} — use `-{last_index}` as option1 next time to continue from here."
    await ctx.send(summary)

# ---------------- COMMANDS ----------------
# /fetch  <channel_id> [option1] [option2]  -> download + reupload as-is (PDFs and images)
# /fetch2 <channel_id> [option1] [option2]  -> same, but PDFs are renamed with Groq
#
# option1 > 0        -> download the latest option1 files (no skip)
# option1 = N         -> download everything, newest first, until an error occurs
# option1 < 0         -> skip the first |option1| files found, then look at option2:
#     option2 > 0       -> download that many files after the skip
#     option2 = N       -> download everything after the skip, until an error occurs
# Defaults to option1=1 (just the latest file) if nothing is given.
@bot.command(name="fetch")
async def fetch_plain(ctx, target_channel_id: int, option1: str = "1", option2: str = None):
    await run_fetch(ctx, target_channel_id, option1, option2, rename=False)

@bot.command(name="fetch2")
async def fetch_renamed(ctx, target_channel_id: int, option1: str = "1", option2: str = None):
    await run_fetch(ctx, target_channel_id, option1, option2, rename=True)

# ---------------- START ----------------
Thread(target=run_flask).start()
bot.run(DISCORD_TOKEN)
