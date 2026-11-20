"""Local configuration. Secrets are never serialized into research artifacts."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = field(default="gpt-6.2-astra", repr=False)
    run_dir: Path = Path("runs")
    max_api_calls: int = 32
    max_output_tokens: int = 6000
    max_parallel: int = 2
    demo: bool = False

    def __post_init__(self):
        if not 1 <= self.max_api_calls <= 100:
            raise ValueError("API call limit must be between 1 and 100")
        if not 1000 <= self.max_output_tokens <= 32000:
            raise ValueError("Output token limit must be between 1000 and 32000")
        if not 1 <= self.max_parallel <= 3:
            raise ValueError("Parallelism must be between 1 and 3")

    @classmethod
    def from_env(cls, demo=False):
        load_dotenv(override=False)
        return cls(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", "gpt-6.2-astra"),
            run_dir=Path(os.getenv("AETHELGARD_RUN_DIR", "runs")),
            max_api_calls=int(os.getenv("AETHELGARD_MAX_API_CALLS", "32")),
            max_output_tokens=int(os.getenv("AETHELGARD_MAX_OUTPUT_TOKENS", "6000")),
            max_parallel=int(os.getenv("AETHELGARD_MAX_PARALLEL", "2")),
            demo=demo,
        )

    def public(self):
        model = self.model
        if self.api_key.strip():
            model = model.replace(self.api_key.strip(), "[REDACTED]")
        return {
            "model": model,
            "max_api_calls": self.max_api_calls,
            "max_output_tokens": self.max_output_tokens,
            "max_parallel": self.max_parallel,
            "demo": self.demo,
        }
