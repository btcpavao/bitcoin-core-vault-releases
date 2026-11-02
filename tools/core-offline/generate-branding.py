#!/usr/bin/python3

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]

SOURCE = ROOT / "tools/core-offline/branding"
CORE = ROOT / "config/includes.chroot/usr/share/core-signer"
PLYMOUTH = ROOT / "config/includes.chroot/usr/share/plymouth/themes/core-signer"

CORE.mkdir(parents=True, exist_ok=True)
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
    src = Image.open(path).convert("RGBA")
    src.thumbnail(box, Image.Resampling.LANCZOS)

    out = Image.new("RGBA", box, (0, 0, 0, 0))
    out.alpha_composite(
        src,
        (
            (box[0] - src.width) // 2,
            (box[1] - src.height) // 2,
        ),
    )
    return out


def text_asset(text, font, colour):
    dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    d = ImageDraw.Draw(dummy)

    box = d.textbbox((0, 0), text, font=font)

    width = box[2] - box[0] + 6
    height = box[3] - box[1] + 6

    image = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (3 - box[0], 3 - box[1]),
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
    "Bitcoin Core",
    TITLE_FONT,
    WHITE,
)

line1 = text_asset(
    "Offline, stateless Bitcoin Core environment",
    BODY_FONT,
    WHITE,
)

line2 = text_asset(
    "Session data lives only in RAM and does not persist after shutdown.",
    BODY_FONT,
    WHITE,
)

credit = text_asset(
    "Powered by Debian",
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

assets = {
    "bitcoin-ui.png": bitcoin,
    "debian-ui.png": debian,
    "boot-title.png": title,
    "boot-line1.png": line1,
    "boot-line2.png": line2,
    "powered-by-debian.png": credit,
    "progress-track.png": track,
}

for name, image in assets.items():
    image.save(CORE / name)
    image.save(PLYMOUTH / name)

fill.save(PLYMOUTH / "progress-fill.png")
fill.save(CORE / "progress-fill.png")

# Keep old fallback files as plain black canvases.
black = Image.new("RGBA", (1920, 1080), (0, 0, 0, 255))

for directory in (CORE, PLYMOUTH):
    black.save(directory / "background.png")
    black.save(directory / "background-ready.png")

print("RESPONSIVE BRAND ASSETS GENERATED")
