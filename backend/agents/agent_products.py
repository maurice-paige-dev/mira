from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.product_tools import search_products, get_categories_tool, get_product_by_name_tool
from backend.agents.tools.chroma_utils import query_chromadb

PRODUCT_TOOLS = [search_products, get_categories_tool, get_product_by_name_tool]

PROMPT = """You are the Products Agent for an ecommerce system. Your job is to help customers find and learn about products.

You have these tools:
- search_products(search, category, in_stock_only) — search/filter products
- get_categories_tool() — list categories with stats
- get_product_by_name_tool(product_name) — get detailed info about a product

Use the tools to answer the user's question, then summarize the results in a friendly, helpful way."""


def products_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(PRODUCT_TOOLS)

    user_query = query or last_msg
    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
