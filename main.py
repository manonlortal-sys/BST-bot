import os
import random
import discord
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask

import config
import permissions
import embeds
from state import STATE, Player, Team

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# FLASK SERVER
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Discord actif !"

def run_flask():
    # Serveur Flask sur Render (port par défaut : 10000 ou celui fourni par Render)
    import threading
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port)).start()


# =========================
# UTILS
# =========================
def valid_team(p1, p2, p3):
    classes = {p1.cls, p2.cls, p3.cls}
    return None not in classes and len(classes) == 3


# =========================
# COMMANDES
# =========================
@bot.tree.command(name="inscription")
async def inscription(interaction: discord.Interaction, joueur: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not permissions.is_orga_or_admin(interaction):
        return await interaction.followup.send("Accès refusé.")
    if any(p.user_id == joueur.id for p in STATE.players):
        return await interaction.followup.send("Déjà inscrit.")
    STATE.players.append(Player(user_id=joueur.id))
    await refresh_players_embed(interaction)
    await interaction.followup.send("Joueur inscrit.")


@bot.tree.command(name="classe")
async def classe(interaction: discord.Interaction, joueur: discord.Member, classe: str):
    await interaction.response.defer(ephemeral=True)
    if not permissions.is_orga_or_admin(interaction):
        return await interaction.followup.send("Accès refusé.")
    classe = classe.lower().strip()
    if classe not in config.CLASSES:
        return await interaction.followup.send("Classe invalide.")
    for p in STATE.players:
        if p.user_id == joueur.id:
            p.cls = classe
    await refresh_players_embed(interaction)
    await interaction.followup.send("Classe mise à jour.")


@bot.tree.command(name="tirage")
async def tirage(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not permissions.is_orga_or_admin(interaction):
        return await interaction.followup.send("Accès refusé.")
    if len(STATE.players) % 3 != 0:
        return await interaction.followup.send("Nombre de joueurs non divisible par 3.")
    if any(p.cls is None for p in STATE.players):
        return await interaction.followup.send("Tous les joueurs doivent avoir une classe.")

    for _ in range(100):
        random.shuffle(STATE.players)
        teams = []
        ok = True
        for i in range(0, len(STATE.players), 3):
            p1, p2, p3 = STATE.players[i:i+3]
            if not valid_team(p1, p2, p3):
                ok = False
                break
            teams.append(Team(id=len(teams)+1, players=(p1, p2, p3)))
        if ok:
            STATE.teams = teams
            break
    else:
        return await interaction.followup.send("Impossible de créer des équipes valides.")

    await send_teams_embed(interaction)
    await interaction.followup.send("Tirage effectué.")


# =========================
# EMBEDS
# =========================
async def refresh_players_embed(interaction):
    channel = interaction.client.get_channel(config.CHANNEL_EMBEDS_ID)
    if STATE.embed_message_id is None:
        msg = await channel.send(embed=embeds.embed_players(STATE.players))
        STATE.embed_message_id = msg.id
    else:
        msg = await channel.fetch_message(STATE.embed_message_id)
        await msg.edit(embed=embeds.embed_players(STATE.players))


async def send_teams_embed(interaction):
    channel = interaction.client.get_channel(config.CHANNEL_EMBEDS_ID)
    await channel.send(embed=embeds.embed_teams(STATE.teams))


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot prêt : {bot.user}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    run_flask()
    TOKEN = os.environ["DISCORD_TOKEN"]
    bot.run(TOKEN)
