const M = {
  body: "#e8956a",
  light: "#f3aa78",
  shade: "#bf6848",
  dark: "#16161e",
  glow: "#ffbf8f",
  spark: "#f7a8c4",
  violet: "#9d7cd8",
}

const MASCOT_ROWS = [
  [
    { text: "  ", fg: "" },
    { text: "▄▄", fg: M.light },
    { text: "          ", fg: "" },
    { text: "▄▄", fg: M.light },
  ],
  [
    { text: " ", fg: "" },
    { text: "▄█", fg: M.body },
    { text: "▀▄", fg: M.light },
    { text: "      ", fg: "" },
    { text: "▄▀", fg: M.light },
    { text: "█▄", fg: M.body },
  ],
  [
    { text: " ", fg: "" },
    { text: "▀█▄▄█▀", fg: M.shade },
    { text: "  ", fg: "" },
    { text: "▀█▄▄█▀", fg: M.shade },
  ],
  [
    { text: "    ", fg: "" },
    { text: "▄██████▄", fg: M.body },
  ],
  [
    { text: "   ", fg: "" },
    { text: "▐", fg: M.shade },
    { text: "█", fg: M.body },
    { text: "▀", fg: M.dark, bg: M.body },
    { text: "██", fg: M.body },
    { text: "▀", fg: M.dark, bg: M.body },
    { text: "█", fg: M.body },
    { text: "▌", fg: M.shade },
  ],
  [
    { text: "   ", fg: "" },
    { text: "▐", fg: M.shade },
    { text: "██", fg: M.body },
    { text: "▄▄", fg: M.dark, bg: M.body },
    { text: "██", fg: M.body },
    { text: "▌", fg: M.shade },
  ],
  [
    { text: "    ", fg: "" },
    { text: "▀", fg: M.shade },
    { text: "██████", fg: M.body },
    { text: "▀", fg: M.shade },
  ],
  [
    { text: "  ", fg: "" },
    { text: "▀▄", fg: M.shade },
    { text: "  ", fg: "" },
    { text: "▀▀", fg: M.shade },
    { text: "  ", fg: "" },
    { text: "▀▀", fg: M.shade },
    { text: "  ", fg: "" },
    { text: "▄▀", fg: M.shade },
  ],
]

export function Mascot() {
  return (
    <box style={{ flexDirection: "column", width: 18, height: 8 }}>
      {MASCOT_ROWS.map((row, i) => (
        <text key={`mascot-${i}`}>
          {row.map((seg, j) =>
            seg.fg
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
      <text fg={M.spark}>{"✦"}</text>
      <text fg={M.violet}>{" ·"}</text>
      <text fg={M.glow}>{"· "}</text>
      <text fg={M.spark}>{" ✧"}</text>
    </box>
  )
}
