export type MessageRole = 'human' | 'ai' | 'system'

export interface Message {
  id?: string
  role: MessageRole
  content: string
}

export interface Thread {
  thread_id: string
  title: string
}

export interface Ticket {
  ticket_id: string
  thread_id: string
  summary: string
  created_at: string
}

export interface ThreadDetail {
  thread_id: string
  status: 'bot' | 'awaiting_human' | 'resolved'
  ticket_id?: string
  summary: string
  top_score: number
  low_conf_streak: number
  threshold: number
  messages: Message[]
}

export type ConversationStatus = 'bot' | 'awaiting_human' | 'resolved'

export interface StreamEvent {
  type: 'token' | 'state' | 'done' | 'error'
  content?: string
  node?: string
  status?: ConversationStatus
  ticket_id?: string
}
