import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.telemetry import get_logger

log = get_logger("supervisor")


class RouteToProducts(BaseModel):
    """Route the conversation to the Products agent for product lookups, category browsing, inventory checks, and product search."""
    query: str = Field(description="The user's product-related question")


class RouteToShipping(BaseModel):
    """Route to the Shipping agent for shipping cost estimates, shipper history, delivery timeframes, and per-country shipping info."""
    query: str = Field(description="The user's shipping-related question")


class RouteToQuote(BaseModel):
    """Route to the Quote agent for building price quotes, checking stock availability, and computing totals."""
    query: str = Field(description="The user's quote-related question")


class RouteToPricing(BaseModel):
    """Route to the Pricing agent for price history, price comparisons, pricing changes, promotional discounts, and overpricing concerns."""
    query: str = Field(description="The user's pricing-related question")


class RouteToCustomerService(BaseModel):
    """Route to the Customer Service Escalation agent for complaints, return requests, order issues, damaged goods, billing disputes, and any issue that needs human intervention or policy lookup."""
    query: str = Field(description="The user's issue or complaint")


class RouteToImages(BaseModel):
    """Route to the Images agent for product image lookups, image uploads, associating images with products, and listing product photos."""
    query: str = Field(description="The user's image-related request")


ROUTE_TOOLS = [
    RouteToProducts,
    RouteToShipping,
    RouteToQuote,
    RouteToPricing,
    RouteToCustomerService,
    RouteToImages,
]

AGENT_MAP = {
    "RouteToProducts": "products",
    "RouteToShipping": "shipping",
    "RouteToQuote": "quote",
    "RouteToPricing": "pricing",
    "RouteToCustomerService": "customer_service",
    "RouteToImages": "images",
}

SYSTEM_PROMPT = """You are the supervisor for an ecommerce assistant. Your team has six agents:

1. Products Agent — Handles product searches, category listings, inventory details, and product information. Use this for "show me products", "what categories", "tell me about product X".

2. Shipping Agent — Handles shipping cost estimates, shipper information, shipping history, and per-country shipping details. Use this for "how much to ship", "shipping to country X", "who ships product Y".

3. Quote Agent — Handles building price quotes, checking stock, computing totals, and multi-item quotes. Use this for "get me a quote", "I want to buy X items", "quote for products A and B".

4. Pricing Agent — Handles price history, price comparisons, pricing changes, promotional discounts, and overpricing concerns. Use this for "what was the price last month", "this seems expensive", "are there any discounts", "price change for product X".

5. Customer Service Agent — Handles complaints, return/refund requests, order issues, damaged goods, billing disputes, and any situation that requires escalation to a human team member. Use this for "I want to return", "my order is damaged", "I was overcharged", "speak to a representative".

6. Images Agent — Handles product image lookups, image uploads, associating images with products, and listing product photos. Use this for "show me the product", "what does it look like", "upload an image for product X", "do you have a photo of this?".

If the user's request is a simple greeting or follow-up that doesn't need a specialist, respond directly. For follow-ups like "how about shipping" or "what else do you have", use conversation context to route correctly.

When a complaint or issue is detected, route to Customer Service first. The Customer Service agent can then involve other agents if needed to gather information.

Current conversation context: {context}
Conversation history:
{messages}"""


def _build_llm():
    return ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )


def supervisor_node(state):
    messages = state["messages"]
    context = state["session_context"]

    llm = _build_llm()
    llm_with_tools = llm.bind_tools(ROUTE_TOOLS)

    history_str = "\n".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}"
        for m in messages[-10:]
    )
    context_str = json.dumps({k: v for k, v in context.items() if v is not None}, indent=2)

    prompt = SYSTEM_PROMPT.format(context=context_str, messages=history_str)
    result = llm_with_tools.invoke([SystemMessage(content=prompt)] + messages[-5:])

    if result.tool_calls:
        tool_call = result.tool_calls[0]
        agent_name = AGENT_MAP.get(tool_call["name"])
        if agent_name:
            log.info("routing", agent=agent_name, query=tool_call["args"].get("query", ""))
            return {
                "next_agent": agent_name,
                "messages": [result],
                "tool_results": {"query": tool_call["args"].get("query", "")},
            }

    return {
        "next_agent": None,
        "messages": [result],
    }
