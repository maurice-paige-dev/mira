from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from backend.session_store import AgentState
from backend.agents.agent_supervisor import supervisor_node
from backend.agents.agent_products import products_agent_node
from backend.agents.agent_shipping import shipping_agent_node
from backend.agents.agent_quote import quote_agent_node
from backend.agents.agent_pricing import pricing_agent_node
from backend.agents.agent_customer_service import customer_service_agent_node
from backend.agents.agent_images import images_agent_node


def _router(state):
    next_agent = state.get("next_agent")
    if next_agent is None or next_agent == "supervisor":
        return "supervisor"
    return next_agent


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("products", products_agent_node)
    builder.add_node("shipping", shipping_agent_node)
    builder.add_node("quote", quote_agent_node)
    builder.add_node("pricing", pricing_agent_node)
    builder.add_node("customer_service", customer_service_agent_node)
    builder.add_node("images", images_agent_node)

    builder.add_edge(START, "supervisor")

    builder.add_conditional_edges(
        "supervisor",
        _router,
        {
            "supervisor": END,
            "products": "products",
            "shipping": "shipping",
            "quote": "quote",
            "pricing": "pricing",
            "customer_service": "customer_service",
            "images": "images",
        },
    )

    for agent in ["products", "shipping", "quote", "pricing", "customer_service", "images"]:
        builder.add_edge(agent, "supervisor")

    checkpointer = MemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    return graph
