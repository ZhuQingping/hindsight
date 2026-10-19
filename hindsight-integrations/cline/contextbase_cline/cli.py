"""Command-line interface for the Cline ContextBase integration.

Exposed as the ``contextbase-cline`` console script:

    contextbase-cline install
    contextbase-cline install --api-url  --api-token hsk_...
    contextbase-cline install --global
    contextbase-cline uninstall
"""

import argparse
import os
from pathlib import Path

from .install import DEFAULT_API_URL, run_install, run_uninstall


def _run_install(args: argparse.Namespace) -> int:
    run_install(
        api_url=args.api_url,
        api_token=args.api_token,
        project_dir=Path(args.project_dir),
        global_install=args.global_install,
    )
    return 0


def _run_uninstall(args: argparse.Namespace) -> int:
    run_uninstall(project_dir=Path(args.project_dir), global_install=args.global_install)
    return 0


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory to install into (default: current directory)",
    )
    parser.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="Use ~/Documents/Cline/Rules/Hooks/ instead of the project's .clinerules/hooks/",
    )


def _add_install_parser(subparsers: argparse._SubParsersAction) -> None:
    install = subparsers.add_parser(
        "install",
        help="Install the ContextBase lifecycle hooks into Cline.",
    )
    install.add_argument(
        "--api-url",
        default=os.environ.get("CONTEXTBASE_API_URL"),
        help=(
            f"ContextBase API base URL written to ~/.contextbase/cline.json. For ContextBase Cloud use {DEFAULT_API_URL}."
        ),
    )
    install.add_argument(
        "--api-token",
        default=os.environ.get("CONTEXTBASE_API_TOKEN"),
        help="ContextBase API token (required for ContextBase Cloud).",
    )
    _add_target_args(install)
    install.set_defaults(func=_run_install)


def _add_uninstall_parser(subparsers: argparse._SubParsersAction) -> None:
    uninstall = subparsers.add_parser(
        "uninstall",
        help="Remove the ContextBase lifecycle hooks from Cline.",
    )
    _add_target_args(uninstall)
    uninstall.set_defaults(func=_run_uninstall)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="contextbase-cline",
        description="Install ContextBase long-term memory for Cline (via lifecycle hooks).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_install_parser(subparsers)
    _add_uninstall_parser(subparsers)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
