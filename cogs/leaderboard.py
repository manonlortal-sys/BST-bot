import os
import discord
from discord.ext import commands
from discord import app_commands

# Fonctions DB depuis storage.py
from storage import (
    get_leaderboard_post,
    set_leaderboard_post,
    get_leaderboard_totals,
    agg_totals_all,
    get_player_stats,
)


# ---------- ENV ----------
LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))


# ---------- Leaderboards ----------
async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None:
        return

    # ---------- Leaderboard Défense ----------
    def_post = get_leaderboard_post(guild.id, "defense")
    if def_post:
        try:
            msg_def = await channel.fetch_message(def_post[1])
        except discord.NotFound:
            msg_def = await channel.send("📊 **Leaderboard Défense**")
            set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")
    else:
        msg_def = await channel.send("📊 **Leaderboard Défense**")
        set_leaderboard_post(guild.id, channel.id, msg_def.id, "defense")

    top_def = get_leaderboard_totals(guild.id, "defense")
    top_block = "\n".join([f"• <@{uid}> : {cnt} défenses" for uid, cnt in top_def]) or "_Aucun défenseur encore_"

    total_w, total_l, total_inc, total_att = agg_totals_all(guild.id)
    ratio = f"{(total_w/total_att*100):.1f}%" if total_att else "0%"

    embed_def = discord.Embed(title="📊 Leaderboard Défense", color=discord.Color.blue())
    embed_def.add_field(name="Top défenseurs", value=top_block, inline=False)
    embed_def.add_field(
        name="Stats globales (historique)",
        value=f"Attaques : {total_att}\nVictoire : {total_w}\nDéfaites : {total_l}\nIncomplet : {total_inc}\nRatio victoire : {ratio}",
        inline=False
    )
    await msg_def.edit(embed=embed_def)

    # ---------- Leaderboard Pingeurs ----------
    ping_post = get_leaderboard_post(guild.id, "pingeur")
    if ping_post:
        try:
            msg_ping = await channel.fetch_message(ping_post[1])
        except discord.NotFound:
            msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
            set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")
    else:
        msg_ping = await channel.send("📊 **Leaderboard Pingeurs**")
        set_leaderboard_post(guild.id, channel.id, msg_ping.id, "pingeur")

    top_ping = get_leaderboard_totals(guild.id, "pingeur")
    ping_block = "\n".join([f"• <@{uid}> : {cnt} pings" for uid, cnt in top_ping]) or "_Aucun pingeur encore_"

    embed_ping = discord.Embed(title="📊 Leaderboard Pingeurs", color=discord.Color.gold())
    embed_ping.add_field(name="Top pingeurs", value=ping_block, inline=False)
    await msg_ping.edit(embed=embed_ping)


# ---------- Cog ----------
class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Voir les stats d’un joueur")
    @app_commands.describe(member="Membre à inspecter (optionnel)")
    async def stats(self, interaction: discord.Interaction, member: discord.Member = None):
        target = member or interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Impossible de récupérer le serveur.", ephemeral=True)
            return

        defenses, pings, wins, losses = get_player_stats(guild.id, target.id)

        embed = discord.Embed(title=f"📊 Stats de {target.display_name}", color=discord.Color.green())
        embed.add_field(name="Défenses prises", value=str(defenses), inline=True)
        embed.add_field(name="Pings faits", value=str(pings), inline=True)
        embed.add_field(name="Victoires", value=str(wins), inline=True)
        embed.add_field(name="Défaites", value=str(losses), inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
