# Agentic Conversational Workflow — LangGraph Multi-Agent Chat

## 1. Motivation

The current `/chat` endpoint (`backend/api_rag.py`) is a stateless RAG lookup:

```
POST /chat  {query}  →  embed → ChromaDB search → format string → response
```

It has no concept of conversation, cannot chain multiple questions, cannot
execute actions (quoting, checking stock, estimating shipping), and produces a
fixed template answer with no LLM reasoning. Every query is independent.

A true agentic conversational workflow solves these problems:

| Limitation | Solution |
|---|---|
| **Stateless** — each query is independent | LangGraph maintains conversation state across turns: message history, session context, active quote draft |
| **No tool execution** — can only search ChromaDB | 6 specialized agents (Products, Shipping, Quote, Pricing, Customer Service, Images) each have tools to query PostgreSQL, search ChromaDB, compute shipping, build quotes, handle pricing changes, manage issue escalation, and serve product images |
| **No LLM reasoning** — template-based answer | Local LLM (Ollama/llama3) interprets the query, decides which agent to invoke, and generates natural-language responses from tool results |
| **Flat results** — no structured data flow | LangGraph state graph routes: user → supervisor → specialist agent → tool → response → user |
| **No session management** | Server-side session store with session IDs; frontend sends session_id to maintain context across page refreshes |
| **No streaming** — user waits for full response | SSE streaming emits agent steps (thinking, tool calls, results) and final answer as they happen |

---

## 2. Proposed Approach

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        USER (React Chatbot)                      │
│  POST /chat  {query, session_id}                                 │
│  GET  /chat/stream/{session_id}  (SSE)                          │
└────────────────────────┬─────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────┐
│                       FastAPI — api_rag.py (upgraded)                   │
│                                                                   │
│  POST /chat: creates session, enqueues message, returns session_id│
│  GET  /chat/stream/{session_id}: SSE stream of agent events       │
│  GET  /chat/history/{session_id}: past conversation               │
│  POST /api/images/upload: upload product image (returns CDN URL)  │
│                                                                   │
│  LangGraph runs in a background thread per session                │
└────────────────────────┬─────────────────────────────────────────┘
                         │ LangGraph graph
┌────────────────────────▼─────────────────────────────────────────┐
│                    LANGGRAPH SUPERVISOR                            │
│  (Llama 3 via Ollama, tool-calling prompt)                       │
│                                                                   │
│  Receives: {messages: [...], session_context: {}}                │
│  Decides: which agent to call or responds directly               │
│  State: append-only message list + shared session dict            │
└───┬──────────────┬──────────────┬──────────────┬──────────────────┬─────────────────────┐
    │              │              │              │                  │                     │
    ▼              ▼              ▼              ▼                  ▼                     ▼
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐ ┌──────────────┐
│ Products │ │ Shipping │ │  Quote   │ │ Pricing  │ │ Customer Service │ │   Images     │
│  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │ │  Escalation Agent│ │   Agent      │
│          │ │          │ │          │ │          │ │                  │ │              │
│ tools:   │ │ tools:   │ │ tools:   │ │ tools:   │ │ tools:           │ │ tools:       │
│ • search │ │ • estim- │ │ • build  │ │ • get    │ │ • search_issue   │ │ • get_image  │
│   product│ │   ate    │ │   quote  │ │   price  │ │ • get_relevant_  │ │   _url      │
│ • list   │ │   ship-  │ │ • check  │ │   hist-  │ │   policies       │ │ • upload    │
│   categ- │ │   ping   │ │   stock  │ │   ory    │ │ • escalate_to_   │ │   _image    │
│   ories  │ │ • ship-  │ │ • quote  │ │ • check  │ │   human          │ │ • list_prod │
│ • get by │ │   ping   │ │   hist-  │ │   over-  │ │ • search_chromadb│ │   _images   │
│   name   │ │   hist-  │ │   ory    │ │   price  │ │                  │ │ • delete_   │
│          │ │   ory    │ │          │ │ • apply_  │ │                  │ │   image     │
│          │ │          │ │          │ │   promo  │ │                  │ │             │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘ └──────┬───────┘
     │            │            │            │                │                  │
     └────────────┼────────────┼────────────┼────────────────┼──────────────────┘
                  │            │            │                │
┌─────────────────▼────────────▼────────────▼────────────────▼─────────────────────────┐
│                              TOOL LAYER                                              │
│                                                                                      │
│  PostgreSQL (via repository.py)                                                      │
│  ChromaDB (via vector_store.query_shipping)                                         │
│  Catalog API logic (quoting, shipping estimation)                                   │
│  Image CDN (S3 + CloudFront)                                                         │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed design

#### 2.1 LangGraph state

```python
from typing import TypedDict, Annotated, Sequence
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class SessionContext(TypedDict):
    session_id: str
    customer_name: str | None
    active_quote: dict | None  # in-progress quote draft
    prefer_category: str | None
    escalation_ticket: dict | None  # open customer service ticket
    pricing_override: dict | None  # active pricing change request
    last_viewed_product: str | None  # most recently viewed product name (for image lookups)
    created_at: str
    last_active: str

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_context: SessionContext
    next_agent: str | None  # supervisor sets this for routing
    tool_results: dict  # temporary storage for tool outputs
    error: str | None
```

`add_messages` reducer appends new messages to the list — this is the core of
LangGraph's conversational memory. `session_context` is a shared dict all agents
can read/write (e.g., updating `active_quote`).

#### 2.2 Graph structure

```
                    ┌──────────────┐
                    │  ENTRY POINT │
                    │ (__start__)  │
                    └──────┬───────┘
                           │
                    ┌──────▼──────────────┐
                    │     SUPERVISOR      │
                    │ (llama3 via Ollama) │
                    │                    │
                    │ "Which agent       │
                    │  handles this?"    │
                    └──┬───┬───┬───┬───┬───┬──────┘
                       │   │   │   │   │   │
         ┌─────────────┘   │   │   │   │   └─────────────┐
         ▼                 ▼   ▼   ▼   ▼                 ▼
  ┌────────────┐   ┌────────────┐   ┌────────────┐ ┌──────────────┐ ┌───────────┐
  │  PRODUCTS  │   │  SHIPPING  │   │   QUOTE    │ │    PRICING   │ │  IMAGES   │
  │   AGENT    │   │   AGENT    │   │   AGENT    │ │    AGENT     │ │   AGENT   │
  │            │   │            │   │            │ │              │ │           │
  │ Tool-call  │   │ Tool-call  │   │ Tool-call  │ │ Tool-call    │ │ Tool-call │
  │ → respond  │   │ → respond  │   │ → respond  │ │ → respond    │ │ → respond │
  └──────┬─────┘   └──────┬─────┘   └──────┬─────┘ └──────┬───────┘ └─────┬─────┘
         │                │                │              │               │
         │     ┌──────────┼────────────────┼──────────────┘               │
         │     │          │                │                              │
         │     │   ┌──────▼────────────┐   │                              │
         │     │   │  CUSTOMER SERVICE │   │                              │
         │     │   │  ESCALATION AGENT │   │                              │
         │     │   │                  │   │                              │
         │     │   │ Tool-call        │   │                              │
         │     │   │ → respond        │   │                              │
         │     │   └──────┬───────────┘   │                              │
         │     │          │               │                              │
         └─────┼──────────┼───────────────┼──────────────────────────────┘
               │          │               │
        ┌──────▼──────────▼───────────────▼──────┐
        │              SUPERVISOR                │  (loop back)
        │     (re-route or respond)              │
        └──────┬─────────────────────────────────┘
               │
        ┌──────▼───────┐
        │ ___end___    │
        └──────────────┘
```

The supervisor runs in a loop:
1. Decide which agent to call or respond directly.
2. If agent → route to agent node, agent executes tools and returns.
3. Re-enter supervisor to decide next action.
4. If direct response → end.

LangGraph's `Command` primitive is used for routing (instead of `go_to`/edges).

#### 2.3 Supervisor agent

The supervisor is a Llama 3 model (via Ollama) with a tool-calling prompt that
defines six routing tools — one per specialist agent:

```python
from pydantic import BaseModel, Field

class RouteToProducts(BaseModel):
    """Route the conversation to the Products agent for product lookups,
    category browsing, inventory checks, and product search."""
    query: str = Field(description="The user's product-related question")

class RouteToShipping(BaseModel):
    """Route to the Shipping agent for shipping cost estimates,
    shipper history, delivery timeframes, and per-country shipping info."""
    query: str = Field(description="The user's shipping-related question")

class RouteToQuote(BaseModel):
    """Route to the Quote agent for building price quotes,
    checking stock availability, and computing totals."""
    query: str = Field(description="The user's quote-related question")

class RouteToPricing(BaseModel):
    """Route to the Pricing agent for price history, price comparisons,
    pricing changes, promotional discounts, and overpricing concerns."""
    query: str = Field(description="The user's pricing-related question")

class RouteToCustomerService(BaseModel):
    """Route to the Customer Service Escalation agent for complaints,
    return requests, order issues, damaged goods, billing disputes,
    and any issue that needs human intervention or policy lookup."""
    query: str = Field(description="The user's issue or complaint")

class RouteToImages(BaseModel):
    """Route to the Images agent for product image lookups, image uploads,
    associating images with products, and listing product photos. Use this
    for "show me the product", "what does it look like", "upload an image",
    "add a photo to product X"."""
    query: str = Field(description="The user's image-related request")
```

The supervisor prompt:

```
You are the supervisor for an ecommerce assistant. Your team has six agents:

1. Products Agent — Handles product searches, category listings, inventory 
   details, and product information. Use this for "show me products", 
   "what categories", "tell me about product X".

2. Shipping Agent — Handles shipping cost estimates, shipper information, 
   shipping history, and per-country shipping details. Use this for 
   "how much to ship", "shipping to country X", "who ships product Y".

3. Quote Agent — Handles building price quotes, checking stock, computing 
   totals, and multi-item quotes. Use this for "get me a quote", 
   "I want to buy X items", "quote for products A and B".

4. Pricing Agent — Handles price history, price comparisons, pricing 
   changes, promotional discounts, and overpricing concerns. Use this for 
   "what was the price last month", "this seems expensive", "are there 
   any discounts", "price change for product X".

5. Customer Service Agent — Handles complaints, return/refund requests, 
   order issues, damaged goods, billing disputes, and any situation that 
   requires escalation to a human team member. Use this for "I want to 
   return", "my order is damaged", "I was overcharged", "speak to a 
   representative".

6. Images Agent — Handles product image lookups, image uploads, 
   associating images with products, and listing product photos. Use this 
   for "show me the product", "what does it look like", "upload an image 
   for product X", "do you have a photo of this?".

If the user's request is a simple greeting or follow-up that doesn't need 
a specialist, respond directly. For follow-ups like "how about shipping" 
or "what else do you have", use conversation context to route correctly.

When a complaint or issue is detected, route to Customer Service first.
The Customer Service agent can then involve other agents if needed to 
gather information (e.g., asking Products about an item, or Quote to 
verify a past order).

Current conversation context: {session_context}
Conversation history:
{messages}
```

#### 2.4 Specialist agents

Each specialist agent is a LangGraph `Node` that receives the full state,
executes tools, and returns a response message.

**Products Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `search_products(search, category, in_stock_only)` | `repository.get_products()` | List products with filters |
| `get_categories()` | `repository.get_categories()` | Aggregated category stats |
| `get_product_by_name(name)` | `repository.get_product_by_name()` | Single product detail |
| `search_chromadb(query)` | `vector_store.query_shipping()` | Semantic search across all docs |

**Shipping Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `estimate_shipping(product_name, quantity, destination_country)` | `api_catalog._estimate_shipping()` | Compute shipping cost estimate |
| `get_shipping_history(product_name)` | `repository.get_shipping_cost()` | Past shipping records for a product |
| `search_chromadb(query)` | `vector_store.query_shipping()` | Semantic search (e.g., "shipping to Canada") |

**Quote Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `build_quote(items, destination_country, customer_name)` | `api_catalog._estimate_shipping()` + `api_catalog.quote` logic | Full quote with line items, shipping, totals |
| `check_stock(product_name, quantity)` | `repository.get_product_by_name()` | Verify stock availability |

**Pricing Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `get_price_history(product_name, months)` | `repository.get_products()` + aggregation | Price trend over time for a product |
| `check_overpricing(product_name)` | Compare `unit_price` vs category `avg_price` from `repository.get_categories()` | Flag if product is priced significantly above category average |
| `apply_promotion(product_name, discount_pct, reason)` | Writes to a `promotions` table or logs the change | Apply a temporary price adjustment (records in session context, not committed to product DB) |
| `get_category_price_range(category)` | `repository.get_categories()` | Min, max, avg price for a category |
| `search_chromadb(query)` | `vector_store.query_shipping()` | Semantic search across invoices, POs (e.g., "previous pricing on hiking boots") |

**Customer Service Escalation Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `search_issue_resolution(query)` | `search_chromadb()` across past order docs, invoices, shipping records | Find relevant history for the customer's issue |
| `get_relevant_policies(issue_type)` | `search_chromadb()` for policy documents | Look up return policy, warranty terms, shipping guarantees |
| `escalate_to_human(details)` | Writes to an `escalations` table or generates a webhook event | Creates a ticket for human customer service team; returns a ticket ID and ETA |
| `search_chromadb(query)` | `vector_store.query_shipping()` | General search across all documents for context |

**Images Agent** — tools:

| Tool | Source | Description |
|---|---|---|
| `get_image_url(product_name, variant)` | S3 presigned URL or `image_cdn_url` from `Product` model | Returns CDN URL for a product's image (thumbnail, full) |
| `upload_image(product_name, file_data, variant)` | Uploads to S3 bucket under `products/{product_name}/`, updates `Product.image_cdn_url` in DB | Accepts base64-encoded image data, stores in CDN, returns URL |
| `list_product_images(product_name)` | S3 list objects under `products/{product_name}/` | Returns all available images for a product |
| `delete_image(product_name, variant)` | S3 delete object | Removes an image from the CDN |

Image CDN architecture:

```
                    ┌──────────────────────────────────────┐
                    │         Image CDN (S3 + CF)          │
                    │                                      │
                    │  S3 Bucket: ecommerce-images-{env}   │
                    │  Prefix: products/{product_name}/    │
                    │    ├── thumbnail.jpg                 │
                    │    ├── full.jpg                      │
                    │    └── additional_views/             │
                    │                                      │
                    │  CloudFront distribution:            │
                    │  https://images.ecommerce.com/       │
                    └──────────────────────────────────────┘
                              ▲
                    upload ───┘└─── CDN URL
                              │
                    ┌─────────┴──────────┐
                    │  API + Agent Layer │
                    │  POST /api/images/ │
                    │  upload             │
                    └────────────────────┘
```

The `Product` model in `backend/db/models.py` gets a new field:

```python
class Product(Base):
    # ...existing fields...
    image_cdn_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Stores the primary CloudFront URL, e.g.
    # "https://images.ecommerce.com/products/hiking-boot/full.jpg"
```

Upload endpoint: `POST /api/images/upload` (added to the catalog API):

```json
// Request (multipart/form-data)
{
  "product_name": "Ultra-light Hiking Boot",
  "variant": "full",
  "file": <binary image>
}

// Response
{
  "product_name": "Ultra-light Hiking Boot",
  "variant": "full",
  "cdn_url": "https://images.ecommerce.com/products/ultra-light-hiking-boot/full.jpg",
  "size_bytes": 245760,
  "content_type": "image/jpeg"
}
```

The Images agent uses these tools in conversation:
- `"show me that hiking boot"` → agent calls `get_image_url("Ultra-light Hiking Boot")` → returns a markdown image link the frontend renders
- `"upload a photo for hiking boots"` → agent calls `upload_image(...)` → stores in S3 → confirms
- `"what images do you have for this product"` → agent calls `list_product_images(...)` → lists all variants

The CDN URLs returned by the agent are sent as SSE events and rendered by
the frontend as inline images in the chat.

The Customer Service agent can also request information from other agents by
adding a tool call to its LLM response — the supervisor handles re-routing.
For example: if a customer complains about a damaged product, the Customer
Service agent can use `search_issue_resolution` to find the order, then
request the Quote agent to verify pricing, and finally escalate.

Each tool is wrapped as a `@tool` decorated function that the agent's LLM can
call via tool-calling. The Llama 3 model must support tool/function calling
(e.g., `llama3.1` or `llama3.2` via Ollama).

#### 2.5 Session management

Sessions are stored in-memory (for now) with a `SessionStore` class:

```python
import uuid
import time
from typing import Dict

class SessionStore:
    def __init__(self):
        self._sessions: dict[str, AgentState] = {}
        self._events: dict[str, list[dict]] = {}  # SSE event buffers

    def create_session(self) -> str:
        session_id = uuid.uuid4().hex[:12]
        self._sessions[session_id] = AgentState(
            messages=[],
            session_context=SessionContext(
                session_id=session_id,
                customer_name=None,
                active_quote=None,
                prefer_category=None,
                created_at=time.isoformat(),
                last_active=time.isoformat(),
            ),
            next_agent=None,
            tool_results={},
            error=None,
        )
        self._events[session_id] = []
        return session_id

    def get_state(self, session_id: str) -> AgentState | None:
        return self._sessions.get(session_id)

    def append_event(self, session_id: str, event: dict):
        self._events[session_id].append(event)

    def get_events_since(self, session_id: str, since_index: int) -> list[dict]:
        return self._events[session_id][since_index:]
```

Session TTL: sessions expire after 30 minutes of inactivity. A background
cleanup coroutine runs every 5 minutes.

#### 2.6 Streaming (SSE)

The agent emits structured events to an event buffer as it runs:

```
event: agent_start
data: {"agent": "supervisor", "input": "How much does it cost to ship hiking boots to Canada?"}

event: tool_call
data: {"agent": "shipping", "tool": "estimate_shipping", "args": {"product_name": "Hiking Boot", "quantity": 1, "destination_country": "Canada"}}

event: tool_result
data: {"agent": "shipping", "tool": "estimate_shipping", "result": {"shipper_name": "FedEx", "unit_shipping": 25.50, ...}}

event: agent_end
data: {"agent": "shipping", "output": "The shipping cost is..."}

event: message
data: {"role": "assistant", "content": "Shipping a pair of hiking boots to Canada costs approximately $25.50 via FedEx."}
```

The frontend reads from `GET /chat/stream/{session_id}` over SSE and renders
each event type in the UI.

#### 2.7 API changes

**`POST /api/chat`** (replaces existing):

```json
// Request
{
  "query": "I need hiking boots and shipping to Canada",
  "session_id": "a1b2c3d4e5f6"  // optional — null creates new session
}

// Response
{
  "session_id": "a1b2c3d4e5f6",
  "stream_url": "/chat/stream/a1b2c3d4e5f6"
}
```

**`GET /chat/stream/{session_id}`** (new):

```
text/event-stream
Events: agent_start, tool_call, tool_result, agent_end, message, error, done
```

**`GET /chat/history/{session_id}`** (new):

```json
{
  "session_id": "a1b2c3d4e5f6",
  "messages": [
    {"role": "user", "content": "I need hiking boots"},
    {"role": "assistant", "content": "We have several...", "agent_trace": [...]}
  ],
  "context": { "customer_name": null, ... }
}
```

#### 2.8 Frontend changes

The React `ChatBot.jsx` component is upgraded:

| Feature | Implementation |
|---|---|
| **Session ID** | Generate on mount, store in `sessionStorage`, send with every request |
| **Streaming** | `EventSource` or `fetch` with SSE reader on `/chat/stream/{session_id}` |
| **Agent trace display** | Collapsible "thinking" panel showing agent → tool → result steps |
| **State persistence** | `sessionStorage` survives refresh; server has full history via session_id |
| **Error handling** | Reconnect SSE on disconnect, show agent errors inline |

Styling additions:
- Agent trace panel: light gray background, monospace font, tree structure
- Tool calls: icon + tool name + args (collapsible)
- Tool results: truncated preview with expand option
- Visual indicator when agent is "thinking" (animated dots)

#### 2.9 Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    ...existing...
    "langgraph>=0.2.0",
    "langchain-ollama>=0.2.0",
    "langchain-core>=0.3.0",
    "sse-starlette>=2.1.0",
    "boto3>=1.35.0",
]
```

No OpenAI/Anthropic dependencies — the LLM runs locally via Ollama.

#### 2.10 Configuration

```python
# backend/config.py or env vars
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")  # must support tool calling
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))

# Image CDN
S3_IMAGES_BUCKET = os.getenv("S3_IMAGES_BUCKET", "ecommerce-images-dev")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "https://images.ecommerce.com")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
```

---

## 3. Key Decisions

| Decision | Rationale |
|---|---|
| **LangGraph over raw LangChain** | LangGraph provides state graphs, message reducers, and branching — essential for multi-agent routing and conversation memory. Raw LangChain chains are linear and cannot model agent-to-agent handoff. |
| **Ollama + Llama 3 locally** | No API cost, no external dependency, data stays on-prem. Matches the existing local-first philosophy (sentence-transformers is already local). Configurable via env var if a cloud model is preferred later. |
| **Supervisor + 6 specialist agents** | Balances modularity with complexity. Each agent has a focused set of tools. Images is separate because it works with binary data (S3 uploads, CDN URLs, presigned URLs) and has a completely different tool interface than text-based lookup agents. A single-agent system with all 15+ tools would confuse tool selection. |
| **Background thread per session + SSE streaming** | Keeps the FastAPI event loop responsive. LangGraph runs synchronously in a thread; SSE buffer decouples agent execution from HTTP transport. |
| **In-memory session store (not Redis/DB)** | Simplest start — no extra infra. Migrate to Redis when the TTL-based cleanup becomes insufficient or across-pod session sharing is needed. |
| **Replace /chat entirely (not coexist)** | Avoids maintaining two chat backends. The new agent can fall back to pure ChromaDB search if Ollama is unavailable (graceful degradation). |
| **SSE over WebSocket** | SSE is simpler (HTTP-only, no upgrade, works with standard load balancers). The frontend only needs to read a stream, not send over it. |
| **Tool-calling via `@tool` decorators** | LangChain's standard tool interface. Llama 3.1+ supports JSON mode and tool calling natively via Ollama. |

### Rejected alternatives

| Alternative | Why rejected |
|---|---|
| **OpenAI / Anthropic** | Adds API cost, internet dependency, and external data exposure. Local first. |
| **Single agent with all tools** | Prompt would be complex; higher chance of wrong tool selection. Separate agents keep prompts focused. |
| **CrewAI / AutoGen** | Additional abstractions on top of LangGraph; less control over state and streaming. LangGraph is the underlying framework these tools wrap anyway. |
| **WebSocket for streaming** | Requires sticky sessions or a shared session store. SSE is stateless (client polls) and works with any load balancer. |
| **Redis session store** | Adds operational dependency. In-memory is sufficient for single-replica dev/staging. |
| **Pregenerated embeddings via LLM** | ChromaDB already uses sentence-transformers; no need to invoke the LLM for embedding generation. |

---

## 4. Open Questions

1. **Ollama deployment**: Should Ollama run as a sidecar container, a separate Deployment in the K8s cluster, or is a local process sufficient? For dev, local process is fine. For K8s deploy, a separate Deployment with GPU (if available) or CPU-only (llama3 fits in 8GB RAM).

2. **Tool-calling support in local models**: Llama 3.1 8B supports tool calling via Ollama, but quality varies. Should we add OpenAI compatibility as a configurable fallback if the local model fails to produce valid tool calls?

3. **Session storage persistence**: In-memory sessions are lost on pod restart. Is this acceptable for the initial version, or should we add SQLite-backed sessions?

4. **Rate limiting**: Should we limit requests per session to prevent runaway agent loops (max N tool calls per user message)?

5. **Agent timeout**: How long should a single agent run before timing out (default 30s)? What happens on timeout — return error or fall back to ChromaDB-only search?

6. **Multi-user isolation**: Session store is single-process. If deployed with multiple replicas, an external session store (Redis) is needed. Defer to phase 2?

---

## 5. Implementation Plan

### Phase 1 — Foundation (1 session)

| Step | Files | What | Verification |
|---|---|---|---|
| 1 | `pyproject.toml` | Add `langgraph`, `langchain-ollama`, `langchain-core`, `sse-starlette` | `pip install -e .` succeeds |
| 2 | `backend/config.py` | Add `OLLAMA_BASE_URL`, `LLM_MODEL`, `LLM_TEMPERATURE`, `SESSION_TTL_MINUTES` | Import succeeds |
| 3 | `backend/session_store.py` | `SessionStore` class: create, get, append_event, get_events_since, cleanup | Unit test with mock |

### Phase 2 — Tool layer (1 session)

| Step | Files | What | Verification |
|---|---|---|---|
| 4 | `backend/agents/tools/product_tools.py` | `search_products()`, `get_categories()`, `get_product_by_name()`, `search_chromadb()` as `@tool` functions | Each tool callable standalone |
| 5 | `backend/agents/tools/shipping_tools.py` | `estimate_shipping()`, `get_shipping_history()`, `search_chromadb()` | Each tool callable standalone |
| 6 | `backend/agents/tools/quote_tools.py` | `build_quote()`, `check_stock()` | Each tool callable standalone |
| 7 | `backend/agents/tools/pricing_tools.py` | `get_price_history()`, `check_overpricing()`, `apply_promotion()`, `get_category_price_range()`, `search_chromadb()` | Each tool callable standalone |
| 8 | `backend/agents/tools/customer_service_tools.py` | `search_issue_resolution()`, `get_relevant_policies()`, `escalate_to_human()`, `search_chromadb()` | Each tool callable standalone |
| 9 | `backend/agents/tools/image_tools.py` | `get_image_url()`, `upload_image()`, `list_product_images()`, `delete_image()` against S3 + CloudFront | Each tool callable standalone with local S3 mock |

### Phase 3 — LangGraph agents (1-2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 10 | `backend/agents/agent_supervisor.py` | Supervisor node: prompt + 6 routing tools + `Command` routing | Given a product query, routes to Products agent; given a complaint, routes to Customer Service; given "show me", routes to Images |
| 11 | `backend/agents/agent_products.py` | Products agent node: binds tools, tool-calling loop, returns message | `"show me hiking boots"` returns product list |
| 12 | `backend/agents/agent_shipping.py` | Shipping agent node | `"shipping to Canada"` returns estimate |
| 13 | `backend/agents/agent_quote.py` | Quote agent node | `"quote for 2 hiking boots"` returns quote |
| 14 | `backend/agents/agent_pricing.py` | Pricing agent node: price history, overpricing checks, promotions | `"has the price changed"` returns history; `"this seems expensive"` checks overpricing |
| 15 | `backend/agents/agent_customer_service.py` | Customer Service agent node: issue lookup, policy search, human escalation | `"I want to return"` finds order and offers escalation |
| 16 | `backend/agents/agent_images.py` | Images agent node: S3/CloudFront image tools | `"show me a photo of hiking boots"` returns CDN image URL |
| 17 | `backend/agents/graph.py` | Assemble `StateGraph` with supervisor + 6 agents + conditional edges | `graph.invoke({"messages": [query]})` returns final state |

### Phase 4 — API integration (1-2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 18 | `backend/api_rag.py` | **Rewrite**: POST /chat creates session + enqueues; GET /chat/stream SSE; GET /chat/history | `curl POST /chat` returns session_id |
| 19 | `backend/api_rag.py` | Wire LangGraph execution to session store + event buffer | SSE stream emits agent events |
| 20 | `backend/api_rag.py` | Graceful degradation: if Ollama unreachable, fall back to direct ChromaDB search (legacy path) | Kill Ollama → /chat still works with plain RAG |
| 21 | `backend/api_catalog.py` | Add `POST /api/images/upload` — multipart file upload, stores to S3, updates `Product.image_cdn_url`, returns CDN URL | `curl -F "file=@boot.jpg" -F "product_name=Hiking Boot" -F "variant=full" http://localhost:8001/api/images/upload` returns CDN URL |
| 22 | `backend/db/models.py` | Add `image_cdn_url` column to `Product` model | `python -c "from backend.db.models import Product; print(Product.image_cdn_url)"` |

### Phase 5 — Frontend (1-2 sessions)

| Step | Files | What | Verification |
|---|---|---|---|
| 23 | `frontend/chatbot/src/ChatBot.jsx` | Add session_id lifecycle: generate on mount, store in sessionStorage, send with requests | Refresh preserves session |
| 24 | `frontend/chatbot/src/ChatBot.jsx` | SSE reader: connect to stream URL, parse events, update state | Agent steps appear in real time; image CDN URLs render as inline images |
| 25 | `frontend/chatbot/src/ChatBot.jsx` | Agent trace UI: collapsible panel showing agent → tool → result | Click to expand shows tool calls |
| 26 | `frontend/chatbot/src/ChatBot.css` | Styling for trace panel, thinking indicator, tool call visualization, image rendering | Visual design matches app theme |

### Phase 6 — Testing (1 session)

| Step | Files | What | Verification |
|---|---|---|---|
| 27 | `tests/test_session_store.py` | Unit tests for SessionStore CRUD, TTL cleanup | Tests pass |
| 28 | `tests/test_agent_tools.py` | Unit tests for each tool function (mock DB + ChromaDB + S3) | Tests pass |
| 29 | `tests/test_agent_graph.py` | Graph tests with mocked LLM (returns fixed tool call) | `test_product_query`, `test_shipping_query`, `test_quote_query`, `test_pricing_query`, `test_customer_service_query`, `test_images_query` |
| 30 | `tests/test_api_rag.py` | Update existing tests: new response shape, streaming, history, session | All tests pass |
| 31 | `tests/test_chatbot_streaming.py` | SSE stream test: `EventSource` client reads N events including image CDN events | Stream completes with `done` event |
| 32 | `tests/test_image_api.py` | Unit tests for image upload endpoint, S3 mock, CDN URL generation | Upload returns URL, product model updated |

### Verification criteria

- `POST /api/chat` returns `{session_id, stream_url}`
- `GET /chat/stream/{session_id}` emits SSE events culminating in `message` and `done`
- `"show me hiking boots"` → Products agent → tool search_products → returns product list in natural language
- `"shipping to Canada for those boots"` → Supervisor routes to Shipping agent (with context from previous turn) → returns estimate
- `"get me a quote"` → Quote agent → builds quote with stock check + shipping → returns grand total
- `"has the price of hiking boots changed?"` → Pricing agent → tool get_price_history → returns price trend over time
- `"this seems expensive compared to other boots"` → Pricing agent → tool check_overpricing → compares vs category average
- `"I want to return my hiking boots, they arrived damaged"` → Customer Service agent → search_issue_resolution finds order → escalate_to_human creates ticket → returns ticket ID and next steps
- `"show me what the hiking boots look like"` → Images agent → tool get_image_url → returns CDN URL → frontend renders inline image
- `"upload a product photo for hiking boots"` → Images agent → tool upload_image → stores in S3 → updates Product.image_cdn_url → returns confirmation with CDN URL
- `"what images do you have for hiking boots"` → Images agent → tool list_product_images → returns list of variants with URLs
- `POST /api/images/upload` with a JPEG file → 200 response with CDN URL; `Product.image_cdn_url` is populated
- Refresh page → session restored from sessionStorage → history available via `/chat/history/{session_id}`
- Kill Ollama → `/chat` falls back to legacy ChromaDB search, returns formatted text
- All existing catalog API endpoints (`/api/products`, `/api/quote`, etc.) unchanged
