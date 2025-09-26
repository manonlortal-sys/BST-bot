import os
import json
from datetime import datetime, timezone
import discord
from discord.ext import commands
from discord import app_commands

from storage import (
    get_leaderboard_totals_all,
    agg_totals_all,
    agg_totals_by_team,
    hourly_split_all,
    seed_leaderboard_totals,
    seed_aggregates,
)

SNAPSHOT_CHANNEL_ID = int(os.getenv("SNAPSHOT_CHANNEL_ID", "0"))
ADMIN_ROLE_ID       = int(os.getenv("ADMIN_ROLE_ID", "0"))

def paris_now_iso() -> str:
    # On tag le fuseau via offset actuel
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

class SnapshotsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._restored_once = False

    # ---------- Commande manuelle ----------
    @app_commands.command(name="snapshot-save", description="Sauvegarder un snapshot des leaderboards et agrégats (manuel).")
    async def snapshot_save(self, interaction: discord.Interaction):
        if not await self._is_admin(interaction):
            await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Serveur introuvable.", ephemeral=True)
            return

        if not SNAPSHOT_CHANNEL_ID:
            await interaction.response.send_message("SNAPSHOT_CHANNEL_ID manquant.", ephemeral=True)
            return

        # Collecte des données actuelles
        w_all, l_all, inc_all, att_all = agg_totals_all(guild.id)
        w_g1, l_g1, inc_g1, att_g1 = agg_totals_by_team(guild.id, 1)
        w_g2, l_g2, inc_g2, att_g2 = agg_totals_by_team(guild.id, 2)
        m, a, s, n = hourly_split_all(guild.id)

        defense_by_user = get_leaderboard_totals_all(guild.id, "defense")
        ping_by_user    = get_leaderboard_totals_all(guild.id, "pingeur")

        payload = {
            "schema_version": 1,
            "guild_id": guild.id,
            "generated_at": paris_now_iso(),
            "global": {
                "attacks": att_all, "wins": w_all, "losses": l_all, "incomplete": inc_all
            },
            "team_1": {
                "attacks": att_g1, "wins": w_g1, "losses": l_g1, "incomplete": inc_g1
            },
            "team_2": {
                "attacks": att_g2, "wins": w_g2, "losses": l_g2, "incomplete": inc_g2
            },
            "hourly_buckets": {
                "morning": m, "afternoon": a, "evening": s, "night": n
            },
            "defense_by_user": defense_by_user,
            "ping_by_user": ping_by_user
        }

        channel = self.bot.get_channel(SNAPSHOT_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Canal snapshots introuvable.", ephemeral=True)
            return

        content = f"📦 Snapshot sauvegardé — `{payload['generated_at']}`\n```json\n{json.dumps(payload, ensure_ascii=False, separators=(',',':'))}\n```"
        await channel.send(content)
        await interaction.response.send_message("✅ Snapshot envoyé dans le canal dédié.", ephemeral=True)

    async def _is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        if ADMIN_ROLE_ID and any(r.id == ADMIN_ROLE_ID for r in getattr(interaction.user, "roles", [])):
            return True
        return False

    # ---------- Restauration auto au premier on_ready ----------
    @commands.Cog.listener()
    async def on_ready(self):
        if self._restored_once:
            return
        self._restored_once = True

        # Si la DB est déjà peuplée (leaderboard_totals non vide), ne rien faire
        from storage import get_leaderboard_totals
        any_rows = False
        try:
            # un appel rapide : s'il y a au moins 1 entrée, on considère peuplé
            # (on teste 'defense' et 'pingeur')
            from storage import with_db
            @with_db
            def _has_rows(con, guild_id: int) -> bool:
                r = con.execute("SELECT 1 FROM leaderboard_totals WHERE guild_id=? LIMIT 1", (guild_id,)).fetchone()
                return r is not None
            for g in self.bot.guilds:
                if _has_rows(g.id):
                    any_rows = True
                    break
        except Exception:
            pass
        if any_rows:
            return

        if not SNAPSHOT_CHANNEL_ID:
            return  # rien à faire

        # Charger le dernier snapshot et reseeder
        for guild in self.bot.guilds:
            try:
                await self._restore_latest_for_guild(guild)
            except Exception as e:
                print(f"⚠️ Restauration snapshot échouée pour {guild.id} :", e)

    async def _restore_latest_for_guild(self, guild: discord.Guild):
        channel = self.bot.get_channel(SNAPSHOT_CHANNEL_ID)
        if channel is None or not isinstance(channel, discord.TextChannel):
            return

        latest_json = None
        async for m in channel.history(limit=50):  # on regarde les 50 derniers messages (suffisant)
            if m.author.id != self.bot.user.id:
                continue
            if not m.content:
                continue
            # Cherche un bloc ```json ... ```
            content = m.content
            head = "```json"
            if head in content:
                try:
                    start = content.index(head) + len(head)
                    end = content.index("```", start)
                    json_str = content[start:end].strip()
                    latest_json = json.loads(json_str)
                    break
                except Exception:
                    continue
        if not latest_json:
            return

        if int(latest_json.get("guild_id", 0)) != guild.id:
            # si multi-serveur avec un seul canal snapshots, on ignore les autres guilds
            return

        # Seed aggregates
        global_tot = latest_json.get("global", {})
        team1      = latest_json.get("team_1", {})
        team2      = latest_json.get("team_2", {})
        hourly     = latest_json.get("hourly_buckets", {})
        seed_aggregates(guild.id, global_tot, team1, team2, hourly)

        # Seed leaderboard totals (defense & pingeur)
        defense_by_user = {int(k): int(v) for k, v in latest_json.get("defense_by_user", {}).items()}
        ping_by_user    = {int(k): int(v) for k, v in latest_json.get("ping_by_user", {}).items()}
        seed_leaderboard_totals(guild.id, "defense", defense_by_user)
        seed_leaderboard_totals(guild.id, "pingeur", ping_by_user)

        # Mettre à jour/Créer les messages de leaderboard
        try:
            from .leaderboard import update_leaderboards
            await update_leaderboards(self.bot, guild)
        except Exception:
            pass

async def setup(bot: commands.Bot):
    await bot.add_cog(SnapshotsCog(bot))
