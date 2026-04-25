// Cherry blossom branch — extends from top-right corner
// Half-block pixel art, designed to be positioned absolute top-right

const BRANCH_ROWS = [
  { segments: [
    { text: "                         ", fg: "" },
    { text: "▄▄▄", fg: "#f7a8c4" },
    { text: "▄", fg: "#ffb7d5" },
    { text: "▄▄", fg: "#f7a8c4" },
  ]},
  { segments: [
    { text: "                      ", fg: "" },
    { text: "▄", fg: "#e890ab" },
    { text: "█▓▒", fg: "#f7a8c4" },
    { text: "▓█", fg: "#ffb7d5" },
    { text: "▓▒", fg: "#f7a8c4" },
    { text: "▄", fg: "#e890ab" },
  ]},
  { segments: [
    { text: "                    ", fg: "" },
    { text: "▄", fg: "#e890ab" },
    { text: "▓█", fg: "#ffb7d5" },
    { text: "▒", fg: "#f7a8c4" },
    { text: "▄▄", fg: "#8b6952" },
    { text: "▒", fg: "#f7a8c4" },
    { text: "█▓", fg: "#ffb7d5" },
    { text: "▄", fg: "#e890ab" },
  ]},
  { segments: [
    { text: "                  ", fg: "" },
    { text: "▀", fg: "#f7a8c4" },
    { text: "▓▒", fg: "#e890ab" },
    { text: "▄▄▄▄", fg: "#8b6952" },
    { text: "▒▓", fg: "#e890ab" },
    { text: "▀", fg: "#f7a8c4" },
  ]},
  { segments: [
    { text: "              ", fg: "" },
    { text: "▄▄▄", fg: "#f7a8c4" },
    { text: "▄▄", fg: "#8b6952" },
    { text: "▀▀▀▀", fg: "#6b5242" },
  ]},
  { segments: [
    { text: "           ", fg: "" },
    { text: "▄", fg: "#e890ab" },
    { text: "▓█▓", fg: "#f7a8c4" },
    { text: "▄▄", fg: "#8b6952" },
    { text: "▀▀", fg: "#6b5242" },
  ]},
  { segments: [
    { text: "          ", fg: "" },
    { text: "▀", fg: "#f7a8c4" },
    { text: "▒▓", fg: "#e890ab" },
    { text: "▀", fg: "#f7a8c4" },
    { text: "▀", fg: "#8b6952" },
  ]},
  { segments: [
    { text: "            ", fg: "" },
    { text: "▀", fg: "#e890ab" },
  ]},
]

export function CherryBranch() {
  return (
    <box style={{ flexDirection: "column", width: 35, height: 8 }}>
      {BRANCH_ROWS.map((row, i) => (
        <text key={`br-${i}`}>
          {row.segments.map((seg, j) =>
            seg.fg
              ? <span key={`s-${i}-${j}`} fg={seg.fg}>{seg.text}</span>
              : <span key={`s-${i}-${j}`}>{seg.text}</span>
          )}
        </text>
      ))}
    </box>
  )
}
