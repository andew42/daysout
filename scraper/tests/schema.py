"""The real schema, read from the Go source.

The scraper writes to a database the Go server creates, so its tests must
run against that exact schema. A copy pasted in here drifts the moment a
column is added — it already did once, and the tests failed for a reason
that had nothing to do with what they were testing. Extract it instead.
"""

import pathlib
import re

SCHEMA_GO = pathlib.Path(__file__).resolve().parents[2] / "backend" / "store" / "schema.go"


def load():
    source = SCHEMA_GO.read_text(encoding="utf-8")
    match = re.search(r"const schema = `(.*?)`", source, re.DOTALL)
    if not match:
        raise RuntimeError(f"no schema literal found in {SCHEMA_GO}")
    return match.group(1)


SCHEMA = load()
