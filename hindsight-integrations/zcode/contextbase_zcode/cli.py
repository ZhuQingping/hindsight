"""Command-line interface for the ZCode contextbase integration.

Exposed as the ``contextbase-zcode`` console script:

    contextbase-zcode install
    contextbase-zcode install --api-url https://service.example --api-token hsk_...
    contextbase-zcode uninstall
"""

import argparse
import os

from .install import run_install, run_uninstall


def _run_install(args: argparse.Namespace) -> int:
    run_install(api_url=args.api_url, api_token=args.api_token)
    return 0


def _run_uninstall(_args: argparse.Namespace) -> int:
    run_uninstall()
    return 0


def _add_install_parser(subparsers: argparse._SubParsersAction) -> None:
    install = subparsers.add_parser(
        "install",
        help="Install the contextbase hook scripts into ZCode.",
    )
    install.add_argument(
        "--api-url",
        default=os.environ.get("CONTEXTBASE_API_URL"),
        help=(
            "contextbase API base URL written to ~/.contextbase/zcode.json. "
            "For hosted mode, use the URL provided by your service administrator. "
            "Omit to connect to a local contextbase-embed daemon."
        ),
    )
    install.add_argument(
        "--api-token",
        default=os.environ.get("CONTEXTBASE_API_TOKEN"),
        help="contextbase API token (required for contextbase Cloud).",
    )
    install.set_defaults(func=_run_install)


def _add_uninstall_parser(subparsers: argparse._SubParsersAction) -> None:
    uninstall = subparsers.add_parser(
        "uninstall",
        help="Remove the contextbase hook scripts from ZCode.",
    )
    uninstall.set_defaults(func=_run_uninstall)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contextbase-zcode",
        description="Install contextbase long-term memory for ZCode.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_install_parser(subparsers)
    _add_uninstall_parser(subparsers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
