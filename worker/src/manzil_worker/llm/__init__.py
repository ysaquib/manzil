"""LLM client seam (DESIGN §11.1). The ONLY package that may import provider
SDKs. Every model call goes through call_structured / call_agent / call_vision
(client.py, P0-7); per-stage model pins live in config.py; prompts in prompts/.
Langfuse tracing on every call from the first call (NFR6)."""
