from typing import Annotated
from typing_extensions import TypedDict
from datetime import datetime
import uuid

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
from tool_box import TripIdtoTripODTool, FindNextAvailTripTool

# ==================================== Configuration ====================================
load_dotenv()

tools = [TripIdtoTripODTool(), FindNextAvailTripTool()]

config = {
    "configurable": {
        "passenger_id": "jason_jiahao",
        "thread_id": uuid.uuid4(),
    }
}

# ==================================== Error Handler ====================================
def handle_tool_error(state) -> dict:
    error = state.get("error")
    tool_calls = state["messages"][-1].tool_calls
    return {
        "messages": [
            ToolMessage(
                content=f"Tool Error: {repr(error)}\nPlease revise your input.",
                tool_call_id=tc["id"],
            )
            for tc in tool_calls
        ]
    }

def create_tool_node_with_fallback(tools: list) -> Runnable:
    return ToolNode(tools).with_fallbacks(
        [RunnableLambda(handle_tool_error)], exception_key="error"
    )

# ==================================== Debug Printer ====================================
def print_event(event: dict, _printed: set, max_length=1500):
    current_state = event.get("dialog_state")
    if current_state:
        print("Currently in:", current_state[-1])
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

# ==================================== State Definition ====================================
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]

# ==================================== Assistant Node ====================================
class Assistant:
    def __init__(self, runnable: Runnable):
        self.runnable = runnable

    def __call__(self, state: State, config: RunnableConfig):
        while True:
            result = self.runnable.invoke(state)
            if not result.tool_calls and (
                not result.content
                or isinstance(result.content, list) and not result.content[0].get("text")
            ):
                messages = state["messages"] + [("user", "Respond with a real output.")]
                state = {**state, "messages": messages}
            else:
                break
        return {"messages": result}

# ==================================== Prompt ====================================
tweet_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are a tweet writer for GO Transit. Write short, engaging tweets (280 characters or fewer) based on "
        "system updates. Only use the available tools to retrieve facts. Do not fabricate.\n\n"
        "Tweet types allowed:\n"
        "1. Service Alert: '<origin> <time> - <destination> <time> #Gotrain <status> [#tag]'\n"
        "2. Station Event: '<station> <event> #Gotrain #event'\n"
        "3. Greetings: 'Stay safe! #Gotrain #weather'\n\n"
        "Instructions:\n"
        "- Replace trip IDs with OD pair: 'Origin time - Destination time'\n"
        "- Suggest next trip if current one is cancelled/delayed\n"
        "- Choose one tweet type only.\n"
        "- Don't return the entire reasoning trace, just the tweet as final answer.\n"
        "- Be informative and friendly.",
    ),
    ("placeholder", "{messages}")
])

llm = init_chat_model("openai:gpt-4o")

twitter_writer_runnable = tweet_prompt | llm.bind_tools(tools)

# ==================================== Graph Assembly ====================================
builder = StateGraph(State)

builder.add_node("assistant", Assistant(twitter_writer_runnable))
builder.add_node("tools", create_tool_node_with_fallback(tools))

builder.set_entry_point("assistant")
builder.add_conditional_edges("assistant", tools_condition)
builder.add_edge("tools", "assistant")
builder.add_edge("assistant", END)

# ==================================== Final Graph ====================================
memory = MemorySaver()
checkpointer = InMemorySaver()

twitter_writer_graph = builder.compile(checkpointer=checkpointer)
