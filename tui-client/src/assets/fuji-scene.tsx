// Japanese scenery — Mt. Fuji + pagoda + cherry trees
// Positioned bottom-right of the status bar area
// Half-block pixel art

const SCENE_ROWS = [
  { segments: [
    { text: "              ", fg: "" },
    { text: "▄", fg: "#e0e0f0" },
  ]},
  { segments: [
    { text: "             ", fg: "" },
    { text: "▄", fg: "#e0e0f0" },
    { text: "█", fg: "#e0e0f0", bg: "#7a5ca8" },
    { text: "▄", fg: "#e0e0f0" },
  ]},
  { segments: [
    { text: "           ", fg: "" },
    { text: "▄", fg: "#7a5ca8" },
    { text: "▓▓", fg: "#9d7cd8", bg: "#7a5ca8" },
    { text: "█", fg: "#e0e0f0", bg: "#7a5ca8" },
    { text: "▓▓", fg: "#9d7cd8", bg: "#7a5ca8" },
    { text: "▄", fg: "#7a5ca8" },
  ]},
  { segments: [
    { text: "    ", fg: "" },
    { text: "▄▄", fg: "#f0a0b8" },
    { text: "   ", fg: "" },
    { text: "▄", fg: "#7a5ca8" },
    { text: "▓▓▓▓", fg: "#8b6cb8", bg: "#7a5ca8" },
    { text: "▓▓▓▓", fg: "#8b6cb8", bg: "#7a5ca8" },
    { text: "▄", fg: "#7a5ca8" },
  ]},
  { segments: [
    { text: "  ", fg: "" },
    { text: "▄", fg: "#f7a8c4" },
    { text: "█▓", fg: "#f0a0b8" },
    { text: "▄", fg: "#f7a8c4" },
    { text: " ", fg: "" },
    { text: "▄█▄", fg: "#6b5242" },
    { text: "▓▓▓▓▓▓", fg: "#6b5242", bg: "#7a5ca8" },
    { text: "▓▓▓▓▓▓", fg: "#6b5242", bg: "#7a5ca8" },
    { text: "▄", fg: "#7a5ca8" },
  ]},
  { segments: [
    { text: "  ", fg: "" },
    { text: "▀", fg: "#f0a0b8" },
    { text: "█", fg: "#8b6952" },
    { text: "▀", fg: "#f0a0b8" },
    { text: " ", fg: "" },
    { text: "█", fg: "#8b6952" },
    { text: "▓", fg: "#a08060" },
    { text: "█", fg: "#8b6952" },
    { text: " ", fg: "" },
    { text: "▄█▄", fg: "#6b5242" },
    { text: "▄", fg: "#e0a040" },
    { text: "█", fg: "#6b5242" },
  ]},
  { segments: [
    { text: "  ", fg: "" },
    { text: " ", fg: "" },
    { text: "█", fg: "#6b4232" },
    { text: "  ", fg: "" },
    { text: "█", fg: "#6b4232" },
    { text: "▓", fg: "#a08060" },
    { text: "█", fg: "#6b4232" },
    { text: " ", fg: "" },
    { text: "█", fg: "#6b4232" },
    { text: "▓▓", fg: "#a08060" },
    { text: "█", fg: "#e0a040", bg: "#6b5242" },
    { text: "█", fg: "#6b4232" },
  ]},
  { segments: [
    { text: "▒▒▓▓▒▒▓▓▒▒▓▓▒▒▓▓▒", fg: "#2a3050" },
  ]},
]

export function FujiScene() {
  return (
    <box style={{ flexDirection: "column", width: 20, height: 8 }}>
      {SCENE_ROWS.map((row, i) => (
        <text key={`fj-${i}`}>
          {row.segments.map((seg, j) =>
            seg.fg
              ? <span key={`s-${i}-${j}`} fg={seg.fg} bg={seg.bg}>{seg.text}</span>
              : <span key={`s-${i}-${j}`}>{seg.text}</span>
          )}
        </text>
      ))}
    </box>
  )
}
