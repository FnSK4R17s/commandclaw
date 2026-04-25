const B = {
  wood: "#7a4d40",
  bark: "#4f3040",
  dark: "#2a1e2c",
  pink: "#f6a6c3",
  hot: "#e789aa",
  pale: "#ffc0d9",
  white: "#ffdce8",
}

const BRANCH_ROWS = [
  [
    { text: "                          ", fg: "" },
    { text: "▄", fg: B.hot },
    { text: "▄█▄", fg: B.pink },
    { text: "  ", fg: "" },
    { text: "▄█▄", fg: B.pale },
  ],
  [
    { text: "                     ", fg: "" },
    { text: "▄█▄", fg: B.pink },
    { text: " ▄", fg: B.hot },
    { text: "██", fg: B.pink },
    { text: "▓", fg: B.white },
    { text: "██▄", fg: B.pink },
  ],
  [
    { text: "                 ", fg: "" },
    { text: "▄█▄", fg: B.hot },
    { text: "  ", fg: "" },
    { text: "▄", fg: B.wood },
    { text: "▀▀▀", fg: B.bark },
    { text: "▄", fg: B.wood },
    { text: " ", fg: "" },
    { text: "▀█", fg: B.hot },
    { text: "▓", fg: B.white },
    { text: "█▀", fg: B.pink },
  ],
  [
    { text: "             ", fg: "" },
    { text: "▄██", fg: B.pink },
    { text: "▓", fg: B.white },
    { text: "██▄", fg: B.hot },
    { text: "   ", fg: "" },
    { text: "▀▀▀▀", fg: B.bark },
    { text: "▄▄", fg: B.wood },
  ],
  [
    { text: "          ", fg: "" },
    { text: "▄", fg: B.wood },
    { text: "▀▀▀", fg: B.bark },
    { text: "▄", fg: B.wood },
    { text: "      ", fg: "" },
    { text: "▄▄", fg: B.wood },
    { text: "▀▀▀", fg: B.bark },
  ],
  [
    { text: "       ", fg: "" },
    { text: "▄█▄", fg: B.pale },
    { text: "  ", fg: "" },
    { text: "▀▀▀▀", fg: B.bark },
    { text: "▄▄▄", fg: B.wood },
  ],
  [
    { text: "        ", fg: "" },
    { text: "▀█", fg: B.hot },
    { text: "▓", fg: B.white },
    { text: "█▀", fg: B.pink },
    { text: "   ", fg: "" },
    { text: "▀▀", fg: B.bark },
    { text: "▄", fg: B.wood },
  ],
  [
    { text: "          ", fg: "" },
    { text: "▀", fg: B.pink },
    { text: "       ", fg: "" },
    { text: "▀", fg: B.bark },
  ],
]

export function CherryBranch() {
  return (
    <box style={{ flexDirection: "column", width: 38, height: 8 }}>
      {BRANCH_ROWS.map((row, i) => (
        <text key={`br-${i}`}>
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
