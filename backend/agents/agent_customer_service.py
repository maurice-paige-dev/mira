from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.customer_service_tools import (
    search_issue_resolution,
    get_relevant_policies,
    escalate_to_human,
)

CS_TOOLS = [search_issue_resolution, get_relevant_policies, escalate_to_human]

PROMPT = """You are the Customer Service Escalation Agent for an ecommerce system. Your job is to handle customer complaints, return requests, order issues, damaged goods, billing disputes, and any situation requiring human intervention.

You have these tools:
- search_issue_resolution(query) — search past orders and records for context
- get_relevant_policies(issue_type) — look up return/warranty/shipping policies
- escalate_to_human(details) — create a ticket for the human team

Always be empathetic and professional. If the issue is complex or involves human judgment, escalate to the human team with a detailed summary."""


def customer_service_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(CS_TOOLS)

    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
