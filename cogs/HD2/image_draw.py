import io
import discord
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from .GameStatus import ApiStatus
from .helldive import Planet

CELL_SIZE = 200
from utility.views import BaseView

SCALE = 1.2


def draw_grid(filepath, cell_size=200):
    with Image.open(filepath).convert("RGBA") as img:
        img = img.resize((int(img.width * SCALE), int(img.height * SCALE)))

        overlay2 = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw2 = ImageDraw.Draw(overlay2)
        cell_size = int(CELL_SIZE * SCALE)
        width, height = img.size
        # for x in range(0, width, cell_size):
        #     draw2.line([(x, 0), (x, height)], fill=(255, 255, 255, 60), width=1)
        # for y in range(0, height, cell_size):
        #     draw2.line([(0, y), (width, y)], fill=(255, 255, 255, 60), width=1)
        img = Image.alpha_composite(img, overlay2)
    return img


def get_im_coordinates(x, y):

    coordinate = int(round(x * 1000.0 * SCALE + 1000 * SCALE, 0)), int(
        round(1000 * SCALE - y * 1000.0 * SCALE, 1)
    )
    return coordinate


def draw_supply_lines(img, color=(0, 255, 0, 200), apistat: ApiStatus = None):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for index, planet in apistat.planets.items():
        gpos = planet.position
        x, y = get_im_coordinates(gpos.x, gpos.y)
        waypoints = planet.waypoints
        for ind in waypoints:
            target = apistat.planets[ind]
            tgpos = target.position
            tx, ty = get_im_coordinates(tgpos.x, tgpos.y)
            draw.line(
                [(x, y), (tx, ty)],
                fill=color,
                width=1,
            )
        waypoints = planet.attacking
        for ind in waypoints:
            target = apistat.planets[ind]
            tgpos = target.position
            tx, ty = get_im_coordinates(tgpos.x, tgpos.y)
            draw.line(
                [(x, y), (tx, ty)],
                fill=(255, 0, 0, 200),
                width=3,
            )
    img = Image.alpha_composite(img, overlay)
    return img


def highlight(img, planet: Planet, color=(255, 0, 0, 200), apistat: ApiStatus = None):
    gpos = planet.position
    x, y = gpos.x, gpos.y
    coordinate = get_im_coordinates(x, y)
    task_planets = []
    if apistat:
        for a in apistat.assignments.values():
            assignment = a.get_first()
            task_planets.extend(assignment.get_task_planets())

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    hper = str(planet.health_percent())
    name = str(planet.name).replace(" ", "\n")
    if apistat and apistat.warall:
        for pf in apistat.warall.war_info.planetInfos:
            if pf.index == planet.index:
                name = str(planet.name).replace(" ", "\n")
                hper = f"{pf.sector}:" + str(planet.sector)
                break

    font = ImageFont.truetype("./assets/Michroma-Regular.ttf", 8)
    font2 = ImageFont.truetype("./assets/Michroma-Regular.ttf", 8)
    bbox = draw.textbbox((0, 0), name, font=font, align="center", spacing=0)

    out = 2
    owner = planet.currentOwner.lower()
    colors = {
        "automaton": (254 - 50, 109 - 50, 114 - 50, 200),  # Red
        "terminids": (255 - 50, 193 - 50, 0, 200),  # Yellow
        "humans": (0, 150, 150, 200),  # Cyan-like color
        "illuminate": (150, 0, 150, 200),
    }
    outline = colors[owner]

    if planet.index in task_planets:
        print(task_planets)
        hper = f"{hper}"
        outline = (255, 255, 255)
    bbox2 = draw.textbbox((0, 0), str(hper), font=font2, align="center", spacing=0)
    background_box = [
        coordinate[0] - bbox[2] / 2 - 2,
        coordinate[1] - bbox[3] - 2 - 10,
        coordinate[0] + bbox[2] / 2 + 2,
        coordinate[1] - 10,
    ]

    draw.rectangle(background_box, fill=colors[owner], outline=outline, width=out)
    draw.rectangle(
        (
            [
                background_box[0],
                background_box[3] + 20,
                background_box[0] + bbox2[2] + 2,
                background_box[3] + 20 + bbox2[3] + 2,
            ]
        ),
        fill=colors[owner],
        outline=outline,
    )
    with Image.open("./assets/planet.png").convert("RGBA") as planet:
        img.alpha_composite(planet, (coordinate[0] - 10, coordinate[1] - 10))

    draw.text(
        (coordinate[0] - bbox[2] / 2, coordinate[1] - bbox[3] - 10),
        name,
        fill=(255, 255, 255),
        font=font,
        align="center",
        spacing=0,
    )
    draw.text(
        (background_box[0], background_box[3] + 20),
        hper,
        fill=(255, 255, 255),
        font=font2,
        align="center",
        spacing=0,
    )
    img = Image.alpha_composite(img, overlay)
    return img


def crop_image(image, coordinate, off_by, cell_size=200):
    #return image
    ccr = coordinate
    bc = ccr + off_by + np.array((0, 0))
    uc = ccr - off_by
    left = max(uc[0] * cell_size, 0)
    top = max(uc[1] * cell_size, 0)
    right = min(bc[0] * cell_size, image.width)
    bottom = min(bc[1] * cell_size, image.height)
    cropped_img = image.crop((left, top, right, bottom))
    return cropped_img


class MapViewer(BaseView):
    """
    scrollable palworld map.
    """

    def __init__(
        self,
        *,
        user,
        timeout=30 * 15,
        img=None,
        initial_coor=None,
    ):
        super().__init__(user=user, timeout=timeout)
        self.value = False
        self.done = None
        self.img = img
        self.focus_cell = np.array(initial_coor) // CELL_SIZE

    def make_embed(self):
        coors = f"Viewing cell {self.focus_cell[0]}, {self.focus_cell[1]}"
        embed = discord.Embed(
            description=f"Current galactic map view.  \n{coors}"[:4000],
            timestamp=discord.utils.utcnow(),
        )

        cropped_img = crop_image(self.img, self.focus_cell, off_by=np.array((2, 2)))
        with io.BytesIO() as image_binary:
            cropped_img.save(image_binary, "PNG")
            image_binary.seek(0)
            file = discord.File(fp=image_binary, filename="highlighted_palmap.png")

        embed.set_image(url="attachment://highlighted_palmap.png")

        return embed, file

    async def on_timeout(self) -> None:
        self.value = "timeout"
        self.stop()

    @discord.ui.button(label="Up", style=discord.ButtonStyle.green, row=2)
    async def move_up(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.focus_cell += np.array((0, -1))
        # await interaction.response.defer()
        embed, file = self.make_embed()
        await interaction.response.edit_message(
            content="", embed=embed, attachments=[file]
        )

    @discord.ui.button(label="Down", style=discord.ButtonStyle.green, row=4)
    async def move_down(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.focus_cell += np.array((0, 1))
        # await interaction.response.defer()
        embed, file = self.make_embed()
        await interaction.response.edit_message(
            content="", embed=embed, attachments=[file]
        )

    @discord.ui.button(label="Left", style=discord.ButtonStyle.green, row=3)
    async def move_left(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.focus_cell += np.array((-1, 0))
        # await interaction.response.defer()
        embed, file = self.make_embed()

        await interaction.response.edit_message(
            content="", embed=embed, attachments=[file]
        )

    @discord.ui.button(label="Right", style=discord.ButtonStyle.green, row=3)
    async def move_right(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        self.focus_cell += np.array((1, 0))
        # await interaction.response.defer()
        embed, file = self.make_embed()

        await interaction.response.edit_message(
            content="", embed=embed, attachments=[file]
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.grey, row=4)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        await interaction.response.edit_message(content="Terminating.")
        self.stop()
