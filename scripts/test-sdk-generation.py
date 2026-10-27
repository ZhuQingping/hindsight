"""Check that SDK documentation branding preserves wire identifiers and data literals."""

import argparse
import importlib.util
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "node"])
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("sdk_brand", Path(__file__).with_name("brand-sdk-generated.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if args.language == "python":
        source = '''"""Hindsight API"""
# HINDSIGHT_API example
value = Field(default="hindsight-customer", description="Hindsight documentation")
wire = {"hindsight_field": "Hindsight original data"}
'''
        result = module.brand_python(source)
        assert '"""ContextBase API"""' in result
        assert 'description="ContextBase documentation"' in result
        assert 'default="hindsight-customer"' in result
        assert 'wire = {"hindsight_field": "Hindsight original data"}' in result
    else:
        source = '/** Hindsight API */\nconst value = "hindsight-customer";\n'
        assert module.brand_node(source) == '/** ContextBase API */\nconst value = "hindsight-customer";\n'
        # Comment-shaped text in a data literal must stop generation rather than be rewritten.
        try:
            module.brand_node('const value = "/* Hindsight customer data */";\n')
        except subprocess.CalledProcessError:
            pass
        else:
            raise AssertionError("Expected rejection of a data change")
    print(f"PASS: {args.language} SDK branding preserves wire identifiers and data literals")


if __name__ == "__main__":
    main()
