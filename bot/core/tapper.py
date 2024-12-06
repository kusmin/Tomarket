import asyncio
from datetime import datetime, timedelta
import json
import os,sys
from random import randint, choices,random
from time import time
from urllib.parse import unquote, quote

import aiohttp
import pytz
from aiohttp_proxy import ProxyConnector
from better_proxy import Proxy
from pyrogram import Client
from pyrogram.errors import Unauthorized, UserDeactivated, AuthKeyUnregistered, FloodWait
from pyrogram.raw.functions.messages import RequestAppWebView
from pyrogram.raw.functions import account, messages
from pyrogram.raw.types import InputBotAppShortName,InputNotifyPeer, InputPeerNotifySettings

from typing import Callable
import functools
from tzlocal import get_localzone
from bot.config import settings
from bot.exceptions import InvalidSession
from bot.utils import logger
from .agents import generate_random_user_agent
from .headers import headers
from .api_check import check_base_url

def error_handler(func: Callable):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            await asyncio.sleep(1)
    return wrapper

def convert_to_local_and_unix(iso_time):
    dt = datetime.fromisoformat(iso_time.replace('Z', '+00:00'))
    local_dt = dt.astimezone(get_localzone())
    unix_time = int(local_dt.timestamp())
    return unix_time

def next_daily_check():
    current_time = datetime.now()
    next_day = current_time + timedelta(days=1)
    return next_day

class Tapper:
    def __init__(self, tg_client: Client, proxy: str | None):
        self.session_name = tg_client.name
        self.tg_client = tg_client
        self.proxy = proxy

    async def get_tg_web_data(self) -> str:
        
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        try:
            if not self.tg_client.is_connected:
                try:
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)
            
            while True:
                try:
                    peer = await self.tg_client.resolve_peer('Tomarket_ai_bot')
                    break
                except FloodWait as fl:
                    fls = fl.value

                    logger.warning(f"{self.session_name} | FloodWait {fl}")
                    logger.info(f"{self.session_name} | Sleep {fls}s")
                    await asyncio.sleep(fls + 10)
            
            ref_id = choices([settings.REF_ID,"0001b3Lf","000059BV"], weights=[65, 30, 5], k=1)[0] # change this to weights=[100,0,0] if you don't want to support me
            web_view = await self.tg_client.invoke(RequestAppWebView(
                peer=peer,
                app=InputBotAppShortName(bot_id=peer, short_name="app"),
                platform='android',
                write_allowed=True,
                start_param=ref_id
            ))

            auth_url = web_view.url
            tg_web_data = unquote(
                string=unquote(string=auth_url.split('tgWebAppData=')[1].split('&tgWebAppVersion')[0]))
            
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()

            return ref_id, tg_web_data

        except Exception as error:
            logger.error(f"{self.session_name} | Unknown error: {error}")
            await asyncio.sleep(delay=3)
            return None, None
        
        
    @error_handler
    async def join_and_mute_tg_channel(self, link: str):
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        if not self.tg_client.is_connected:
            await self.tg_client.connect()

        parsed_link = link if 'https://t.me/+' in link else link[13:]

        try:
            chat = await self.tg_client.get_chat(parsed_link)

            if chat.username:
                chat_username = chat.username
            elif chat.id:
                chat_username = chat.id
            else:
                logger.info("Unable to get channel username or id")
                return

            logger.info(f"{self.session_name} | Retrieved channel: <y>{chat_username}</y>")
            
            try:
                logger.info(f"{self.session_name} | Checking if already a member of chat <y>{chat_username}</y>")
                await asyncio.sleep(randint(5, 10))
                await self.tg_client.get_chat_member(chat_username, "me")
                logger.info(f"{self.session_name} | Already a member of chat <y>{chat_username}</y>")
            except Exception as error:
                if hasattr(error, 'ID') and error.ID == 'USER_NOT_PARTICIPANT':
                    logger.info(f"{self.session_name} | Not a member of chat <y>{chat_username}</y>. Joining...")
                    await asyncio.sleep(randint(100, 200))
                    try:
                        chat = await self.tg_client.join_chat(parsed_link)
                        chat_id = chat.id
                        logger.info(f"{self.session_name} | Successfully joined chat <y>{chat_username}</y>")
                        await asyncio.sleep(random.randint(5, 10))
                        peer = await self.tg_client.resolve_peer(chat_id)
                        await self.tg_client.invoke(account.UpdateNotifySettings(
                            peer=InputNotifyPeer(peer=peer),
                            settings=InputPeerNotifySettings(mute_until=2147483647)
                        ))
                        logger.info(f"{self.session_name} | Successfully muted chat <y>{chat_username}</y>")
                    except FloodWait as e:
                        logger.warning(f"Flood wait triggered. Waiting for {e.value} seconds.")
                        await asyncio.sleep(e.value)
                else:
                    logger.error(f"{self.session_name} | Error while checking channel: <y>{chat_username}</y>: {str(error.ID)}")

        except FloodWait as e:
            logger.warning(f"{self.session_name} | Flood wait triggered. Waiting for {e.value} seconds.")
            await asyncio.sleep(e.value)

        except Exception as e:
            logger.error(f"{self.session_name} | Error joining/muting channel {link}: {str(e)}")
        
        finally:
            if self.tg_client.is_connected:
                await self.tg_client.disconnect()
            await asyncio.sleep(random.randint(10, 20))

    @error_handler
    async def make_request(self, http_client, method, endpoint=None, url=None, **kwargs):
        full_url = url or f"https://api-web.tomarket.ai/tomarket-game/v1{endpoint or ''}"
        response = await http_client.request(method, full_url, **kwargs)
        return await response.json()
        
    @error_handler
    async def login(self, http_client, tg_web_data: str, ref_id: str) -> tuple[str, str]:
        response = await self.make_request(http_client, "POST", "/user/login", json={"init_data": tg_web_data, "invite_code": ref_id, "from":"","is_bot":False})
        return response.get('data', {}).get('access_token', None)

    @error_handler
    async def check_proxy(self, http_client: aiohttp.ClientSession) -> None:
        response = await self.make_request(http_client, 'GET', url='https://httpbin.org/ip', timeout=aiohttp.ClientTimeout(5))
        ip = response.get('origin')
        logger.info(f"{self.session_name} | Proxy IP: {ip}")

    @error_handler
    async def get_balance(self, http_client):
        return await self.make_request(http_client, "POST", "/user/balance")

    @error_handler
    async def claim_daily(self, http_client):
        return await self.make_request(http_client, "POST", "/daily/claim", json={"game_id": "fa873d13-d831-4d6f-8aee-9cff7a1d0db1"})

    @error_handler
    async def start_farming(self, http_client):
        return await self.make_request(http_client, "POST", "/farm/start", json={"game_id": "53b22103-c7ff-413d-bc63-20f6fb806a07"})

    @error_handler
    async def claim_farming(self, http_client):
        return await self.make_request(http_client, "POST", "/farm/claim", json={"game_id": "53b22103-c7ff-413d-bc63-20f6fb806a07"})

    @error_handler
    async def play_game(self, http_client):
        return await self.make_request(http_client, "POST", "/game/play", json={"game_id": "59bcd12e-04e2-404c-a172-311a0084587d"})

    @error_handler
    async def claim_game(self, http_client, points=None , stars=None):
        return await self.make_request(http_client, "POST", "/game/claim", json={"game_id": "59bcd12e-04e2-404c-a172-311a0084587d", "points": points ,"stars": stars})


    @error_handler
    async def get_tasks(self, http_client,data=None):
        return await self.make_request(http_client, "POST", "/tasks/list", json=data)

    @error_handler
    async def start_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/start", json=data)

    @error_handler
    async def check_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/check", json=data)

    @error_handler
    async def claim_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/claim", json=data)
    @error_handler
    async def get_ticket(self, http_client, data):
        return await self.make_request(http_client, "POST", "/user/tickets", json=data)
    
    @error_handler
    async def play_ticket(self, http_client):
        return await self.make_request(http_client, "POST", "/spin/raffle", json={"category":"ticket_spin_1"})

    @error_handler
    async def get_combo(self, http_client,data=None):
        return await self.make_request(http_client, "POST", "/tasks/puzzle",json=data)
    
    @error_handler
    async def claim_combo(self, http_client,data):
        return await self.make_request(http_client, "POST", "/tasks/puzzleClaim",json=data)

    @error_handler
    async def get_stars(self, http_client):
        return await self.make_request(http_client, "POST", "/tasks/classmateTask")

    @error_handler
    async def start_stars_claim(self, http_client, data):
        return await self.make_request(http_client, "POST", "/tasks/classmateStars", json=data)
    
    @error_handler
    async def check_blacklist(self, http_client, data):
        return await self.make_request(http_client, "POST", "/rank/blacklist", json=data)
    
    @error_handler
    async def check_airdrop(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/check", json=data)

    @error_handler
    async def token_weeks(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/weeks", json=data)
    
    @error_handler
    async def claim_airdrop(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/claim", json=data)
    
    @error_handler
    async def airdrop_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/airdropTasks", json=data)
    
    @error_handler
    async def airdrop_start_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/startTask", json=data)

    @error_handler
    async def airdrop_check_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/checkTask", json=data)

    @error_handler
    async def airdrop_claim_task(self, http_client, data):
        return await self.make_request(http_client, "POST", "/token/claimTask", json=data)
    
    @error_handler
    async def check_toma(self,http_client,data):
        return await self.make_request(http_client, "POST", "/token/tomatoes", json=data)
    
    @error_handler
    async def convert_toma(self, http_client):
        return await self.make_request(http_client, "POST", "/token/tomatoToStar") 
    
    @error_handler
    async def check_season_reward(self,http_client,data):
        return await self.make_request(http_client, "POST", "/token/season", json=data)

    @error_handler
    async def launchpad_list(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/list", json=data)

    @error_handler
    async def launchpad_get_auto_farms(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/getAutoFarms", json=data)

    @error_handler
    async def launchpad_toma_balance(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/tomaBalance", json=data)

    @error_handler
    async def launchpad_tasks(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/tasks", json=data)

    @error_handler
    async def launchpad_task_claim(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/taskClaim", json=data)

    @error_handler
    async def launchpad_invest_toma(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/investToma", json=data)

    @error_handler
    async def launchpad_claim_auto_farm(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/claimAutoFarm", json=data)

    @error_handler
    async def launchpad_start_auto_farm(self, http_client, data):
        return await self.make_request(http_client, "POST", "/launchpad/startAutoFarm", json=data)

    @error_handler
    async def get_puzzle(self, taskId):
        urls = [
            "https://raw.githubusercontent.com/yanpaing007/Tomarket/refs/heads/main/bot/config/combo.json",
            "https://raw.githubusercontent.com/zuydd/database/refs/heads/main/tomarket.json"
        ]
        
        async with aiohttp.ClientSession() as session:
            for idx, url in enumerate(urls):
                repo_type = "main" if idx == 0 else "backup"
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            try:
                                text = await response.text()
                                data = json.loads(text)
                                puzzle = data.get('puzzle', None)
                                code = puzzle.get('code') if puzzle else data.get('code', None)
                                
                                if puzzle and puzzle.get('task_id') == taskId:
                                    logger.success(f"{self.session_name} | Puzzle retrieved successfully from {repo_type} repo: {puzzle}")
                                    return code
                                elif repo_type == "backup":
                                    logger.info(f"{self.session_name} | Puzzle not found even in backup repo,trying from local combo.json...")
                                    get_local = self.get_local_puzzle(taskId)
                                    if get_local:
                                        return get_local
                                    return None
                            except json.JSONDecodeError as json_err:
                                logger.error(f"{self.session_name} - Error parsing JSON from {repo_type} repo: {json_err}")
                        else:
                            logger.error(f"{self.session_name} - Failed to retrieve puzzle from {repo_type} repo. Status code: {response.status}")
                except aiohttp.ClientError as e:
                    logger.error(f"{self.session_name} - Exception occurred while retrieving puzzle from {repo_type} repo: {e}")
        
        logger.info(f"{self.session_name} - Failed to retrieve puzzle from both main and backup repos.")
        return None
    
    def get_local_puzzle(self,taskId):
        try:
            with open('bot/config/combo.json', 'r') as local_file:
                data = json.load(local_file)
                puzzle = data.get('puzzle', None)
                code = puzzle.get('code') if puzzle else None

                if puzzle and puzzle.get('task_id') == taskId:
                    logger.info(f"{self.session_name} - Puzzle retrieved successfully from local file: {puzzle}")
                    return code
                else:
                    logger.info(f"{self.session_name} - Puzzle with {taskId} not found in local file.Please change the task_id and code in combo.json if you knew the code.")
                    return None

        except FileNotFoundError:
            logger.error(f"{self.session_name} - Local file combo.json not found.")
        except json.JSONDecodeError as json_err:
            logger.error(f"{self.session_name} - Error parsing JSON from local file: {json_err}")

        logger.info(f"{self.session_name} - Failed to retrieve puzzle from both main and backup repos, and local file.")
        return None
    
    

    @error_handler
    async def create_rank(self, http_client):
        evaluate = await self.make_request(http_client, "POST", "/rank/evaluate")
        if evaluate and evaluate.get('status', 404) == 0:
            await self.make_request(http_client, "POST", "/rank/create")
            return True
        return False
    
    @error_handler
    async def get_rank_data(self, http_client):
        return await self.make_request(http_client, "POST", "/rank/data")

    @error_handler
    async def upgrade_rank(self, http_client, stars: int):
        return await self.make_request(http_client, "POST", "/rank/upgrade", json={'stars': stars})
    
    @error_handler
    async def name_change(self, emoji: str) -> bool:
        # await asyncio.sleep(random.randint(3, 5))
        if self.proxy:
            proxy = Proxy.from_str(self.proxy)
            proxy_dict = dict(
                scheme=proxy.protocol,
                hostname=proxy.host,
                port=proxy.port,
                username=proxy.login,
                password=proxy.password
            )
        else:
            proxy_dict = None

        self.tg_client.proxy = proxy_dict

        if not self.tg_client.is_connected:
                try:
                    logger.info(f"{self.session_name} | Sleeping 5 seconds before connecting tg_client...")
                    await asyncio.sleep(5)
                    await self.tg_client.connect()

                except (Unauthorized, UserDeactivated, AuthKeyUnregistered):
                    raise InvalidSession(self.session_name)

        try:
            user = await self.tg_client.get_me()
            
            current_name = user.first_name
            logger.info(f"{self.session_name} | Current Name: <y>{current_name}</y>")
            
            new_name = current_name + emoji if emoji not in current_name else current_name
            
            if current_name != new_name:
                try:
                    await self.tg_client.update_profile(first_name=new_name)
                    logger.info(f"{self.session_name} | Name changed to: <y>{new_name}</y>")
                    return True  
                except Exception as e:
                    logger.error(f"{self.session_name} | Error updating {new_name}: {str(e)}")
                    await asyncio.sleep(5)
                    return False
            else:
                logger.info(f"{self.session_name} | Name already contains the emoji.")
                return False

        except Exception as e:
            logger.error(f"{self.session_name} | Error during name change: {str(e)}")
            return False

        finally:
            if self.tg_client.is_connected:
                await asyncio.sleep(5)
                await self.tg_client.disconnect()
            await asyncio.sleep(randint(10, 20))
            
    async def night_sleep(self):
        now = datetime.now()
        start_hour = randint(settings.NIGHT_SLEEP_TIME[0][0], settings.NIGHT_SLEEP_TIME[0][1])
        end_hour = randint(settings.NIGHT_SLEEP_TIME[1][0], settings.NIGHT_SLEEP_TIME[1][1])

        if now.hour >= start_hour or now.hour < end_hour:
            wake_up_time = now.replace(hour=end_hour, minute=randint(0,59), second=randint(0,59), microsecond=0)
            if now.hour >= start_hour:
                wake_up_time += timedelta(days=1)
            sleep_duration = (wake_up_time - now).total_seconds()
            logger.info(f"{self.session_name} |<yellow> Night sleep activated,Bot is going to sleep until </yellow><light-red>{wake_up_time.strftime('%I:%M %p')}</light-red>.")
            await asyncio.sleep(sleep_duration)
    
    async def run(self) -> None:        
        if settings.USE_RANDOM_DELAY_IN_RUN:
            random_delay = randint(settings.RANDOM_DELAY_IN_RUN[0], settings.RANDOM_DELAY_IN_RUN[1])
            logger.info(f"{self.tg_client.name} | Bot will start in <light-red>{random_delay}s</light-red>")
            await asyncio.sleep(delay=random_delay)
       
            
        proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
        http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
        if self.proxy:
            await self.check_proxy(http_client=http_client)
        
        if settings.FAKE_USERAGENT:            
            http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')


        end_farming_dt = 0
        token_expiration = 0
        tickets = 0
        next_combo_check = 0
        next_check_time = None
        
        while True:
            try:
                if check_base_url() is False:
                        logger.warning(f"{self.session_name} | <yellow>API might have changed.Retrying in 10 minutes...</yellow>")
                        logger.info(f"{self.session_name} | <light-red>Sleep 10m</light-red>")
                        await asyncio.sleep(600)
                        continue
                if http_client.closed:
                    if proxy_conn:
                        if not proxy_conn.closed:
                            proxy_conn.close()

                    proxy_conn = ProxyConnector().from_url(self.proxy) if self.proxy else None
                    http_client = aiohttp.ClientSession(headers=headers, connector=proxy_conn)
                    if settings.FAKE_USERAGENT:            
                        http_client.headers['User-Agent'] = generate_random_user_agent(device_type='android', browser_type='chrome')
                current_time = time()
                if current_time >= token_expiration:
                    if (token_expiration != 0):
                        logger.info(f"{self.session_name} | <yellow>Token expired, refreshing...</yellow>")
                    ref_id, init_data = await self.get_tg_web_data()
                    
                    access_token = await self.login(http_client=http_client, tg_web_data=init_data, ref_id=ref_id)
                    
                if not access_token:
                    logger.error(f"{self.session_name} | <light-red>Failed login</light-red>")
                    logger.info(f"{self.session_name} | Sleep <light-red>300s</light-red>")
                    await asyncio.sleep(delay=300)
                    continue
                else:
                    logger.info(f"{self.session_name} | <green>🍅 Login successful!</green>")
                    http_client.headers["Authorization"] = f"{access_token}"
                    token_expiration = time() + 3600
                await asyncio.sleep(delay=1)
                
                balance = await self.get_balance(http_client=http_client)
                if 'data' not in balance:
                    if balance.get('status') == 401:
                        logger.info(f"{self.session_name} | Access Denied. Re-authenticating...")
                        ref_id, init_data = await self.get_tg_web_data()
                        access_token = await self.login(http_client=http_client, tg_web_data=init_data, ref_id=ref_id)
                        if not access_token:
                            logger.error(f"{self.session_name} | <light-red>Failed login</light-red>")
                            logger.info(f"{self.session_name} | Sleep <light-red>300s</light-red>")
                            await asyncio.sleep(300)
                            continue
                        else:
                            logger.info(f"{self.session_name} | <green>🍅 Login successful</green>")
                            http_client.headers["Authorization"] = f"{access_token}"
                            token_expiration = time() + 3600
                            balance = await self.get_balance(http_client=http_client)
                    else:
                        logger.error(f"{self.session_name} | Balance response missing 'data' key: {balance}")
                        continue

                available_balance = balance['data'].get('available_balance', 0)
                logger.info(f"{self.session_name} | Current balance | <light-red>{available_balance} 🍅</light-red>")
                ramdom_end_time = randint(1500, 3580)
                if 'farming' in balance['data']:
                    end_farm_time = balance['data']['farming']['end_at']
                    if end_farm_time > time():
                        end_farming_dt = end_farm_time + ramdom_end_time
                        logger.info(f"{self.session_name} | Farming in progress, next claim in <light-red>{round((end_farming_dt - time()) / 60)}m.</light-red>")

                if time() > end_farming_dt:
                    claim_farming = await self.claim_farming(http_client=http_client)
                    if claim_farming and 'status' in claim_farming:
                        if claim_farming.get('status') == 500:
                            start_farming = await self.start_farming(http_client=http_client)
                            if start_farming and 'status' in start_farming and start_farming['status'] in [0, 200]:
                                logger.success(f"{self.session_name} | Farm started.. 🍅")
                                end_farming_dt = start_farming['data']['end_at'] + ramdom_end_time
                                logger.info(f"{self.session_name} | Next farming claim in <light-red>{round((end_farming_dt - time()) / 60)}m.</light-red>")
                        elif claim_farming.get('status') == 0:
                            farm_points = claim_farming['data']['claim_this_time']
                            logger.success(f"{self.session_name} | Success claim farm. Reward: <light-red>+{farm_points}</light-red> 🍅")
                            start_farming = await self.start_farming(http_client=http_client)
                            if start_farming and 'status' in start_farming and start_farming['status'] in [0, 200]:
                                logger.success(f"{self.session_name} | Farm started.. 🍅")
                                end_farming_dt = start_farming['data']['end_at'] + ramdom_end_time
                                logger.info(f"{self.session_name} | Next farming claim in <light-red>{round((end_farming_dt - time()) / 60)}m.</light-red>")
                    await asyncio.sleep(1.5)


                if settings.AUTO_DAILY_REWARD and (next_check_time is None or datetime.now() > next_check_time):
                    claim_daily = await self.claim_daily(http_client=http_client)
                    if claim_daily and 'status' in claim_daily and claim_daily.get("status", 400) != 400:
                        logger.success(f"{self.session_name} | Daily: <light-red>{claim_daily['data']['today_game']}</light-red> reward: <light-red>{claim_daily['data']['today_points']}</light-red>")
                    next_check_time = next_daily_check()
                    logger.info(f"{self.session_name} | Next daily check in <light-red>{next_check_time}</light-red>")

                await asyncio.sleep(1.5)

                if settings.AUTO_PLAY_GAME:
                    ticket = await self.get_balance(http_client=http_client)
                    tickets = ticket.get('data', {}).get('play_passes', 0)
                    logger.info(f"{self.session_name} | Game Play Tickets: {tickets} 🎟️")

                    await asyncio.sleep(1.5)
                    if tickets > 0:
                        logger.info(f"{self.session_name} | Start ticket games...")
                        games_points = 0
                        retry_count = 0
                        max_retries = 5
                        if settings.PLAY_RANDOM_GAME:
                            if  tickets > settings.PLAY_RANDOM_GAME_COUNT[1]: 
                                tickets = randint(settings.PLAY_RANDOM_GAME_COUNT[0], settings.PLAY_RANDOM_GAME_COUNT[1])
                                logger.info(f"{self.session_name} | Playing with: {tickets} 🎟️ this round")
                            

                        while tickets > 0:
                            logger.info(f"{self.session_name} | Starting game...,Tickets remaining: {tickets} 🎟️")
                           
                            play_game = await self.play_game(http_client=http_client)
                            if play_game and 'status' in play_game:
                                    stars_amount = play_game.get('data', {}).get('stars', 0)
                                    if play_game.get('status') == 0:
                                        await asyncio.sleep(30)  
                                        
                                        claim_game = await self.claim_game(http_client=http_client, points=randint(settings.POINTS_COUNT[0], settings.POINTS_COUNT[1]), stars=stars_amount)
                                        
                                        if claim_game and 'status' in claim_game:
                                            if claim_game['status'] == 500 and claim_game['message'] == 'game not start':
                                                retry_count += 1
                                                if retry_count >= max_retries:
                                                    logger.warning(f"{self.session_name} | Max retries reached, stopping game attempts.")
                                                    break
                                                logger.info(f"{self.session_name} | Game not started, retrying...")
                                                continue

                                            if claim_game.get('status') == 0:
                                                games_points += claim_game.get('data', {}).get('points', 0)
                                                logger.success(f"{self.session_name} | Game Finished! Claimed points: <light-red>+{claim_game.get('data', {}).get('points', 0)} </light-red> 🍅 | Stars: <cyan>+{claim_game.get('data', {}).get('stars', 0)}</cyan> ⭐")
                                                await asyncio.sleep(randint(3, 5))
                            tickets -= 1
                            ticket = await self.get_balance(http_client=http_client)
                            check_ticket = ticket.get('data', {}).get('play_passes', 0)
                            if check_ticket and check_ticket == 0:
                                logger.info(f"{self.session_name} | No more tickets available!")
                                break

                        logger.info(f"{self.session_name} | All Games finished! Total claimed points: <light-red>{games_points} 🍅</light-red>")

                if settings.AUTO_TASK:
                    logger.info(f"{self.session_name} | Start checking tasks.")
                    tasks = await self.get_tasks(http_client=http_client, data={"language_code":"en", "init_data":init_data})
                    tasks_list = []

                    if tasks and tasks.get("status", 500) == 0:
                        for category, task_group in tasks["data"].items():
                            if isinstance(task_group, list):
                                for task in task_group:
                                    if isinstance(task, dict):  
                                        if task.get('enable') and not task.get('invisible', False) and task.get('status') != 3:
                                            if task.get('taskId') in [10099,10080,10134,10099,10186]:
                                                continue
                                            if task.get('startTime') and task.get('endTime'):
                                                task_start = convert_to_local_and_unix(task['startTime'])
                                                task_end = convert_to_local_and_unix(task['endTime'])
                                        
                                                if task_start <= time() <= task_end  and task.get('type') not in ['charge_stars_season2', 'chain_donate_free','daily_donate','new_package','charge_stars_season3','medal_donate']:
                                                    tasks_list.append(task)
                                            
                                            elif task.get('type') not in ['wallet', 'mysterious', 'classmate', 'classmateInvite', 'classmateInviteBack', 'charge_stars_season2','chain_donate_free','daily_donate','charge_stars_season3','medal_donate']:
                                                tasks_list.append(task)
                                        if task.get('type') == 'youtube' and task.get('status') != 3:
                                            tasks_list.append(task)
                            elif isinstance(task_group, dict):  
                                for group_name, group_tasks in task_group.items():
                                    if isinstance(group_tasks, list):
                                        for task in group_tasks:
                                            if task.get('enable') or not task.get('invisible', False):
                                                if task.get('taskId') in [10099,10080,10134,10099,10186]:
                                                   continue
                    
                                                tasks_list.append(task)
                    if len(tasks_list) == 0:
                        logger.info(f"{self.session_name} | No tasks available.")
                    else:
                        logger.info(f"{self.session_name} | Tasks collected: {len(tasks_list)}")
                    for task in tasks_list:
                        wait_second = task.get('waitSecond', 0)
                        claim = None
                        check = None
                        
                        if task.get('type') == 'emoji' and settings.AUTO_TASK: # Emoji task
                                logger.info(f"{self.session_name} | Start task <light-red>{task['name']}.</light-red> Wait {30}s 🍅")
                                await asyncio.sleep(30)
                                await self.name_change(emoji='🍅')
        
                                starttask = await self.start_task(http_client=http_client, data={'task_id': task['taskId'],'init_data':init_data})
                                await asyncio.sleep(3)
                                check = await self.check_task(http_client=http_client, data={'task_id': task['taskId'], 'init_data': init_data})
                                await asyncio.sleep(3)
                                if check:
                                    logger.info(f"{self.session_name} | Task <light-red>{task['name']}</light-red> checked! 🍅")
                                    claim = await self.claim_task(http_client=http_client, data={'task_id': task['taskId']})
                        else:
                            starttask = await self.start_task(http_client=http_client, data={'task_id': task['taskId'],'init_data':init_data})
                            task_data = starttask.get('data', {}) if starttask else None
                            if task_data == 'ok' or task_data.get('status') == 1 or task_data.get('status') ==2 if task_data else False:
                                logger.info(f"{self.session_name} | Start task <light-red>{task['name']}.</light-red> Wait {wait_second}s 🍅")
                                await asyncio.sleep(wait_second + 3)
                                await self.check_task(http_client=http_client, data={'task_id': task['taskId'],'init_data':init_data})
                                await asyncio.sleep(3)
                                claim = await self.claim_task(http_client=http_client, data={'task_id': task['taskId']})
                        if claim:
                                if claim['status'] == 0:
                                    reward = task.get('score', 'unknown')
                                    logger.success(f"{self.session_name} | Task <light-red>{task['name']}</light-red> claimed! Reward: {reward} 🍅")
                                else:
                                    logger.info(f"{self.session_name} | Task <light-red>{task['name']}</light-red> not claimed. Reason: {claim.get('message', 'Unknown error')}")
                        await asyncio.sleep(2)

                await asyncio.sleep(3)

                if await self.create_rank(http_client=http_client):
                    logger.success(f"{self.session_name} | Rank created! 🍅")
                
                if settings.AUTO_RANK_UPGRADE:
                    rank_data = await self.get_rank_data(http_client=http_client)
                    unused_stars = rank_data.get('data', {}).get('unusedStars', 0)
                    current_rank = rank_data.get('data', {}).get('currentRank', "Unknown rank").get('name', "Unknown rank")
                    
                    try:
                        unused_stars = int(float(unused_stars)) 
                    except ValueError:
                        unused_stars = 0
                    logger.info(f"{self.session_name} | Unused stars {unused_stars} ⭐")
                    if unused_stars > 0:
                        upgrade_rank = await self.upgrade_rank(http_client=http_client, stars=unused_stars)
                        if upgrade_rank.get('status', 500) == 0:
                            logger.success(f"{self.session_name} | Rank upgraded! 🍅")
                        else:
                            logger.info(
                                f"{self.session_name} | Rank not upgraded. Reason: <light-red>{upgrade_rank.get('message', 'Unknown error')}</light-red>")
                    if current_rank:
                        logger.info(f"{self.session_name} | Current rank: <cyan>{current_rank}</cyan>")
                        
                await asyncio.sleep(1.5)
                            
                            
                            
                if settings.AUTO_CLAIM_COMBO and next_combo_check < time():
                    combo_info = await self.get_combo(http_client, data={"language_code": "en", "init_data": init_data})

                    if combo_info is None or not isinstance(combo_info, dict):
                        logger.error(f"{self.session_name} | Failed to retrieve combo info | Response: {combo_info}")
                        return
                    
                    combo_info_data = combo_info.get('data', [None])[0]
                    if not combo_info_data:
                        logger.error(f"{self.session_name} | Combo info data is missing or invalid!")
                        return

                    start_time = combo_info_data.get('startTime')
                    end_time = combo_info_data.get('endTime')
                    status = combo_info_data.get('status')
                    task_id = combo_info_data.get('taskId')
                    task_type = combo_info_data.get('type')

                    if combo_info.get('status') == 0 and combo_info_data is not None:
                        if status > 0:
                            logger.info(f"{self.session_name} | Daily Combo already claimed.")
                            try:
                                next_combo_check = int(datetime.fromisoformat(end_time).timestamp())
                                logger.info(f"{self.session_name} | Next combo check in <light-red>{round((next_combo_check - time()) / 60)}m.</light-red>")
                            except ValueError as ve:
                                logger.error(f"{self.session_name} | Error parsing combo end time: {end_time} | Exception: {ve}")

                        try:
                            combo_end_time = datetime.fromisoformat(end_time)
                            if status == 0 and combo_end_time > datetime.now():
                                star_amount = combo_info_data.get('star')
                                games_token = combo_info_data.get('games')
                                tomato_token = combo_info_data.get('score')

                                
                                payload =await self.get_puzzle(task_id)
                                if payload is None:
                                    logger.warning(f"{self.session_name} | Failed to retrieve puzzle payload,puzzle might expire! Raise an issue on the GitHub repository.")
                                else:

                                    combo_json = {"task_id": task_id, "code": payload}
                
                                    claim_combo = await self.claim_combo(http_client, data=combo_json)
                                    if (claim_combo is not None and 
                                        claim_combo.get('status') == 0 and 
                                        claim_combo.get('message') == '' and 
                                        isinstance(claim_combo.get('data'), dict) and 
                                        not claim_combo['data']):
                                        
                                        logger.success(
                                            f"{self.session_name} | Claimed combo | Stars: +{star_amount} ⭐ | Games Token: +{games_token} 🎟️ | Tomatoes: +{tomato_token} 🍅"
                                        )

                                        next_combo_check = int(combo_end_time.timestamp())
                                        logger.info(f"{self.session_name} | Next combo check in <light-red>{round((next_combo_check - time()) / 60)}m.</light-red>")
                                    else:
                                        logger.info(f"{self.session_name} | Combo not claimed. Reason: <light-red>{claim_combo.get('message', 'Unknown error')}</light-red>")

                        except ValueError as ve:
                            logger.error(f"{self.session_name} | Error parsing combo end time: {end_time} | Exception: {ve}")
                        except Exception as e:
                            logger.error(f"{self.session_name} | An error occurred while processing the combo: {e}")

                    await asyncio.sleep(1.5)
                    
                # is_first_run = True
                # if is_first_run:
                #     logger.info(f"{self.session_name} | Performing TGE:Step-4...")
                #     await asyncio.sleep(randint(15, 25))
                #     await self.join_and_mute_tg_channel(link="https://t.me/tomarket_ai")
                #     is_first_run = False
                #     await asyncio.sleep(5)
                          
                if settings.AUTO_RAFFLE:
                    tickets = await self.get_ticket(http_client=http_client, data={"language_code":"en","init_data":init_data})
                    if tickets and tickets.get('status', 500) == 0:
                        tickets = tickets.get('data', {}).get('ticket_spin_1', 0)
                        
                        if tickets > 0:
                            logger.info(f"{self.session_name} | Raffle Tickets: <light-red>{tickets} 🎟️</light-red>")
                            logger.info(f"{self.session_name} | Start ticket raffle...")
                            while tickets > 0:
                                play_ticket = await self.play_ticket(http_client=http_client)
                                if play_ticket and play_ticket.get('status', 500) == 0:
                                    results = play_ticket.get('data', {}).get('results', [])
                                    if results:
                                        raffle_result = results[0]  # Access the first item in the list
                                        amount = raffle_result.get('amount', 0)
                                        item_type = raffle_result.get('type', 0)
                                        logger.success(f"{self.session_name} | Raffle result: {amount} | <light-red>{item_type}</light-red>")
                                    tickets -= 1
                                    await asyncio.sleep(5)
                            logger.info(f"{self.session_name} | Raffle finish! 🍅")
                        else:
                            logger.info(f"{self.session_name} | No raffle tickets available!")
                            
                await asyncio.sleep(1.5)
                            
                            
                if settings.AUTO_CLAIM_AIRDROP:
                    airdrop_check = await self.check_airdrop(http_client=http_client, data={"language_code":"en","init_data":init_data,"round":"One"})
                    if airdrop_check and airdrop_check.get('status', 500) == 0:
                        token_weeks = await self.token_weeks(http_client=http_client,
                                                             data={"language_code": "en", "init_data": init_data})
                        round_names = [item['round']['name'] for item in token_weeks['data'] if not item['claimed'] and int(float(item['stars'])) > 0]
                        logger.info(f"{self.session_name} | Effective claim round:{round_names}.") if round_names else logger.info(f"{self.session_name} | No Weekly airdrop available to claim.")
                        for round_name in round_names:
                            claim_airdrop = await self.claim_airdrop(http_client=http_client,
                                                                     data={"round": f"{round_name}"})
                            if claim_airdrop and claim_airdrop.get('status', 500) == 0:
                                logger.success(
                                    f"{self.session_name} | Airdrop claimed! Token: <light-red>+{claim_airdrop.get('data', {}).get('amount', 0)} TOMA</light-red> 🍅")
                            else:
                                logger.error(
                                    f"{self.session_name} | Airdrop not claimed. Reason: {claim_airdrop.get('message', 'Unknown error')}")
                            await asyncio.sleep(randint(3, 5))
                await asyncio.sleep(randint(3, 5))
                                
                if settings.AUTO_AIRDROP_TASK:
                    airdrop_task = await self.airdrop_task(http_client=http_client, data={"language_code":"en","init_data":init_data,"round":"One"})
                    if airdrop_task and airdrop_task.get('status', 500) == 0:
                        
                        task_list = airdrop_task.get('data', [])
                        if isinstance(task_list, list):
                            for task in task_list:
                               
                                if not isinstance(task, dict):
                                    continue
                                    
                                current_counter = int(task.get('currentCounter', 0))  
                                check_counter = int(task.get('checkCounter', 0))     
                                current_round = str(task.get('round', 'Unknown'))
                                name = str(task.get('name', 'Unknown'))
                                task_id = task.get('taskId')
                                status = int(task.get('status', 500))
                            
                                if current_round == 'One':
                                    if status == 0:
                                        start_task = await self.airdrop_start_task(http_client=http_client, data={"task_id": task_id,"round":"One"})
                                        if start_task and start_task.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Airdrop task <light-red>{name}</light-red> started!")
                                        await asyncio.sleep(randint(5, 8))
                                    elif status == 1:
                                        check_task = await self.airdrop_check_task(http_client=http_client, data={"task_id": task_id,"round":"One"})
                                        if check_task and check_task.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Airdrop task <light-red>{name}</light-red> checked!")
                                        await asyncio.sleep(randint(5, 8))
                                    elif status == 2 and current_counter == check_counter:
                                    # elif status == 2:
                                        claim_task = await self.airdrop_claim_task(http_client=http_client, data={"task_id": task_id,"round":"One"})
                                        if claim_task and claim_task.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Airdrop task <light-red>{name}</light-red> claimed!")
                                        else:
                                            logger.error(f"{self.session_name} | Failed to claim task <light-red>{name}</light-red>. Response: {claim_task}")
                                        await asyncio.sleep(randint(5, 8))
                            
                    else:
                        logger.error(f"{self.session_name} | Failed to get airdrop tasks. Reason: {airdrop_task.get('message', 'Unknown error')}")
                await asyncio.sleep(randint(3, 5))

                if settings.AUTO_LAUNCHPAD_AND_CLAIM:
                    try:
                        logger.info(f"{self.session_name} | Getting launchpad info...")
                        farms = await self.launchpad_get_auto_farms(http_client=http_client, data={})
                        farms_hash = {}
                        if farms and farms.get('status', 500) == 0:
                            farms_hash = {farm['launchpad_id']: farm for farm in farms.get('data', [])}

                        launchpad_list = await self.launchpad_list(http_client=http_client,
                                                                   data={"language_code": "en", "init_data": init_data})

                        if launchpad_list and launchpad_list.get('status', 500) == 0:
                            for farm in launchpad_list.get('data', []):
                                status = farm.get('status', 0)
                                settleStatus = farm.get('settleStatus', 0)

                                if settleStatus == 1 and status == 2:
                                    can_claim = float(farms_hash.get(farm.get('id')).get('can_claim'))
                                    if can_claim > 0:
                                        claim_auto_farm = await self.launchpad_claim_auto_farm(http_client=http_client,
                                                                                               data={
                                                                                                   'launchpad_id': farm.get(
                                                                                                       'id')})
                                        if claim_auto_farm and claim_auto_farm.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Claim auto farm successfully!")
                                        else:
                                            logger.error(
                                                f"{self.session_name} | Failed to claim auto farm. Reason: {claim_auto_farm.get('message', 'Unknown error')}")
                                        await asyncio.sleep(randint(1, 3))

                                if settleStatus != 1 or status != 1:
                                    continue
                                tasks = await self.launchpad_tasks(http_client=http_client,
                                                                   data={'launchpad_id': farm.get('id')})
                                if tasks and tasks.get('status', 500) != 0:
                                    continue

                                first_farming = False
                                for task in tasks.get('data', []):
                                    if task.get('status') != 3:
                                        task_claim = await self.launchpad_task_claim(http_client=http_client, data={
                                            'launchpad_id': farm.get('id'), 'task_id': task.get('taskId')})
                                        if task_claim and task_claim.get('status', 500) == 0 and task_claim.get(
                                                'data', {}).get('success', False):
                                            first_farming = True
                                            logger.success(
                                                f"{self.session_name} | claimed launchpad task.")
                                        else:
                                            logger.error(
                                                f"{self.session_name} | Failed to claim launchpad task. Reason: {task_claim.get('message', 'Unknown error')}")
                                        await asyncio.sleep(randint(3, 5))
                                await asyncio.sleep(randint(30, 35))
                                toma_balance = await self.launchpad_toma_balance(http_client=http_client,
                                                                                 data={"language_code": "en",
                                                                                       "init_data": init_data})
                                balance = float(
                                    toma_balance.get('data', {}).get('balance', 0) if toma_balance and toma_balance.get(
                                        'status', 500) == 0 else 0)
                                invest_toma_amount = balance if balance >= float(farm.get('minInvestToma')) else 0
                                await asyncio.sleep(randint(1, 3))
                                if first_farming:
                                    invest_toma = await self.launchpad_invest_toma(http_client=http_client,
                                                                                   data={'launchpad_id': farm.get('id'),
                                                                                         'amount': invest_toma_amount})
                                    if invest_toma and invest_toma.get('status', 500) == 0:
                                        logger.success(
                                            f"{self.session_name} | Invest toma {invest_toma_amount} completed!")
                                    else:
                                        logger.error(
                                            f"{self.session_name} | Failed to invest toma. Reason: {invest_toma.get('message', 'Unknown error')}")
                                    await asyncio.sleep(randint(1, 3))
                                    start_auto_farm = await self.launchpad_start_auto_farm(http_client=http_client,
                                                                                           data={
                                                                                               'launchpad_id': farm.get(
                                                                                                   'id')})
                                    if start_auto_farm and start_auto_farm.get('status', 500) == 0:
                                        logger.success(f"{self.session_name} | Start auto toma successfully!")
                                    else:
                                        logger.error(
                                            f"{self.session_name} | Failed to start auto toma. Reason: {start_auto_farm.get('message', 'Unknown error')}")
                                else:
                                    can_claim = float(farms_hash.get(farm.get('id')).get('can_claim'))
                                    end_at = float(farms_hash.get(farm.get('id')).get('end_at'))
                                    logger.info(
                                        f"{self.session_name} | current_time: {current_time}s, launchpad_end_at: {end_at}s")
                                    if current_time > end_at:
                                        await asyncio.sleep(randint(1, 3))
                                        claim_auto_farm = await self.launchpad_claim_auto_farm(http_client=http_client,
                                                                                               data={
                                                                                                   'launchpad_id': farm.get(
                                                                                                       'id')})
                                        if claim_auto_farm and claim_auto_farm.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Claim auto farm successfully!")
                                            can_claim = 0
                                        else:
                                            logger.error(
                                                f"{self.session_name} | Failed to claim auto farm. Reason: {claim_auto_farm.get('message', 'Unknown error')}")
                                    if can_claim <= 0:
                                        await asyncio.sleep(randint(1, 3))
                                        start_auto_farm = await self.launchpad_start_auto_farm(http_client=http_client,
                                                                                               data={
                                                                                                   'launchpad_id': farm.get(
                                                                                                       'id')})
                                        if start_auto_farm and start_auto_farm.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Start auto toma successfully!")
                                        else:
                                            logger.error(
                                                f"{self.session_name} | Failed to start auto toma. Reason: {start_auto_farm.get('message', 'Unknown error')}")
                                    if invest_toma_amount >= 10000:
                                        invest_toma = await self.launchpad_invest_toma(http_client=http_client,
                                                                                       data={'launchpad_id': farm.get(
                                                                                           'id'),
                                                                                           'amount': invest_toma_amount})
                                        if invest_toma and invest_toma.get('status', 500) == 0:
                                            logger.success(
                                                f"{self.session_name} | Invest toma {invest_toma_amount} completed!")
                                        else:
                                            logger.error(
                                                f"{self.session_name} | Failed to invest toma. Reason: {invest_toma.get('message', 'Unknown error')}")
                                        await asyncio.sleep(randint(1, 3))
                        logger.info(f"{self.session_name} | No launchpad available...")
                    except Exception as e:
                        logger.error(f"{self.session_name} | Error:{e}")

                await asyncio.sleep(randint(3, 5))
                
                if settings.AUTO_CONVERT_TOMA:
                    check_toma = await self.check_toma(http_client=http_client, data={"language_code":"en","init_data":init_data})
                    check_toma_status = check_toma.get('status', 500) if check_toma else 500
                    check_toma_message = check_toma.get('message', 'Unknown error') if check_toma else 'Unknown error'
                    check_toma_balance = int(float(check_toma.get('data', {}).get('balance', 0) if check_toma and check_toma.get('data', {}) else 0))
                    
                    
                    if check_toma and check_toma_status == 0:
                        if check_toma_balance > 21000 and check_toma_balance >= randint(settings.MIN_BALANCE_BEFORE_CONVERT[0], settings.MIN_BALANCE_BEFORE_CONVERT[1]):
                            logger.info(f"{self.session_name} | Available TOMA balance to convert: <light-red>{check_toma_balance} 🍅</light-red>")
                            
                            convert_toma = await self.convert_toma(http_client=http_client)
                            if convert_toma and convert_toma.get('status', 500) == 0 and convert_toma.get('data', {}).get('success', False):
                                logger.success(f"{self.session_name} | Converted <light-red>TOMA</light-red> 🍅")
                            else:
                                logger.error(f"{self.session_name} | Failed to convert TOMA. Reason: {convert_toma.get('message', 'Unknown error')}")
                                
                        check_season_reward = await self.check_season_reward(http_client=http_client, data={"language_code":"en","init_data":init_data})
                        if check_season_reward and check_season_reward.get('status', 500) == 0:
                            toma_season = check_season_reward.get('data', {}).get('toma', 0)
                            stars_season = check_season_reward.get('data', {}).get('stars', 0)
                            isCurrent = check_season_reward.get('data',{}).get('isCurrent',True)
                            is_claimed = check_season_reward.get('data',{}).get('claimed',True)
                            current_round = check_season_reward.get('data',{}).get('round',{}).get('name')
                            logger.info(f"{self.session_name} | Current Weekly reward: <light-red>+{toma_season}</light-red> Toma 🍅 for <cyan>{stars_season}</cyan> ⭐")
                            
                            if 'tomaAirDrop' and 'status' in check_season_reward.get('data',{}):
                                check_claim_status = check_season_reward.get('data',{}).get('tomaAirDrop',{}).get('status',0)
                                token_claim_amount = int(float(check_season_reward.get('data',{}).get('tomaAirDrop',{}).get('amount',0)))
                                if check_claim_status == 2 and token_claim_amount > 0 and isCurrent is False and not is_claimed:
                                    logger.info(f"{self.session_name} | Claiming Weekly airdrop , <light-red>{token_claim_amount}</light-red> token 🍅...")
                                    claim_weekly_airdrop = await self.claim_airdrop(http_client=http_client,data ={"round":current_round})
                                    if claim_weekly_airdrop and claim_weekly_airdrop.get('status',500) == 0:
                                        logger.success(f"{self.session_name} | Successfully claimed weekly airdrop allocation,<light-red>+{token_claim_amount}</light-red> 🍅")
                                    else:
                                        logger.error(f"{self.session_name} | Failed to claim weekly airdrop,Reason :{claim_weekly_airdrop.get('message','Unkown')}")            
                    else:
                        logger.error(f"{self.session_name} | Failed to check TOMA balance. Reason: {check_toma_message}")
                        
                            
                if settings.AUTO_ADD_WALLET:
                    wallet_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'wallet.json')

                    with open(wallet_file_path, 'r') as wallet_file:
                        wallet_data = json.load(wallet_file)
                        my_address = wallet_data.get(self.session_name, {}).get('address', None)
                        if not my_address:
                            logger.warning(f"{self.session_name} | Wallet address not found for {self.session_name} in wallet.json")
                        else:

                            tomarket_wallet = await self.make_request(http_client, "POST", "/tasks/walletTask")
                            if tomarket_wallet and tomarket_wallet.get('status', 500) == 0:
                                server_address = tomarket_wallet.get('data', {}).get('walletAddress', None)
                                if server_address == my_address:
                                    logger.info(f"{self.session_name} | Current wallet address: '{server_address}'!")
                                if server_address == '':
                                    logger.info(f"{self.session_name} | Wallet address '{my_address}' not found in tomarket bot! Trying to add...")
                                    
                                    add_wallet = await self.make_request(http_client, "POST", "/tasks/address", json={"wallet_address": my_address})
                                    if add_wallet and add_wallet.get('status', 500) == 0:
                                        logger.success(f"{self.session_name} | Wallet address '{my_address}' added successfully!")
                                    else:
                                        logger.error(f"{self.session_name} | Failed to add wallet address.Reason: {add_wallet.get('message', 'Unknown error')}")
                                elif server_address != my_address:
                                    logger.info(f"{self.session_name} | Wallet address mismatch! Server: '{server_address}' | Your Address: '{my_address}'")
                                    logger.info(f"{self.session_name} | Trying to remove wallet address...")
                                    remove_wallet = await self.make_request(http_client, "POST", "/tasks/deleteAddress")
                                    if remove_wallet and remove_wallet.get('status', 500) == 0 and remove_wallet.get('data',{}) == 'ok':
                                        logger.success(f"{self.session_name} | Wallet address removed successfully!")
                                        logger.info(f"{self.session_name} | Trying to add wallet address...")
                                        add_wallet = await self.make_request(http_client, "POST", "/tasks/address", json={"wallet_address": my_address})
                                        if add_wallet and add_wallet.get('status', 500) == 0:
                                            logger.success(f"{self.session_name} | Wallet address '{my_address}' added successfully!")
                                        else:
                                            logger.error(f"{self.session_name} | Failed to add wallet address.Reason: {add_wallet.get('message', 'Unknown error')}")
                                    else:
                                        logger.error(f"{self.session_name} | Failed to remove wallet address!") 
                            else:
                                logger.error(f"{self.session_name} | Failed to retrieve wallet information from tomarket bot! Status: {tomarket_wallet.get('status', 'Unknown')}")
                
                tomarket_wallet = await self.make_request(http_client, "POST", "/tasks/walletTask")
                if tomarket_wallet and tomarket_wallet.get('status', 500) == 0:
                    current_address = tomarket_wallet.get('data', {}).get('walletAddress', None)
                    if current_address == '' or current_address is None:
                        logger.info(f"{self.session_name} | Wallet address not found in tomarket bot, add it before OCT 31!")
                    else:
                        logger.info(f"{self.session_name} | Current wallet address: <cyan>'{current_address}'</cyan>")
                        

                sleep_time = end_farming_dt - time()
                logger.info(f'{self.session_name} | Sleep <light-red>{round(sleep_time / 60, 2)}m.</light-red>')
                await asyncio.sleep(sleep_time)
                await http_client.close()
                if proxy_conn:
                    if not proxy_conn.closed:
                        proxy_conn.close()
            except InvalidSession as error:
                raise error

            except Exception as error:
                logger.error(f"{self.session_name} | Unknown error: {error}")
                await asyncio.sleep(delay=3)
                logger.info(f'{self.session_name} | Sleep <light-red>10m.</light-red>')
                await asyncio.sleep(600)
                


async def run_tapper(tg_client: Client, proxy: str | None):
    try:
        await Tapper(tg_client=tg_client, proxy=proxy).run()
    except InvalidSession:
        logger.error(f"{tg_client.name} | Invalid Session")
