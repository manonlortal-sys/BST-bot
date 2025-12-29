import discord
from discord.ext import commands
from datetime import timezone

SOURCE_CHANNEL_IDS = {
    1455171459507949581,
    1455171459507949582,
    1455171458807500889,
}

DESTINATION_CHANNEL_ID = 1418245195849400370


def is_image(att: discord.Attachment) -> bool:
    if att.content_type:
        return att.content_type.startswith("image/")
    return att.filename.lower().endswith(
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
    )


class Copie(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.id not in SOURCE_CHANNEL_IDS:
            return

        dest_channel = self.bot.get_channel(DESTINATION_CHANNEL_ID)
        if dest_channel is None:
            try:
                dest_channel = await self.bot.fetch_channel(DESTINATION_CHANNEL_ID)
            except Exception:
                return

        embed = discord.Embed(
            description=message.content or "*[Pas de texte]*",
            timestamp=message.created_at,
        )

        embed.set_author(
            name=str(message.author),
            icon_url=message.author.display_avatar.url
        )

        embed.add_field(
            name="Canal",
            value=f"#{message.channel.name}",
            inline=True
        )

        embed.add_field(
            name="Date",
            value=message.created_at.astimezone(timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S UTC"),
            inline=True
        )

        first_image = None
        for att in message.attachments:
            if is_image(att):
                first_image = att
                break

        if first_image:
            embed.set_image(url=first_image.url)

        files = []
        for att in message.attachments:
            if first_image and att.id == first_image.id:
                continue
            try:
                files.append(await att.to_file())
            except Exception:
                pass

        await dest_channel.send(embed=embed, files=files if files else None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Copie(bot))
