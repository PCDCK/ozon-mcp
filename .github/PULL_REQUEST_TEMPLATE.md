## Changes

<!-- One short paragraph describing what this PR does and why. -->

## Type

- [ ] Bug fix
- [ ] New knowledge (examples / quirks / workflows / overrides)
- [ ] New feature
- [ ] Refactor
- [ ] Documentation

## Checklist

- [ ] `uv run pytest tests/ --ignore=tests/live` passes
- [ ] `uv run ruff check src tests` passes
- [ ] `uv run mypy src/ozon_mcp` passes (strict mode)
- [ ] `tests/unit/test_knowledge_integrity.py` passes
- [ ] `CHANGELOG.md` updated under `## [Unreleased]`
- [ ] No real `OZON_*` credentials in code, tests, or fixtures
- [ ] If you added a YAML entry: `review_status` / `source` set
- [ ] If you added a new MCP tool: integration test added in `tests/integration/`

## Notes for the reviewer

<!-- Anything not obvious from the diff: surprising design decisions,
edge cases you considered, follow-up work to schedule. -->
