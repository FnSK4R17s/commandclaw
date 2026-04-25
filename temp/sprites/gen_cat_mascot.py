#!/usr/bin/env python3
"""Generate a CommandClaw cat mascot sprite from a hand-tuned pixel grid."""

from pathlib import Path

_ = None
K = "body"
D = "shade"
Y = "eyes"
W = "chest"
P = "nose"
G = "ground"
B = "background"

PALETTE = {
    "background": "#bd7756",
    "body": "#151522",
    "shade": "#333342",
    "eyes": "#ffd51d",
    "chest": "#f6f4ef",
    "nose": "#d07080",
    "ground": "#edbd86",
}

# Each yellow eye block in the reference is one source pixel and renders as a
# 9x9 bitmap square. 207px image width / 9px source pixel = 23 drawn pixels;
# 95px image height / 9px source pixel rounds to 11 drawn pixels.
REFERENCE_W_PX = 207
REFERENCE_H_PX = 95
SOURCE_PIXEL_PX = 9
SPRITE_W = REFERENCE_W_PX // SOURCE_PIXEL_PX
SPRITE_H = round(REFERENCE_H_PX / SOURCE_PIXEL_PX)

# 23 wide x 11 tall. The terminal footprint is 23 columns x 6 rows.
# This tracks the supplied reference at the inferred source-pixel resolution.
ART = [
    "..........KD...K.......",
    "..........K....K.......",
    ".........KKKKKKK.......",
    ".....K..KKKKKKKKK.K....",
    ".....K.KKKYKKYKKKKK....",
    ".....K..KKKKKKKKK.K....",
    "........KKKKKKKKK......",
    ".......KKKKKKKKKK......",
    ".......KKKKWKKWKK......",
    ".......KKKKWKKWKK......",
    "G.GG.GGGGGGGGG..GG.G.G.",
]
ART = [row.ljust(SPRITE_W, ".") for row in ART]
if len(ART) != SPRITE_H or any(len(row) != SPRITE_W for row in ART):
    raise ValueError(f"ART must be {SPRITE_W}x{SPRITE_H}.")
if sum(row.count("Y") for row in ART) != 2:
    raise ValueError("Expected two one-pixel yellow eyes.")

KEY = {
    ".": _,
    "K": K,
    "D": D,
    "Y": Y,
    "W": W,
    "P": P,
    "G": G,
    "B": B,
}

pixels = [[KEY[ch] for ch in row] for row in ART]

W_PX = len(pixels[0])
H_PX = len(pixels)
TERM_H = (H_PX + 1) // 2


def rgb(name):
    hex_c = PALETTE[name]
    return int(hex_c[1:3], 16), int(hex_c[3:5], 16), int(hex_c[5:7], 16)


def cell(top, bot):
    if top is None and bot is None:
        return (None, None, " ")
    elif top is None:
        return (bot, None, "▄")
    elif bot is None:
        return (top, None, "▀")
    else:
        return (top, bot, "▀")


def merge_row(cells):
    segs = []
    fg, bg, text = cells[0]
    for f, b, ch in cells[1:]:
        if f == fg and b == bg:
            text += ch
        else:
            segs.append((fg, bg, text))
            fg, bg, text = f, b, ch
    segs.append((fg, bg, text))
    return segs


def render_ansi():
    reset = "\x1b[0m"
    print(f"\n  Cat sprite ({W_PX}x{H_PX} px -> {W_PX} cols x {TERM_H} rows)\n")
    for y in range(0, H_PX, 2):
        line = "  "
        for x in range(W_PX):
            top = pixels[y][x]
            bot = pixels[y + 1][x] if y + 1 < H_PX else None
            fg_name, bg_name, ch = cell(top, bot)

            parts = ""
            if fg_name:
                r, g, b = rgb(fg_name)
                parts += f"\x1b[38;2;{r};{g};{b}m"
            if bg_name:
                r, g, b = rgb(bg_name)
                parts += f"\x1b[48;2;{r};{g};{b}m"
            line += parts + ch + reset
        print(line)
    print()


def render_preview_png():
    from PIL import Image, ImageDraw

    cell_px = SOURCE_PIXEL_PX
    bg = rgb("background")

    sw, sh = W_PX * cell_px, H_PX * cell_px

    canvas = Image.new("RGB", (sw, sh), bg)
    draw = ImageDraw.Draw(canvas)

    for y, row in enumerate(pixels):
        for x, c in enumerate(row):
            if c is not None:
                draw.rectangle(
                    [
                        x * cell_px,
                        y * cell_px,
                        (x + 1) * cell_px - 1,
                        (y + 1) * cell_px - 1,
                    ],
                    fill=rgb(c),
                )

    out = Path(__file__).with_name("preview_cat.png")
    canvas.save(out)
    print(f"Saved {out}")


def generate_tsx():
    rows = []
    for y in range(0, H_PX, 2):
        cells = []
        for x in range(W_PX):
            top = pixels[y][x]
            bot = pixels[y + 1][x] if y + 1 < H_PX else None
            cells.append(cell(top, bot))
        rows.append(merge_row(cells))

    lines = []
    lines.append("const M = {")
    for name, hex_val in PALETTE.items():
        lines.append(f'  {name}: "{hex_val}",')
    lines.append("}")
    lines.append("")
    lines.append("const MASCOT_ROWS: { text: string; fg?: string; bg?: string }[][] = [")

    for segs in rows:
        lines.append("  [")
        for fg, bg, text in segs:
            parts = [f'text: "{text}"']
            if fg is not None:
                parts.append(f"fg: M.{fg}")
            if bg is not None:
                parts.append(f"bg: M.{bg}")
            lines.append("    { " + ", ".join(parts) + " },")
        lines.append("  ],")

    lines.append("]")
    lines.append("")
    lines.append("export function Mascot() {")
    lines.append("  return (")
    lines.append(
        f"    <box style={{{{ flexDirection: \"column\", width: {W_PX}, "
        f"height: {TERM_H} }}}}>"
    )
    lines.append("      {MASCOT_ROWS.map((row, i) => (")
    lines.append('        <text key={`mascot-${i}`}>')
    lines.append("          {row.map((seg, j) =>")
    lines.append("            seg.fg || seg.bg")
    lines.append(
        '              ? <span key={`m-${i}-${j}`} fg={seg.fg} '
        "bg={seg.bg}>{seg.text}</span>"
    )
    lines.append('              : <span key={`m-${i}-${j}`}>{seg.text}</span>')
    lines.append("          )}")
    lines.append("        </text>")
    lines.append("      ))}")
    lines.append("    </box>")
    lines.append("  )")
    lines.append("}")
    lines.append("")
    lines.append("export function Sparkles() {")
    lines.append("  return (")
    lines.append('    <box style={{ position: "absolute", width: 4, height: 4 }}>')
    lines.append('      <text fg="#ecc820">{\"\\u2726\"}</text>')
    lines.append('      <text fg="#9d7cd8">{\" \\u00b7\"}</text>')
    lines.append('      <text fg="#cc6878">{\"\\u00b7 \"}</text>')
    lines.append('      <text fg="#ecc820">{\" \\u2727\"}</text>')
    lines.append("    </box>")
    lines.append("  )")
    lines.append("}")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    render_ansi()
    render_preview_png()
    tsx = generate_tsx()
    out = Path("/apps/commandclaw/tui-client/src/assets/mascot.tsx")
    with out.open("w") as f:
        f.write(tsx)
    print(f"Written TSX to {out}")
