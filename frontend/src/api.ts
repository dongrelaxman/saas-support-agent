import type { Thread, ThreadDetail, Ticket, StreamEvent } from './types'

const BASE = '/api'

export async function saveThread(thread_id: string, title: string): Promise<void> {
  await fetch(`${BASE}/threads`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id, title }),
  })
}

export async function listThreads(): Promise<Thread[]> {
  const res = await fetch(`${BASE}/threads`)
  const data = await res.json()
  return data.threads as Thread[]
}

export async function getThread(thread_id: string): Promise<ThreadDetail> {
  const res = await fetch(`${BASE}/threads/${thread_id}`)
  if (!res.ok) throw new Error('Thread not found')
  return res.json() as Promise<ThreadDetail>
}

export async function listTickets(): Promise<Ticket[]> {
  const res = await fetch(`${BASE}/tickets`)
  const data = await res.json()
  return data.tickets as Ticket[]
}

export async function resumeThread(
  thread_id: string,
  agent_message: string,
  resolved: boolean
): Promise<{ status: string; message: string }> {
  const res = await fetch(`${BASE}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id, agent_message, resolved }),
  })
  return res.json()
}

/**
 * Stream a chat message and call handlers for each event.
 * Uses fetch + ReadableStream to support SSE over POST.
 */
export async function streamChat(
  thread_id: string,
  message: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thread_id, message }),
    signal,
  })

  if (!res.ok || !res.body) {
    onEvent({ type: 'error', content: 'Network error' })
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6)) as StreamEvent
          onEvent(event)
        } catch {
          // malformed line — skip
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
