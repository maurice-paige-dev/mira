import uuid
import time
import threading
from typing import TypedDict, Annotated, Sequence

from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

from backend.config import SESSION_TTL_MINUTES


class SessionContext(TypedDict):
    session_id: str
    customer_name: str | None
    active_quote: dict | None
    prefer_category: str | None
    escalation_ticket: dict | None
    pricing_override: dict | None
    last_viewed_product: str | None
    created_at: str
    last_active: str


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_context: SessionContext
    next_agent: str | None
    tool_results: dict
    error: str | None


class SessionStore:
    def __init__(self):
        self._sessions: dict[str, AgentState] = {}
        self._events: dict[str, list[dict]] = {}
        self._lock = threading.Lock()
        self._start_cleanup()

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex[:12]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            self._sessions[session_id] = AgentState(
                messages=[],
                session_context=SessionContext(
                    session_id=session_id,
                    customer_name=None,
                    active_quote=None,
                    prefer_category=None,
                    escalation_ticket=None,
                    pricing_override=None,
                    last_viewed_product=None,
                    created_at=now,
                    last_active=now,
                ),
                next_agent=None,
                tool_results={},
                error=None,
            )
            self._events[session_id] = []
        return session_id

    def get_state(self, session_id: str) -> AgentState | None:
        with self._lock:
            state = self._sessions.get(session_id)
            if state is not None:
                state["session_context"]["last_active"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
            return state

    def update_state(self, session_id: str, state: AgentState):
        with self._lock:
            self._sessions[session_id] = state

    def append_event(self, session_id: str, event: dict):
        with self._lock:
            if session_id in self._events:
                self._events[session_id].append(event)

    def get_events_since(self, session_id: str, since_index: int) -> list[dict]:
        with self._lock:
            events = self._events.get(session_id, [])
            return events[since_index:]

    def _start_cleanup(self):
        def _cleanup():
            while True:
                time.sleep(300)
                now = time.time()
                ttl = SESSION_TTL_MINUTES * 60
                with self._lock:
                    stale = [
                        sid for sid, state in self._sessions.items()
                        if now - time.mktime(
                            time.strptime(state["session_context"]["last_active"], "%Y-%m-%dT%H:%M:%SZ")
                        ) > ttl
                    ]
                    for sid in stale:
                        del self._sessions[sid]
                        self._events.pop(sid, None)

        thread = threading.Thread(target=_cleanup, daemon=True)
        thread.start()


_store = SessionStore()


def get_store() -> SessionStore:
    return _store
