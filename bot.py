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
DISCORD_TOKEN = os.getenv("DT")   # ◄ Replace with your bot token
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbx2u3wJFIJ3MaQOQTlqeVYk-k0g-GjBf39mOtb2UhvhfHUMWU2quydZu_5-uwC_6d5W/exec"
GEMINI_API_KEY = os.getenv("GAT")     # ◄ Paste your new AIzaSy... key here

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
    """
    Passes raw PDF bytes directly to Gemini 1.5 Flash out of RAM context.
    Uses multimodal OCR to read typed text or handwriting and outputs a structured name.
    """
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Rigid instruction layout enforcing structured deterministic format boundaries
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
        
        # Package the binary memory buffer data directly as a document component part
        pdf_part = {
            "mime_type": "application/pdf",
            "data": file_bytes
        }
        
        # Ship parameters off to Google Cloud endpoints
        response = model.generate_content([prompt, pdf_part])
        
        # Sanitize any stray characters the model might output
        cleaned_name = response.text.strip().replace("`", "").replace('"', '').replace("'", "")
        
        if cleaned_name.endswith(".pdf"):
            return cleaned_name
        return f"{cleaned_name}.pdf"

    except Exception as e:
        print(f"Gemini API Processing Exception: {e}")
        # Secure safety fallback: return the original name string if the API block stumbles
        return original_filename

# --- Main Command Handler ---
@bot.command(name="fetch")
async def fetch_resources(ctx, target_channel_id: int, doc_count: int):
    # Enforce administrative privacy guidelines
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
    await ctx.send(f"Found {total_found} PDFs. Initiating isolated serial streaming transfer...")

    success_count = 0
    
    for attachment in pdf_queue:
        try:
            # 1. Download document structure into raw memory space
            file_bytes = await attachment.read()
            original_name = attachment.filename
            final_name = original_name
            
            # 2. Nonsense Evaluation Layer Trigger Check
            is_nonsense = False
            base_name = os.path.splitext(original_name.lower())[0]
            
            # Trigger conditions: missing vowels, pure digit arrays, or generic system tags
            if not any(char in base_name for char in "aeiou") and len(base_name) > 4:
                is_nonsense = True
            elif re.match(r'^\d+$', base_name) or "download" in base_name or "document" in base_name:
                is_nonsense = True
                
            if is_nonsense:
                await ctx.send(f"Nonsense filename target identified (`{original_name}`). Routing to Gemini API processing layers...")
                
                # Execute external multimodal content validation sequence
                computed_name = analyze_pdf_with_llm(file_bytes, original_name)
                if computed_name:
                    final_name = computed_name
                    await ctx.send(f"✨ AI Reclassified file layout to: `{final_name}`")

            # 3. Process data into Base64 format AFTER content inspection is complete
            base64_encoded = base64.b64encode(file_bytes).decode('utf-8')
            
            payload = {
                "fileName": final_name,
                "fileData": base64_encoded
            }
            
            # 4. Transmit processed data structure directly to Google Web App URL (Generous 60s window)
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, lambda: requests.post(GAS_WEBAPP_URL, json=payload, timeout=60)
            )
            
            res_data = response.json()
            if res_data.get("status") == "success":
                success_count += 1
                await ctx.send(f"Uploaded [{success_count}/{total_found}]: `{final_name}`")
            else:
                await ctx.send(f"Google Apps Script runtime failure on `{final_name}`: {res_data.get('message')}")
            
            # 5. Immediate physical memory clearance instructions to avoid memory leaks
            del file_bytes
            del base64_encoded
            del payload

        except Exception as e:
            await ctx.send(f"Error handling `{attachment.filename}`: {str(e)}")
        
        # Controlled pacing break to strictly follow Google's ingestion thresholds
        await asyncio.sleep(1.5)

    await ctx.send(f"Process complete. Successfully populated your Google Drive folder with {success_count} resources.")

# Start structural thread loop to handle Flask connections
Thread(target=run_flask).start()

# Initialize core bot daemon
bot.run(DISCORD_TOKEN)

