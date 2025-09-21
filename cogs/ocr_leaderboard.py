# cogs/ocr_leaderboard.py
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import base64
import os
import io
import requests

# Liste des effets connus
EFFECTS = [
    "PA", "PM", "PO", "Vitalité", "Force", "Agilité", "Intelligence", "Chance", "Sagesse",
    "Puissance", "Coups Critiques", "Dommages Terre", "Dommages Feu", "Dommages Air", "Dommages Eau",
    "Fuite", "Prospection", "Tacle", "Esquive PM", "Esquive PA", "Initiative", "Retrait PM", "Retrait PA",
    "Invocations", "Dommages Critiques", "Résistance Terre", "Résistance Air", "Résistance Feu",
    "Résistance Neutre", "Résistance Critiques", "Résistance Poussée", "Soins", "Dommages Poussée",
    "Résistance Eau"
]

# Clé API Google Vision (depuis variable d'environnement)
GOOGLE_VISION_KEY = os.getenv("GOOGLE_VISION_KEY")

class OCRLeaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_message = None
        self.active = False  # devient True après /fm

    # ----------------- Commande /fm -----------------
    @app_commands.command(name="fm", description="Active l'analyse des screens pour le leaderboard")
    async def fm(self, interaction: discord.Interaction):
        self.active = True
        embed = discord.Embed(
            title="📊 Leaderboard",
            description="Le leaderboard se mettra à jour automatiquement.",
            color=0x00ff00
        )
        self.leaderboard_message = await interaction.channel.send(embed=embed)
        await interaction.response.send_message("✅ Analyse des images activée.", ephemeral=True)

    # ----------------- Écoute des messages -----------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not self.active:
            return
        if message.attachments:
            for attach in message.attachments:
                if attach.content_type and attach.content_type.startswith("image/"):
                    await self.process_image(message, attach)

    # ----------------- Appel Google Vision -----------------
    async def process_image(self, message, attachment):
        img_bytes = await attachment.read()
        encoded_image = base64.b64encode(img_bytes).decode("utf-8")

        # Requête API Google Vision
        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_KEY}"
        body = {
            "requests": [
                {
                    "image": {"content": encoded_image},
                    "features": [{"type": "TEXT_DETECTION"}]
                }
            ]
        }
        response = requests.post(url, json=body)
        if response.status_code != 200:
            return  # échec OCR
        result = response.json()
        try:
            parsed_text = result["responses"][0]["textAnnotations"][0]["description"]
        except (KeyError, IndexError):
            return  # aucun texte reconnu

        # ----------------- Filtrage initial -----------------
        keywords = ["min", "max", "effets", "fusionner tout", "fusionner", "stop"]
        if not all(k.lower() in parsed_text.lower() for k in keywords):
            return  # mot clé manquant, ignorer

        # ----------------- Parsing du tableau -----------------
        lines = parsed_text.splitlines()
        try:
            header_index = next(i for i, l in enumerate(lines) if "min" in l.lower() and "max" in l.lower() and "effets" in l.lower())
        except StopIteration:
            return  # pas de tableau

        table_lines = lines[header_index + 1:]
        over_exo_lines = []

        for line in table_lines:
            if not line.strip():
                continue
            parts = line.split()
            # Ligne exo : pas de min/max, valeur + effet
            if len(parts) >= 2 and not parts[0].replace("%","").isdigit():
                value_str = parts[0].replace("%","")
                if value_str.isdigit():
                    value = int(value_str)
                    effect_name = None
                    for i in range(1, len(parts)+1):
                        candidate = " ".join(parts[1:i])
                        if candidate in EFFECTS:
                            effect_name = candidate
                            break
                    if effect_name:
                        over_exo_lines.append(f"✨ exo {effect_name}")
                continue
            # Ligne over : min max valeur effet
            if len(parts) >= 4 and parts[0].replace("%","").isdigit() and parts[1].replace("%","").isdigit():
                min_val = int(parts[0].replace("%",""))
                max_val = int(parts[1].replace("%",""))
                val = int(parts[2].replace("%",""))
                effect_name = None
                for i in range(3, len(parts)+1):
                    candidate = " ".join(parts[3:i])
                    if candidate in EFFECTS:
                        effect_name = candidate
                        break
                if effect_name and val > max_val:
                    over_exo_lines.append(f"🔥 over {val} {effect_name} ({max_val} max)")

        if not over_exo_lines:
            return  # rien à ajouter

        # ----------------- Nom équipement -----------------
        equip_line = next((l for l in lines if "niv." in l.lower()), None)
        if equip_line:
            equip_name = equip_line.lower().split("niv.")[0].strip().title()
        else:
            equip_name = "Équipement inconnu"

        # ----------------- Création embed -----------------
        embed = self.leaderboard_message.embeds[0] if self.leaderboard_message and self.leaderboard_message.embeds else discord.Embed(title="📊 Leaderboard", description="", color=0x00ff00)
        date_str = datetime.datetime.now().strftime("%d/%m/%Y")
        entry_text = f"📅 {date_str} – {message.author.display_name}\n🛡 {equip_name}\n" + "\n".join(over_exo_lines)
        embed.description += entry_text + "\n\n"

        if self.leaderboard_message:
            await self.leaderboard_message.edit(embed=embed)
        else:
            self.leaderboard_message = await message.channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(OCRLeaderboard(bot))
