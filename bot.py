import os
import re
import base64
import asyncio
import requests
from flask import Flask
from threading import Thread
import discord
from discord.ext import commands
import google.generativeai as genai

# --- Configuration ---
DISCORD_TOKEN = os.getenv("DT")
GAS_WEBAPP_URL = os.getenv("GAS_WEBAPP_URL")
GEMINI_API_KEY = os.getenv("GAT")

# Configure the Google AI SDK Engine
genai.configure(api_key=GEMINI_API_KEY)

# Flask web server to satisfy Render's 24/7 web port binding requirement
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# Discord Bot Engine Initialization
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot successfully connected as {bot.user.name}")

# --- Core Intelligent LLM Naming Engine ---
def analyze_pdf_with_llm(file_bytes, original_filename):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            "You are an academic document classification assistant for a university computer science department.\n"
            "Analyze the provided document pages and output a clean filename based on these strict formatting rules:\n\n"
            "1. Identify the Professor's name (e.g., Amrouche, Nacer, Belkacem). If completely unknown, use 'Unknown'.\n"
            "2. Determine if the document is an EVALUATION (Exam, Rattrapage, Interro, Controle, Test) or INSTRUCTIONAL (Cours, TD, TP, Serie, Fiche).\n"
            "3. IF EVALUATION: Output format MUST be exactly: Prof Name | Year Type.pdf (e.g., 'Amrouche | 2025 Examen.pdf' or 'Unknown | 2024 Rattrapage.pdf').\n"
            "4. IF INSTRUCTIONAL: Output format MUST be exactly: Prof Name | Chapter or Material Title.pdf (e.g., 'Nacer | Chapitre 2 Graphes.pdf' or 'Belkacem | TD 1 Matrices.pdf').\n\n"
            "Rules:\n"
            "- Do not include introductory text, markdown code blocks (```), quotes, or explanations.\n"
            "- Output ONLY the final, raw filename string ending in '.pdf'.\n"
            "- Treat French and English academic terms as matching equivalents."
        )

        pdf_part = {
            "mime_type": "application/pdf",
            "data": file_bytes
        }

        response = model.generate_content([prompt, pdf_part])

        cleaned_name = response.text.strip().replace("`", "").replace('"', '').replace("'", "")

        if cleaned_name.endswith(".pdf"):
            return cleaned_name
        return f"{cleaned_name}.pdf"

    except Exception as e:
        print(f"Gemini API Processing Exception: {e}")
        return original_filename

# --- Main Command Handler ---
@bot.command(name="fetch")
async def fetch_resources(ctx, target_channel_id: int, doc_count: int):
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.author.send("Error: The `/fetch` command can only be used here in our private chat.")
        return

    target_channel = bot.get_channel(target_channel_id)
    if not target_channel:
        await ctx.send("Could not access that channel. Verify my server roles or check the ID.")
        return

    await ctx.send(f"Connected to #{target_channel.name}. Scanning historical logs...")

    pdf_queue = []
    scan_limit = None if doc_count == -1 else 500

    async for message in target_channel.history(limit=scan_limit, oldest_first=False):
        for attachment in message.attachments:
            if attachment.filename.lower().endswith('.pdf'):
                pdf_queue.append(attachment)
                if doc_count != -1 and len(pdf_queue) >= doc_count:
                    break
        if doc_count != -1 and len(pdf_queue) >= doc_count:
            break

    total_found = len(pdf_queue)
    await ctx.send(f"Found {total_found} PDFs. Initiating upload...")

    success_count = 0

    for attachment in pdf_queue:
        try:
            # 1. Download into memory
            file_bytes = await attachment.read()
            original_name = attachment.filename

            # 2. Always run through Gemini for proper naming
            await ctx.send(f"Analyzing `{original_name}` with Gemini...")
            computed_name = analyze_pdf_with_llm(file_bytes, original_name)
            final_name = computed_name
            await ctx.send(f"✨ Renamed to: `{final_name}`")

            # 3. Encode to Base64
            base64_encoded = base64.b64encode(file_bytes).decode('utf-8')

            payload = {
                "fileName": final_name,
                "fileData": base64_encoded
            }

            # 4. Send to Google Apps Script
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.post(GAS_WEBAPP_URL, json=payload, timeout=60)
            )

            res_data = response.json()
            if res_data.get("status") == "success":
                success_count += 1
                await ctx.send(f"Uploaded [{success_count}/{total_found}]: `{final_name}`")
            else:
                await ctx.send(f"Upload failed for `{final_name}`: {res_data.get('message')}")

            # 5. Clear memory
            del file_bytes
            del base64_encoded
            del payload

        except Exception as e:
            await ctx.send(f"Error handling `{attachment.filename}`: {str(e)}")

        await asyncio.sleep(1.5)

    await ctx.send(f"Done. Successfully uploaded {success_count}/{total_found} files to Google Drive.")

# Start Flask thread
Thread(target=run_flask).start()

# Start bot
bot.run(DISCORD_TOKEN)
