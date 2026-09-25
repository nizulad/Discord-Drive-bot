import os
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

