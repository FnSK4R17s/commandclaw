#!/usr/bin/env python3
"""Generate mascot.tsx from pixel grid — no hand-coding half-blocks."""

_ = None
R = "red"
O = "skin"
B = "brown"
K = "black"

PALETTE = {
    "red": "#c81010",
    "skin": "#e49434",
    "brown": "#744414",
    "black": "#000000",
}

pixels = [
    [_,_,_,R,R,R,R,R,_,_,_,_],
    [_,_,R,R,R,R,R,R,R,R,R,_],
    [_,_,B,B,B,O,O,K,O,_,_,_],
    [_,B,O,B,O,O,O,K,O,O,O,_],
    [_,B,O,B,B,O,O,O,K,O,O,O],
    [_,B,B,O,O,O,O,K,K,K,K,_],
    [_,_,_,O,O,O,O,O,O,O,_,_],
    [_,_,R,R,B,R,R,R,_,_,_,_],
    [_,R,R,R,B,R,R,B,R,R,R,_],
    [R,R,R,R,B,B,B,B,R,R,R,R],
    [O,O,R,B,O,B,B,O,B,R,O,O],
    [O,O,O,B,B,B,B,B,B,O,O,O],
    [O,O,B,B,B,B,B,B,B,B,O,O],
    [_,_,B,B,B,_,_,B,B,B,_,_],
    [_,B,B,B,_,_,_,_,B,B,B,_],
    [B,B,B,B,_,_,_,_,B,B,B,B],
]

W = len(pixels[0])
H = len(pixels)


def cell_key(top, bot):
    """Return (fg, bg, char). ▀ = fg is top, bg is bottom. ▄ = fg is bottom."""
    if top is None and bot is None:
        return (None, None, " ")
    elif top is None:
        return (bot, None, "▄")
    elif bot is None:
        return (top, None, "▀")
    else:
        return (top, bot, "▀")


def generate():
    rows = []
    for y in range(0, H, 2):
        cells = []
        for x in range(W):
            top = pixels[y][x]
            bot = pixels[y + 1][x] if y + 1 < H else None
            cells.append(cell_key(top, bot))
        rows.append(cells)

    # Merge runs of identical (fg, bg) into segments
    segments_per_row = []
    for cells in rows:
        segs = []
        cur_fg, cur_bg, cur_text = cells[0]
        for fg, bg, ch in cells[1:]:
            if fg == cur_fg and bg == cur_bg:
                cur_text += ch
            else:
                segs.append((cur_fg, cur_bg, cur_text))
                cur_fg, cur_bg, cur_text = fg, bg, ch
        segs.append((cur_fg, cur_bg, cur_text))
        segments_per_row.append(segs)

    # Generate TSX
    lines = []
    lines.append('const M = {')
    for name, hex_val in PALETTE.items():
        lines.append(f'  {name}: "{hex_val}",')
    lines.append('}')
    lines.append('')
    lines.append('const MASCOT_ROWS: { text: string; fg?: string; bg?: string }[][] = [')

    for i, segs in enumerate(segments_per_row):
        lines.append('  [')
        for fg, bg, text in segs:
            parts = []
            parts.append(f'text: "{text}"')
            if fg is not None:
                parts.append(f"fg: M.{fg}")
            if bg is not None:
                parts.append(f"bg: M.{bg}")
            lines.append("    { " + ", ".join(parts) + " },")
        lines.append('  ],')

    lines.append(']')
    lines.append('')
    lines.append('export function Mascot() {')
    lines.append('  return (')
    lines.append(f'    <box style={{{{ flexDirection: "column", width: {W}, height: {H // 2} }}}}>')
    lines.append('      {MASCOT_ROWS.map((row, i) => (')
    lines.append('        <text key={`mascot-${i}`}>')
    lines.append('          {row.map((seg, j) =>')
    lines.append('            seg.fg || seg.bg')
    lines.append('              ? <span key={`m-${i}-${j}`} fg={seg.fg} bg={seg.bg}>{seg.text}</span>')
    lines.append('              : <span key={`m-${i}-${j}`}>{seg.text}</span>')
    lines.append('          )}')
    lines.append('        </text>')
    lines.append('      ))}')
    lines.append('    </box>')
    lines.append('  )')
    lines.append('}')
    lines.append('')
    lines.append('export function Sparkles() {')
    lines.append('  return (')
    lines.append('    <box style={{ position: "absolute", width: 4, height: 4 }}>')
    lines.append('      <text fg="#f7a8c4">{"\\u2726"}</text>')
    lines.append('      <text fg="#9d7cd8">{" \\u00b7"}</text>')
    lines.append('      <text fg="#ffbf8f">{"\\u00b7 "}</text>')
    lines.append('      <text fg="#f7a8c4">{" \\u2727"}</text>')
    lines.append('    </box>')
    lines.append('  )')
    lines.append('}')

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    tsx = generate()
    print(tsx)
    out = "/apps/commandclaw/tui-client/src/assets/mascot.tsx"
    with open(out, "w") as f:
        f.write(tsx)
    print(f"\nWritten to {out}")
