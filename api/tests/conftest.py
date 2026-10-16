import os

# Tests never send traces, even when the developer's .env has Langfuse keys
# (real environment variables take precedence over .env in pydantic-settings).
os.environ["LANGFUSE_PUBLIC_KEY"] = ""
os.environ["LANGFUSE_SECRET_KEY"] = ""
