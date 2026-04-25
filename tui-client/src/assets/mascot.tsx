// CommandClaw mascot — pixel art crab/claw creature
// Uses ▀▄█ half-block rendering for 2x vertical resolution

export function Mascot() {
  return (
    <box style={{ flexDirection: "column", width: 16, height: 8 }}>
      <text>
        <span fg="#2a2035">{"  "}</span>
        <span fg="#e8956a">{"  ▄▄▄▄▄▄  "}</span>
      </text>
      <text>
        <span fg="#2a2035">{" "}</span>
        <span fg="#d4845a">{"▄"}</span>
        <span fg="#e8956a" bg="#e8956a">{"██"}</span>
        <span fg="#1a1b2e" bg="#e8956a">{"▄▄"}</span>
        <span fg="#e8956a" bg="#e8956a">{"██"}</span>
        <span fg="#d4845a">{"▄"}</span>
      </text>
      <text>
        <span fg="#d4845a">{"▄"}</span>
        <span fg="#e8956a" bg="#e8956a">{"█"}</span>
        <span fg="#ffffff" bg="#e8956a">{"◆"}</span>
        <span fg="#e8956a" bg="#e8956a">{"██"}</span>
        <span fg="#ffffff" bg="#e8956a">{"◆"}</span>
        <span fg="#e8956a" bg="#e8956a">{"█"}</span>
        <span fg="#d4845a">{"▄"}</span>
        <span fg="#2a2035">{"  "}</span>
      </text>
      <text>
        <span fg="#d4845a" bg="#e8956a">{"█"}</span>
        <span fg="#e8956a" bg="#e8956a">{"██"}</span>
        <span fg="#1a1b2e" bg="#e8956a">{"▀▀"}</span>
        <span fg="#e8956a" bg="#e8956a">{"██"}</span>
        <span fg="#d4845a" bg="#e8956a">{"█"}</span>
        <span fg="#2a2035">{"  "}</span>
      </text>
      <text>
        <span fg="#2a2035">{" "}</span>
        <span fg="#e8956a">{"▀"}</span>
        <span fg="#d4845a">{"▄▄▄▄▄▄"}</span>
        <span fg="#e8956a">{"▀"}</span>
        <span fg="#2a2035">{"  "}</span>
      </text>
      <text>
        <span fg="#d4845a">{"▀▄"}</span>
        <span fg="#2a2035">{"  "}</span>
        <span fg="#d4845a">{"▀▀▀▀"}</span>
        <span fg="#2a2035">{"  "}</span>
        <span fg="#d4845a">{"▄▀"}</span>
      </text>
    </box>
  )
}

export function Sparkles() {
  return (
    <box style={{ position: "absolute", width: 3, height: 4 }}>
      <text fg="#9d7cd8">{"✦"}</text>
      <text fg="#7a5ca8">{" ·"}</text>
      <text fg="#b4a0d8">{"· "}</text>
      <text fg="#9d7cd8">{" ✧"}</text>
    </box>
  )
}
