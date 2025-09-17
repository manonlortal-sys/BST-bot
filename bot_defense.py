

"
f"Choisis ci-dessous : **Couleur**, **Pair/Impair**, ou **1–18 / 19–36**.
"
f"(Tu as 5 min pour choisir, sinon la partie s'annule)"
),
color=COLOR_GOLD
)
if THUMB_URL: embed.set_thumbnail(url=THUMB_URL)


view = DuelSelectionView(game)
await interaction.response.send_message(embed=embed, view=view)
sent = await interaction.original_response()
game.lobby_msg_id = sent.id


async def duel_timeout():
await asyncio.sleep(300)
if game.duel_type is None and game.joiner_id is None:
channel = interaction.channel
await channel.send(f"⏳ Temps écoulé — duel non choisi par <@{user_id}>. Partie annulée.")
# Retire le message si souhaité :
# try:
# m = await channel.fetch_message(game.lobby_msg_id)
# await m.edit(view=None)
# except:
# pass
try:
active_games[channel_id].remove(game)
if not active_games[channel_id]:
active_games.pop(channel_id, None)
except Exception:
pass


bot.loop.create_task(duel_timeout())

# =========================
#  Fonctions existantes (défenses…)
# =========================
# ... (reprends ici tes commandes defstats, liste, alliance, alliances7j, graphic)

# =========================
#  Démarrage
# =========================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print("Sync error:", e)
    print(f"Connecté en tant que {bot.user}")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN manquant")
    bot.run(TOKEN)
