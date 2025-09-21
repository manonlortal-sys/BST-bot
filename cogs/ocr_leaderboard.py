# cogs/ocr_leaderboard.py
import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image
import pytesseract
import json
import io
import datetime
import re
from statistics import mean

LEADERBOARD_JSON = "data/leaderboard.json"
MANDATORY_WORDS = ["min", "max", "effets", "fusionner tout", "fusionner", "stop"]

# seuils simples pour décider couleur (à affiner si nécessaire)
def rgb_to_type(r, g, b):
    if g > 100 and r < 120 and b < 120:
        return "vert"
    if r > 180 and g > 90 and b < 120:
        return "orange"
    if b > 140 and r < 120 and g < 120:
        return "bleu"
    return "vert"

class OCRLeaderboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        try:
            with open(LEADERBOARD_JSON, "r", encoding="utf-8") as f:
                self.leaderboard = json.load(f)
        except FileNotFoundError:
            self.leaderboard = []

    # détection couleur : moyenne des pixels dans la bbox (region relative to tableau_region)
    def detect_color_in_bbox(self, pil_img: Image.Image, bbox):
        """
        bbox in coordinates relative to pil_img: (left, top, right, bottom)
        Retourne 'vert' | 'orange' | 'bleu'
        """
        left, top, right, bottom = bbox
        # clamp
        left = max(0, int(left))
        top = max(0, int(top))
        right = min(pil_img.width, int(right))
        bottom = min(pil_img.height, int(bottom))
        if right <= left or bottom <= top:
            return "vert"
        region = pil_img.crop((left, top, right, bottom))
        # réduire taille si trop grand
        w, h = region.size
        max_sample = 3000
        if w * h > max_sample:
            # downscale for speed while preserving color distribution
            scale = (max_sample / (w*h)) ** 0.5
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            region = region.resize((nw, nh))
        pixels = list(region.getdata())
        if not pixels:
            return "vert"
        rs = [p[0] for p in pixels]
        gs = [p[1] for p in pixels]
        bs = [p[2] for p in pixels]
        r_avg = mean(rs)
        g_avg = mean(gs)
        b_avg = mean(bs)
        return rgb_to_type(r_avg, g_avg, b_avg)

    def parse_number(self, text):
        """Retourne int si trouvé sinon None"""
        m = re.search(r"(-?\d+)", text.replace(" ", ""))
        return int(m.group(1)) if m else None

    def normalize_col_text(self, words):
        """Assemble la liste de mots en une chaîne propre"""
        return " ".join(words).strip()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots
        if message.author.bot:
            return
        # must contain attachments
        if not message.attachments:
            return

        for attachment in message.attachments:
            if not attachment.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                continue

            img_bytes = await attachment.read()
            try:
                image = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            except Exception:
                continue

            # OCR global pour filtrage initial et récupérer la partie "haut"
            try:
                full_text = pytesseract.image_to_string(image, lang="fra")
            except Exception:
                full_text = ""

            if not full_text:
                continue
            text_lower = full_text.lower()
            if not all(word in text_lower for word in MANDATORY_WORDS):
                # image non pertinente
                continue

            # --- Extraire le nom de l'équipement ---
            # OCR sur bande supérieure (top band)
            w, h = image.size
            top_band_h = max(30, int(h * 0.18))  # 18% du haut environ, ajustable
            top_band = image.crop((0, 0, int(w * 0.6), top_band_h))  # on prend colonne gauche majoritaire
            top_text = pytesseract.image_to_string(top_band, lang="fra")
            # nettoyer et retirer la ligne Niv.
            lines = [ln.strip() for ln in top_text.splitlines() if ln.strip()]
            nom_equipement = "Équipement inconnu"
            for ln in lines:
                if ln.lower().startswith("niv.") or ln.lower().startswith("niv"):
                    continue
                # on prend la première ligne non niv comme nom
                nom_equipement = ln
                break

            # --- Définir zone tableau : 2e quart horizontal ---
            left = w // 4
            right = w // 2
            top = max(5, int(h * 0.18))  # commencer juste en dessous de la bande du nom
            bottom = h - 10
            tableau_region = image.crop((left, top, right, bottom))
            tr_w, tr_h = tableau_region.size

            # --- OCR détaillé sur la région du tableau avec position des mots ---
            ocr_data = pytesseract.image_to_data(tableau_region, lang="fra", output_type=pytesseract.Output.DICT)
            n_boxes = len(ocr_data['text'])
            # regrouper par line_num
            lines_words = {}
            for i in range(n_boxes):
                word = ocr_data['text'][i].strip()
                if not word:
                    continue
                line_num = ocr_data['line_num'][i]
                left_w = ocr_data['left'][i]
                top_w = ocr_data['top'][i]
                width_w = ocr_data['width'][i]
                height_w = ocr_data['height'][i]
                right_w = left_w + width_w
                # stocker
                lines_words.setdefault(line_num, []).append({
                    "word": word,
                    "left": left_w,
                    "top": top_w,
                    "right": right_w,
                    "bottom": top_w + height_w
                })

            # Pour chaque line_num, séparer en 3 colonnes selon la position horizontale
            table_lines_parsed = []  # liste de dicts: {min, max, col3_text, col3_bbox}
            for ln_idx in sorted(lines_words.keys()):
                words = sorted(lines_words[ln_idx], key=lambda x: x["left"])
                if not words:
                    continue
                # déterminer col width
                col_width = tr_w / 3.0
                col1_words = []
                col2_words = []
                col3_words = []
                col3_left = None
                col3_right = None
                col3_top = None
                col3_bottom = None
                for winfo in words:
                    cx = (winfo["left"] + winfo["right"]) / 2.0
                    # colonne 0,1,2 selon cx
                    col_idx = min(2, int(cx // col_width))
                    if col_idx == 0:
                        col1_words.append(winfo["word"])
                    elif col_idx == 1:
                        col2_words.append(winfo["word"])
                    else:
                        col3_words.append(winfo["word"])
                        # bbox mise à jour
                        if col3_left is None or winfo["left"] < col3_left:
                            col3_left = winfo["left"]
                        if col3_right is None or winfo["right"] > col3_right:
                            col3_right = winfo["right"]
                        if col3_top is None or winfo["top"] < col3_top:
                            col3_top = winfo["top"]
                        if col3_bottom is None or winfo["bottom"] > col3_bottom:
                # si colonne 3 vide, on peut tenter heuristique (mots à droite)
                col1_txt = self.normalize_col_text(col1_words)
                col2_txt = self.normalize_col_text(col2_words)
                col3_txt = self.normalize_col_text(col3_words)

                # calcul bbox colonne3 relatif à tableau_region coord
                if col3_left is not None:
                    bbox = (col3_left, col3_top, col3_right, col3_bottom)
                else:
                    # fallback: utiliser droite du region
                    bbox = (int(tr_w * 0.65), 0, tr_w, tr_h)

                table_lines_parsed.append({
                    "col1": col1_txt,
                    "col2": col2_txt,
                    "col3": col3_txt,
                    "col3_bbox": bbox
                })

            # Si l'OCR donne zéro lignes structurées, fallback simple : tenter splitlines du texte de la région
            if not table_lines_parsed:
                raw = pytesseract.image_to_string(tableau_region, lang="fra")
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    # heuristique séparateur multiple espaces
                    parts = re.split(r"\s{2,}|\t", line)
                    if len(parts) >= 3:
                        col1, col2, col3 = parts[0], parts[1], " ".join(parts[2:])
                    elif len(parts) == 2:
                        col1, col2, col3 = parts[0], "", parts[1]
                    else:
                        col1, col2, col3 = "", "", parts[0]
                    table_lines_parsed.append({
                        "col1": col1.strip(),
                        "col2": col2.strip(),
                        "col3": col3.strip(),
                        "col3_bbox": (int(tr_w * 0.65), 0, tr_w, tr_h)
                    })

            # --- Pour chaque ligne, detecter la couleur et parser min/max/valeur/unite/effect ---
            improvements = []
            for parsed in table_lines_parsed:
                col1 = parsed["col1"]
                col2 = parsed["col2"]
                col3 = parsed["col3"]
                bbox = parsed["col3_bbox"]
                # detect color in bbox (bbox relative to tableau_region)
                color_type = self.detect_color_in_bbox(tableau_region, bbox)

                if color_type == "vert":
                    continue  # on ignore

                # parse numeric min / max
                min_val = self.parse_number(col1) if col1 else None
                max_val = self.parse_number(col2) if col2 else None

                # parse col3: valeur et unité/effet
                # ex: "298 Vitalité" -> value=298, unit/effet="Vitalité"
                # ex: "1 PA" -> value=1, unit="PA"
                # ex: "Exo 1 PA" or other noisy -> find first number and remaining words
                value_num = self.parse_number(col3)
                # find unit/effect: words after the number
                unit = None
                if value_num is not None:
                    # split by number
                    m = re.search(r"(-?\d+)", col3.replace(" ", ""))
                    # safer split: find first numeric token in original col3
                    tokens = re.split(r"\s+", col3)
                    # find index of token containing the number
                    idx_num = None
                    for i, t in enumerate(tokens):
                        if re.search(r"-?\d+", t):
                            idx_num = i
                            break
                    if idx_num is not None and idx_num + 1 < len(tokens):
                        unit = " ".join(tokens[idx_num+1:])
                    else:
                        # fallback: try to pick the first non-numeric token
                        nonnum = [t for t in tokens if not re.search(r"-?\d+", t)]
                        unit = nonnum[0] if nonnum else None
                else:
                    # no number found — skip
                    continue

                improvements.append({
                    "type": color_type,       # "orange" or "bleu"
                    "min": min_val,           # maybe None
                    "max": max_val,           # maybe None
                    "value": value_num,
                    "unit": unit.strip() if unit else None,
                    "raw_col3": col3
                })

            # si aucune amélioration pertinente détectée -> ignorer screen
            if not improvements:
                continue

            # construire une entrée "screen" contenant toutes les améliorations pour cet équipement
            screen_entry = {
                "joueur": message.author.name,
                "equipement": nom_equipement,
                "date": datetime.datetime.utcnow().isoformat(),
                "improvements": improvements,
                "source_url": attachment.url
            }
            self.leaderboard.append(screen_entry)

            # sauvegarde
            try:
                with open(LEADERBOARD_JSON, "w", encoding="utf-8") as f:
                    json.dump(self.leaderboard, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print("Erreur sauvegarde leaderboard:", e)

    @app_commands.command(name="fm", description="Afficher le leaderboard FM")
    async def fm(self, interaction: discord.Interaction):
        if not self.leaderboard:
            await interaction.response.send_message("Le leaderboard est vide.", ephemeral=True)
            return

        # afficher les N derniers screens (par ex. 10)
        N = 10
        recent = self.leaderboard[-N:]
        embed = discord.Embed(title="📊 Leaderboard FM", color=discord.Color.gold())
        for entry in reversed(recent):  # du plus récent au plus ancien
            header = f"{entry['joueur']} → {entry['equipement']}"
            lines = []
            for imp in entry["improvements"]:
                if imp["type"] == "orange":
                    maxpart = f" ({imp['max']} max)" if imp.get("max") is not None else ""
                    lines.append(f"over {imp['value']}{maxpart}")
                elif imp["type"] == "bleu":
                    unitpart = f" {imp['unit']}" if imp.get("unit") else ""
                    lines.append(f"exo {imp['value']}{unitpart}")
            # assembler bloc
            desc = header + "\n" + "\n".join(lines) + "\n" + entry["date"][:19].replace("T", " ")
            embed.add_field(name="\u200b", value=desc, inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(OCRLeaderboard(bot))
