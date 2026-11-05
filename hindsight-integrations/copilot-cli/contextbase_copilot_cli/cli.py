"""Command-line interface for the GitHub Copilot CLI ContextBase integration.

Exposed as the ``contextbase-copilot-cli`` console script:

    contextbase-copilot-cli install
    contextbase-copilot-cli install --api-url  --api-token hsk_...
    contextbase-copilot-cli install --scope repo
    contextbase-copilot-cli uninstall
    contextbase-copilot-cli uninstall --scope repo
"""

import argparse
import os

from .install import run_install, run_uninstall

DEFAULT_API_URL = ""


def _run_install(args: argparse.Namespace) -> int:
    run_install(api_url=args.api_url, api_token=args.api_token, scope=args.scope)
    return 0


def _run_uninstall(args: argparse.Namespace) -> int:
    run_uninstall(scope=args.scope)
    return 0


def _add_scope_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scope",
        choices=["user", "repo"],
        default="user",
        help=(
            "Where to register hooks: 'user' (~/.copilot/hooks/, default, active for "
            "every session on this machine) or 'repo' (.github/hooks/ in the current "
            "repository, for team-shared hook config)."
        ),
    )


def _add_install_parser(subparsers: argparse._SubParsersAction) -> None:
    install = subparsers.add_parser(
        "install",
        help="Install the ContextBase hook scripts into GitHub Copilot CLI.",
    )
    install.add_argument(
        "--api-url",
        default=os.environ.get("CONTEXTBASE_API_URL"),
        help=(
            "ContextBase API base URL written to ~/.contextbase/copilot-cli.json. "
            f"For ContextBase Cloud use {DEFAULT_API_URL}. "
            "Omit to connect to a local contextbase-embed daemon."
        ),
    )
    install.add_argument(
        "--api-token",
        default=os.environ.get("CONTEXTBASE_API_TOKEN"),
        help="ContextBase API token (required for ContextBase Cloud).",
    )
    _add_scope_argument(install)
    install.set_defaults(func=_run_install)


def _add_uninstall_parser(subparsers: argparse._SubParsersAction) -> None:
    uninstall = subparsers.add_parser(
        "uninstall",
        help="Remove the ContextBase hook scripts from GitHub Copilot CLI.",
    )
    _add_scope_argument(uninstall)
    uninstall.set_defaults(func=_run_uninstall)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contextbase-copilot-cli",
        description="Install ContextBase long-term memory for GitHub Copilot CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_install_parser(subparsers)
    _add_uninstall_parser(subparsers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
