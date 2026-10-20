"""Read public deployment settings without loading dotenv or mutating the process."""

import os


def service_env(name: str, default: str = "") -> str:
    """Read an API_/CP_ setting with the same precedence as native entrypoints.

    Presence, including an empty value, wins over the internal namespace. Offline
    commands must agree with API/UI startup without importing the native engine or
    discovering a parent .env file just to resolve a configuration alias.
    """
    return os.environ.get(f"CONTEXTBASE_{name}", os.environ.get(f"HINDSIGHT_{name}", default))
