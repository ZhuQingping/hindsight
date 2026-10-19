"""ContextBase memory integration for Devin Desktop (formerly Windsurf / Codeium).

Wires the ContextBase MCP server (multi-bank mode) into **both** agents Devin
Desktop ships — Cascade and Devin Local — and writes always-on memory rules for
each: a per-project rule naming this repo's bank plus a global rule for
cross-project memory. Both agents then have ``recall``/``retain``/``reflect``
tools and use them automatically, scoped per project.

CLI::

    cd your-project
    contextbase-devin-desktop init --api-token hsk_...
"""

__version__ = "0.2.0"
