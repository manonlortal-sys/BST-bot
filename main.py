import os
import threading
import discord
from discord.ext import commands
from flask import Flask

# ---------- Flask (Render) ----------
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
INTENTS.members = True
INTENTS.reactions = True


class CafardBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=INTENTS,
        )

    async def setup_hook(self):
        # 🔹 Charge tous les cogs nécessaires
        for ext in [
            "cogs.cafard",
            "cogs.ladder_screens",   # détection des screens
            # plus tard :
            # "cogs.ladder_validation",
            # "cogs.ladder_leaderboard",
        ]:
            try:
                await self.load_extension(ext)
                print(f"✅ Cog chargé : {ext}")
            except Exception as e:
                print(f"❌ Erreur chargement {ext} → {e}")

        # Sync global des slash commands
        await self.tree.sync()
        print("🔄 Slash commands synchronisées")


bot = CafardBot()


@bot.event
async def on_ready():
    print(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")


# ---------- Lancement ----------
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(os.getenv("DISCORD_TOKEN"))