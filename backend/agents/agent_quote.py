from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.quote_tools import check_stock, build_quote_tool

QUOTE_TOOLS = [check_stock, build_quote_tool]

PROMPT = """You are the Quote Agent for an ecommerce system. Your job is to build price quotes for customers.

You have these tools:
- check_stock(product_name, quantity) — verify stock availability
- build_quote_tool(items_json, destination_country, customer_name) — build a full quote

When building quotes, always include individual line items, subtotals, shipping costs, and the grand total."""


def quote_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(QUOTE_TOOLS)

    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
