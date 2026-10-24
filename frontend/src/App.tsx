import { useState } from 'react'
import ChatPage from './pages/ChatPage'
import ConsolePage from './pages/ConsolePage'

type Tab = 'chat' | 'console'

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')

  return (
    <div className="h-screen flex flex-col bg-gray-950">
      {/* Top nav */}
      <header className="flex-shrink-0 bg-gray-900 border-b border-gray-800 flex items-center px-6 h-14">
        <div className="flex items-center gap-3 mr-8">
          <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <span className="text-sm font-semibold text-gray-100">TaskPilot Support</span>
        </div>

        <nav className="flex gap-1">
          <button
            onClick={() => setTab('chat')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === 'chat'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
            }`}
          >
            Chat
          </button>
          <button
            onClick={() => setTab('console')}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
              tab === 'console'
                ? 'bg-gray-700 text-white'
                : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
            }`}
          >
            Agent Console
          </button>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-400" />
          <span className="text-xs text-gray-500">GPT-4o mini · Weaviate · Postgres</span>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 min-h-0">
        {tab === 'chat'    && <ChatPage />}
        {tab === 'console' && <ConsolePage />}
      </main>
    </div>
  )
}
