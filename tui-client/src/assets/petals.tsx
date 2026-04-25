// Falling cherry blossom petals — scattered decorative elements
// Each petal is a small colored character at a fixed position

interface Petal {
  x: number
  y: number
  char: string
  color: string
}

const PETAL_CHARS = ["❀", "✿", "·", "•", "⁕", "∘"]
const PETAL_COLORS = ["#f7a8c4", "#e890ab", "#ffb7d5", "#d4809a", "#f0a0b8"]

export function generatePetals(width: number, height: number): Petal[] {
  const count = Math.floor((width * height) / 120)
  const petals: Petal[] = []

  // Deterministic placement using simple hash
  for (let i = 0; i < count; i++) {
    const seed = (i * 7919 + 1009) % 9973
    petals.push({
      x: (seed * 3) % (width - 4) + 2,
      y: (seed * 7) % (height - 6) + 3,
      char: PETAL_CHARS[seed % PETAL_CHARS.length]!,
      color: PETAL_COLORS[seed % PETAL_COLORS.length]!,
    })
  }

  return petals
}

export function Petals({ width, height }: { width: number; height: number }) {
  const petals = generatePetals(width, height)

  return (
    <>
      {petals.map((p, i) => (
        <box
          key={`petal-${i}`}
          style={{
            position: "absolute",
            left: p.x,
            top: p.y,
            width: 1,
            height: 1,
          }}
        >
          <text fg={p.color}>{p.char}</text>
        </box>
      ))}
    </>
  )
}
