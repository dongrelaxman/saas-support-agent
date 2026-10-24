import sys
import os
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.llm_workflow import workflow, checkpointer, save_conversation, get_all_conversations
import streamlit as st
from langchain_core.messages import HumanMessage


def load_thread_history(thread_id):
    config = {"configurable": {"thread_id": thread_id}}
    state = checkpointer.get(config)
    if state is None:
        return []
    return [
        {'role': msg.type, 'content': msg.content}
        for msg in state.channel_values.get("messages", [])
    ]


# ── session state init ────────────────────────────────────────────────────────
if 'thread_id' not in st.session_state:
    st.session_state['thread_id'] = str(uuid.uuid4())

if 'message_history' not in st.session_state:
    st.session_state['message_history'] = []

if 'conversations' not in st.session_state:
    st.session_state['conversations'] = get_all_conversations()


# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("Langgraph Chatbot")

    if st.button("+ New Chat", use_container_width=True):
        st.session_state['thread_id'] = str(uuid.uuid4())
        st.session_state['message_history'] = []
        st.rerun()

    st.divider()
    st.subheader("Previous Conversations")

    for convo in reversed(st.session_state['conversations']):
        is_active = convo['thread_id'] == st.session_state['thread_id']
        label = f"{'▶ ' if is_active else ''}{convo['title']}"
        if st.button(label, key=convo['thread_id'], use_container_width=True):
            st.session_state['thread_id'] = convo['thread_id']
            st.session_state['message_history'] = load_thread_history(convo['thread_id'])
            st.rerun()


# ── chat UI ───────────────────────────────────────────────────────────────────
for message in st.session_state['message_history']:
    with st.chat_message(message['role']):
        st.text(message['content'])

user_input = st.chat_input("Type here")

if user_input:
    # register new thread on first message — save to DB so it survives refresh
    thread_ids = [c['thread_id'] for c in st.session_state['conversations']]
    if st.session_state['thread_id'] not in thread_ids:
        title = user_input[:40]
        save_conversation(st.session_state['thread_id'], title)
        st.session_state['conversations'] = get_all_conversations()

    st.session_state['message_history'].append({'role': 'human', 'content': user_input})
    with st.chat_message('human'):
        st.text(user_input)

    config = {'configurable': {'thread_id': st.session_state['thread_id']}}
    initial_state = {'messages': [HumanMessage(content=user_input)]}

    with st.chat_message('assistant'):
        ai_message = st.write_stream(
            message_chunk.content
            for message_chunk, _ in workflow.stream(
                initial_state,
                config=config,
                stream_mode='messages'
            )
        )

    st.session_state['message_history'].append({'role': 'assistant', 'content': ai_message})
