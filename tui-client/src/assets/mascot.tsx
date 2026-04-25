const M = {
  background: "#bd7756",
  body: "#151522",
  shade: "#333342",
  eyes: "#ffd51d",
  chest: "#f6f4ef",
  nose: "#d07080",
  ground: "#edbd86",
}

const MASCOT_ROWS: { text: string; fg?: string; bg?: string }[][] = [
  [
    { text: "          " },
    { text: "▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.shade },
    { text: "   " },
    { text: "▀", fg: M.body, bg: M.body },
    { text: "       " },
  ],
  [
    { text: "     " },
    { text: "▄", fg: M.body },
    { text: "  " },
    { text: "▄", fg: M.body },
    { text: "▀▀▀▀▀▀▀", fg: M.body, bg: M.body },
    { text: "▄", fg: M.body },
    { text: " " },
    { text: "▄", fg: M.body },
    { text: "    " },
  ],
  [
    { text: "     " },
    { text: "▀", fg: M.body, bg: M.body },
    { text: " " },
    { text: "▀", fg: M.body },
    { text: "▀▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.eyes, bg: M.body },
    { text: "▀▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.eyes, bg: M.body },
    { text: "▀▀▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.body },
    { text: "▀", fg: M.body, bg: M.body },
    { text: "    " },
  ],
  [
    { text: "       " },
    { text: "▄", fg: M.body },
    { text: "▀▀▀▀▀▀▀▀▀", fg: M.body, bg: M.body },
    { text: "      " },
  ],
  [
    { text: "       " },
    { text: "▀▀▀▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.chest, bg: M.chest },
    { text: "▀▀", fg: M.body, bg: M.body },
    { text: "▀", fg: M.chest, bg: M.chest },
    { text: "▀▀", fg: M.body, bg: M.body },
    { text: "      " },
  ],
  [
    { text: "▀", fg: M.ground },
    { text: " " },
    { text: "▀▀", fg: M.ground },
    { text: " " },
    { text: "▀▀▀▀▀▀▀▀▀", fg: M.ground },
    { text: "  " },
    { text: "▀▀", fg: M.ground },
    { text: " " },
    { text: "▀", fg: M.ground },
    { text: " " },
    { text: "▀", fg: M.ground },
    { text: " " },
  ],
]

export function Mascot() {
  return (
    <box style={{ flexDirection: "column", width: 23, height: 6 }}>
      {MASCOT_ROWS.map((row, i) => (
        <text key={`mascot-${i}`}>
          {row.map((seg, j) =>
            seg.fg || seg.bg
              ? <span key={`m-${i}-${j}`} fg={seg.fg} bg={seg.bg}>{seg.text}</span>
              : <span key={`m-${i}-${j}`}>{seg.text}</span>
          )}
        </text>
      ))}
    </box>
  )
}

export function Sparkles() {
  return (
    <box style={{ position: "absolute", width: 4, height: 4 }}>
      <text fg="#ecc820">{"\u2726"}</text>
      <text fg="#9d7cd8">{" \u00b7"}</text>
      <text fg="#cc6878">{"\u00b7 "}</text>
      <text fg="#ecc820">{" \u2727"}</text>
    </box>
  )
}
