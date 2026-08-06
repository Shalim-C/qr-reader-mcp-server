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

- Run `pytest tests/ -v` and make sure all tests pass
- If you add a new enhancement operation, add a test in `tests/`
- Keep PRs focused — one change per PR

## License

MIT — see [LICENSE](LICENSE).
