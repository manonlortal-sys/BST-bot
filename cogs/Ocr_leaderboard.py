import discord
from discord.ext import commands
from discord import app_commands
import pytesseract
from PIL import Image
import json
import io
import aiohttp
import datetime

LEADERBOARD_JSON = "data/leaderboard.json"

# Liste des mots obligatoires pour filtrer l'image
MANDATORY_WORDS = ["min", "max", "effets", "fusionner tout", "fusionner", "stop"]

class OCRLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Charger le leaderboard existant ou créer un nouveau
        try:
            with open(LEADERBOARD_JSON, "r", encoding="utf-8") as f:
                self.leaderboard = json.load(f)
        except FileNotFoundError:
            self.leaderboard = []

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        # Vérifier s'il y a une image attachée
        if not message.attachments:
            return

        for attachment in message.attachments:
            if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue

            # Télécharger l'image
            img_bytes = await attachment.read()
            image = Image.open(io.BytesIO(img_bytes))

            # OCR rapide pour filtrage
            text = pytesseract.image_to_string(image, lang="fra")  # Dofus FR
            text_lower = text.lower()
            if not all(word in text_lower for word in MANDATORY_WORDS):
                continue  # Ignorer l'image si mots obligatoires manquants

            # Extraction du nom de l'équipement
            # On suppose que le nom est en haut à gauche (avant le tableau)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            nom_equipement = lines[0] if lines else "Équipement inconnu"

            # Extraire le tableau (min/max/effets)
            tableau_lines = []
            for line in lines:
                if "min" in line.lower() or "max" in line.lower() or "effets" in line.lower():
                    tableau_lines.append(line)

            # Ici il faudrait ajouter la détection couleur pour chaque ligne
            # Pour l'exemple, on fait un placeholder simple
            tableau_analyse = []
            for line in tableau_lines:
                # placeholder: si "nouveau" dans le texte → bleu, "dépasse" → orange, sinon vert
                if "nouveau" in line.lower():
                    ligne_type = "bleu"
                elif "dépasse" in line.lower():
                    ligne_type = "orange"
                else:
                    ligne_type = "vert"

                tableau_analyse.append({
                    "caracteristique": line,
                    "valeur": line,  # à remplacer par la valeur exacte extraite
                    "type": ligne_type
                })

            # Filtrage post-analyse : si tout est vert, on ignore l'image
            if all(l["type"] == "vert" for l in tableau_analyse):
                continue

            # Ajouter chaque ligne dans le leaderboard
            for l in tableau_analyse:
                entry = {
                    "nom_equipement": nom_equipement,
                    "caracteristique": l["caracteristique"],
                    "valeur": l["valeur"],
                    "type": l["type"],
                    "joueur": message.author.name,
                    "date": datetime.datetime.utcnow().isoformat()
                }
                self.leaderboard.append(entry)

            # Sauvegarder le JSON
            with open(LEADERBOARD_JSON, "w", encoding="utf-8") as f:
                json.dump(self.leaderboard, f, ensure_ascii=False, indent=4)

    @app_commands.command(name="fm", description="Afficher le leaderboard FM")
    async def fm(self, interaction: discord.Interaction):
        if not self.leaderboard:
            await interaction.response.send_message("Le leaderboard est vide.", ephemeral=True)
            return

        embed = discord.Embed(title="📊 Leaderboard FM", color=discord.Color.gold())
        for entry in self.leaderboard[-10:]:  # afficher les 10 dernières améliorations
            desc = f"{entry['joueur']} → {entry['nom_equipement']}\n" \
                   f"{entry['caracteristique']} ({entry['type']}) → {entry['valeur']}\n" \
                   f"{entry['date'][:19].replace('T',' ')}"
            embed.add_field(name="\u200b", value=desc, inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(OCRLeaderboard(bot))
