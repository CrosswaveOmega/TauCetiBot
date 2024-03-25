from collections import defaultdict
from io import BytesIO
from typing import List, Optional, Tuple
import discord

# import datetime


from discord.ext import commands

from discord import app_commands
from assets import AssetLookup
from bot import TC_Cog_Mixin, super_context_menu
import cogs.ResearchAgent as ra

from gptmod.chromatools import ChromaTools
import gptmod.sentence_mem as smem
from utility import WebhookMessageWrapper as web
import gui
from utility.mytemplatemessages import MessageTemplates
from .AICalling import AIMessageTemplates
from langchain.docstore.document import Document
import datetime
from utility.embed_paginator import pages_of_embeds, pages_of_embed_attachments
from utility.debug import Timer
from utility.views import BaseView
from database.database_note import NotebookAux
import base64

async def owneronly(interaction: discord.Interaction):
    return await interaction.client.is_owner(interaction.user)


topictype = app_commands.Range[str, 2, 128]
keytype = app_commands.Range[str, 2, 128]
contenttype = app_commands.Range[str, 5, 4096]

from io import BytesIO

    

async def file_to_data_uri(file: discord.File) -> str:
    # Read the bytes from the file
    with BytesIO(file.fp.read()) as f:
        # Read the bytes from the file-like object
        file_bytes = f.read()
    # Base64 encode the bytes
    base64_encoded = base64.b64encode(file_bytes).decode('ascii')
    # Construct the data URI
    data_uri = f'data:{"image"};base64,{base64_encoded}'
    return data_uri

async def data_uri_to_file(data_uri: str, filename: str) -> discord.File:
    # Split the data URI into its components
    metadata, base64_data = data_uri.split(',')
    # Get the content type from the metadata
    content_type = metadata.split(';')[0].split(':')[1]
    # Decode the base64 data
    file_bytes = base64.b64decode(base64_data)
    # Create a discord.File object
    file = discord.File(BytesIO(file_bytes), filename=filename, spoiler=False)
    return file

class NoteContentModal(discord.ui.Modal, title="Enter Note Contents"):
    """Modal for adding a followup."""

    def __init__(self, *args, content=None, key=None, topic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.done = None
        self.followup_input = discord.ui.TextInput(
            label="Enter Content here.",
            max_length=4000,
            default=content,
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.followup_input)
        self.keyinput = discord.ui.TextInput(
            label="Enter key", max_length=128, default=key, required=True
        )
        self.topicvalue = discord.ui.TextInput(
            label="Enter topic", max_length=128, default=topic, required=True
        )
        self.add_item(self.keyinput)
        self.add_item(self.topicvalue)

    async def on_submit(self, interaction):
        followup = self.followup_input.value
        key = self.keyinput.value
        topic = self.topicvalue.value
        self.done = (followup, key, topic)
        await interaction.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.stop()

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        return await super().on_error(interaction, error)


class NoteEditView(BaseView):
    """
    View that allows one to edit their
    """

    def __init__(self, *, user, timeout=30 * 15, content=None, key=None, topic=None):
        super().__init__(user=user, timeout=timeout)
        self.value = False
        self.mydrop = None
        self.done = None
        self.content = content
        self.key = key
        self.topic = topic

    def make_embed(self):
        embed = discord.Embed(
            description=f"{self.content}"[:4000],
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="topic", value=self.topic)

        embed.add_field(name="key", value=self.key)
        if not self.is_finished():
            embed.add_field(
                name="timeout",
                value=f"timeout in: {discord.utils.format_dt(self.get_timeout_dt(),'R')}",
                inline=False,
            )
        return embed

    async def on_timeout(self) -> None:
        self.value = "timeout"
        self.stop()

    @discord.ui.button(label="Edit note", style=discord.ButtonStyle.primary, row=1)
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = NoteContentModal(
            content=self.content, key=self.key, topic=self.topic, timeout=self.timeout
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.done:
            c, k, t = modal.done
            self.content = c if c is not None else self.content
            self.key = k if k is not None else self.key
            self.topic = t if t is not None else self.topic
            self.update_timeout()
            await interaction.edit_original_response(embed=self.make_embed())
            # await self.note_add_callback(interaction,c,k,t)
        else:
            await interaction.edit_original_response(content="Cancelled")

    @discord.ui.button(label="Complete", style=discord.ButtonStyle.green, row=4)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not (self.content and self.key and self.topic):
            await interaction.response.edit_message(
                content="You are missing the content, key, or topic!",
                embed=self.make_embed(),
            )
        else:
            await interaction.response.edit_message(
                content="Complete", embed=self.make_embed()
            )
            self.value = True
            self.done = (self.content, self.key, self.topic)
            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="Canceled", embed=self.make_embed()
        )
        self.value = False
        self.stop()


class UserNotes:
    def __init__(self, bot, user):
        # dimensions = 384
        self.userid: int = user.id
        metadata = {"desc": "Simple user note taker.  384 dimensions."}
        self.coll = ChromaTools.get_collection(
            f"usernotes_{self.userid}",
            embed=bot.embedding,
            path="saveData/usernotes",
            metadata=metadata,
        )
        self.shortterm = {}

    async def add_to_mem(
        self, ctx: commands.Context, content: str, key: str = "gen", topic: str = "any", file:Optional[discord.File]=None
    ):
        meta = {}
        meta["key"] = key
        meta["foruser"] = self.userid
        meta["topic"] = topic
        meta["value"] = content
        meta["date"] = ctx.message.created_at.timestamp()
        meta['fileuri']=""
        meta['fname']=""
        if file:
            meta['fileuri']=await file_to_data_uri(file)
            meta['fname']=file.filename
        meta["split"] = 1
        to_add = f"Topic: {topic}\n: Key:{key}\nContent:{content}"
        doc = Document(page_content=to_add, metadata=meta)
        docs = [doc]
        ids = [
            f"u:{doc.metadata['foruser']},topic:[{doc.metadata['topic']}],key[{doc.metadata['key']}],sid:[{doc.metadata['split']}]"
            for e, doc in enumerate(docs)
        ]
        if docs:
            self.coll.add_documents(docs, ids)
            await NotebookAux.add(
                self.userid, ids[0], key, topic, ctx.message.created_at
            )
            return doc

    async def search_sim(
        self,
        content: str,
        key: Optional[str] = None,
        topic: Optional[str] = None,
        k: int = 5,
    ) -> Tuple[List[Document], str]:
        """
        Search though chroma collection, and get the k most relevant results.
        """
        persist = "saveData"
        filterwith = {"foruser": self.userid}
        conditions = [{"foruser": self.userid}]
        if key:
            conditions.append({"key": key})
        if topic:
            conditions.append({"topic": topic})

        if len(conditions) > 1:
            filterwith = {"$and": conditions}
        docs = await self.coll.asimilarity_search_with_score_and_embedding(
            content, k=k, filter=filterwith
        )
        docs2 = ((d[0], d[1]) for d in docs)

        new_output = ""
        tosend = []
        for source in docs2:
            tosend.append(source)
            if source.page_content:
                content = smem.indent_string(source.page_content.strip(), 1)
                output = f"*{content}\n"
                new_output += output
        return tosend, new_output

    async def get_note(self, key: Optional[str] = None, topic: Optional[str] = None):
        counts = self.coll._collection.count()
        print("COUNTED UP", counts)
        got = await NotebookAux.get_ids(self.userid, key, topic, offset=0)
        filterwith = {"foruser": self.userid}
        conditions = [{"foruser": self.userid}]
        if key:
            conditions.append({"key": key})
        if topic:
            conditions.append({"topic": topic})

        if len(conditions) > 1:
            filterwith = {"$and": conditions}
        try:
            docs = await self.coll.aget(
                ids=got, where=filterwith, limit=128, include=["documents", "metadatas"]
            )
            docs2 = smem.results_to_docs(docs)
            docs2.sort(key=lambda x: x.metadata["date"], reverse=True)
            return docs2
        except ValueError as e:
            raise e
            return None

    async def get_topics(self):
        filterwith = {"foruser": self.userid}

        try:
            # results = await self.coll.aget(where=filterwith, include=["metadatas"])

            st = await NotebookAux.list_topic(self.userid)
            se = defaultdict(int)
            for m in st:
                topic, count = m
                se[topic] = count
            return se
        except ValueError as e:
            raise e
            return None

    async def get_keys(self):
        filterwith = {"foruser": self.userid}

        try:
            st = await NotebookAux.list_keys(self.userid)

            return st
        except ValueError as e:
            raise e
            return None

    async def delete_note(self, key: Optional[str] = None, topic: Optional[str] = None):
        filterwith = {"foruser": self.userid}
        conditions = [{"foruser": self.userid}]
        if key:
            conditions.append({"key": key})
        if topic:
            conditions.append({"topic": topic})

        try:
            self.coll._collection.delete(where=filterwith)
            await NotebookAux.remove(self.userid, key, topic)

            return True
        except ValueError as e:
            gui.dprint(e)
            return False

    async def delete_user_notes(self, userid):
        try:
            self.coll.delete_collection()
            await NotebookAux.remove(self.userid)
            return True
        except ValueError as e:
            gui.dprint(e)
            return False

    async def note_to_embed(self, doc: Document):
        fil=None
        embed = discord.Embed(
            description=f"{doc.metadata['value']}"[:4000],
            timestamp=datetime.datetime.fromtimestamp(
                doc.metadata["date"], datetime.timezone.utc
            ),
        )
        embed.add_field(name="topic", value=doc.metadata["topic"][:500])
        embed.add_field(name="key", value=doc.metadata["key"][:500])
        if 'fname' in doc.metadata:
            if doc.metadata['fname']:
                fil=await data_uri_to_file(doc.metadata['fileuri'],doc.metadata['fname'])
        return embed, fil

    # async def update_aux(self):


@app_commands.allow_installs(guilds=False, users=True)
class Notes(app_commands.Group, name="notes", description="User Note Commands"):
    pass


class Global(commands.Cog, TC_Cog_Mixin):
    """General commands"""

    def __init__(self, bot: commands.Bot):
        self.helptext = "Some assorted testing commands."
        self.bot = bot
        self.globalonly = True
        self.memehook = AssetLookup.get_asset("memehook", "urls")
        self.usertopics = {}
        self.init_context_menus()

    gnote = Notes()

    @super_context_menu(name="Extracool", flags="user")
    async def coooler(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        cont = message.content
        guild = message.guild
        embed = discord.Embed(description=f"It says *{message.content}")
        if hasattr(message, "author"):
            embed.add_field(
                name="Author", value=f"* {str(message.author)}{type(message.author)}, "
            )

        if hasattr(message, "jump_url"):
            embed.add_field(name="url", value=f"* {str(message.jump_url)}, ")
        if hasattr(message, "channel"):
            embed.add_field(name="channel", value=f"* {str(message.channel)}, ")
            if hasattr(message.channel, "parent"):
                embed.add_field(
                    name="parent", value=f"* {str(message.channel.parent)}, "
                )

        await interaction.response.send_message(
            content="Message details below.",
            ephemeral=True,
            embed=embed,
        )

    @super_context_menu(name="Repost That Meme", flags="user")
    async def memethief(
        self, interaction: discord.Interaction, message: discord.Message
    ) -> None:
        username = interaction.user.display_name
        avatar = str(interaction.user.avatar)
        content = message.content
        embeds = message.embeds

        files = []
        for a in message.attachments:
            this_file = await a.to_file()
            files.append(this_file)
        await web.postMessageAsWebhookWithURL(
            self.memehook,
            message_content=content,
            display_username=username,
            avatar_url=avatar,
            embed=embeds,
            file=files,
        )
        await interaction.response.send_message(
            content="Reposted yer meme!",
            ephemeral=True,
        )

    @super_context_menu(name="usercool", flags="user")
    async def coooler2(
        self, interaction: discord.Interaction, user: discord.User
    ) -> None:
        embed = discord.Embed(description=f"This user is {user}")

        await interaction.response.send_message(
            content="User details below.",
            ephemeral=True,
            embed=embed,
        )

    @app_commands.command(name="search", description="search the interwebs.")
    @app_commands.describe(query="Query to search google with.")
    @app_commands.allow_installs(guilds=True, users=True)
    async def websearch(self, interaction: discord.Interaction, query: str) -> None:
        """Do a web search"""
        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> Searching", ephemeral=True
        )
        results = ra.tools.google_search(ctx.bot, query, 7)
        allstr = ""
        emb = discord.Embed(title=f"Search results {query}")
        readable_links = []

        def indent_string(inputString, spaces=2):
            indentation = " " * spaces
            indentedString = "\n".join(
                [indentation + line for line in inputString.split("\n")]
            )
            return indentedString

        outputthis = f"### Search results for {query} \n\n"
        for r in results["items"]:
            desc = r.get("snippet", "NA")
            allstr += r["link"] + "\n"
            emb.add_field(
                name=f"{r['title'][:200]}",
                value=f"{r['link']}\n{desc}"[:1000],
                inline=False,
            )
            outputthis += f"+ **Title: {r['title']}**\n **Link:**{r['link']}\n **Snippit:**\n{indent_string(desc,1)}"
        await mess.edit(content=None, embed=emb)

    @app_commands.command(name="supersearch", description="use db search.")
    @app_commands.describe(query="Query to search DB for")
    @app_commands.allow_installs(guilds=True, users=True)
    async def doc_talk(self, interaction: discord.Interaction, query: str) -> None:
        """get bot info for this server"""
        owner = await interaction.client.is_owner(interaction.user)
        if not owner:
            await interaction.response.send_message("This command is owner only.")
            return

        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> Searching", ephemeral=True
        )
        try:
            ans, source, _ = await ra.actions.research_op(query, 9)
            emb = discord.Embed(description=ans)
            emb.add_field(name="source", value=str(source)[:1000], inline=False)

            audit = await AIMessageTemplates.add_emb_audit(ctx, embed=emb)

            await mess.edit(content=None, embed=emb)
        except Exception as e:
            await ctx.send("something went wrong...")

    @gnote.command(name="set_topic", description="WIP.  Set your note topic")
    @app_commands.describe(
        topic="The topic to add all notes to unless stated otherwise."
    )
    async def set_topic(
        self, interaction: discord.Interaction, topic: topictype
    ) -> None:
        """get bot info for this server"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        user = interaction.user
        if not user.id in self.usertopics:
            self.usertopics[user.id] = "any"
        self.usertopics[user.id] = topic
        mess = await ctx.send(f"Set your default topic to {topic}.", ephemeral=True)

    @gnote.command(name="add_note", description="WIP.  Add a quick note using key.")
    @app_commands.describe(
        content="Content of your note.",
        key="The key to save your note under.",
        topic="The topic for the key to your note under.  Use set topic to change the default one.",
    )
    async def add_note(
        self,
        interaction: discord.Interaction,
        content: contenttype,
        key: keytype,
        topic: Optional[topictype] = None,
        image: Optional[discord.Attachment]=None
    ) -> None:
        """Add a note."""

        if not topic:
            topic = self.usertopics.get(interaction.user.id, "any")
        ctx: commands.Context = await self.bot.get_context(interaction)
        view = NoteEditView(
            user=interaction.user,
            content=content,
            key=key,
            topic=topic,
            timeout=10 * 60,
        )
        emb = view.make_embed()
        tmes = await ctx.send(
            "Please apply any edits using the Edit Note button, and press complete when you're satisfied!",
            embed=emb,
            view=view,
            ephemeral=True,
        )
        await view.wait()

        if view.done:
            c, k, t = view.done
            fil=None
            if image:
                fil=await image.to_file()
            await tmes.edit(
                content="<a:LoadingBlue:1206301904863502337> adding note...",
                view=None,
                embed=view.make_embed(),
            )
            with Timer() as op_timer:
                notes = UserNotes(self.bot, interaction.user)
                note = await notes.add_to_mem(ctx, c, k, t, file=fil)
                emb, fil = await notes.note_to_embed(note)
                await ctx.send(embed=emb, file=fil, ephemeral=True)
            await tmes.edit(
                content=f"added note in {op_timer.get_time()} seconds", embed=None
            )
        else:
            message = "Cancelled"
            if view.value:
                if view.value == "timeout":
                    message = "You timed out."
            await tmes.edit(content=message, view=None, embed=view.make_embed())

    @gnote.command(
        name="get_note",
        description="WIP.  Get a note under a key/topic pair, or get all notes for any key or topic.",
    )
    @app_commands.describe(
        key="The key the target note was saved under.",
        topic="The topic for the note.  Use set topic to change the default one.",
    )
    async def get_note(
        self,
        interaction: discord.Interaction,
        key: Optional[keytype] = None,
        topic: Optional[topictype] = None,
    ) -> None:
        """get 5 notes"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> getting note", ephemeral=True
        )
        if topic == "any" and interaction.user.id in self.usertopics:
            topic = self.usertopics[interaction.user.id]
        with Timer() as op_timer:
            notes = UserNotes(self.bot, interaction.user)
            docs = await notes.get_note(key, topic)
            embs = []
            for n in docs:
                emb = await notes.note_to_embed(n)
                embs.append(emb)
        await pages_of_embed_attachments(ctx, embs, ephemeral=True)
        await mess.edit(content=f"got notes in {op_timer.get_time()} seconds")

    @gnote.command(
        name="list_topics",
        description="WIP.  List all of your note topics.",
    )
    async def list_topics(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """get 5 notes"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> getting topics", ephemeral=True
        )
        with Timer() as op_timer:
            notes = UserNotes(self.bot, interaction.user)
            docs = await notes.get_topics()
            page = commands.Paginator(prefix=None, suffix=None)
            for k, v in docs.items():
                page.add_line(f"`{k}`:{v}")

            embs = []
            for p in page.pages:
                em = discord.Embed(description=p)
                embs.append(em)
        await pages_of_embeds(ctx, embs, ephemeral=True)
        await mess.edit(content=f"got topics in {op_timer.get_time()} seconds")

    @gnote.command(
        name="list_keys",
        description="WIP.  List all your keys",
    )
    async def list_keys(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """get 5 notes"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> getting topics", ephemeral=True
        )
        with Timer() as op_timer:
            notes = UserNotes(self.bot, interaction.user)
            docs = await notes.get_keys()

            print(docs)

            embs = []
            for k, v in docs.items():
                page = commands.Paginator(prefix=None, suffix=None)
                for s in v:
                    page.add_line(f"* {s}")
                pages = len(page.pages)
                for e, p in enumerate(page.pages):
                    spages = f"{e+1}/{pages}" if pages > 1 else ""
                    em = discord.Embed(title=f"Topic: `{k}` {spages}", description=p)
                    embs.append(em)
        await pages_of_embeds(ctx, embs, ephemeral=True)
        await mess.edit(
            content=f"Retrieved all topics in {op_timer.get_time()} seconds"
        )

    @gnote.command(name="search_notes", description="WIP.  search for a note")
    @app_commands.describe(
        content="Content to search",
        key="Restrict search to notes with this key.",
        topic="Restrict search to notes with this topic.",
    )
    async def search_note(
        self,
        interaction: discord.Interaction,
        content: contenttype,
        key: Optional[keytype] = None,
        topic: Optional[topictype] = None,
    ) -> None:
        """get 5 notes"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        mess = await ctx.send(
            "<a:LoadingBlue:1206301904863502337> getting note", ephemeral=True
        )
        with Timer() as op_timer:
            notes = UserNotes(self.bot, interaction.user)
            docs, pc = await notes.search_sim(content, key, topic)
            embs = []
            for n in docs:
                emb = await notes.note_to_embed(n)
                embs.append(emb)
        await pages_of_embed_attachments(ctx, embs, ephemeral=True)
        await mess.edit(content=f"got notes in {op_timer.get_time()} seconds")

    @gnote.command(name="purge_all_notes", description="Delete all your notes.")
    @app_commands.describe()
    async def purge_notes(self, interaction: discord.Interaction) -> None:
        """get bot info for this server"""

        ctx: commands.Context = await self.bot.get_context(interaction)
        cont, mess = await MessageTemplates.confirm(
            ctx, "Are you sure you want to delete your notes?", True
        )
        if not cont:
            await mess.delete()
        mess = await ctx.send("<a:LoadingBlue:1206301904863502337> deleting all note")
        notes = UserNotes(self.bot, interaction.user)
        await notes.delete_user_notes(interaction.user.id)
        await mess.edit(content="Deleted all your notes.")

    @app_commands.command(name="pingtest", description="ping")
    @app_commands.allow_installs(guilds=True, users=True)
    async def ping(self, interaction: discord.Interaction) -> None:
        """get bot info for this server"""
        await interaction.response.send_message("Reading you loud and clear!")

    @app_commands.command(name="context_test", description="ping")
    @app_commands.allow_installs(users=True)
    async def ping2(self, interaction: discord.Interaction) -> None:
        """get bot info for this server"""
        await interaction.response.send_message("Reading you loud and clear!")


async def setup(bot):
    await bot.add_cog(Global(bot))
