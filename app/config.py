import os


class Settings:
    def __init__(self) -> None:
        self.database_url = os.getenv(
            "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/transactions"
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.llm_provider = os.getenv("LLM_PROVIDER", "fallback")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")


settings = Settings()
