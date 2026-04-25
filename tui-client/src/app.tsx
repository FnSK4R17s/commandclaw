import { useKeyboard, useRenderer, useTerminalDimensions } from "@opentui/react"
import { useCallback, useRef, useState } from "react"
import { Mascot } from "./assets/mascot"
import { CherryBranch } from "./assets/cherry-branch"
import { Petals } from "./assets/petals"
import { FujiScene } from "./assets/fuji-scene"
import { streamChat, healthCheck } from "./sse-client"

interface Message {
  role: "user" | "agent" | "system"
  content: string
}

const C = {
  bg: "#1a1b2e",
  headerBg: "#16161e",
  inputBg: "#1f2035",
  inputBorder: "#e06080",
  inputBorderDim: "#5a3050",
  accent: "#c0a0d0",
  userFg: "#7aa2f7",
  agentFg: "#9ece6a",
  systemFg: "#565f89",
  textFg: "#c0caf5",
  errorFg: "#f7768e",
  statusBg: "#16161e",
  dimFg: "#565f89",
  versionFg: "#e890ab",
  titleFg: "#e0e0f0",
  sakura: "#f7a8c4",
}

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
        content: "Cannot reach CommandClaw server. Start with: commandclaw serve",
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
        onDone: () => { setIsStreaming(false) },
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

  const headerHeight = 7
  const inputHeight = 3
  const statusHeight = 2

  return (
    <box style={{ flexDirection: "column", width: "100%", height: "100%", backgroundColor: C.bg }}>

      {/* === HEADER === */}
      <box style={{
        flexDirection: "row",
        height: headerHeight,
        width: "100%",
        backgroundColor: C.headerBg,
        paddingLeft: 2,
        paddingTop: 1,
      }}>
        {/* Mascot */}
        <Mascot />

        {/* Title block */}
        <box style={{ flexDirection: "column", paddingLeft: 2, paddingTop: 1 }}>
          <text>
            <span fg={C.titleFg}><b>CommandClaw</b></span>
            {"  "}
            <span fg={C.versionFg}>v0.1.0</span>
            {"  "}
            <span fg={C.sakura}>{"✿"}</span>
          </text>
          <text fg={C.dimFg}>
            {agentId ? `agent: ${agentId}` : "connecting..."}
          </text>
        </box>

        {/* Cherry branch — top right */}
        <box style={{ position: "absolute", right: 0, top: 0 }}>
          <CherryBranch />
        </box>
      </box>

      {/* === CHAT AREA === */}
      <box style={{ flexGrow: 1, width: "100%", position: "relative" }}>
        {/* Falling petals overlay */}
        <Petals width={width} height={height - headerHeight - inputHeight - statusHeight} />

        {/* Messages */}
        <scrollbox style={{
          width: "100%",
          height: "100%",
          paddingLeft: 3,
          paddingRight: 3,
          paddingTop: 1,
        }}>
          {messages.map((msg, i) => (
            <box key={`msg-${i}`} style={{ width: "100%", paddingBottom: 1 }}>
              <text>
                <span fg={
                  msg.role === "user" ? C.userFg
                    : msg.role === "agent" ? C.agentFg
                      : C.systemFg
                }>
                  {msg.role === "user" ? "you> " : msg.role === "agent" ? "agent> " : "[system] "}
                </span>
                <span fg={msg.role === "system" ? C.systemFg : C.textFg}>
                  {msg.content}
                  {msg.role === "agent" && isStreaming && i === messages.length - 1 ? " ▊" : ""}
                </span>
              </text>
            </box>
          ))}
        </scrollbox>
      </box>

      {/* === INPUT === */}
      <box style={{
        height: inputHeight,
        width: "100%",
        borderStyle: "rounded",
        borderColor: isStreaming ? C.inputBorderDim : C.inputBorder,
        paddingLeft: 1,
        backgroundColor: C.inputBg,
      }}>
        <text fg={C.titleFg}><b>{">"}</b> </text>
        <input
          placeholder={isStreaming ? "Agent is responding..." : "Type a message..."}
          onInput={setInputValue}
          onSubmit={sendMessage}
          focused={!isStreaming}
          width={width - 8}
        />
      </box>

      {/* === STATUS BAR === */}
      <box style={{
        height: statusHeight,
        width: "100%",
        backgroundColor: C.statusBg,
        borderStyle: "single",
        borderColor: C.inputBorderDim,
        flexDirection: "row",
        justifyContent: "space-between",
        paddingLeft: 2,
        paddingRight: 2,
        position: "relative",
      }}>
        <text fg={C.dimFg}>
          {connected
            ? <span fg={C.agentFg}>{"●"} connected</span>
            : <span fg={C.errorFg}>{"●"} disconnected</span>
          }
          {"  "}
          {isStreaming ? <span fg={C.sakura}>streaming...</span> : "ready"}
        </text>

        <text fg={C.dimFg}>
          ESC to quit
        </text>

        {/* Fuji scene — bottom right */}
        <box style={{ position: "absolute", right: 1, bottom: -7 }}>
          <FujiScene />
        </box>
      </box>
    </box>
  )
}
