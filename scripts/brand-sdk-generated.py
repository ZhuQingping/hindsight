"""Brand generated SDK documentation without changing wire fields or data defaults."""

import argparse
import ast
import json
import re
import subprocess
import tokenize
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def brand_text(value: str) -> str:
    return (
        value.replace("HINDSIGHT", "CONTEXTBASE")
        .replace("Hindsight", "ContextBase")
        .replace("hindsight", "contextbase")
    )


def brand_python(source: str) -> str:
    """Edit only docstrings, field descriptions and comments; package names come from generator config."""
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        text_node = None
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                text_node = node.body[0].value
        elif isinstance(node, ast.keyword) and node.arg == "description":
            text_node = node.value
        if isinstance(text_node, ast.Constant) and isinstance(text_node.value, str):
            # AST columns are UTF-8 byte offsets, unlike tokenize's character offsets.
            start = offsets[text_node.lineno - 1] + len(
                lines[text_node.lineno - 1].encode()[: text_node.col_offset].decode()
            )
            end = offsets[text_node.end_lineno - 1] + len(
                lines[text_node.end_lineno - 1].encode()[: text_node.end_col_offset].decode()
            )
            spans.add((start, end))
    for token in tokenize.generate_tokens(StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            spans.add((offsets[token.start[0] - 1] + token.start[1], offsets[token.end[0] - 1] + token.end[1]))
    for start, end in sorted(spans, reverse=True):
        source = source[:start] + brand_text(source[start:end]) + source[end:]
    return source


def brand_node(source: str) -> str:
    branded = re.sub(
        r"/\*[\s\S]*?\*/|^[ \t]*//[^\n]*", lambda match: brand_text(match.group()), source, flags=re.MULTILINE
    )
    if branded != source:
        # A comment-like sequence can occur inside a string. Compare the parsed code
        # with comments removed so a wire field/default is never silently rewritten.
        validator = """
const fs = require('node:fs');
const ts = require(require.resolve('typescript', {paths: [process.argv[1]]}));
const values = JSON.parse(fs.readFileSync(0, 'utf8'));
const printer = ts.createPrinter({removeComments: true});
const code = value => printer.printFile(ts.createSourceFile('sdk.ts', value, ts.ScriptTarget.Latest, true));
if (code(values.source) !== code(values.branded)) throw Error('SDK branding attempted to change executable code or data');
"""
        subprocess.run(
            ["node", "-e", validator, str(ROOT / "hindsight-clients/typescript")],
            input=json.dumps({"source": source, "branded": branded}),
            text=True,
            check=True,
        )
    return branded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "node"])
    args = parser.parse_args()
    directory = (
        ROOT / "hindsight-clients/python/contextbase_client_api"
        if args.language == "python"
        else ROOT / "hindsight-clients/typescript/generated"
    )
    suffix = ".py" if args.language == "python" else ".ts"
    for path in directory.rglob(f"*{suffix}"):
        original = path.read_text()
        branded = brand_python(original) if args.language == "python" else brand_node(original)
        if path == directory / "api/__init__.py":
            branded = branded.rstrip("\n") + "\n"
        if branded != original:
            path.write_text(branded)


if __name__ == "__main__":
    main()
