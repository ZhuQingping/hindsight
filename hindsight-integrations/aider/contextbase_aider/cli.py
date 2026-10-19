"""``contextbase-aider`` — a drop-in wrapper for ``aider`` with long-term memory.

Use it exactly like ``aider`` (all arguments pass straight through); it recalls
relevant project memory before the session and retains the transcript after::

    contextbase-aider                         # interactive, memory loaded
    contextbase-aider -m "fix the auth bug"   # recall uses the message as the query
    contextbase-aider src/app.py              # any aider args work

Configure via ``~/.contextbase/aider.json`` or environment variables
(``CONTEXTBASE_API_TOKEN``, ``CONTEXTBASE_AIDER_BANK_ID``, ...). The bank defaults to
the git repo name, so memory follows the project.
"""

from __future__ import annotations

import sys
from typing import Optional

from . import __version__, runner


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("--contextbase-version",):
        print(f"contextbase-aider {__version__}")
        return 0
    return runner.run(args)


if __name__ == "__main__":
    sys.exit(main())
