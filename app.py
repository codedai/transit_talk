import os
import uuid
import json
import ast
import asyncio

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

from langgraph_sdk import get_sync_client
from langgraph.checkpoint.memory import InMemorySaver

from transit_talk_graph import transit_talk_graph as client

# =========================== Setup ===========================
load_dotenv()
checkpointer = InMemorySaver()

config = {
    "configurable": {
        "passenger_id": "jason_jiahao",
        "thread_id": '12345',
    }
}

# ======================== UI Helpers =========================
def show_route_options(raw_content: str) -> None:
    """
    Parse get_route output (string) and display each option
    in a two-column layout: left = itinerary text, right = folium map.
    """
    try:
        parsed = json.loads(raw_content)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(raw_content)

    if (not isinstance(parsed, list) or len(parsed) != 2
            or not all(isinstance(x, list) for x in parsed)):
        st.error("⚠️ Unexpected tool response format.")
        return

    descriptions, map_paths = parsed
    with st.expander("🔍 Route options", expanded=True):
        tabs = st.tabs([f"Option {i}" for i in range(len(descriptions))])
        for idx, (text, html_path, tab) in enumerate(zip(descriptions, map_paths, tabs), start=1):
            with tab:
                st.markdown(f"### Option {idx}")
                col_text, col_map = st.columns([1, 1])

                with col_text:
                    st.markdown(f"```text\n{text}\n```")

                with col_map:
                    if os.path.exists(html_path):
                        html = open(html_path, "r", encoding="utf-8").read()
                        components.html(html, height=450, scrolling=False)
                    else:
                        st.warning(f"Map file not found: {html_path}")

def add_event_to_session_state(event):
    """Update Streamlit session state from LangGraph tool or assistant message."""
    message = event.get("messages")
    if not message:
        return

    if isinstance(message, list):
        message = message[-1]

    if message.type == "tool" and message.tool_call_id and message.name == "get_route":
        show_route_options(message.content)
    elif message.type == "tool":
        pass
    else:
        if message.content:
            st.session_state.messages.append({
                "role": message.type,
                "content": message.content
            })
            st.chat_message(message.type).write(message.content)

# ======================== App UI ============================
st.title("💬 Transit Talk")
st.caption("🚀 Let Me Help You Plan Your Trip!")

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

if "route_info" not in st.session_state:
    st.session_state["route_info"] = [[], []]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# ========================= Run Client ==========================
if prompt := st.chat_input():
    for event in client.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config,
        stream_mode='values',
    ):
        add_event_to_session_state(event)

# ==================== LangGraph Platform Support ====================
# Uncomment below and comment out the local client block if using LangGraph Platform

# client = get_sync_client(url=os.getenv("LANGGRAPH_API_URL"))
# if prompt := st.chat_input():
#     for event in client.runs.stream(
#         None,
#         "agent",
#         input={"messages": [{"role": "user", "content": prompt}]},
#         config=config,
#         stream_mode='values',
#     ):
#         add_event_to_session_state(event)
