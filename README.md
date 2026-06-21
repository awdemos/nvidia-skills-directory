# NVIDIA Skills Directory

A complete, agentic-reader-optimized directory of the official NVIDIA skills published at [`NVIDIA/skills`](https://github.com/NVIDIA/skills).

## What's here

- **`DIRECTORY.md`** — the canonical catalog. 201 NVIDIA skills with stable anchors, category/product/license indexes, deep links to each `SKILL.md`, and explicit notes on MCP server coverage.
- **`nvidia_skills_catalog.json`** — structured JSON extract of all 201 skills.
- **`nvidia_skills_catalog.md`** — full markdown table of all 201 skills.
- **`nvidia_skills_summary.md`** — rollup counts by category, product, and license.
- **`scripts/generate_directory.py`** — generator that reads the JSON catalog and emits `DIRECTORY.md`.
- **`tests/test_directory.py`** — acceptance tests locking the directory contract.

## Source

Data was extracted from:

- Repository: [`https://github.com/NVIDIA/skills`](https://github.com/NVIDIA/skills)
- Commit: [`366564ddf68ad55b3c12a2faee3d2fd3d3de3b36`](https://github.com/NVIDIA/skills/tree/366564ddf68ad55b3c12a2faee3d2fd3d3de3b36)
- Total skills cataloged: **201**
- MCP servers found: **0** (none in the upstream repo; none in this workspace)

## Regenerate the directory

```bash
uv run scripts/generate_directory.py
```

## Run the tests

```bash
uv run pytest tests/test_directory.py -v
```

## Other quality checks

```bash
uv run ruff check scripts tests
uv run ruff format --check scripts tests
uv run basedpyright
```

## License

The directory contents reflect the licenses declared in each upstream skill (mostly Apache-2.0). This repository's tooling is provided under the same permissive terms; see individual files for details.
