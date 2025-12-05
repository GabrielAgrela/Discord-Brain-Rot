import aiohttp
import asyncio
from src.common.database import Database
import os

class RiotAPI:
    def __init__(self, api_key):
        self.api_key = api_key
        self.db = Database()
        self.base_url = "https://euw1.api.riotgames.com"

    async def get_acc_from_riot_id(self, game_name, tag_line):
        url = f"https://europe.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        headers = {"X-Riot-Token": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
        return None

    async def get_current_game(self, puuid):
        url = f"{self.base_url}/lol/spectator/v5/active-games/by-summoner/{puuid}"
        headers = {"X-Riot-Token": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    return await resp.json()
        return None

    async def update_database(self):
        # Stub for now
        return 0

class LoLService:
    def __init__(self, bot):
        self.bot = bot
        self.api = RiotAPI(os.getenv("RIOT_API_KEY"))
