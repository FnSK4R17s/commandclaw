// Animated falling cherry blossom petals

import { useEffect, useState } from "react"

interface Petal {
  x: number
  y: number
  char: string
  color: string
  speed: number
  drift: number
}

const PETAL_CHARS = ["❀", "✿", "·", "•", "⁕", "∘", "◦"]
const PETAL_COLORS = ["#f7a8c4", "#e890ab", "#ffb7d5", "#d4809a", "#f0a0b8"]

function createPetals(width: number, height: number): Petal[] {
  const count = Math.max(Math.floor((width * height) / 100), 6)
  const petals: Petal[] = []

  for (let i = 0; i < count; i++) {
    const seed = (i * 7919 + 1009) % 9973
    petals.push({
      x: (seed * 3) % (width - 4) + 2,
      y: (seed * 7) % height,
      char: PETAL_CHARS[seed % PETAL_CHARS.length]!,
      color: PETAL_COLORS[seed % PETAL_COLORS.length]!,
      speed: 0.3 + (seed % 5) * 0.15,
      drift: ((seed % 3) - 1) * 0.4,
    })
  }

  return petals
}

export function Petals({ width, height }: { width: number; height: number }) {
  const [petals, setPetals] = useState(() => createPetals(width, height))

  useEffect(() => {
    const interval = setInterval(() => {
      setPetals((prev: Petal[]) =>
        prev.map((p: Petal) => {
          let newY = p.y + p.speed
          let newX = p.x + p.drift

          if (newY >= height) {
            newY = -1
            newX = Math.floor(Math.random() * (width - 4)) + 2
          }
          if (newX < 0) newX = width - 2
          if (newX >= width) newX = 1

          return { ...p, x: newX, y: newY }
        }),
      )
    }, 150)

    return () => clearInterval(interval)
  }, [width, height])

  useEffect(() => {
    setPetals(createPetals(width, height))
  }, [width, height])

  return (
    <>
      {petals.map((p, i) => (
        <box
          key={`petal-${i}`}
          style={{
            position: "absolute",
            left: Math.round(p.x),
            top: Math.round(p.y),
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
