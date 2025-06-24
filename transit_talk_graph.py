from typing import Annotated
from typing_extensions import TypedDict
from datetime import datetime
import os

from dotenv import load_dotenv

# LangChain core
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnableConfig

# LangGraph core
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages, AnyMessage
from langgraph.checkpoint.memory import MemorySaver, InMemorySaver
from langgraph.prebuilt import ToolNode, tools_condition

# Tools (custom)
from tools import (
    get_route,
    get_weather,
    get_current_time,
    get_go_transit_policy_docs,
    get_all_go_transit_alert,
    get_go_transit_trip_updates,
)

import uuid

config = {
    "configurable": {
        "passenger_id": "jason_jiahao",
        "thread_id": uuid.uuid4(),
    }
}

def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Error: {repr(error)}\n please fix your mistakes.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }


def create_tool_node_with_fallback(tools: list) -> dict:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )

def print_event(event: dict, _printed: set, max_length=1500):
    current_state = event.get("dialog_state")
    if current_state:
        print("Currently in: ", current_state[-1])
    message = event.get("messages")
    if message:
        if isinstance(message, list):
            message = message[-1]
        if message.id not in _printed:
            msg_repr = message.pretty_repr(html=True)
            if len(msg_repr) > max_length:
                msg_repr = msg_repr[:max_length] + " ... (truncated)"
            print(msg_repr)
            _printed.add(message.id)


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

# ==================================== Assistant ====================================
class Assistant:
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def __call__(self, state: State, config: RunnableConfig):
        while True:
            result = self.runnable.invoke(state)
            # If the LLM happens to return an empty response, we will re-prompt it
            # for an actual response.
            if not result.tool_calls and (
                not result.content
                or isinstance(result.content, list)
                and not result.content[0].get("text")
            ):
                messages = state["messages"] + [("user", "Respond with a real output.")]
                state = {**state, "messages": messages}
            else:
                break
        return {"messages": result}



# ==================================== Graph ====================================

llm = init_chat_model("openai:gpt-4o-mini")

assistant_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful customer service assistant for public transit travel. Use the provided tools to search the trip information based on the given origin and destination. If the user asks about the weather, use the weather tool to get the weather information. If the user asks about the current time, use the current time tool to get the current time. If the user asks about the go-transit policy related questions, use the policy tool to get the policy information. When searching, be persistent. Expand your query bounds if the first search returns no results. "
            " If a search comes up empty, expand your search before giving up."
            "\nCurrent time: {time}.",
        ),
        ("placeholder", "{messages}"),
    ]
).partial(time=datetime.now)

tools = [get_route, get_weather, get_current_time, get_go_transit_policy_docs]

trip_advisor_runnable = assistant_prompt | llm.bind_tools(tools) 

builder = StateGraph(State)

builder.add_node("assistant", Assistant(trip_advisor_runnable))
builder.add_node("tools", create_tool_node_with_fallback(tools))

builder.add_edge(START, "assistant")
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "assistant")
builder.add_edge("assistant", END)


memory = MemorySaver()
checkpointer = InMemorySaver() 
transit_talk_graph = builder.compile(checkpointer=checkpointer,)


