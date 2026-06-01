from langchain_core.tools import tool

from backend.agents.tools.chroma_utils import query_chromadb
from backend.telemetry import get_logger

log = get_logger("customer_service_tools")


@tool
def search_issue_resolution(query: str) -> str:
    """Search past orders, invoices, and shipping records for context about a customer issue."""
    try:
        results = query_chromadb(query, n_results=5)
        if not results:
            return "No relevant records found for this issue."
        lines = [f"Found {len(results)} relevant record(s):"]
        for r in results:
            meta = r.get("metadata", {})
            text = r.get("text", "")[:200]
            lines.append(f"- {meta.get('source', 'unknown')}: {text}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error searching records: {e}"


@tool
def get_relevant_policies(issue_type: str) -> str:
    """Look up company policies relevant to a customer issue type (return, refund, warranty, shipping damage)."""
    try:
        results = query_chromadb(f"{issue_type} policy", n_results=3)
        if not results:
            return f"No policy documents found for '{issue_type}'. Please escalate to a human agent."
        lines = [f"Policies related to '{issue_type}':"]
        for r in results:
            text = r.get("text", "")[:300]
            lines.append(f"- {text}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error looking up policies: {e}"


@tool
def escalate_to_human(details: str) -> str:
    """Escalate a customer issue to a human team member. Provide full context of the issue."""
    import uuid
    ticket_id = uuid.uuid4().hex[:8].upper()
    log.info("escalation_created", ticket_id=ticket_id, details=details)
    return (
        f"✅ Escalation ticket created.\n"
        f"Ticket ID: {ticket_id}\n"
        f"Details: {details}\n"
        f"Status: A human agent will review this within 24 hours.\n"
        f"You will be notified when there is an update."
    )
