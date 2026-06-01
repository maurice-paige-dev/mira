from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.shipping_tools import estimate_shipping, get_shipping_history
from backend.agents.tools.chroma_utils import query_chromadb

SHIPPING_TOOLS = [estimate_shipping, get_shipping_history]

PROMPT = """You are the Shipping Agent for an ecommerce system. Your job is to help customers with shipping cost estimates, shipper information, and shipping history.

You have these tools:
- estimate_shipping(product_name, quantity, destination_country) — compute shipping cost
- get_shipping_history(product_name) — past shipping records

Always provide clear cost breakdowns and mention the shipper name."""


def shipping_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(SHIPPING_TOOLS)

    user_query = query or last_msg
    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
