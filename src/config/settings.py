from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENT_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = Field(default="sqlite:///./data/agent.db")
    log_level: str = Field(default="INFO")

    # LLM provider — auto-detected from whichever key is set if left blank
    llm_provider: str = Field(default="")   # "anthropic" | "gemini"
    llm_model: str = Field(default="")      # uses provider default when blank

    # Provider keys — set exactly one
    anthropic_api_key: str = Field(default="")
    gemini_api_key: str = Field(default="")

    # ── Privacy invariant & execution bounds ─────────────────────────────
    # Only schema (columns+dtypes) + this many sample rows ever reach the LLM.
    sample_rows: int = Field(default=5)
    # Per-cell string cap (chars) applied to every sampled/result cell.
    sample_cell_chars: int = Field(default=200)
    # Max rows kept in a bounded result summary sent to the answer node.
    result_rows: int = Field(default=20)
    # Wall-clock timeout (seconds) for locally-executed generated code.
    exec_timeout: int = Field(default=30)
    # Max refine loops before best-guess-with-flag.
    max_retries: int = Field(default=3)
    # Reject uploads larger than this many megabytes.
    max_upload_mb: int = Field(default=500)
    # On-disk uploaded-file store.
    uploads_dir: str = Field(default="./data/uploads")

    # ── Phase 3 — sources, memory, DB pushdown ───────────────────────────
    # How many prior conversation turns (question + answer) are fed back to the
    # LLM nodes for a session (privacy-safe prose only — never raw rows).
    memory_turns: int = Field(default=8)
    # Safety cap wrapped around any generated read-only SQL so a stray SELECT *
    # cannot pull a whole DB table into memory.
    sql_max_rows: int = Field(default=100_000)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
