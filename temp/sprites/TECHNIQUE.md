# Terminal Pixel Art - Half-Block Rendering

## Core technique

Each terminal cell renders **2 vertical pixels** using Unicode half-block characters with truecolor (24-bit) fg/bg colors.

```
  ▀  = top half filled
  ▄  = bottom half filled
  █  = both halves filled (solid)
     = both halves empty (transparent)
```

## The rule

The character shape is always drawn in the **foreground** color. The other half shows the **background** color.

| Top pixel | Bottom pixel | Char | fg | bg |
|-----------|--------------|------|----|----|
| color A | color B | `▀` | A | B |
| color A | transparent | `▀` | A | none |
| transparent | color B | `▄` | B | none |
| color A | color A | `▀` | A | A |
| transparent | transparent | ` ` | none | none |

**Critical:** `▄` uses **fg** for the bottom pixel, NOT bg. Getting this wrong produces garbled sprites.

## Size math

A pixel grid of W x H becomes **W columns x ceil(H / 2) rows** in the terminal.

| Sprite size | Terminal footprint |
|-------------|--------------------|
| 12 x 16 | 12 cols x 8 rows |
| 16 x 16 | 16 cols x 8 rows |
| 24 x 24 | 24 cols x 12 rows |
| 32 x 32 | 32 cols x 16 rows |

## Input format

Define a palette and a 2D pixel array:

```python
_ = None
R = "red"
O = "skin"
B = "brown"

PALETTE = {
    "red": "#c81010",
    "skin": "#e49434",
    "brown": "#744414",
}

pixels = [
    [_, _, R, R, R, _, _],  # row 0
    [_, R, R, R, R, R, _],  # row 1
    [_, B, O, O, O, B, _],  # row 2
    [B, O, O, O, O, O, B],  # row 3
]
```

## Conversion algorithm

```python
def cell(top, bot):
    if top is None and bot is None:
        return (None, None, " ")
    elif top is None:
        return (bot, None, "▄")    # fg = bottom color
    elif bot is None:
        return (top, None, "▀")    # fg = top color
    else:
        return (top, bot, "▀")     # fg = top, bg = bottom


for y in range(0, H, 2):
    for x in range(W):
        top = pixels[y][x]
        bot = pixels[y + 1][x] if y + 1 < H else None
        fg, bg, ch = cell(top, bot)
        # emit with ANSI or OpenTUI span
```

## Merging runs

Adjacent cells with the same `(fg, bg)` pair merge into a single span. This reduces the number of `<span>` elements and ANSI escape sequences.

```tsx
// Before
<span fg="red">▀</span><span fg="red">▀</span><span fg="red">▀</span>

// After
<span fg="red">▀▀▀</span>
```

## OpenTUI component pattern

```tsx
const ROWS: { text: string; fg?: string; bg?: string }[][] = [
  [
    { text: "  " },
    { text: "▀▀▀", fg: M.red, bg: M.red },
    { text: "▄▄", fg: M.brown },
  ],
]

export function Sprite() {
  return (
    <box style={{ flexDirection: "column", width: W, height: Math.ceil(H / 2) }}>
      {ROWS.map((row, i) => (
        <text key={i}>
          {row.map((seg, j) =>
            seg.fg || seg.bg
              ? <span key={j} fg={seg.fg} bg={seg.bg}>{seg.text}</span>
              : <span key={j}>{seg.text}</span>
          )}
        </text>
      ))}
    </box>
  )
}
```

## ANSI terminal output

```python
RESET = "\x1b[0m"
fg = lambda r, g, b: f"\x1b[38;2;{r};{g};{b}m"
bg = lambda r, g, b: f"\x1b[48;2;{r};{g};{b}m"

# Example cell: top=#c81010, bottom=#744414
print(fg(200, 16, 16) + bg(116, 68, 20) + "▀" + RESET)
```

## Pipeline: PNG to sprite component

```
source PNG
  -> identify source pixel size from a known one-pixel feature
  -> crop or map to drawn-pixel grid
  -> quantize to a small palette without dither
  -> read pixel grid
  -> pair rows, apply cell() logic
  -> merge runs
  -> emit TSX component or ANSI string
```

## What does NOT work

- Raw ANSI escapes in the OpenTUI render buffer.
- Kitty/Sixel/iTerm2 inline images for this path.
- `FrameBufferRenderable` for image loading.
- Hand-coding half-block spans for anything above very small sprites.
