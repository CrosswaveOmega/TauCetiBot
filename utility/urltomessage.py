from typing import Optional, Tuple, Union
import discord
import operator
import asyncio
import csv
from discord.ext import commands, tasks

from discord import Webhook
from pathlib import Path
import json

class LinkError(Exception):
    pass

class BotError(Exception):
    pass
def urlto_gcm_ids(link="")->Tuple[int,int,int]:
    """extract guildid, channelid, and messageid from a link.

    Args:
        link (str, optional): _description_. Defaults to "".

    Raises:
        LinkError: If the passed in link is either not a string or does not contain the needed ids.

    Returns:
        guild
    """
    # Attempt to extract guild, channel, and messageids from url.
    if not isinstance(link, str):
        raise LinkError(f"Link {link} is not a string.")
    linkcontents = link.split('/')
    if len(linkcontents) < 7:
        raise LinkError(f"Link {link} only has {len(linkcontents)} is not valid.")
    guild_id = int(linkcontents[4])
    channel_id = int(linkcontents[5])
    message_id = int(linkcontents[6])
    return guild_id, channel_id, message_id

async def urltomessage(link="", bot=None, partial=False)-> Optional[Union[discord.Message, discord.PartialMessage]]:

    message=None
    try:
        if bot is None:
            raise BotError("Bot was not defined.")
        tup = urlto_gcm_ids(link)
        guild_id, channel_id, message_id = tup
        guild = bot.get_guild(guild_id)
        if guild is None:
            raise BotError("Failed to get guild {guild_id}.")
        channel = guild.get_channel(channel_id)
        if channel is None:
            raise BotError("Failed to get channel {channel_id}.")
        message = None
        try:
            if partial:
                message= channel.get_partial_message(message_id)
            else:
                message = await channel.fetch_message(message_id)
        except discord.errors.NotFound:
            raise BotError("Failed to get message {message_id}, it does not appear to exist.")
    except Exception as e:
        print(e)
        if bot:
            await bot.send_error(e,"URL_TO_MESSAGE_ERROR")
        return None
    return message