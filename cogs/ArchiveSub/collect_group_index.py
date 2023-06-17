import asyncio
import gui
from datetime import datetime, timedelta, timezone
from .archive_database import ArchivedRPMessage, ChannelSep, HistoryMakers
from database import DatabaseSingleton
from queue import Queue
from bot import StatusEditMessage
'''

Groups the collected history messages into "ChannelSep" objects, that store the location and time of each set of 
server message.

'''
DEBUG_MODE=False

async def iterate_backlog(backlog,group_id):
    tosend = []
    now=datetime.now()
    while backlog.empty()==False:
        if DEBUG_MODE: gui.gprint(F"Backlog Pass {group_id}:")
        new_backlog=Queue()
        charsinotherbacklog = set()
        current_chana = None
        running = True
        if (datetime.now()-now).total_seconds()>1:
            await asyncio.sleep(0.1)
            now=datetime.now()
        while backlog.empty()==False:
            hm=backlog.get()
            channelind = hm.get_chan_sep()
            if hm.author in charsinotherbacklog and hm.get_chan_sep() == current_chana:
                running=False
                current_chana = 'CHARA_DID_A_SPLIT'
            if current_chana is None:
                group_id += 1
                if DEBUG_MODE: gui.gprint('inb',current_chana,hm.get_chan_sep(),group_id)
                current_chana = channelind
            if channelind == current_chana and running:
                if DEBUG_MODE: gui.gprint('in',current_chana,hm.get_chan_sep(),group_id)
                hm.update(channel_sep_id=group_id)
                HistoryMakers.add_channel_sep_if_needed(hm,group_id)
            else:
                new_backlog.put(hm)
                charsinotherbacklog.add(hm.author)
        if DEBUG_MODE: gui.gprint("Pass complete.")
        DatabaseSingleton('voc').commit()
        

        backlog = new_backlog
    return tosend,group_id

async def do_group(server_id, group_id=0, forceinterval=240, withbacklog=240, maximumwithother=200,ctx=None,glimit=999999999):
    # sort message list by created_at attribute
    print("Running ok.")
    newlist =ArchivedRPMessage().get_messages_without_group(server_id)
    #await asyncio.gather(
    #                    asyncio.to_thread(ArchivedRPMessage().get_messages_without_group,server_id)
    #                )
    length=len(newlist)
    # initialize variables
    tosend, charsinbacklog =  [], set()
    cc_count, current_chana = 0, None
    firsttime = datetime.fromtimestamp(0).replace(tzinfo=timezone.utc)
    
    backlog=Queue()
    status_mess=None

    now=datetime.now()
    # iterate through the sorted message list
    for e,hm in enumerate(newlist):
        if (datetime.now()-now).total_seconds()>1:
                gui.gprint(f"Now at: {e}/{length}, group_id:{group_id}.")
                await asyncio.sleep(0.1)
                now=datetime.now()
        if status_mess: #This will ensure that the script won't have a 'heart attack' while processing large messages.
            gui.gprint(f"Now at: {e}/{length}, group_id:{group_id}.")
            #await status_mess.editw(min_seconds=20,content=f"Now at: {e}/{length}, group_id:{group_id}.")
        if DEBUG_MODE: gui.gprint('i',hm)
        mytime=(hm.created_at).replace(tzinfo=timezone.utc)
        # create string to identify category, channel, thread combo
        chanin = hm.get_chan_sep()
        hm.is_active=False
        #f"{hm.category}-{hm.channel}-{hm.thread}"
        # calculate time elapsed since first message
        timedel = mytime - firsttime
        minutes = timedel.total_seconds() // 60
        
        # check if a new group should be started
        split=False
        if cc_count > maximumwithother and current_chana != chanin:
            split = True
        elif hm.author in charsinbacklog and chanin == current_chana:
            split = True
        elif minutes >= withbacklog and (backlog or chanin != current_chana) or minutes >= forceinterval:
            split = True
        else:
            split = False

        # start a new group if split condition is met
        if split: 
            # add backlog messages to tosend list with new group_id
            
            DatabaseSingleton('voc').commit()
            
            ts, group_id = await iterate_backlog(backlog, group_id)
            await asyncio.sleep(0.1)
            tosend += ts
            # reset backlog and character set
            backlog, charsinbacklog = Queue(), set()
            # reset character count and current channel
            cc_count, current_chana = 0, None
            # set new first time to current message time rounded down to nearest 15-minute interval
            firsttime = mytime - (mytime - datetime.min.replace(tzinfo=timezone.utc)) % timedelta(minutes=15)

        # if current_chana is None, set it to the current channel
        if current_chana is None:
            current_chana = hm.get_chan_sep()
            group_id+=1
            if group_id>glimit:
                
                DatabaseSingleton('voc').commit()
                ts, group_id = iterate_backlog(backlog, group_id)
                tosend += ts
                print('done')
                return -5, group_id
            if DEBUG_MODE: gui.gprint('inb',current_chana,hm.get_chan_sep(),group_id)
            
        # add message to current group if it belongs to the current channel
        
        if chanin == current_chana:
            if DEBUG_MODE: gui.gprint('in',current_chana,hm.get_chan_sep(),group_id)
            hm.update(channel_sep_id=group_id)
            HistoryMakers.add_channel_sep_if_needed(hm,group_id)
            cc_count += 1
        # otherwise add message to backlog and add author to character set
        else:
            backlog.put(hm)
            charsinbacklog.add(hm.author)
    #Commit to database.
    DatabaseSingleton('voc').commit()
    # add remaining backlog messages to tosend list
    
    ts, group_id = await iterate_backlog(backlog, group_id)
    #ChannelSep.derive_channel_seps_mass(server_id)
    tosend += ts

    return length, group_id

    