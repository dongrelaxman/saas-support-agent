import type { Message } from '../types'

interface Props {
  message: Message
  streaming?: boolean
}

export default function MessageBubble({ message, streaming = false }: Props) {
  const isHuman = message.role === 'human'
  const isSystem = message.role === 'system'

  if (isSystem) {
    return (
      <div className="flex justify-center my-2">
        <div className="max-w-xl rounded-lg bg-gray-800/60 border border-gray-700 px-4 py-2 text-xs text-gray-400 italic">
          {message.content}
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${isHuman ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isHuman && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center mr-3 mt-1 text-xs font-semibold">
          AI
        </div>
      )}
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
          isHuman
            ? 'bg-indigo-600 text-white rounded-br-sm'
            : 'bg-gray-800 text-gray-100 rounded-bl-sm'
        } ${streaming ? 'cursor-blink' : ''}`}
      >
        {message.content}
      </div>
      {isHuman && (
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-600 flex items-center justify-center ml-3 mt-1 text-xs font-semibold">
          U
        </div>
      )}
    </div>
  )
}
