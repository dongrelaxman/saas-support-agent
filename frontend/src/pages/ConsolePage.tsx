import { useState, useEffect, useCallback, useRef } from 'react'
import type { Ticket, ThreadDetail } from '../types'
import { getThread, resumeThread } from '../api'
import MessageBubble from '../components/MessageBubble'

function timeAgo(iso: string) {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60)   return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

function ScoreBadge({ score, threshold }: { score: number; threshold: number }) {
  const pct   = Math.round(score * 100)
  const below = score < threshold
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-mono ${
      below ? 'bg-red-500/10 text-red-400' : 'bg-green-500/10 text-green-400'
    }`}>
      {pct}%
      <span className="opacity-50">{below ? '↓' : '↑'} threshold</span>
    </span>
  )
}

export default function ConsolePage() {
  const [tickets, setTickets]         = useState<Ticket[]>([])
  const [wsStatus, setWsStatus]       = useState<'connecting' | 'open' | 'closed'>('connecting')
  const [newBadge, setNewBadge]       = useState(false)
  const [selected, setSelected]       = useState<Ticket | null>(null)
  const [detail, setDetail]           = useState<ThreadDetail | null>(null)
  const [reply, setReply]             = useState('')
  const [resolved, setResolved]       = useState(false)
  const [sending, setSending]         = useState(false)
  const [loadingDetail, setLoading]   = useState(false)
  const [sent, setSent]               = useState(false)
  const prevTicketIds                 = useRef<Set<string>>(new Set())
  const wsRef                         = useRef<WebSocket | null>(null)

  // ── WebSocket connection ────────────────────────────────────────────────────
  useEffect(() => {
    function connect() {
      const ws = new WebSocket(`ws://${window.location.host}/ws/console`)
      wsRef.current = ws

      ws.onopen  = () => setWsStatus('open')
      ws.onclose = () => {
        setWsStatus('closed')
        setTimeout(connect, 3000)   // auto-reconnect
      }
      ws.onerror = () => ws.close()

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data as string)
          if (data.type !== 'tickets') return
          const incoming: Ticket[] = data.tickets

          // Flash badge if there are new ticket IDs
          const incomingIds = new Set(incoming.map((t: Ticket) => t.ticket_id))
          const hasNew = [...incomingIds].some(id => !prevTicketIds.current.has(id))
          if (hasNew && prevTicketIds.current.size > 0) setNewBadge(true)
          prevTicketIds.current = incomingIds

          setTickets(incoming)
        } catch { /* ignore */ }
      }

      // Keep-alive ping every 25 s
      const pingId = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 25_000)

      return () => clearInterval(pingId)
    }

    const cleanup = connect()
    return () => {
      cleanup?.()
      wsRef.current?.close()
    }
  }, [])

  // ── Select a ticket ─────────────────────────────────────────────────────────
  const selectTicket = useCallback(async (ticket: Ticket) => {
    setNewBadge(false)
    setSelected(ticket)
    setDetail(null)
    setReply('')
    setResolved(false)
    setSent(false)
    setLoading(true)
    try {
      setDetail(await getThread(ticket.thread_id))
    } finally {
      setLoading(false)
    }
  }, [])

  // ── Send agent reply ─────────────────────────────────────────────────────────
  const handleSend = useCallback(async () => {
    if (!selected || !reply.trim() || sending) return
    setSending(true)
    try {
      await resumeThread(selected.thread_id, reply.trim(), resolved)
      setSent(true)
      setSelected(null)
      setDetail(null)
      setReply('')
    } finally {
      setSending(false)
    }
  }, [selected, reply, resolved, sending])

  // ── Status dot ───────────────────────────────────────────────────────────────
  const StatusDot = () => {
    if (wsStatus === 'open')        return <span className="w-2 h-2 rounded-full bg-green-400" />
    if (wsStatus === 'connecting')  return <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
    return <span className="w-2 h-2 rounded-full bg-red-400" />
  }

  return (
    <div className="flex h-full">

      {/* ── Ticket list ────────────────────────────────────────────────────── */}
      <aside className="w-80 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-4 border-b border-gray-800 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold text-gray-200">Open tickets</h2>
              {newBadge && (
                <span className="px-1.5 py-0.5 rounded bg-amber-500 text-black text-xs font-bold animate-bounce">
                  NEW
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5">
              <StatusDot />
              {wsStatus === 'open'       ? 'Live' :
               wsStatus === 'connecting' ? 'Connecting…' : 'Disconnected — retrying'}
              &nbsp;·&nbsp;{tickets.length} awaiting response
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {tickets.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="w-12 h-12 rounded-xl bg-green-500/10 flex items-center justify-center mb-3">
                <svg className="w-6 h-6 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <p className="text-gray-500 text-sm">No open tickets</p>
            </div>
          )}

          {tickets.map(ticket => (
            <button
              key={ticket.ticket_id}
              onClick={() => selectTicket(ticket)}
              className={`w-full text-left p-3 rounded-xl transition-colors ${
                selected?.ticket_id === ticket.ticket_id
                  ? 'bg-amber-500/10 border border-amber-500/30'
                  : 'hover:bg-gray-800 border border-transparent'
              }`}
            >
              <div className="flex items-start gap-2">
                <span className="flex-shrink-0 w-2 h-2 rounded-full bg-amber-400 mt-1.5 animate-pulse" />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-mono text-gray-400 truncate">
                    {ticket.thread_id.slice(0, 18)}…
                  </p>
                  {ticket.summary && (
                    <p className="text-xs text-gray-300 mt-1 line-clamp-2">{ticket.summary}</p>
                  )}
                  <p className="text-xs text-gray-600 mt-1">{timeAgo(ticket.created_at)}</p>
                </div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* ── Ticket detail ──────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0">

        {!selected && !sent && (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <div className="w-16 h-16 rounded-2xl bg-gray-800 flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
            </div>
            <p className="text-gray-500 text-sm">Select a ticket to view the conversation</p>
          </div>
        )}

        {sent && (
          <div className="flex-1 flex flex-col items-center justify-center text-center">
            <div className="w-16 h-16 rounded-2xl bg-green-500/10 flex items-center justify-center mb-4">
              <svg className="w-8 h-8 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-gray-300 font-medium">Response sent</p>
            <p className="text-gray-500 text-xs mt-1">The customer has received your reply.</p>
            <button onClick={() => setSent(false)} className="mt-4 text-indigo-400 hover:text-indigo-300 text-sm">
              Back to tickets
            </button>
          </div>
        )}

        {selected && !sent && (
          <>
            {/* Header */}
            <div className="px-6 py-4 border-b border-gray-800 flex items-center justify-between flex-shrink-0">
              <div>
                <p className="text-xs text-gray-500">Thread</p>
                <p className="text-sm font-mono text-gray-200">{selected.thread_id}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-gray-500">Ticket</p>
                <p className="text-xs font-mono text-amber-400">{selected.ticket_id.slice(0, 8)}</p>
              </div>
            </div>

            {/* Escalation context + summary */}
            {detail && (
              <div className="px-6 pt-4 space-y-3 flex-shrink-0">
                {/* Escalation reason */}
                <div className="p-3 rounded-xl bg-gray-800/60 border border-gray-700">
                  <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-2">
                    Escalation reason
                  </p>
                  <div className="flex flex-wrap items-center gap-3 text-xs">
                    <span className="text-gray-400">
                      {detail.low_conf_streak >= 3
                        ? `${detail.low_conf_streak} consecutive low-confidence turns`
                        : 'User explicitly requested a human'}
                    </span>
                    <span className="text-gray-600">·</span>
                    <span className="text-gray-400">
                      Best similarity score:
                    </span>
                    <ScoreBadge score={detail.top_score} threshold={detail.threshold} />
                    <span className="text-gray-600">·</span>
                    <span className="text-gray-500">
                      threshold {Math.round(detail.threshold * 100)}%
                    </span>
                  </div>
                </div>

                {/* Rolling summary */}
                {detail.summary && (
                  <div className="p-3 rounded-xl bg-gray-800/40 border border-gray-700/60">
                    <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">
                      Conversation summary
                    </p>
                    <p className="text-xs text-gray-300 leading-relaxed">{detail.summary}</p>
                  </div>
                )}
              </div>
            )}

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-6 py-4 min-h-0">
              {loadingDetail && (
                <div className="flex justify-center py-12">
                  <span className="w-6 h-6 border-2 border-gray-700 border-t-indigo-500 rounded-full animate-spin" />
                </div>
              )}
              {detail && !loadingDetail && detail.messages.map((msg, i) => (
                <MessageBubble key={msg.id ?? i} message={msg} />
              ))}
            </div>

            {/* Reply form */}
            <div className="border-t border-gray-800 p-6 flex-shrink-0">
              <p className="text-xs text-gray-500 mb-3 font-medium uppercase tracking-wider">
                Agent reply
              </p>
              <textarea
                value={reply}
                onChange={e => setReply(e.target.value)}
                placeholder="Type your reply to the customer…"
                rows={3}
                className="w-full bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-sm text-gray-100 placeholder-gray-600 resize-none outline-none focus:border-indigo-500 transition-colors"
              />
              <div className="mt-3 flex items-center justify-between">
                <label className="flex items-center gap-2 cursor-pointer select-none">
                  <div
                    onClick={() => setResolved(v => !v)}
                    className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors ${resolved ? 'bg-green-500' : 'bg-gray-700'}`}
                  >
                    <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${resolved ? 'translate-x-5' : 'translate-x-0.5'}`} />
                  </div>
                  <span className="text-sm text-gray-400">Mark as resolved</span>
                </label>
                <button
                  onClick={handleSend}
                  disabled={!reply.trim() || sending}
                  className="px-5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center gap-2"
                >
                  {sending && (
                    <span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                  )}
                  Send reply
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
