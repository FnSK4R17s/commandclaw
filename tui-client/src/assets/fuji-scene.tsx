const F = {
  snow: "#f4f1ff",
  high: "#a9b4ea",
  mid: "#6672b2",
  low: "#3f487c",
  water: "#253052",
  water2: "#334374",
  wood: "#7b4c3c",
  roof: "#c35f68",
  lantern: "#e2ad62",
  blossom: "#f0a0b8",
  blossomHot: "#d980a0",
}

const SCENE_ROWS = [
  [
    { text: "                  ", fg: "" },
    { text: "▄", fg: F.snow },
  ],
  [
    { text: "                 ", fg: "" },
    { text: "▄█▄", fg: F.snow },
  ],
  [
    { text: "              ", fg: "" },
    { text: "▄", fg: F.mid },
    { text: "██", fg: F.high },
    { text: "█", fg: F.snow },
    { text: "██", fg: F.high },
    { text: "▄", fg: F.mid },
  ],
  [
    { text: "        ", fg: "" },
    { text: "▄▄", fg: F.low },
    { text: "███████████", fg: F.mid },
    { text: "▄▄", fg: F.low },
  ],
  [
    { text: "  ", fg: "" },
    { text: "▄█▄", fg: F.blossom },
    { text: "   ", fg: "" },
    { text: "▀▀", fg: F.low },
    { text: "█████████", fg: F.low },
    { text: "▀▀", fg: F.low },
    { text: "   ", fg: "" },
    { text: "▄▄▄", fg: F.roof },
  ],
  [
    { text: " ", fg: "" },
    { text: "▄██▄", fg: F.blossomHot },
    { text: "        ", fg: "" },
    { text: "░░░░░░", fg: F.water2 },
    { text: "    ", fg: "" },
    { text: "▄███▄", fg: F.roof },
  ],
  [
    { text: "  ", fg: "" },
    { text: "█", fg: F.wood },
    { text: "▓", fg: F.lantern },
    { text: "█", fg: F.wood },
    { text: "     ", fg: "" },
    { text: "▄▄", fg: F.wood },
    { text: " ", fg: "" },
    { text: "▄▄", fg: F.wood },
    { text: "     ", fg: "" },
    { text: "█", fg: F.wood },
    { text: "▓", fg: F.lantern },
    { text: "▓", fg: F.roof },
    { text: "█", fg: F.wood },
  ],
  [
    { text: "▓▓▓▓", fg: F.water },
    { text: "▒▒▒▒▒▒", fg: F.water2 },
    { text: "▓▓▓▓▓", fg: F.water },
    { text: "▒▒▒▒▒▒", fg: F.water2 },
    { text: "▓▓▓▓▓", fg: F.water },
  ],
]

export function FujiScene() {
  return (
    <box style={{ flexDirection: "column", width: 32, height: 8 }}>
      {SCENE_ROWS.map((row, i) => (
        <text key={`fj-${i}`}>
          {row.map((seg, j) =>
            seg.fg
              ? <span key={`s-${i}-${j}`} fg={seg.fg}>{seg.text}</span>
              : <span key={`s-${i}-${j}`}>{seg.text}</span>
          )}
        </text>
      ))}
    </box>
  )
}
