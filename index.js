const express = require('express');
const { Client, GatewayIntentBits } = require('discord.js');

const app = express();
const PORT = process.env.PORT || 3000;

app.get('/', (req, res) => {
  res.send('Bot is alive!');
});

app.listen(PORT, () => {
  console.log(`Server listening on port ${PORT}`);
});

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.DirectMessages,
  ],
});

const TARGET_CHANNEL_ID = '1399062753028608100';

client.once('ready', async () => {
  console.log(`Logged in as ${client.user.tag}`);
  try {
    const channel = await client.channels.fetch(TARGET_CHANNEL_ID);
    if (channel) {
      await channel.send('hi');
      console.log('Successfully sent hi!');
    }
  } catch (err) {
    console.error('Error fetching channel or sending message:', err);
  }
});

client.login(process.env.DISCORD_BOT_TOKEN);
