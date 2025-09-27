# cogs/leaderboard.py
import os
import discord
from discord.ext import commands

import storage  # pour accéder à d'éventuelles fonctions optionnelles (attaques incomplètes)

from storage import (
    get_leaderboard_post,
    set_leaderboard_post,
    get_leaderboard_totals,
    agg_totals_all,
    agg_totals_by_team,
    hourly_split_all,
)

LEADERBOARD_CHANNEL_ID = int(os.getenv("LEADERBOARD_CHANNEL_ID", "0"))

# Séparateur visuel uniforme (entre toutes les sous-catégories)
SEP = "━━━━━━━━━━━━━━━━━━"

def medals_top_defenders(top: list[tuple[int, int]]) -> str:
    """Formate la liste des défenseurs (médailles top 3, puis puces)."""
    lines = []
    for i, (uid, cnt) in enumerate(top):
        if i == 0:
            lines.append(f"🥇 <@{uid}> : {cnt} défenses")
        elif i == 1:
            lines.append(f"🥈 <@{uid}> : {cnt} défenses")
        elif i == 2:
            lines.append(f"🥉 <@{uid}> : {cnt} défenses")
        else:
            lines.append(f"• <@{uid}> : {cnt} défenses")
    return "\n".join(lines) if lines else "_Aucun défenseur encore_"

def fmt_stats_block(att: int, w: int, l: int, inc: int) -> str:
    ratio = f"{(w/att*100):.1f}%" if att else "0%"
    return (
        f"⚔️ Attaques : {att}\n"
        f"🏆 Victoires : {w}\n"
        f"❌ Défaites : {l}\n"
        f"😡 Incomplet : {inc}\n"
        f"📊 Ratio victoire : {ratio}"
    )

def fmt_hourly_block(buckets: tuple[int, int, int, int], total: int) -> str:
    m, a, s, n = buckets
    def pct(x: int) -> str:
        return f"{(x/total*100):.1f}%" if total else "0%"
    return (
        f"🌅 Matin : {m} ({pct(m)})\n"
        f"🌞 Après-midi : {a} ({pct(a)})\n"
        f"🌙 Soir : {s} ({pct(s)})\n"
        f"🌌 Nuit : {n} ({pct(n)})"
    )

async def update_leaderboards(bot: commands.Bot, guild: discord.Guild):
    if not LEADERBOARD_CHANNEL_ID:
        return
    channel = bot.get_channel(LEADERBOARD_CHANNEL_ID)
    if channel is None or not isinstance(channel, discord.TextChannel):
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

    # Données
    # Top défenseurs : grand plafond pour lister (presque) tout en restant safe vis-à-vis des limites d'embed
    top_def = get_leaderboard_totals(guild.id, "defense", limit=100)
    top_block = medals_top_defenders(top_def)

    # Totaux globaux & par guilde
    w_all, l_all, inc_all, att_all = agg_totals_all(guild.id)
    w_g1, l_g1, inc_g1, att_g1 = agg_totals_by_team(guild.id, 1)
    w_g2, l_g2, inc_g2, att_g2 = agg_totals_by_team(guild.id, 2)

    # Répartition horaire (globale)
    buckets_all = hourly_split_all(guild.id)

    # Attaques incomplètes : fonctions optionnelles (si ajoutées dans storage)
    get_incomp_total = getattr(storage, "get_incomplete_attacks_total", None)
    get_incomp_hourly = getattr(storage, "hourly_split_incomplete_attacks", None)

    if callable(get_incomp_total):
        inc_att_total = int(get_incomp_total(guild.id))
    else:
        # Repli : on utilise la valeur "incomplete" globale (défenses incomplètes) faute de données dédiées
        inc_att_total = inc_all

    if callable(get_incomp_hourly):
        buckets_incomp = get_incomp_hourly(guild.id)  # tuple[int,int,int,int]
    else:
        buckets_incomp = (0, 0, 0, 0)

    # ----- Construction de l'embed -----
    embed_def = discord.Embed(title="📊 LEADERBOARD DÉFENSE", color=discord.Color.blue())

    # TOP DÉFENSEURS
    embed_def.add_field(name="**🏆 TOP DÉFENSEURS**", value=top_block, inline=False)

    # Séparateur
    embed_def.add_field(name="\u200b", value=SEP, inline=False)

    # STATS GLOBALES
    embed_def.add_field(name="**📌 STATS GLOBALES**", value=fmt_stats_block(att_all, w_all, l_all, inc_all), inline=False)

    # Séparateur
    embed_def.add_field(name="\u200b", value=SEP, inline=False)

    # RÉPARTITION HORAIRE
    embed_def.add_field(name="**🕒 RÉPARTITION HORAIRE**", value=fmt_hourly_block(buckets_all, att_all), inline=False)

    # Séparateur
    embed_def.add_field(name="\u200b", value=SEP, inline=False)

    # ATTAQUES INCOMPLÈTES (total + répartition horaire si dispo)
    embed_def.add_field(name="**⚠️ ATTAQUES INCOMPLÈTES**", value=f"😡 **Total** : {inc_att_total}", inline=False)
    if any(buckets_incomp):
        embed_def.add_field(
            name="**🕒 RÉPARTITION HORAIRE — ATTAQUES INCOMPLÈTES**",
            value=fmt_hourly_block(buckets_incomp, sum(buckets_incomp)),
            inline=False
        )

    # Séparateur
    embed_def.add_field(name="\u200b", value=SEP, inline=False)

    # STATS GUILDE 1 & STATS GUILDE 2 (côte à côte)
    g1_block = fmt_stats_block(att_g1, w_g1, l_g1, inc_g1)
    g2_block = fmt_stats_block(att_g2, w_g2, l_g2, inc_g2)
    embed_def.add_field(name="**📌 STATS GUILDE 1**", value=g1_block, inline=True)
    embed_def.add_field(name="**📌 STATS GUILDE 2**", value=g2_block, inline=True)

    # Forcer un saut propre après les colonnes
    embed_def.add_field(name="\u200b", value="\u200b", inline=False)

    # Push
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

    top_ping = get_leaderboard_totals(guild.id, "pingeur", limit=100)
    ping_lines = []
    for i, (uid, cnt) in enumerate(top_ping):
        if i == 0:
            ping_lines.append(f"🥇 <@{uid}> : {cnt} pings")
        elif i == 1:
            ping_lines.append(f"🥈 <@{uid}> : {cnt} pings")
        elif i == 2:
            ping_lines.append(f"🥉 <@{uid}> : {cnt} pings")
        else:
            ping_lines.append(f"• <@{uid}> : {cnt} pings")
    ping_block = "\n".join(ping_lines) if ping_lines else "_Aucun pingeur encore_"

    embed_ping = discord.Embed(title="📊 Leaderboard Pingeurs", color=discord.Color.gold())
    embed_ping.add_field(name="**🏅 Top pingeurs**", value=ping_block, inline=False)
    await msg_ping.edit(embed=embed_ping)


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

async def setup(bot: commands.Bot):
    await bot.add_cog(LeaderboardCog(bot))
