#!/usr/bin/env python3
"""Fluent 3D emoji -> terminal sprite converter.

Outputs:
  pixel_art/{name}_{size}.png  — pixel-art PNG sprites
  ansi/{name}.ansi              — ANSI terminal sprites (truecolor)
  ansi/{name}.txt               — plain-text preview
"""

from pathlib import Path
from PIL import Image

RESET = "\x1b[0m"
SIZES = [(16, 16), (24, 24), (32, 32)]
PALETTE_COLORS = 12

SRC = Path(__file__).parent / "source"
PIX = Path(__file__).parent / "pixel_art"
ANSI_DIR = Path(__file__).parent / "ansi"


def autocrop_transparent(img: Image.Image) -> Image.Image:
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    bbox = img.getbbox()
    return img.crop(bbox) if bbox else img


def make_pixel_sprite(
    img: Image.Image,
    size: tuple[int, int],
    colors: int = PALETTE_COLORS,
) -> Image.Image:
    src = autocrop_transparent(img.copy())
    src.thumbnail(size, Image.LANCZOS)

    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - src.width) // 2
    y = (size[1] - src.height) // 2
    canvas.paste(src, (x, y), src)

    quantized = canvas.convert("P", palette=Image.ADAPTIVE, colors=colors, dither=Image.NONE)
    return quantized.convert("RGBA")


def ansi_fg(r, g, b):
    return f"\x1b[38;2;{r};{g};{b}m"


def ansi_bg(r, g, b):
    return f"\x1b[48;2;{r};{g};{b}m"


def sprite_to_ansi(img: Image.Image) -> str:
    w, h = img.size
    pixels = img.load()
    lines = []

    for y in range(0, h, 2):
        line = []
        for x in range(w):
            top = pixels[x, y]
            bot = pixels[x, y + 1] if y + 1 < h else (0, 0, 0, 0)
            ta, ba = top[3], bot[3]

            if ta < 32 and ba < 32:
                line.append(" ")
            elif ta < 32:
                line.append(ansi_bg(bot[0], bot[1], bot[2]) + "▄" + RESET)
            elif ba < 32:
                line.append(ansi_fg(top[0], top[1], top[2]) + "▀" + RESET)
            else:
                line.append(
                    ansi_fg(top[0], top[1], top[2])
                    + ansi_bg(bot[0], bot[1], bot[2])
                    + "▀"
                    + RESET
                )
        lines.append("".join(line))

    return "\n".join(lines)


def sprite_to_plain(img: Image.Image) -> str:
    """Rough luminance-based ASCII fallback."""
    ramp = " .:-=+*#%@"
    w, h = img.size
    pixels = img.load()
    lines = []

    for y in range(0, h, 2):
        line = []
        for x in range(w):
            top = pixels[x, y]
            if top[3] < 32:
                line.append(" ")
                continue
            lum = 0.299 * top[0] + 0.587 * top[1] + 0.114 * top[2]
            idx = int(lum / 255 * (len(ramp) - 1))
            line.append(ramp[idx])
        lines.append("".join(line))

    return "\n".join(lines)


def main():
    PIX.mkdir(parents=True, exist_ok=True)
    ANSI_DIR.mkdir(parents=True, exist_ok=True)

    sources = sorted(SRC.glob("*.png"))
    if not sources:
        print("No source PNGs found in", SRC)
        return

    for src_path in sources:
        name = src_path.stem
        img = Image.open(src_path).convert("RGBA")
        print(f"\n{'=' * 40}")
        print(f"  {name}  ({img.size[0]}x{img.size[1]} source)")
        print(f"{'=' * 40}")

        for size in SIZES:
            sprite = make_pixel_sprite(img, size)
            out = PIX / f"{name}_{size[0]}x{size[1]}.png"
            sprite.save(out)
            print(f"  -> {out.name}")

        # ANSI from 24x24 sprite
        sprite_24 = make_pixel_sprite(img, (24, 24))
        ansi_str = sprite_to_ansi(sprite_24)
        ansi_file = ANSI_DIR / f"{name}.ansi"
        ansi_file.write_text(ansi_str)

        plain = sprite_to_plain(sprite_24)
        (ANSI_DIR / f"{name}.txt").write_text(plain)

        print(f"\n  ANSI preview (24x24):\n")
        print(ansi_str)
        print()


if __name__ == "__main__":
    main()
