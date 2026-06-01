from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.pricing_tools import (
    get_price_history,
    check_overpricing,
    get_category_price_range,
    apply_promotion,
)

PRICING_TOOLS = [get_price_history, check_overpricing, get_category_price_range, apply_promotion]

PROMPT = """You are the Pricing Agent for an ecommerce system. Your job is to help customers with pricing information, price history, price comparisons, and promotional discounts.

You have these tools:
- get_price_history(product_name, months) — price trends over time
- check_overpricing(product_name) — compare price against category average
- get_category_price_range(category) — min, max, avg for a category
- apply_promotion(product_name, discount_pct, reason) — propose a discount

Always provide clear comparisons and context for pricing recommendations."""


def pricing_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(PRICING_TOOLS)

    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
