from langchain_core.prompts import ChatPromptTemplate

ANSWER_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a customer support agent for TaskPilot.\n"
        "Answer ONLY using the context provided below. "
        "Do not add any facts that are not present in the documents.\n"
        "Cite every fact with its source file inline, like [Source: filename.md].\n\n"
        "Context:\n{context}",
    ),
    ("human", "{question}"),
])

HEDGED_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a customer support agent for TaskPilot.\n"
        "The retrieved information may not fully cover this question.\n"
        "Give your best answer using ONLY the context below, but clearly state "
        "that you are not fully confident.\n"
        "If the context does not help, say so honestly and suggest the user "
        "contacts support directly.\n"
        "Cite any sources you do use with [Source: filename.md].\n\n"
        "Context:\n{context}",
    ),
    ("human", "{question}"),
])
