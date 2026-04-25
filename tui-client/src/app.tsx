import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/react"
import { useCallback, useRef, useState } from "react"
import { streamChat, healthCheck } from "./sse-client"

interface Message {
  role: "user" | "agent" | "system"
  content: string
}

const COLORS = {
  bg: "#1a1b26",
  headerBg: "#16161e",
  inputBg: "#1f2335",
  border: "#3b4261",
  accent: "#c0a0d0",
  userFg: "#7aa2f7",
  agentFg: "#9ece6a",
  systemFg: "#565f89",
  textFg: "#c0caf5",
  errorFg: "#f7768e",
  statusBg: "#16161e",
  dimFg: "#565f89",
}

const LOGO = [
  "  /\\_/\\  ",
  " ( o.o ) ",
  "  > ^ <  ",
]

export function App() {
  const renderer = useRenderer()
  const { width, height } = useTerminalDimensions()
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState("")
  const [isStreaming, setIsStreaming] = useState(false)
  const [agentId, setAgentId] = useState<string | null>(null)
  const [connected, setConnected] = useState(false)
  const sessionId = useRef(`tui-${Date.now()}`)

  const checkConnection = useCallback(async () => {
    const health = await healthCheck()
    if (health) {
      setAgentId(health.agent_id)
      setConnected(true)
      setMessages([{
        role: "system",
        content: `Connected to agent: ${health.agent_id}`,
      }])
    } else {
      setMessages([{
        role: "system",
        content: "Cannot reach CommandClaw server at localhost:8080. Start with: commandclaw serve",
      }])
    }
  }, [])

  useState(() => { checkConnection() })

  const sendMessage = useCallback(async () => {
    const text = inputValue.trim()
    if (!text || isStreaming) return

    setInputValue("")
    setMessages(prev => [...prev, { role: "user", content: text }])
    setIsStreaming(true)

    let agentResponse = ""

    setMessages(prev => [...prev, { role: "agent", content: "" }])

    await streamChat(
      sessionId.current,
      text,
      {
        onToken: (token) => {
          agentResponse += token
          setMessages(prev => {
            const updated = [...prev]
            updated[updated.length - 1] = { role: "agent", content: agentResponse }
            return updated
          })
        },
        onDone: () => {
          setIsStreaming(false)
        },
        onError: (error) => {
          setMessages(prev => [...prev, { role: "system", content: `Error: ${error}` }])
          setIsStreaming(false)
        },
      },
    )
  }, [inputValue, isStreaming])

  useKeyboard((key) => {
    if (key.name === "escape") {
      renderer.destroy()
    }
  })

  const headerHeight = 5
  const statusHeight = 1
  const inputHeight = 3
  const chatHeight = Math.max(height - headerHeight - statusHeight - inputHeight, 3)

  return (
    <box
      style={{
        flexDirection: "column",
        width: "100%",
        height: "100%",
        backgroundColor: COLORS.bg,
      }}
    >
      {/* Header */}
      <box
        style={{
          flexDirection: "row",
          height: headerHeight,
          width: "100%",
          backgroundColor: COLORS.headerBg,
          paddingLeft: 2,
          paddingTop: 1,
          gap: 2,
        }}
      >
        <box style={{ flexDirection: "column", width: 10 }}>
          {LOGO.map((line, i) => (
            <text key={`logo-${i}`} fg={COLORS.accent}>{line}</text>
          ))}
        </box>
        <box style={{ flexDirection: "column", paddingTop: 0 }}>
          <text>
            <span fg={COLORS.textFg}><b>CommandClaw</b></span>
            {"  "}
            <span fg={COLORS.dimFg}>v0.1.0</span>
          </text>
          <text fg={COLORS.dimFg}>
            {agentId ? `agent: ${agentId}` : "connecting..."}
          </text>
        </box>
      </box>

      {/* Chat area */}
      <scrollbox
        style={{
          flexGrow: 1,
          height: chatHeight,
          width: "100%",
          paddingLeft: 2,
          paddingRight: 2,
          paddingTop: 1,
        }}
      >
        {messages.map((msg, i) => (
          <box key={`msg-${i}`} style={{ flexDirection: "row", width: "100%", paddingBottom: 1 }}>
            <text fg={
              msg.role === "user" ? COLORS.userFg
                : msg.role === "agent" ? COLORS.agentFg
                  : COLORS.systemFg
            }>
              {msg.role === "user" ? "you> " : msg.role === "agent" ? "agent> " : "[system] "}
            </text>
            <text fg={msg.role === "system" ? COLORS.systemFg : COLORS.textFg}>
              {msg.content}
              {msg.role === "agent" && isStreaming && i === messages.length - 1 ? "  " : ""}
            </text>
          </box>
        ))}
      </scrollbox>

      {/* Input */}
      <box
        style={{
          height: inputHeight,
          width: "100%",
          borderStyle: "rounded",
          borderColor: isStreaming ? COLORS.dimFg : COLORS.accent,
          paddingLeft: 1,
          backgroundColor: COLORS.inputBg,
        }}
      >
        <text fg={COLORS.accent}>{">"} </text>
        <input
          placeholder={isStreaming ? "Agent is responding..." : "Type a message..."}
          onInput={setInputValue}
          onSubmit={sendMessage}
          focused={!isStreaming}
          width={width - 8}
        />
      </box>

      {/* Status bar */}
      <box
        style={{
          height: statusHeight,
          width: "100%",
          backgroundColor: COLORS.statusBg,
          flexDirection: "row",
          justifyContent: "space-between",
          paddingLeft: 2,
          paddingRight: 2,
        }}
      >
        <text fg={COLORS.dimFg}>
          {connected
            ? <span fg={COLORS.agentFg}>{"*"} connected</span>
            : <span fg={COLORS.errorFg}>{"*"} disconnected</span>
          }
        </text>
        <text fg={COLORS.dimFg}>
          {isStreaming ? "streaming..." : "ready"}
          {"  "}
          ESC to quit
        </text>
      </box>
    </box>
  )
}
