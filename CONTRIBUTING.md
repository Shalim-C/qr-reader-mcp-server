# Contributing

Contributions are welcome — bug reports, feature ideas, documentation fixes, and code.

## Getting started

```bash
git clone https://github.com/Shalim-C/qr-reader-mcp-server.git
cd qr-reader-mcp-server
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v
```

CI runs the same suite on Python 3.10, 3.11, 3.12.

## Debugging with MCP Inspector

```bash
npx @modelcontextprotocol/inspector python -m qr_reader.server
```

## Before submitting a PR

Run the full local gate — CI runs exactly this, so a red CI is avoidable:

```bash
python -m ruff check src/ tests/     # lint
python -m mypy src/                  # types
python -m pytest tests/ -v           # full suite
```

Then verify version consistency:

```bash
python -c "
import re
pt = re.search(r'version\s*=\s*\"(.+?)\"', open('pyproject.toml').read()).group(1)
iv = re.search(r'__version__\s*=\s*\"(.+?)\"', open('src/qr_reader/__init__.py').read()).group(1)
assert pt == iv, f'mismatch: {pt} vs {iv}'
print('version OK')"
```

Additional rules:

- **Behavior changes must update tests in the same commit.** A changed
  classification rule (e.g. result-code semantics) without an updated test
  will fail CI — don't push a red main branch.
- If you add a new enhancement operation, add a test in `tests/`
- Keep PRs focused — one change per PR
- Feature additions that ship in the next release also require a
  `CHANGELOG.md` entry

## License

MIT — see [LICENSE](LICENSE).
