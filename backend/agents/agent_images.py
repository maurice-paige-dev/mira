from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage

from backend.config import OLLAMA_BASE_URL, LLM_MODEL, LLM_TEMPERATURE
from backend.agents.tools.image_tools import get_image_url, upload_image_tool, list_product_images, delete_image

IMAGE_TOOLS = [get_image_url, upload_image_tool, list_product_images, delete_image]

PROMPT = """You are the Images Agent for an ecommerce system. Your job is to help customers with product images — looking up photos, uploading images, listing available images, and deleting images.

You have these tools:
- get_image_url(product_name, variant) — get CDN URL for a product image
- upload_image_tool(product_name, variant, base64_data) — upload a product image
- list_product_images(product_name) — list all images for a product
- delete_image(product_name, variant) — delete an image

When showing images, return the CDN URLs so they can be displayed inline in the chat."""


def images_agent_node(state):
    query = state.get("tool_results", {}).get("query", "")
    last_msg = state["messages"][-1].content if state["messages"] else ""

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=LLM_TEMPERATURE,
    )
    llm_with_tools = llm.bind_tools(IMAGE_TOOLS)

    result = llm_with_tools.invoke([
        SystemMessage(content=PROMPT),
        *state["messages"][-3:],
    ])

    return {
        "next_agent": "supervisor",
        "messages": [result],
    }
