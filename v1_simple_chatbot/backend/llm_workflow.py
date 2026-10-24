import os 
from langgraph.graph import StateGraph,START,END
from typing import TypedDict, Annotated,Literal,List
from pydantic import BaseModel,Field
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage,HumanMessage
from langgraph.graph.message import add_messages
from dotenv import load_dotenv

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini")

class ChatState(TypedDict):
    messages : Annotated[List[BaseMessage],add_messages]
    
def chat_node(state:ChatState):
    messages = state['messages']
    response = llm.invoke(messages)
    return {'messages':[response]}
    
    
graph = StateGraph(ChatState)

graph.add_node("chat_node",chat_node)
graph.add_edge(START,"chat_node")
graph.add_edge("chat_node",END)

# checkpoint = InMemorySaver()
DB_URI = "postgresql://postgres:postgres@localhost:5433/agentdb"

conn = Connection.connect(DB_URI, autocommit=True)
checkpointer = PostgresSaver(conn)
checkpointer.setup()

conn.execute("""
    CREATE TABLE IF NOT EXISTS conversation_titles (
        thread_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
""")

def save_conversation(thread_id: str, title: str):
    conn.execute(
        "INSERT INTO conversation_titles (thread_id, title) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (thread_id, title)
    )

def get_all_conversations():
    rows = conn.execute(
        "SELECT thread_id, title FROM conversation_titles ORDER BY created_at DESC"
    ).fetchall()
    return [{'thread_id': r[0], 'title': r[1]} for r in rows]

workflow = graph.compile(checkpointer=checkpointer)
# print(graph.compile()) the graph is visible in ipynb files 

if __name__ == "__main__":
    config = {'configurable':{'thread_id':'user_2'}}
    
    intial_state = {
        "messages" : [
            HumanMessage(content="what is the capital of india")
        ]
    }
    
    response = workflow.invoke(intial_state,config=config)
    
    print(response['messages'][-1].content)
    



