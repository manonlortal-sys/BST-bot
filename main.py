import os
import threading
import discord
from discord.ext import commands
from flask import Flask

# ---------- Flask (pour Render) ----------
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot Cafard is running", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ---------- Discord ----------
INTENTS = discord.Intents.default()
INTENTS.message_content = True


class CafardBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS
        )

    async def setup_hook(self):
        await self.load_extension("cogs.cafard")
        await self.tree.sync()


bot = CafardBot()


@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")


# ---------- Lancement ----------
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(os.getenv("DISCORD_TOKEN"))
