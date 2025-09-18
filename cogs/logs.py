# cogs/logs.py
# Cog de journalisation lisible (incidents) avec:
# - Salon d'incidents (ENV: ERROR_LOG_CHANNEL_ID ou /logs attach)
# - Listeners: slash errors, prefix errors, fallback on_error
# - Throttling: regroupe les erreurs identiques pendant une fenêtre
# - Niveaux: INFO / WARN / ERROR / CRITICAL
# - Commandes admin: /logs test, /logs attach, /logs where, /logs level, /logs mute

from __future__ import annotations
import os
import asyncio
import traceback
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import discord
from discord.ext import commands
from discord import app_commands

TZ_LABEL = "Europe/Paris"
ERROR_LOG_CHANNEL_ID_ENV = int(os.getenv("ERROR_LOG_CHANNEL_ID", "0"))

# Fenêtre de regroupement (seconds) pour une même erreur
THROTTLE_WINDOW = 60

# Niveaux
LEVELS = {"INFO": 10, "WARN": 20, "ERROR": 30, "CRITICAL": 40}

def _now_ts() -> int:
    return int(time.time())

@dataclass
class ThrottleBucket:
    count: int
    first_ts: int
    last_ts: int
    message_id: Optional[int] = None
    level: str = "ERROR"

class LogsCog(commands.Cog):
    """Cog d'incidents lisibles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # (guild_id -> channel_id) surcouche runtime (via /logs attach)
        self._guild_log_channels: Dict[int, int] = {}
        # throttle key -> bucket
        self._throttle: Dict[Tuple[int, str, str, str], ThrottleBucket] = {}
        # seuil minimal de log (global)
        self._min_level = LEVELS["WARN"]
        # muting (ts) pour niveaux < CRITICAL
        self._mute_until_ts: Optional[int] = None

    # ---------- Helpers de formattage ----------

    def _get_log_channel(self, guild: Optional[discord.Guild]) -> Optional[discord.abc.Messageable]:
        if guild is None:
            return None
        ch_id = self._guild_log_channels.get(guild.id, 0) or ERROR_LOG_CHANNEL_ID_ENV
        ch = guild.get_channel(ch_id) if ch_id else None
        return ch if isinstance(ch, (discord.TextChannel, discord.Thread)) else None

    def _advice_for(self, summary: str, error_text: str) -> str:
        text = error_text.lower()
        if "10062" in text or "unknown interaction" in text:
            return (
                "Discord a invalidé l’interaction (réponse trop tard/double réponse).\n"
                "→ Réponds **immédiatement** (`defer`) puis poursuis le traitement.\n"
                "→ Évite les appels bloquants avant la réponse.\n"
                "→ Assure-toi que la View est **persistante** et `custom_id` cohérent."
            )
        if "missing permissions" in text or "forbidden" in text:
            return (
                "Permissions manquantes pour écrire/mentionner/éditer dans ce salon.\n"
                "→ Vérifie: Envoyer des messages, Mentionner @roles, Gérer les messages (si édition)."
            )
        if "privilegedintentsrequired" in text:
            return (
                "Intents privilégiés non activés.\n"
                "→ Active `MESSAGE CONTENT`/`MEMBERS` dans le Developer Portal > Bot > Privileged Gateway Intents."
            )
        return "Vérifie la pile et le contexte. Si récurrent, ajoute du `defer`, des try/except ciblés et du logging."

    def _color_for_level(self, level: str) -> discord.Color:
        if level == "CRITICAL":
            return discord.Color.dark_red()
        if level == "ERROR":
            return discord.Color.red()
        if level == "WARN":
            return discord.Color.orange()
        return discord.Color.blurple()

    def _should_emit(self, level: str) -> bool:
        if level not in LEVELS:
            return True
        if self._mute_until_ts and _now_ts() < self._mute_until_ts and LEVELS[level] < LEVELS["CRITICAL"]:
            return False
        return LEVELS[level] >= self._min_level

    def _key_for_throttle(self, guild_id: int, source: str, action: str, error_code: str) -> Tuple[int, str, str, str]:
        return (guild_id, source, action, error_code or "n/a")

    async def _post_or_edit_incident(
        self,
        guild: Optional[discord.Guild],
        level: str,
        source: str,
        summary: str,
        details: str,
        action: str,
        error_code: str = "",
        context: Optional[dict] = None,
    ):
        if guild is None or not self._should_emit(level):
            return

        ch = self._get_log_channel(guild)
        if ch is None:
            # Pas de salon : on loggue quand même en console pour ne rien perdre.
            print(f"[{level}] {source} :: {summary}\n{details}")
            return

        key = self._key_for_throttle(guild.id, source, action, error_code)
        now = _now_ts()
        bucket = self._throttle.get(key)

        # Construire embed
        embed = discord.Embed(
            title=f"{'🚨' if level in ('ERROR','CRITICAL') else 'ℹ️'} {source}",
            description=summary,
            color=self._color_for_level(level),
        )
        embed.add_field(name="Action", value=f"`{action}`", inline=True)
        if error_code:
            embed.add_field(name="Code", value=f"`{error_code}`", inline=True)
        if context:
            ctx_lines = []
            g = context.get("guild")
            c = context.get("channel")
            u = context.get("user")
            lat = context.get("latency")
            if g: ctx_lines.append(f"Serveur: **{g}**")
            if c: ctx_lines.append(f"Canal: **{c}**")
            if u: ctx_lines.append(f"Utilisateur: **{u}**")
            if lat is not None: ctx_lines.append(f"Latence: **{lat:.2f}s**")
            if ctx_lines:
                embed.add_field(name="Contexte", value="\n".join(ctx_lines), inline=False)
        # Détails (tronqués si trop longs)
        details_trim = details if len(details) < 1500 else (details[:1500] + "\n…(tronqué)")
        embed.add_field(name="Détails", value=f"```\n{details_trim}\n```", inline=False)

        embed.add_field(name="Conseils", value=self._advice_for(summary, details), inline=False)
        embed.set_footer(text=f"Niveau: {level} • {time.strftime('%d/%m/%Y %H:%M:%S')}")

        # Throttle/édition
        if bucket and (now - bucket.last_ts) <= THROTTLE_WINDOW:
            bucket.count += 1
            bucket.last_ts = now
            # Éditer l'ancien message: ajouter un compteur
            try:
                if bucket.message_id:
                    msg = await ch.fetch_message(bucket.message_id)
                    # Ajoute/maj un champ compteur
                    embed.add_field(name="Répétitions", value=f"×{bucket.count} en {now - bucket.first_ts}s", inline=True)
                    await msg.edit(embed=embed)
                    return
            except discord.NotFound:
                bucket.message_id = None  # on repostera
        else:
            # Nouveau bucket
            bucket = ThrottleBucket(count=1, first_ts=now, last_ts=now, message_id=None, level=level)
            self._throttle[key] = bucket

        # Poster un nouveau message d'incident
        embed.add_field(name="Répétitions", value="×1", inline=True)
        sent = await ch.send(embed=embed)
        bucket.message_id = sent.id

    # ---------- Exposition publique pour autres cogs (via utils/logbus) ----------

    async def post_incident(
        self,
        guild: Optional[discord.Guild],
        *,
        level: str = "ERROR",
        source: str,
        summary: str,
        details: str,
        action: str,
        error_code: str = "",
        context: Optional[dict] = None,
    ):
        await self._post_or_edit_incident(guild, level, source, summary, details, action, error_code, context)

    # ---------- Listeners globaux ----------

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        guild = interaction.guild if hasattr(interaction, "guild") else None
        try:
            # Détecter le type d'erreur
            err_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            await self._post_or_edit_incident(
                guild,
                level="ERROR",
                source="Erreur commande slash",
                summary=str(error),
                details=err_text,
                action=getattr(interaction.command, "name", "unknown"),
                error_code=getattr(error, "code", "") or "",
                context={
                    "guild": getattr(guild, "name", None),
                    "channel": getattr(interaction.channel, "name", None),
                    "user": getattr(interaction.user, "display_name", None),
                }
            )
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        guild = ctx.guild
        err_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        await self._post_or_edit_incident(
            guild,
            level="ERROR",
            source="Erreur commande préfixe",
            summary=str(error),
            details=err_text,
            action=getattr(ctx.command, "name", "unknown") if ctx.command else "unknown",
            context={
                "guild": getattr(guild, "name", None),
                "channel": getattr(ctx.channel, "name", None),
                "user": getattr(getattr(ctx, "author", None), "display_name", None),
            }
        )

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        # filet de sécurité pour les commandes de ce cog
        guild = ctx.guild
        err_text = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        await self._post_or_edit_incident(
            guild,
            level="ERROR",
            source="Erreur LogsCog",
            summary=str(error),
            details=err_text,
            action=getattr(ctx.command, "name", "unknown") if ctx.command else "unknown",
            context={
                "guild": getattr(guild, "name", None),
                "channel": getattr(ctx.channel, "name", None),
                "user": getattr(getattr(ctx, "author", None), "display_name", None),
            }
        )

    async def on_error(self, event_method: str, /, *args, **kwargs):
        # (optionnel) si tu veux capter tout le reste, dé-commente et ajoute le listener dans setup
        pass

    # ---------- Commandes admin ----------

    @app_commands.command(name="logs_test", description="Publie un incident de test dans le salon configuré.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs_test(self, interaction: discord.Interaction):
        await interaction.response.send_message("Envoi d’un message de test…", ephemeral=True)
        await self._post_or_edit_incident(
            interaction.guild,
            level="WARN",
            source="Test de journalisation",
            summary="Ceci est un test de message d’incident.",
            details="Tout est OK 👍",
            action="logs_test",
        )
        await interaction.followup.send("✅ Test envoyé.", ephemeral=True)

    @app_commands.command(name="logs_attach", description="Assigne ce salon comme salon d’incidents.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs_attach(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Utilise cette commande dans un serveur.", ephemeral=True)
        self._guild_log_channels[interaction.guild.id] = interaction.channel.id
        await interaction.response.send_message(f"✅ Salon d’incidents défini sur {interaction.channel.mention}.", ephemeral=True)

    @app_commands.command(name="logs_where", description="Affiche le salon d’incidents courant.")
    async def logs_where(self, interaction: discord.Interaction):
        ch = self._get_log_channel(interaction.guild)
        if ch:
            await interaction.response.send_message(f"Salon d’incidents: {ch.mention}", ephemeral=True)
        else:
            txt = "Aucun salon attaché. "
            if ERROR_LOG_CHANNEL_ID_ENV:
                txt += f"(ENV ERROR_LOG_CHANNEL_ID={ERROR_LOG_CHANNEL_ID_ENV})"
            await interaction.response.send_message(txt, ephemeral=True)

    @app_commands.command(name="logs_level", description="Fixe le niveau minimal loggé (INFO/WARN/ERROR/CRITICAL).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs_level(self, interaction: discord.Interaction, level: str):
        up = level.upper()
        if up not in LEVELS:
            return await interaction.response.send_message("Niveau invalide. Choisis: INFO, WARN, ERROR, CRITICAL.", ephemeral=True)
        self._min_level = LEVELS[up]
        await interaction.response.send_message(f"✅ Niveau minimal loggé: **{up}**", ephemeral=True)

    @app_commands.command(name="logs_mute", description="Coupe les logs non-critiques pendant X minutes.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def logs_mute(self, interaction: discord.Interaction, minutes: int):
        minutes = max(1, min(minutes, 120))
        self._mute_until_ts = _now_ts() + minutes * 60
        await interaction.response.send_message(f"🔇 Logs non-critiques en pause pendant {minutes} min.", ephemeral=True)

async def setup(bot: commands.Bot):
    cog = LogsCog(bot)
    await bot.add_cog(cog)
    # (Optionnel) pour capter tout via on_error: bot.add_listener(cog.on_error)
