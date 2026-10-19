"""ContextBase-CrewAI: Persistent memory for AI agent crews.

Provides a ContextBase-backed Storage implementation for CrewAI's
ExternalMemory system, giving your crews long-term memory across runs.

Basic usage::

    from contextbase_crewai import configure, ContextBaseStorage
    from crewai.memory.external.external_memory import ExternalMemory
    from crewai import Crew

    configure(
        contextbase_api_url="",
        api_key="hsk_...",
    )

    crew = Crew(
        agents=[...],
        tasks=[...],
        external_memory=ExternalMemory(
            storage=ContextBaseStorage(bank_id="my-crew")
        ),
    )

Per-agent banks::

    storage = ContextBaseStorage(
        bank_id="crew-shared",
        per_agent_banks=True,
    )
"""

from .config import (
    ContextBaseCrewAIConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .storage import ContextBaseStorage
from .tools import ContextBaseReflectTool

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseCrewAIConfig",
    "ContextBaseStorage",
    "ContextBaseReflectTool",
    "HindsightError",
]
