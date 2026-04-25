#!/usr/bin/env python3
"""Render all 32x32 sprites into a single preview image with labels."""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

CELL = 8  # pixels per sprite-pixel in the preview
PAD = 20
LABEL_H = 30
BG_COLOR = (24, 24, 28)
LABEL_COLOR = (200, 200, 200)

sprites = [
    ("robot", "Robot"),
    ("fire", "Fire"),
    ("rocket", "Rocket"),
    ("factory", "Factory"),
    ("castle", "Castle"),
    ("gear", "Gear"),
]

PIX = Path(__file__).parent / "pixel_art"

images = []
for fname, label in sprites:
    img = Image.open(PIX / f"{fname}_32x32.png").convert("RGBA")
    images.append((img, label))

cols = 3
rows = 2
sprite_w = 32 * CELL
sprite_h = 32 * CELL

total_w = cols * sprite_w + (cols + 1) * PAD
total_h = rows * (sprite_h + LABEL_H) + (rows + 1) * PAD

canvas = Image.new("RGB", (total_w, total_h), BG_COLOR)
draw = ImageDraw.Draw(canvas)

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 16)
except OSError:
    font = ImageFont.load_default()

for i, (img, label) in enumerate(images):
    col = i % cols
    row = i // cols
    ox = PAD + col * (sprite_w + PAD)
    oy = PAD + row * (sprite_h + LABEL_H + PAD)

    # Draw label
    draw.text((ox, oy), label, fill=LABEL_COLOR, font=font)

    # Scale up sprite with nearest-neighbor
    scaled = img.resize((sprite_w, sprite_h), Image.NEAREST)

    # Paste onto canvas (composite for transparency)
    bg_patch = Image.new("RGB", (sprite_w, sprite_h), BG_COLOR)
    bg_patch.paste(scaled, mask=scaled)
    canvas.paste(bg_patch, (ox, oy + LABEL_H))

out = Path(__file__).parent / "preview_32x32.png"
canvas.save(out)
print(f"Saved {out} ({total_w}x{total_h})")

# Also do 16x16 and 24x24 comparison for robot
sizes = [("robot_16x16.png", "16x16"), ("robot_24x24.png", "24x24"), ("robot_32x32.png", "32x32")]
comp_w = 3 * 32 * CELL + 4 * PAD
comp_h = 32 * CELL + LABEL_H + 2 * PAD
comp = Image.new("RGB", (comp_w, comp_h), BG_COLOR)
cdraw = ImageDraw.Draw(comp)

for j, (fname, label) in enumerate(sizes):
    img = Image.open(PIX / fname).convert("RGBA")
    ox = PAD + j * (32 * CELL + PAD)
    oy = PAD
    cdraw.text((ox, oy), f"Robot {label}", fill=LABEL_COLOR, font=font)
    scaled = img.resize((32 * CELL, 32 * CELL), Image.NEAREST)
    bg_patch = Image.new("RGB", (32 * CELL, 32 * CELL), BG_COLOR)
    bg_patch.paste(scaled, mask=scaled)
    comp.paste(bg_patch, (ox, oy + LABEL_H))

comp_out = Path(__file__).parent / "preview_sizes.png"
comp.save(comp_out)
print(f"Saved {comp_out} ({comp_w}x{comp_h})")
