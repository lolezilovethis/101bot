import discord, json, os, aiohttp, re, asyncio, difflib
from discord.ext import commands

# ---------- Config ----------
REQUEST_CHANNEL_ID = int(os.getenv("REQUEST_CHANNEL_ID", "0"))
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# ---------- Load script DB ----------
with open("scripts.json", "r", encoding="utf-8") as f:
    SCRIPTS_DB = json.load(f)

# ---------- Bot setup ----------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} | Slash commands synced.")

# =========================================================
# /find  – now includes fuzzy suggestion & buttons
# =========================================================
@bot.tree.command(name="find", description="Get a Roblox script from the local database")
@discord.app_commands.describe(game="The Roblox game name, e.g. Rivals")
async def find(inter: discord.Interaction, game: str):
    key = game.lower().replace(" ", "")
    data = SCRIPTS_DB.get(key)

    if data:
        embed = discord.Embed(
            title=f"📜 Script for {game.title()}",
            description=f"```lua\n{data['script']}\n```",
            color=0x00FF99
        )
        embed.add_field(name="🔑 Key Needed", value="No" if not data["key_needed"] else "Yes", inline=True)
        embed.add_field(name="🛠️ Works With", value=", ".join(data["executors"]), inline=True)
        embed.set_footer(text="Use scripts at your own risk.")
        await inter.response.send_message(embed=embed)
        return

    # Fuzzy match suggestion
    all_keys = list(SCRIPTS_DB.keys())
    close_matches = difflib.get_close_matches(key, all_keys, n=1, cutoff=0.6)

    if not close_matches:
        await inter.response.send_message(
            f"❌ Script not found.\nTry `/botsearch {game}` or submit a request with `/request {game}`.",
            ephemeral=True
        )
        return

    suggested_key = close_matches[0]
    formatted = re.sub(r'[^a-zA-Z0-9]', ' ', suggested_key).title()

    class SuggestionView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=15)

        @discord.ui.button(label="✅ Yes", style=discord.ButtonStyle.success)
        async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            data = SCRIPTS_DB[suggested_key]
            embed = discord.Embed(
                title=f"📜 Script for {formatted}",
                description=f"```lua\n{data['script']}\n```",
                color=0x00FF99
            )
            embed.add_field(name="🔑 Key Needed", value="No" if not data["key_needed"] else "Yes", inline=True)
            embed.add_field(name="🛠️ Works With", value=", ".join(data["executors"]), inline=True)
            embed.set_footer(text="Use scripts at your own risk.")
            await interaction.response.edit_message(content=None, embed=embed, view=None)

        @discord.ui.button(label="❌ No", style=discord.ButtonStyle.danger)
        async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.edit_message(
                content="❌ Okay. Try `/botsearch` or submit a request with `/request`.",
                view=None
            )

        async def on_timeout(self):
            for child in self.children:
                child.disabled = True

    await inter.response.send_message(
        f"❓ Script not found for `{game}`.\nDid you mean **{formatted}**?",
        view=SuggestionView(),
        ephemeral=True
    )

# =========================================================
# /request – Submit new script ideas
# =========================================================
@bot.tree.command(name="request", description="Ask staff to add a new script")
@discord.app_commands.describe(
    game="The Roblox game you want a script for",
    info="Optional details (executor, link you found, etc.)"
)
async def request_cmd(inter: discord.Interaction, game: str, info: str | None = None):
    if REQUEST_CHANNEL_ID == 0:
        return await inter.response.send_message(
            "❌ Bot owner hasn’t set `REQUEST_CHANNEL_ID`.", ephemeral=True
        )

    embed = discord.Embed(
        title="📝 New Script Request",
        color=0xF1C40F
    )
    embed.add_field(name="Game", value=game, inline=False)
    embed.add_field(name="Requested by", value=inter.user.mention, inline=False)
    if info:
        embed.add_field(name="Extra info", value=info[:1000], inline=False)
    embed.set_footer(text="Use /request again if you need to add more details.")

    channel = bot.get_channel(REQUEST_CHANNEL_ID)
    if channel:
        await channel.send(embed=embed)
        await inter.response.send_message("✅ Your request has been forwarded!", ephemeral=True)
    else:
        await inter.response.send_message(
            "❌ Can’t find the request channel. Check the ID.", ephemeral=True
        )

# =========================================================
# /botsearch – GitHub fallback
# =========================================================
SEARCH_HEADERS = {"Accept": "application/vnd.github.text-match+json"}
if GITHUB_TOKEN:
    SEARCH_HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

async def search_github(game: str):
    query = "+".join(re.split(r"\s+", game.strip()))
    url = (
        "https://api.github.com/search/code"
        f"?q={query}+loadstring+game%3AHttpGet+language%3Alua&per_page=5"
    )

    async with aiohttp.ClientSession(headers=SEARCH_HEADERS) as session:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            data = await r.json()
    if data.get("total_count", 0) == 0:
        return None

    for item in data["items"]:
        html_url = item["html_url"]
        raw_url = re.sub(
            r"https://github.com/([^/]+)/([^/]+)/blob/(.+)",
            r"https://raw.githubusercontent.com/\1/\2/\3",
            html_url,
        )
        return {
            "script": f'loadstring(game:HttpGet("{raw_url}"))()',
            "raw": raw_url,
            "html": html_url,
        }
    return None

@bot.tree.command(name="botsearch", description="Bot searches GitHub for a script")
@discord.app_commands.describe(game="The Roblox game name you’re looking for")
async def botsearch(inter: discord.Interaction, game: str):
    await inter.response.defer(thinking=True)

    result = await search_github(game)
    if not result:
        await inter.followup.send(
            f"❌ Couldn’t find anything.\nTry `/find {game}` or submit `/request {game}`.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title=f"🔍 Possible script for {game.title()}",
        description=f"```lua\n{result['script']}\n```",
        color=0x3498DB
    )
    embed.add_field(name="Source (GitHub)", value=result['html'], inline=False)
    embed.set_footer(text="Not in the local DB. Add it with /request if it works!")
    await inter.followup.send(embed=embed)

# ---------- Run ----------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Add DISCORD_TOKEN in Secrets.")
    bot.run(token)
