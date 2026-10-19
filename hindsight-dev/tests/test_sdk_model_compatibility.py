"""Lock existing generated SDK APIs while adding deployment branding.

The fixture was extracted from f51b165a (native base), never from the follow-up
SDK. Hash public declarations/signatures, excluding generated branding comments.
This catches type changes even on hosts without a Go compiler.
"""

import ast
import hashlib
import json
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "sdk-model-api-f51b165.json"


def model_api_digest(source: str, language: str) -> str:
    if language == "python":
        declarations = []
        for node in ast.parse(source).body:
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            members = []
            for member in node.body:
                if isinstance(member, ast.AnnAssign) and isinstance(member.target, ast.Name):
                    if not member.target.id.startswith("_"):
                        members.append((member.target.id, ast.dump(member.annotation)))
                elif isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not member.name.startswith("_"):
                        members.append(
                            (member.name, ast.dump(member.args), ast.dump(member.returns) if member.returns else None)
                        )
            declarations.append((node.name, members))
        encoded = json.dumps(declarations, sort_keys=True)
    else:
        # Generated Go declarations are one-line function signatures and simple
        # struct fields/aliases. Compare every public method, including setters.
        source = re.sub(r"//[^\n]*", "", source)
        declarations = re.findall(r"^type [A-Z]\w+ struct \{[\s\S]*?^\}", source, re.M)
        declarations += re.findall(r"^type [A-Z]\w+ (?!struct)[^\n]+$", source, re.M)
        signatures = re.findall(r"^func (?:\([^\n]*?\) )?[A-Z][^\n]*?\{", source, re.M)
        encoded = json.dumps([re.sub(r"\s+", " ", value).strip() for value in declarations + signatures])
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_all_existing_generated_model_apis_match_native_baseline():
    fixture = json.loads(FIXTURE.read_text())
    for relative, expected in fixture["model_apis"].items():
        path = ROOT / relative
        assert path.is_file(), f"Existing model removed: {relative}"
        actual = model_api_digest(path.read_text(), "python" if path.suffix == ".py" else "go")
        assert actual == expected, f"Existing SDK model API changed: {relative}"


def test_preparation_preserves_compositions_and_explicit_nullable_items():
    prepare = runpy.run_path(str(ROOT / "scripts/prepare-client-spec.py"))["preserve_item_nullability"]
    schema = {
        "bare": {"items": {"type": "string"}},
        "map": {"items": {"type": "object", "additionalProperties": True}},
        "nullable": {"items": {"type": "string", "nullable": True}},
        "union": {"items": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "reference": {"items": {"$ref": "#/components/schemas/Memory"}},
    }
    prepare(schema)
    assert schema["bare"]["items"] == {"type": "string", "nullable": False}
    assert schema["map"]["items"] == {"type": "object", "additionalProperties": True, "nullable": False}
    assert schema["nullable"]["items"] == {"type": "string", "nullable": True}
    assert schema["union"]["items"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert schema["reference"]["items"] == {"$ref": "#/components/schemas/Memory"}
