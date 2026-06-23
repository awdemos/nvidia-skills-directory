# Upstream Sync Design

## Goal
Add a fully automated weekly GitHub Actions workflow that refreshes `nvidia_skills_catalog.json` and `DIRECTORY.md` from the latest `NVIDIA/skills` upstream commit, then opens a pull request with any changes.

## Background

Currently:
- `nvidia_skills_catalog.json` is a hand-managed snapshot extracted from `NVIDIA/skills`.
- The extraction logic is not stored in this repository.
- `SOURCE_COMMIT` is hardcoded in `scripts/generate_directory.py` and `tests/test_directory.py`.
- `EXPECTED_TOTAL_SKILLS` is hardcoded in `tests/test_directory.py`.

## Constraints
- Keep the existing pinned-commit reproducibility model.
- Do not hand-edit `DIRECTORY.md`; it must always be generated.
- All quality gates (ruff, format, basedpyright, pytest) must pass before a PR is opened.
- The workflow must not push directly to `main`; it must open a PR.

## Components

### 1. `scripts/extract_catalog.py`
A new script that:
1. Clones `https://github.com/NVIDIA/skills.git` to a temporary directory (or uses an existing local clone).
2. Resolves the target commit (defaults to `HEAD` of the default branch).
3. Walks `skills/<slug>/SKILL.md` files at that commit.
4. Parses each `SKILL.md` YAML frontmatter.
5. Emits `nvidia_skills_catalog.json` with the schema:
   - `repo`: `"https://github.com/NVIDIA/skills"`
   - `commit`: the resolved commit hash
   - `total`: number of skills discovered
   - `skills`: list of skill records matching the existing `Skill` model fields.

The script must derive the following fields from frontmatter / file path:
- `slug` from the directory name.
- `entry_url` as `https://github.com/NVIDIA/skills/blob/<commit>/skills/<slug>/SKILL.md`.
- `name`, `description`, `product`, `marketplace_product`, `primary_category`, `all_categories`, `license`, `version`, `author`, `tags` from frontmatter.

If a required field is missing, the script fails loudly.

### 2. `scripts/update_pin.py`
A small helper script that updates the hardcoded constants after extraction:
- `SOURCE_COMMIT` in `scripts/generate_directory.py`.
- `SOURCE_COMMIT` in `tests/test_directory.py`.
- `EXPECTED_TOTAL_SKILLS` in `tests/test_directory.py`.

It should be idempotent and only modify the exact constant values.

### 3. `.github/workflows/sync-upstream.yml`
A workflow that runs:
- On a weekly cron schedule (`0 0 * * 0`).
- On `workflow_dispatch` for manual runs.

Steps:
1. Check out this repository.
2. Install `uv` and Python.
3. Run `scripts/extract_catalog.py` against the latest upstream `HEAD`.
4. Run `scripts/update_pin.py` to sync constants.
5. Run `uv run scripts/generate_directory.py` to regenerate `DIRECTORY.md`.
6. Run the full quality gate:
   - `uv run ruff check scripts tests`
   - `uv run ruff format --check scripts tests`
   - `uv run basedpyright`
   - `uv run pytest tests/test_directory.py -v`
7. If there are any changes and all checks pass, open a pull request using `peter-evans/create-pull-request` or similar.
8. If checks fail, fail the workflow and do not open a PR.

PR title/body should include:
- New upstream commit hash.
- Skill count delta.
- Link to upstream compare view.

## Error Handling
- Extraction failures fail the workflow.
- Schema validation failures fail the workflow.
- Test/quality failures fail the workflow.
- Missing required frontmatter fields fail the workflow.
- No changes after sync is a successful no-op (no PR opened).

## Testing
- Add unit tests for `extract_catalog.py` using a temporary mock upstream tree.
- Keep existing `test_directory.py` acceptance tests unchanged in spirit; update them only via `update_pin.py` when the upstream count changes.
- Run the new workflow on `workflow_dispatch` once after merge to verify it works.

## Future Considerations
- The upstream repo could add MCP servers later. The current design explicitly preserves the zero-state MCP section; if upstream adds MCP servers, the extractor and generator will need updates.
- The extractor could be extended to support incremental updates or caching of the upstream clone to speed up the workflow.
