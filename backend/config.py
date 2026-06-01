import os

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "30"))

S3_IMAGES_BUCKET = os.getenv("S3_IMAGES_BUCKET", "ecommerce-images-dev")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "https://images.ecommerce.com")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

DATABASE_URL = os.getenv("DATABASE_URL", "")
