import { useEffect, useState } from "react"

interface Petal {
  x: number
  y: number
  char: string
  color: string
  speed: number
  drift: number
  wobble: number
}

const PETAL_CHARS = ["*", "·", "•", "°", "✿"]
const PETAL_COLORS = ["#ffc0d9", "#f6a6c3", "#e789aa", "#d97b9c", "#f8d0df"]

function createPetals(width: number, height: number, topOffset: number): Petal[] {
  const count = Math.max(Math.floor((width * height) / 70), 10)
  const petals: Petal[] = []
  const safeTop = Math.min(topOffset, Math.max(height - 1, 0))
  const safeWidth = Math.max(width - 6, 1)
  const safeHeight = Math.max(height - safeTop, 1)

  for (let i = 0; i < count; i++) {
    const seed = (i * 7919 + 1009) % 9973
    petals.push({
      x: (seed * 3) % safeWidth + 3,
      y: (seed * 7) % safeHeight + safeTop,
      char: PETAL_CHARS[seed % PETAL_CHARS.length]!,
      color: PETAL_COLORS[seed % PETAL_COLORS.length]!,
      speed: 0.22 + (seed % 5) * 0.08,
      drift: 0.16 + (seed % 4) * 0.06,
      wobble: (seed % 11) * 0.28,
    })
  }

  return petals
}

export function Petals({
  width,
  height,
  topOffset = 0,
}: {
  width: number
  height: number
  topOffset?: number
}) {
  const [petals, setPetals] = useState(() => createPetals(width, height, topOffset))
  const safeTop = Math.min(topOffset, Math.max(height - 1, 0))

  useEffect(() => {
    const interval = setInterval(() => {
      setPetals((prev: Petal[]) =>
        prev.map((p: Petal) => {
          let newY = p.y + p.speed
          let newX = p.x + p.drift + Math.sin(newY + p.wobble) * 0.28

          if (newY >= height) {
            newY = safeTop
            newX = ((p.x * 13 + p.y * 7 + p.wobble * 19) % Math.max(width - 6, 1)) + 3
          }
          if (newX < 1) newX = Math.max(width - 3, 1)
          if (newX >= width - 1) newX = 2

          return { ...p, x: newX, y: newY }
        }),
      )
    }, 150)

    return () => clearInterval(interval)
  }, [width, height, safeTop])

  useEffect(() => {
    setPetals(createPetals(width, height, topOffset))
  }, [width, height, topOffset])

  return (
    <>
      {petals.map((p, i) => (
        <box
          key={`petal-${i}`}
          style={{
            position: "absolute",
            left: Math.min(Math.max(Math.floor(p.x), 0), Math.max(width - 1, 0)),
            top: Math.min(Math.max(Math.floor(p.y), safeTop), Math.max(height - 1, 0)),
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
