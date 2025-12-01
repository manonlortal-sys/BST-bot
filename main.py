import os
import threading
import http.server
import socketserver

import discord
from discord.ext import commands

# -----------------------------
# Petit serveur HTTP pour Render / UptimeRobot
# -----------------------------


class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Bot actif")

    def log_message(self, format, *args):
        # On évite de spammer la console
        return


def run_http_server():
    port = int(os.getenv("PORT", "10000"))
    with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as httpd:
        httpd.serve_forever()


# On lance le serveur HTTP dans un thread séparé
threading.Thread(target=run_http_server, daemon=True).start()

# -----------------------------
# Bot Discord
# -----------------------------

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise SystemExit("Missing DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    print("🚀 setup_hook…")

    for ext in [
        "cogs.alerts",
        "cogs.reactions",
        "cogs.leaderboard",
        "cogs.ping_panel",
    ]:
        try:
            await bot.load_extension(ext)
            print(f"OK {ext}")
        except Exception as e:
            print(f"ERREUR {ext} → {e}")

    # Sync des commandes slash POUR CHAQUE SERVEUR
    for g in bot.guilds:
        try:
            await bot.tree.sync(guild=discord.Object(id=g.id))
            print("SYNC :", g.id)
        except Exception as e:
            print("SYNC ERROR :", e)


@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")


if __name__ == "__main__":
    print("⚡ Booting…")
    bot.run(DISCORD_TOKEN)
