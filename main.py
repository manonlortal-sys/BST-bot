import os
import asyncio
import logging

import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web

from cogs.utils import ROLE_ADMIN_ID, PING_BUTTON_EMOJI_ID

logging.basicConfig(level=logging.INFO)

INTENTS = discord.Intents.default()
INTENTS.guilds = True
INTENTS.members = True
INTENTS.messages = True
INTENTS.reactions = True

bot = commands.Bot(command_prefix="!", intents=INTENTS)

# Vue persistante du panel (initialisée plus tard)
panel_view = None  # type: ignore


class PingPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="Ping!",
        style=discord.ButtonStyle.danger,
        custom_id="panel_ping",
        emoji=discord.PartialEmoji(name="pingemoji", id=PING_BUTTON_EMOJI_ID),
    )
    async def ping_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )
            return

        await alerts_cog.handle_ping_button(interaction, is_test=False)  # type: ignore

    @discord.ui.button(
        label="Test",
        style=discord.ButtonStyle.primary,
        custom_id="panel_test",
        emoji="⚠️",
    )
    async def test_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        # Vérification admin
        if not isinstance(interaction.user, discord.Member) or not any(
            r.id == ROLE_ADMIN_ID for r in interaction.user.roles
        ):
            await interaction.response.send_message(
                "Ce bouton est réservé aux administrateurs.", ephemeral=True
            )
            return

        alerts_cog = self.bot.get_cog("Alerts")  # type: ignore
        if not alerts_cog:
            await interaction.response.send_message(
                "Système d'alertes indisponible.", ephemeral=True
            )
            return

        await alerts_cog.handle_ping_button(interaction, is_test=True)  # type: ignore


@bot.event
async def on_ready():
    global panel_view

    print(f"Connecté en tant que {bot.user} (ID: {bot.user.id})")

    # Créer et enregistrer la vue persistante UNE FOIS
    if panel_view is None:
        panel_view = PingPanelView(bot)
        bot.add_view(panel_view)

    try:
        synced = await bot.tree.sync()
        print(f"Commandes slash synchronisées ({len(synced)} commandes) : {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"Erreur de sync des commandes : {e}")


# --- Slash command /ping ---


@bot.tree.command(
    name="ping",
    description="Afficher le panel d'alerte défense percepteurs.",
)
@app_commands.checks.has_role(ROLE_ADMIN_ID)
async def ping_command(interaction: discord.Interaction):
    global panel_view

    # Sécurité : si pour une raison quelconque la vue n'existe pas encore
    if panel_view is None:
        panel_view = PingPanelView(bot)
        bot.add_view(panel_view)

    embed = discord.Embed(
        title="🚨 ALERTE DÉFENSE PERCEPTEURS 🚨",
        description='📣 Clique sur le bouton "Ping!" pour générer une alerte de défense percepteurs !',
        color=discord.Color.red(),
    )
    await interaction.response.send_message(embed=embed, view=panel_view)


# --- Petit serveur web pour Render / UptimeRobot ---


async def handle_root(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)

    port = int(os.getenv("PORT", "10000"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Serveur web démarré sur le port {port}")


# --- Démarrage bot + serveur web ---


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("La variable d'environnement DISCORD_TOKEN est manquante.")

    initial_extensions = [
        "cogs.alerts",
        "cogs.leaderboard",
        "cogs.reactions",
    ]

    await start_web_server()

    async with bot:
        for ext in initial_extensions:
            try:
                await bot.load_extension(ext)
                print(f"Extension chargée : {ext}")
            except Exception as e:
                print(f"Erreur en chargeant {ext} : {e}")
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
