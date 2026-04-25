const DEFAULT_BASE_URL = "http://127.0.0.1:8080"

export interface StreamCallbacks {
  onToken: (token: string) => void
  onDone: (result: { success: boolean; error: string | null }) => void
  onError: (error: string) => void
}

export async function streamChat(
  sessionId: string,
  message: string,
  callbacks: StreamCallbacks,
  baseUrl = DEFAULT_BASE_URL,
): Promise<void> {
  const url = `${baseUrl}/chat/${sessionId}/stream`

  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  })

  if (!response.ok) {
    callbacks.onError(`HTTP ${response.status}: ${response.statusText}`)
    return
  }

  const reader = response.body?.getReader()
  if (!reader) {
    callbacks.onError("No response body")
    return
  }

  const decoder = new TextDecoder()
  let buffer = ""
  let currentEvent = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""

    for (const line of lines) {
      const trimmed = line.trim()

      if (trimmed.startsWith("event: ")) {
        currentEvent = trimmed.slice(7)
      } else if (trimmed.startsWith("data: ")) {
        const data = trimmed.slice(6)

        if (currentEvent === "token") {
          callbacks.onToken(data)
        } else if (currentEvent === "done") {
          try {
            callbacks.onDone(JSON.parse(data))
          } catch {
            callbacks.onDone({ success: true, error: null })
          }
        } else if (currentEvent === "error") {
          try {
            callbacks.onError(JSON.parse(data).detail)
          } catch {
            callbacks.onError(data)
          }
        }

        currentEvent = ""
      }
    }
  }
}

export async function healthCheck(
  baseUrl = DEFAULT_BASE_URL,
): Promise<{ status: string; agent_id: string } | null> {
  try {
    const resp = await fetch(`${baseUrl}/health`)
    if (resp.ok) return await resp.json()
    return null
  } catch {
    return null
  }
}
