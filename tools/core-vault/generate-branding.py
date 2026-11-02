#!/usr/bin/python3

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]

SOURCE = ROOT / "tools/core-offline/branding"

VAULT = (
    ROOT
    / "config/includes.chroot/usr/share/core-vault"
)

PLYMOUTH = (
    ROOT
    / "config/includes.chroot/usr/share/plymouth/themes/core-signer"
)

VAULT.mkdir(parents=True, exist_ok=True)
PLYMOUTH.mkdir(parents=True, exist_ok=True)

WHITE = (255, 255, 255, 255)
MUTED = (176, 176, 176, 255)
TRACK = (34, 34, 34, 255)
BORDER = (68, 68, 68, 255)

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TITLE_FONT = ImageFont.truetype(FONT_BOLD, 24)
BODY_FONT = ImageFont.truetype(FONT_REGULAR, 19)
FOOTER_FONT = ImageFont.truetype(FONT_REGULAR, 16)


def logo(path, box):
    source = Image.open(path).convert("RGBA")
    source.thumbnail(box, Image.Resampling.LANCZOS)

    result = Image.new(
        "RGBA",
        box,
        (0, 0, 0, 0),
    )

    result.alpha_composite(
        source,
        (
            (box[0] - source.width) // 2,
            (box[1] - source.height) // 2,
        ),
    )

    return result


def text_asset(text, font, colour):
    dummy = Image.new(
        "RGBA",
        (1, 1),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(dummy)
    box = draw.textbbox((0, 0), text, font=font)

    image = Image.new(
        "RGBA",
        (
            box[2] - box[0] + 6,
            box[3] - box[1] + 6,
        ),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (
            3 - box[0],
            3 - box[1],
        ),
        text,
        font=font,
        fill=colour,
    )

    return image


bitcoin = logo(
    SOURCE / "bitcoin.png",
    (64, 64),
)

debian = logo(
    SOURCE / "debian.png",
    (38, 48),
)

title = text_asset(
    "Bitcoin Core Vault",
    TITLE_FONT,
    WHITE,
)

line1 = text_asset(
    "Dedicated offline Bitcoin Core workspace",
    BODY_FONT,
    WHITE,
)

line2 = text_asset(
    "Create, encrypt, back up and recover wallets without networking.",
    BODY_FONT,
    WHITE,
)

credit = text_asset(
    "Powered by Debian GNU/Linux",
    FOOTER_FONT,
    MUTED,
)

track = Image.new(
    "RGBA",
    (480, 8),
    (0, 0, 0, 0),
)

draw = ImageDraw.Draw(track)

draw.rectangle(
    (0, 1, 479, 7),
    fill=TRACK,
    outline=BORDER,
)

fill = Image.new(
    "RGBA",
    (478, 6),
    WHITE,
)


for name, image in {
    "bitcoin-ui.png": bitcoin,
    "debian-ui.png": debian,
}.items():
    image.save(VAULT / name)


for name, image in {
    "bitcoin-ui.png": bitcoin,
    "debian-ui.png": debian,
    "boot-title.png": title,
    "boot-line1.png": line1,
    "boot-line2.png": line2,
    "powered-by-debian.png": credit,
    "progress-track.png": track,
}.items():
    image.save(PLYMOUTH / name)

fill.save(PLYMOUTH / "progress-fill.png")

print("BITCOIN CORE VAULT BRANDING GENERATED")
