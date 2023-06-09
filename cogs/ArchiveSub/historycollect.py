import gui
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Tuple
from .archive_database import HistoryMakers,ChannelArchiveStatus
from database import ServerArchiveProfile
import discord
from queue import Queue
from bot import StatusEditMessage
import utility.formatutil as futil
'''
Collects all messages in non-blacklisted channels, and adds them to the database in batches of 10.

'''
BATCH_SIZE=10
class ArchiveContext:
    def __init__(self, bot, status_mess="", last_stored_time=None, update=False, bot_messages_only=False,
                 user_messages_only=False, total_archived=0,channel_count=0, channel_spot=0, character_len=0, latest_time=None,
                 total_ignored=0):
        self.bot = bot
        self.status_mess = status_mess
        self.last_stored_time = last_stored_time
        self.update = update
        self.bot_messages_only = bot_messages_only
        self.user_messages_only = user_messages_only
        self.channel_count = channel_count
        self.total_archived=total_archived
        self.channel_spot = channel_spot
        self.character_len = character_len
        self.latest_time = latest_time
        self.total_ignored = total_ignored
    def evaluate_add(self,thisMessage):
        add_check=False
        if self.bot_messages_only and self.user_messages_only:
            add_check=True
        elif self.bot_messages_only: 
            add_check= (thisMessage.author.bot) and (thisMessage.author.id != self.bot.user.id)
        elif self.user_messages_only: 
            add_check= not (thisMessage.author.bot)
        return add_check
    def alter_latest_time(self,new):
        self.latest_time=max(new,self.latest_time)
    async def edit_mess(self,pre='',cname=""):
        place=f"{self.total_archived} messages collected in total.\n",
        text=f"{place}On channel {self.channel_spot}/{self.channel_count},\n {cname},\n Please wait. <a:Loading:812758595867377686>"
        await self.status_mess.editw(min_seconds=15,content=text)


async def iter_hist_messages(cobj:discord.TextChannel, actx:ArchiveContext):

    messages=[]
    mlen=0
    carch=ChannelArchiveStatus.get_by_tc(cobj)
    timev=actx.last_stored_time
    if carch.latest_archive==None:timev=None
    async for thisMessage in cobj.history(after=timev):
        if(thisMessage.created_at<=actx.last_stored_time and actx.update): break 
        add_check=actx.evaluate_add(thisMessage)

        if add_check:
            thisMessage.content=thisMessage.clean_content
            actx.alter_latest_time(thisMessage.created_at.timestamp())
            actx.character_len+=len(thisMessage.content)
            messages.append(thisMessage)
            carch.increment(thisMessage.created_at)
            actx.total_archived+=1
            gui.gprint('now:',actx.total_archived)
            mlen+=1
        else:
            actx.total_ignored+=1
        if(len(messages)%BATCH_SIZE == 0 and len(messages)>0):
            hmes=await HistoryMakers.get_history_message_list(messages)
            messages=[]
        if(mlen%200 == 0 and mlen>0):
            await asyncio.sleep(1)
            await actx.edit_mess(cobj.name)
            #await edittime.invoke_if_time(content=f"{mlen} messages so far in this channel, this may take a moment.   \n On channel {chancount}/{chanlen},\n {cobj.name},\n gathered <a:Loading:812758595867377686>.  This will take a while...")
            #await statusMess.updatew(f"{mlen} messages so far in this channel, this may take a moment.   \n On channel {chancount}/{chanlen},\n {cobj.name},\n gathered <a:Loading:812758595867377686>.  This will take a while...")
    if messages:
        hmes=await HistoryMakers.get_history_message_list(messages)
        messages=[]
    actx.bot.database.commit()
    return messages
async def lazy_grab(cobj:discord.TextChannel, actx:ArchiveContext):
    
    messages=[]
    mlen=0
    carch=ChannelArchiveStatus.get_by_tc(cobj)
    async for thisMessage in cobj.history(limit=100,oldest_first=True,after=carch.latest_archive):
        #if(thisMessage.created_at<=actx.last_stored_time and actx.update): break 
        add_check=actx.evaluate_add(thisMessage)

        if add_check:
            thisMessage.content=thisMessage.clean_content
            actx.alter_latest_time(thisMessage.created_at.timestamp())
            actx.character_len+=len(thisMessage.content)
            messages.append(thisMessage)
            carch.increment(thisMessage.created_at.timestamp())
            actx.total_archived+=1
            mlen+=1
        else:
            actx.total_ignored+=1
        if(len(messages)%BATCH_SIZE == 0 and len(messages)>0):
            hmes=await HistoryMakers.get_history_message_list(messages)
            messages=[]
        if(mlen%200 == 0 and mlen>0):
            await asyncio.sleep(1)
            await actx.edit_mess(cobj.name)
            #await edittime.invoke_if_time(content=f"{mlen} messages so far in this channel, this may take a moment.   \n On channel {chancount}/{chanlen},\n {cobj.name},\n gathered <a:Loading:812758595867377686>.  This will take a while...")
            #await statusMess.updatew(f"{mlen} messages so far in this channel, this may take a moment.   \n On channel {chancount}/{chanlen},\n {cobj.name},\n gathered <a:Loading:812758595867377686>.  This will take a while...")
    if messages:
        hmes=await HistoryMakers.get_history_message_list(messages)
        messages=[]
    return messages
async def collect_server_history(ctx, **kwargs):
        #Collect from desired channels to a point.
        bot=ctx.bot
        channel = ctx.message.channel
        guild=channel.guild
        guildid=guild.id
        profile=ServerArchiveProfile.get_or_new(guildid)

        messages=[]
        statusMessToEdit=await channel.send("I'm getting everything in the given RP channels, this may take a moment!")

        statmess=StatusEditMessage(statusMessToEdit,ctx)
        time=profile.last_archive_time
        print(time)
        await channel.send("Starting at time:{}".format(time.strftime("%B %d, %Y %I:%M:%S %p")))

        if time: time=time.timestamp()
        if time==None: time=1431518400
        last_time=datetime.fromtimestamp(time,timezone.utc)
        new_last_time=last_time.timestamp()
        
        await channel.send("Starting at time:{}".format(last_time.strftime("%B %d, %Y %I:%M:%S %p")))

        chanlen=len(guild.text_channels)

        arch_ctx=ArchiveContext(bot=bot,status_mess=statmess,last_stored_time=last_time,latest_time=new_last_time,channel_count=chanlen,**kwargs)    

        current_channel_count=0
        current_channel_every=max(chanlen//50,1)
        totalcharlen=0
        
        for chan in guild.text_channels:
            arch_ctx.channel_spot+=1
            if profile.has_channel(chan.id)==False and chan.permissions_for(guild.me).view_channel==True and chan.permissions_for(guild.me).read_message_history==True:
                threads=chan.threads
                archived=[]
                async for thread in chan.archived_threads():
                    archived.append(thread)
                threads=threads+archived
                for thread in threads:
                    mess=await iter_hist_messages(thread, arch_ctx)
                    #arch_ctx.alter_latest_time(new_last_time,newtime)
                    messages=messages+mess
                    current_channel_count+=1

                            
                chanmess=await iter_hist_messages(chan, arch_ctx)
                #new_last_time=max(new_last_time,newtime)
                #ignored+=ign
                #totalcharlen+=charlen
                messages=messages+chanmess
                current_channel_count+=1
                await arch_ctx.edit_mess(f"",chan.name)
                if current_channel_count >current_channel_every:
                    await asyncio.sleep(1)
                    
                    #await edittime.invoke_if_time()
                    current_channel_count=0

        if statusMessToEdit!=None: 
            await statusMessToEdit.delete()
        bot.database.commit()
        return messages, arch_ctx.character_len, arch_ctx.latest_time

def check_channel(historychannel:discord.TextChannel) -> Tuple[bool, str]:
    '''Check if the passed in history channel has the needed permissions.'''
    permissions = historychannel.permissions_for(historychannel.guild.me)
    messagableperms=['read_messages','send_messages','manage_messages','manage_webhooks','embed_links','attach_files','add_reactions','external_emojis','external_stickers']
    add="."

    for p, v in permissions:
        if v:
            if p in messagableperms:
                messagableperms.remove(p)
    if len(messagableperms)>0:
        missing=futil.permission_print(messagableperms)
        result=f"I am missing the following permissions for the specified log channel {historychannel.mention}:  {missing}\n  Please update my permissions for this channel."
        return False, result
    return True, "Needed permissions are set in this channel"+add