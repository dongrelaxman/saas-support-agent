import { useState, useEffect, useRef, useCallback } from 'react'
import type { Message, Thread, ConversationStatus } from '../types'
import { streamChat, listThreads, saveThread, getThread } from '../api'
import MessageBubble from '../components/MessageBubble'

function generateId() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.random() * 16 | 0
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16)
  })
}

function formatTitle(msg: string) {
  return msg.length > 40 ? msg.slice(0, 40) + '…' : msg
}

interface LocalThread extends Thread {
  messages: Message[]
  status: ConversationStatus
  ticketId?: string
}

// Sync server state into a LocalThread object
function applyServerState(
  thread: LocalThread,
  detail: Awaited<ReturnType<typeof getThread>>
): LocalThread {
  return {
    ...thread,
    messages:  detail.messages,
    status:    detail.status as ConversationStatus,
    ticketId:  detail.ticket_id ?? thread.ticketId,
  }
}

export default function ChatPage() {
  const [threads, setThreads] = useState<LocalThread[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const bottomRef  = useRef<HTMLDivElement>(null)
  const abortRef   = useRef<AbortController | null>(null)
  const inputRef   = useRef<HTMLTextAreaElement>(null)
  // Always-current snapshot of threads so sendMessage never closes over stale state
  const threadsRef = useRef<LocalThread[]>([])

  // ── Load saved thread list on mount ────────────────────────────────────────
  useEffect(() => {
    listThreads().then(saved => {
      if (saved.length === 0) {
        // No prior conversations — create one automatically so the input is
        // immediately usable without requiring the user to click a button.
        const id = generateId()
        setThreads([{ thread_id: id, title: 'New conversation', messages: [], status: 'bot' }])
        setActiveId(id)
        return
      }
      const loaded: LocalThread[] = saved.map(t => ({
        ...t,
        messages: [],
        status:   'bot' as ConversationStatus,
      }))
      setThreads(loaded)
      setActiveId(loaded[0].thread_id)
    })
  }, [])

  // ── When the active thread changes, fetch its full state from the server ───
  // This restores historical messages when switching threads and picks up the
  // current status so the UI shows the correct banner.
  useEffect(() => {
    if (!activeId || streaming) return
    getThread(activeId)
      .then(detail => {
        setThreads(prev =>
          prev.map(t => t.thread_id === activeId ? applyServerState(t, detail) : t)
        )
      })
      .catch(() => {})     // new thread — no server state yet, that's fine
  }, [activeId])           // eslint-disable-line react-hooks/exhaustive-deps

  // ── Poll the server while waiting for a human agent ────────────────────────
  // When the agent resumes the thread via the console, the server state updates.
  // Polling at 3 s keeps the chat in sync without a persistent WebSocket.
  useEffect(() => {
    if (!activeId) return
    const thread = threads.find(t => t.thread_id === activeId)
    if (thread?.status !== 'awaiting_human') return

    const id = setInterval(async () => {
      const detail = await getThread(activeId).catch(() => null)
      if (!detail) return
      setThreads(prev =>
        prev.map(t => t.thread_id === activeId ? applyServerState(t, detail) : t)
      )
    }, 3_000)

    return () => clearInterval(id)
  }, [activeId, threads.find(t => t.thread_id === activeId)?.status])  // eslint-disable-line react-hooks/exhaustive-deps

  // ── Scroll to bottom on new content ────────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [threads, streamingContent])

  // Keep ref in sync so callbacks always see the latest threads without dep churn
  threadsRef.current = threads

  const activeThread = threads.find(t => t.thread_id === activeId) ?? null

  // ── New chat ────────────────────────────────────────────────────────────────
  const newChat = useCallback(() => {
    const id = generateId()
    const thread: LocalThread = {
      thread_id: id,
      title:     'New conversation',
      messages:  [],
      status:    'bot',
    }
    setThreads(prev => [thread, ...prev])
    setActiveId(id)
    setInput('')
    inputRef.current?.focus()
  }, [])

  // ── Switch thread ───────────────────────────────────────────────────────────
  const selectThread = useCallback((id: string) => {
    abortRef.current?.abort()
    setStreaming(false)
    setStreamingContent('')
    setActiveId(id)
  }, [])

  // ── Send message ────────────────────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    if (!input.trim() || streaming || !activeId) return

    const text = input.trim()

    // Compute isFirst synchronously NOW, before any setThreads calls.
    // React's useState updater functions run lazily during the render phase,
    // so reading isFirst from inside the updater and checking it immediately
    // after setThreads() always sees the initial value (false). Using a ref
    // gives us the current snapshot without stale-closure issues.
    const currentThread = threadsRef.current.find(t => t.thread_id === activeId)
    const isFirst = (currentThread?.messages.length ?? 0) === 0

    setInput('')

    // Optimistic: add the user message immediately
    const userMsg: Message = { role: 'human', content: text, id: generateId() }
    setThreads(prev =>
      prev.map(t =>
        t.thread_id === activeId
          ? { ...t, messages: [...t.messages, userMsg] }
          : t
      )
    )

    setStreaming(true)
    setStreamingContent('')

    const controller = new AbortController()
    abortRef.current  = controller

    let accumulated   = ''
    let finalStatus: ConversationStatus = 'bot'
    let finalTicketId: string | undefined

    try {
      await streamChat(
        activeId,
        text,
        event => {
          if (event.type === 'token' && event.content) {
            accumulated += event.content
            setStreamingContent(accumulated)
          } else if (event.type === 'state') {
            finalStatus   = event.status    ?? 'bot'
            finalTicketId = event.ticket_id ?? undefined
          }
        },
        controller.signal
      )
    } catch {
      // aborted or network error — keep partial streamed content
    }

    const aiMsg: Message = {
      role:    'ai',
      content: accumulated || '…',
      id:      generateId(),
    }

    setThreads(prev =>
      prev.map(t => {
        if (t.thread_id !== activeId) return t
        return {
          ...t,
          title:    isFirst ? formatTitle(text) : t.title,
          messages: [...t.messages, aiMsg],
          status:   finalStatus,
          ticketId: finalTicketId,
        }
      })
    )

    // Persist thread title after the first exchange
    if (isFirst) saveThread(activeId, formatTitle(text))

    setStreamingContent('')
    setStreaming(false)
    inputRef.current?.focus()
  }, [input, streaming, activeId])

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const status    = activeThread?.status ?? 'bot'
  const isWaiting = status === 'awaiting_human'
  const isResolved = status === 'resolved'

  return (
    <div className="flex h-full">
      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <aside className="w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800">
          <button
            onClick={newChat}
            className="w-full py-2 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium transition-colors"
          >
            + New conversation
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto p-2 space-y-1">
          {threads.map(t => (
            <button
              key={t.thread_id}
              onClick={() => selectThread(t.thread_id)}
              className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors truncate ${
                t.thread_id === activeId
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
              }`}
            >
              <span className="flex items-center gap-2">
                {t.status === 'awaiting_human' && (
                  <span className="flex-shrink-0 w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                )}
                {t.status === 'resolved' && (
                  <span className="flex-shrink-0 w-2 h-2 rounded-full bg-green-400" />
                )}
                <span className="truncate">{t.title}</span>
              </span>
            </button>
          ))}
          {threads.length === 0 && (
            <p className="text-center text-gray-600 text-xs mt-8">No conversations yet</p>
          )}
        </nav>
      </aside>

      {/* ── Chat area ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* Status banners */}
        {isWaiting && (
          <div className="bg-amber-500/10 border-b border-amber-500/30 px-6 py-2.5 text-amber-400 text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            A support agent has been notified and will join shortly.
            {activeThread?.ticketId && (
              <span className="ml-auto text-amber-400/60 text-xs font-mono">
                Ticket: {activeThread.ticketId.slice(0, 8)}
              </span>
            )}
          </div>
        )}
        {isResolved && (
          <div className="bg-green-500/10 border-b border-green-500/30 px-6 py-2.5 text-green-400 text-sm flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            This conversation has been resolved by a support agent.
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6">
          {activeThread ? (
            <>
              {activeThread.messages.length === 0 && !streaming && (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="w-16 h-16 rounded-2xl bg-indigo-600/20 flex items-center justify-center mb-4">
                    <svg className="w-8 h-8 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                        d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                    </svg>
                  </div>
                  <p className="text-gray-400 text-sm">How can I help you today?</p>
                </div>
              )}
              {activeThread.messages.map((msg, i) => (
                <MessageBubble key={msg.id ?? i} message={msg} />
              ))}
              {streaming && streamingContent && (
                <MessageBubble
                  message={{ role: 'ai', content: streamingContent }}
                  streaming
                />
              )}
            </>
          ) : (
            <div className="flex items-center justify-center h-full">
              <p className="text-gray-600 text-sm">Select or start a conversation</p>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-800 px-6 py-4">
          <div className="relative flex items-end gap-3 bg-gray-800 rounded-2xl px-4 py-3">
            <textarea
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder={
                !activeThread ? 'Start a new conversation…'
                : isWaiting   ? 'Waiting for a support agent…'
                : isResolved  ? 'This conversation is resolved'
                :               'Type your message… (Enter to send)'
              }
              disabled={streaming || !activeThread || isResolved}
              rows={1}
              className="flex-1 bg-transparent text-gray-100 placeholder-gray-500 text-sm resize-none outline-none max-h-40 overflow-y-auto"
              style={{ minHeight: '24px' }}
            />
            <button
              onClick={sendMessage}
              disabled={streaming || !input.trim() || !activeThread || isResolved}
              className="flex-shrink-0 w-8 h-8 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
            >
              {streaming ? (
                <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
              ) : (
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h14M12 5l7 7-7 7" />
                </svg>
              )}
            </button>
          </div>
          <p className="text-center text-gray-700 text-xs mt-2">
            Shift+Enter for new line · powered by GPT-4o mini + Weaviate
          </p>
        </div>
      </div>
    </div>
  )
}
