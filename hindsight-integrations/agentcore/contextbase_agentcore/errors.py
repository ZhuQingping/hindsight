class ContextBaseAgentCoreError(Exception):
    """Exception raised when a ContextBase memory operation fails inside AgentCore Runtime."""

    pass


class BankResolutionError(ContextBaseAgentCoreError):
    """Raised when bank ID resolution fails — fails closed to prevent memory leakage."""

    pass
