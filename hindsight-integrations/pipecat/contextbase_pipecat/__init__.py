"""ContextBase-Pipecat: Persistent memory for voice AI pipelines.

Provides a ContextBase-backed FrameProcessor for Pipecat pipelines,
giving them long-term memory via automatic recall and retain.

Basic usage::

    from pipecat.pipeline.pipeline import Pipeline
    from contextbase_pipecat import ContextBaseMemoryService

    memory = ContextBaseMemoryService(
        bank_id="user-123",
        contextbase_api_url="http://localhost:8888",
    )

    pipeline = Pipeline([
        transport.input(),
        stt_service,
        user_aggregator,
        memory,            # recall before LLM, retain after each turn
        llm_service,
        assistant_aggregator,
        tts_service,
        transport.output(),
    ])
"""

from .config import (
    ContextBasePipecatConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBasePipecatError
from .memory import ContextBaseMemoryService

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBasePipecatConfig",
    "ContextBasePipecatError",
    "ContextBaseMemoryService",
]
