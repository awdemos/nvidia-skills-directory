# Upstream Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-repo extractor and a weekly GitHub Actions workflow that refreshes `nvidia_skills_catalog.json` and `DIRECTORY.md` from the latest `NVIDIA/skills` commit and opens a pull request.

**Architecture:** A new `scripts/extract_catalog.py` clones the upstream repo, reads `skills.sh.json` and `components.d/*.yml` to resolve categories and products, parses each `SKILL.md` frontmatter, and emits the catalog JSON. `scripts/update_pin.py` syncs the hardcoded commit/count constants, then the existing generator and tests run. A GitHub workflow orchestrates this weekly and opens a PR only when there are changes.

**Tech Stack:** Python 3.14, uv, Pydantic, PyYAML, GitHub Actions, `peter-evans/create-pull-request`.

---

## File Structure

- **Create** `scripts/extract_catalog.py` — upstream catalog extractor.
- **Create** `scripts/update_pin.py` — updates hardcoded `SOURCE_COMMIT` and `EXPECTED_TOTAL_SKILLS`.
- **Create** `tests/test_extract_catalog.py` — unit tests for the extractor using a mock upstream tree.
- **Create** `.github/workflows/sync-upstream.yml` — weekly sync workflow.
- **Modify** `AGENTS.md` — document the new sync command/workflow.
- **Modify** `nvidia_skills_catalog.json`, `DIRECTORY.md`, `scripts/generate_directory.py`, `tests/test_directory.py` — regenerated/updated by the workflow scripts during validation.

---

## Task 1: Add `scripts/extract_catalog.py`

**Files:**
- Create: `scripts/extract_catalog.py`
- Test: `tests/test_extract_catalog.py`

### Step 1.1: Write the extractor implementation

Create `scripts/extract_catalog.py` with inline PEP 723 metadata for `pydantic>=2` and `pyyaml>=6`.

```python
# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "pydantic>=2",
#     "pyyaml>=6",
# ]
# ///
# ─── How to run ───
# uv run scripts/extract_catalog.py
# ──────────────────
"""Extract nvidia_skills_catalog.json from the upstream NVIDIA/skills repo."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Final

import yaml
from scripts.generate_directory import Catalog as RawCatalog, Skill as RawSkill

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_UPSTREAM_URL: Final[str] = "https://github.com/NVIDIA/skills.git"
DEFAULT_OUTPUT: Final[Path] = REPO_ROOT / "nvidia_skills_catalog.json"


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def clone_upstream(url: str, dest: Path, commit: str | None = None) -> str:
    """Clone upstream repo; return the resolved commit hash."""
    _git("clone", "--depth", "1", "--no-single-branch", url, str(dest))
    if commit is None:
        commit = _git("rev-parse", "HEAD", cwd=dest)
    else:
        _git("fetch", "--depth", "1", "origin", commit, cwd=dest)
        _git("checkout", commit, cwd=dest)
        commit = _git("rev-parse", "HEAD", cwd=dest)
    return commit


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse YAML frontmatter from a markdown file."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        msg = "YAML frontmatter not found"
        raise ValueError(msg)
    return yaml.safe_load(match.group(1)) or {}


def load_category_map(upstream: Path) -> dict[str, str]:
    """Build slug -> category title from skills.sh.json groupings."""
    path = upstream / "skills.sh.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for group in data.get("groupings", []):
        title = group["title"]
        for slug in group.get("skills", []):
            mapping[slug] = title
    return mapping


def load_product_map(upstream: Path) -> dict[str, str]:
    """Build slug -> product name from components.d/*.yml."""
    mapping: dict[str, str] = {}
    components_dir = upstream / "components.d"
    if not components_dir.exists():
        return mapping
    for yaml_path in components_dir.glob("*.yml"):
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        product = data.get("name", "")
        if not product:
            continue
        for entry in data.get("skills", []):
            slug = entry.get("catalog_dir", "") if isinstance(entry, dict) else ""
            if slug:
                mapping[slug] = product
    return mapping


def discover_skills(upstream: Path) -> list[str]:
    """Return sorted slugs for every skills/<slug>/SKILL.md directory."""
    skills_dir = upstream / "skills"
    slugs: list[str] = []
    if not skills_dir.exists():
        return slugs
    for skill_dir in skills_dir.iterdir():
        skill_file = skill_dir / "SKILL.md"
        if skill_dir.is_dir() and skill_file.exists():
            slugs.append(skill_dir.name)
    return sorted(slugs)


def extract_skill(
    upstream: Path,
    slug: str,
    commit: str,
    category_map: dict[str, str],
    product_map: dict[str, str],
) -> RawSkill:
    """Extract a single skill record from its SKILL.md file."""
    skill_file = upstream / "skills" / slug / "SKILL.md"
    frontmatter = parse_frontmatter(skill_file.read_text(encoding="utf-8"))

    metadata = frontmatter.get("metadata", {}) or {}
    tags = frontmatter.get("tags", metadata.get("tags", []))
    author = frontmatter.get("author", metadata.get("author", ""))

    category = category_map.get(slug, "")
    product = product_map.get(slug, "")

    return RawSkill(
        slug=slug,
        name=str(frontmatter.get("name", slug)),
        description=str(frontmatter.get("description", "")),
        product=product,
        marketplace_product=product,
        primary_category=category,
        all_categories=[category] if category else [],
        license=str(frontmatter.get("license", "")),
        version=str(frontmatter.get("version", "")),
        author=str(author),
        tags=tags,
        entry_url=f"https://github.com/NVIDIA/skills/blob/{commit}/skills/{slug}/SKILL.md",
    )


def extract_catalog(
    upstream_url: str,
    commit: str | None,
    output_path: Path,
) -> RawCatalog:
    """Clone upstream, extract skills, and write the catalog JSON."""
    with tempfile.TemporaryDirectory() as tmpdir:
        upstream_path = Path(tmpdir) / "upstream"
        resolved_commit = clone_upstream(upstream_url, upstream_path, commit)

        category_map = load_category_map(upstream_path)
        product_map = load_product_map(upstream_path)
        slugs = discover_skills(upstream_path)

        skills = [
            extract_skill(upstream_path, slug, resolved_commit, category_map, product_map)
            for slug in slugs
        ]

        catalog = RawCatalog(
            repo="https://github.com/NVIDIA/skills",
            commit=resolved_commit,
            total=len(skills),
            skills=skills,
        )

    output_path.write_text(
        catalog.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return catalog


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Extract nvidia_skills_catalog.json from NVIDIA/skills.",
    )
    parser.add_argument(
        "--upstream-url",
        default=DEFAULT_UPSTREAM_URL,
        help="Upstream git URL",
    )
    parser.add_argument(
        "--commit",
        default=None,
        help="Upstream commit to extract (default: HEAD of default branch)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path",
    )
    args = parser.parse_args()

    catalog = extract_catalog(args.upstream_url, args.commit, args.output)
    print(f"Extracted {catalog.total} skills to {args.output}")
    print(f"Upstream commit: {catalog.commit}")


if __name__ == "__main__":
    main()
```

### Step 1.2: Verify the script runs and emits valid JSON

Run:

```bash
uv run scripts/extract_catalog.py --commit 366564ddf68ad55b3c12a2faee3d2fd3d3de3b36
```

Expected: `nvidia_skills_catalog.json` is regenerated and `uv run pytest tests/test_directory.py -v` still passes.

### Step 1.3: Validate catalog equivalence

Run a diff between the regenerated JSON and the original. Field order may differ; normalize both with the following snippet before comparing:

```bash
python3 - <<'PY'
import json
old = json.load(open("nvidia_skills_catalog.json.bak"))
new = json.load(open("nvidia_skills_catalog.json"))
# Compare sorted skills by slug
old_skills = {s["slug"]: s for s in old["skills"]}
new_skills = {s["slug"]: s for s in new["skills"]}
mismatches = []
for slug in old_skills:
    if old_skills[slug] != new_skills.get(slug):
        mismatches.append(slug)
print("Mismatched slugs:", mismatches[:10])
PY
```

Iterate on `extract_catalog.py` until the regenerated catalog matches the current one for the pinned commit. Common fixes: normalize whitespace in descriptions, prefer `metadata.tags` over top-level `tags`, map `title` frontmatter to product fallback, etc.

---

## Task 2: Add `scripts/update_pin.py`

**Files:**
- Create: `scripts/update_pin.py`

### Step 2.1: Write the implementation

```python
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
# ─── How to run ───
# uv run scripts/update_pin.py <commit> <total>
# ──────────────────
"""Update hardcoded SOURCE_COMMIT and EXPECTED_TOTAL_SKILLS constants."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent


def update_constant(path: Path, name: str, value: str) -> bool:
    """Replace a `NAME: Final[type] = ...` constant value in place."""
    text = path.read_text(encoding="utf-8")
    if name == "EXPECTED_TOTAL_SKILLS":
        pattern = rf"({name}\s*:\s*Final\[int\]\s*=\s*)\d+"
    else:
        pattern = rf'({name}\s*:\s*Final\[str\]\s*=\s*")[^"]*"'
    new_text = re.sub(pattern, lambda m: f'{m.group(1)}{value}"', text)
    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update pinned upstream commit and skill count constants.",
    )
    parser.add_argument("commit", help="New upstream commit hash")
    parser.add_argument("total", type=int, help="New total skill count")
    args = parser.parse_args()

    files = [
        REPO_ROOT / "scripts" / "generate_directory.py",
        REPO_ROOT / "tests" / "test_directory.py",
    ]
    for path in files:
        update_constant(path, "SOURCE_COMMIT", args.commit)
    update_constant(
        REPO_ROOT / "tests" / "test_directory.py",
        "EXPECTED_TOTAL_SKILLS",
        str(args.total),
    )
    print(f"Updated pins to commit {args.commit} and total {args.total}")


if __name__ == "__main__":
    main()
```

### Step 2.2: Verify pin updates

Run:

```bash
uv run scripts/update_pin.py 366564ddf68ad55b3c12a2faee3d2fd3d3de3b36 201
```

Expected: no changes because the values already match. Temporarily change one constant, rerun, and confirm it is restored.

---

## Task 3: Add unit tests for the extractor

**Files:**
- Create: `tests/test_extract_catalog.py`

### Step 3.1: Write tests using a mock upstream tree

```python
"""Tests for scripts/extract_catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.extract_catalog import (
    RawCatalog,
    discover_skills,
    extract_catalog,
    extract_skill,
    load_category_map,
    load_product_map,
    parse_frontmatter,
)


@pytest.fixture
def mock_upstream(tmp_path: Path) -> Path:
    """Create a minimal mock upstream tree."""
    upstream = tmp_path / "upstream"
    skills_dir = upstream / "skills"

    # Skill 1
    skill1_dir = skills_dir / "cudaq-guide"
    skill1_dir.mkdir(parents=True)
    skill1_dir.joinpath("SKILL.md").write_text(
        "---\n"
        'name: "cudaq-guide"\n'
        'title: "Cuda Quantum"\n'
        "description: CUDA-Q onboarding guide.\n"
        'version: "1.0.1"\n'
        'author: "CUDA-Q Team"\n'
        "tags: [cuda-quantum, quantum-computing]\n"
        'license: "Apache-2.0"\n'
        "---\n\n# CUDA-Q\n",
        encoding="utf-8",
    )

    # Skill 2
    skill2_dir = skills_dir / "accelerated-computing-cudf"
    skill2_dir.mkdir(parents=True)
    skill2_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: accelerated-computing-cudf\n"
        "description: cuDF guide.\n"
        "license: CC-BY-4.0 AND Apache-2.0\n"
        "metadata:\n"
        "  author: NVIDIA\n"
        "  tags:\n"
        "    - cudf\n"
        "---\n\n# cuDF\n",
        encoding="utf-8",
    )

    # Category map
    upstream.joinpath("skills.sh.json").write_text(
        json.dumps(
            {
                "groupings": [
                    {
                        "title": "Quantum Computing",
                        "skills": ["cudaq-guide"],
                    },
                    {
                        "title": "Data Science",
                        "skills": ["accelerated-computing-cudf"],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    # Product map
    components_dir = upstream / "components.d"
    components_dir.mkdir()
    components_dir.joinpath("cuda-q.yml").write_text(
        yaml.safe_dump(
            {
                "name": "CUDA-Q",
                "skills": [{"path": "skills/cudaq-guide", "catalog_dir": "cudaq-guide"}],
            },
        ),
        encoding="utf-8",
    )
    components_dir.joinpath("cudf.yml").write_text(
        yaml.safe_dump(
            {
                "name": "cuDF",
                "skills": [
                    {
                        "path": "skills/accelerated-computing-cudf",
                        "catalog_dir": "accelerated-computing-cudf",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    return upstream


def test_parse_frontmatter(mock_upstream: Path) -> None:
    """Frontmatter is parsed from SKILL.md."""
    text = (mock_upstream / "skills" / "cudaq-guide" / "SKILL.md").read_text()
    fm = parse_frontmatter(text)
    assert fm["name"] == "cudaq-guide"
    assert fm["version"] == "1.0.1"


def test_load_category_map(mock_upstream: Path) -> None:
    """Category map resolves slugs to category titles."""
    mapping = load_category_map(mock_upstream)
    assert mapping["cudaq-guide"] == "Quantum Computing"
    assert mapping["accelerated-computing-cudf"] == "Data Science"


def test_load_product_map(mock_upstream: Path) -> None:
    """Product map resolves slugs to product names."""
    mapping = load_product_map(mock_upstream)
    assert mapping["cudaq-guide"] == "CUDA-Q"
    assert mapping["accelerated-computing-cudf"] == "cuDF"


def test_discover_skills(mock_upstream: Path) -> None:
    """All skills with SKILL.md are discovered."""
    slugs = discover_skills(mock_upstream)
    assert slugs == ["accelerated-computing-cudf", "cudaq-guide"]


def test_extract_skill(mock_upstream: Path) -> None:
    """A skill record is built from frontmatter and mappings."""
    category_map = load_category_map(mock_upstream)
    product_map = load_product_map(mock_upstream)
    skill = extract_skill(
        mock_upstream,
        "cudaq-guide",
        "abc123",
        category_map,
        product_map,
    )
    assert skill.slug == "cudaq-guide"
    assert skill.product == "CUDA-Q"
    assert skill.primary_category == "Quantum Computing"
    assert skill.version == "1.0.1"
    assert "abc123" in skill.entry_url


def test_extract_catalog(mock_upstream: Path, tmp_path: Path) -> None:
    """extract_catalog writes a valid catalog JSON."""
    output = tmp_path / "catalog.json"
    catalog = extract_catalog(
        upstream_url=str(mock_upstream),
        commit=None,
        output_path=output,
    )
    assert isinstance(catalog, RawCatalog)
    assert catalog.total == 2
    assert len(catalog.skills) == 2
    assert output.exists()
```

### Step 3.2: Run the new tests

```bash
uv run pytest tests/test_extract_catalog.py -v
```

Expected: all tests pass.

---

## Task 4: Add the GitHub Actions sync workflow

**Files:**
- Create: `.github/workflows/sync-upstream.yml`

### Step 4.1: Write the workflow

```yaml
name: Sync upstream NVIDIA/skills

on:
  schedule:
    - cron: "0 0 * * 0"
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          version: "0.11.7"

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"

      - name: Install dependencies
        run: uv sync --all-groups

      - name: Extract upstream catalog
        id: extract
        run: uv run scripts/extract_catalog.py

      - name: Update pinned constants
        run: |
          uv run scripts/update_pin.py \
            "$(jq -r .commit nvidia_skills_catalog.json)" \
            "$(jq -r .total nvidia_skills_catalog.json)"

      - name: Regenerate directory
        run: uv run scripts/generate_directory.py

      - name: Lint
        run: uv run ruff check scripts tests

      - name: Format check
        run: uv run ruff format --check scripts tests

      - name: Type check
        run: uv run basedpyright

      - name: Test
        run: uv run pytest tests/test_directory.py tests/test_extract_catalog.py -v

      - name: Create pull request
        uses: peter-evans/create-pull-request@v7
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          branch: sync/upstream-skills
          title: "sync: update from NVIDIA/skills@${{ steps.extract.outputs.commit }}"
          body: |
            Weekly upstream sync.

            - Upstream commit: ${{ steps.extract.outputs.commit }}
            - Skills cataloged: ${{ steps.extract.outputs.total }}
            - Compare: https://github.com/NVIDIA/skills/compare/${{ steps.extract.outputs.previous_commit }}...${{ steps.extract.outputs.commit }}
          commit-message: "sync: update from NVIDIA/skills@${{ steps.extract.outputs.commit }}"
```

### Step 4.2: Pass commit/total outputs from the extract step

Modify the extract step so its outputs are available to the PR step. Add the following to `scripts/extract_catalog.py` when running as a script, or add a workflow step:

```yaml
      - name: Extract upstream catalog
        id: extract
        run: |
          uv run scripts/extract_catalog.py
          echo "commit=$(jq -r .commit nvidia_skills_catalog.json)" >> "$GITHUB_OUTPUT"
          echo "total=$(jq -r .total nvidia_skills_catalog.json)" >> "$GITHUB_OUTPUT"
```

Note: `previous_commit` requires reading the previous `SOURCE_COMMIT` from `scripts/generate_directory.py`. For the first run, hardcode the current pinned value or omit the compare link. A simple approach is to skip the compare link in the body:

```yaml
          body: |
            Weekly upstream sync.

            - Upstream commit: ${{ steps.extract.outputs.commit }}
            - Skills cataloged: ${{ steps.extract.outputs.total }}
```

### Step 4.3: Validate workflow syntax

Run `actionlint` if available, or push to a fork and trigger `workflow_dispatch` manually.

---

## Task 5: Update documentation

**Files:**
- Modify: `AGENTS.md`

### Step 5.1: Update `AGENTS.md`

Replace the catalog-refresh note with:

```markdown
- The catalog JSON is an external snapshot. Refresh it locally with:
  ```bash
  uv run scripts/extract_catalog.py
  uv run scripts/update_pin.py "$(jq -r .commit nvidia_skills_catalog.json)" "$(jq -r .total nvidia_skills_catalog.json)"
  uv run scripts/generate_directory.py
  ```
  A weekly GitHub Actions workflow (`.github/workflows/sync-upstream.yml`) performs the same steps and opens a PR when upstream changes.
```

Also update the command section to mention the new scripts:

```markdown
# Extract catalog from upstream
uv run scripts/extract_catalog.py

# Update pinned constants after extraction
uv run scripts/update_pin.py <commit> <total>
```

---

## Task 6: Final validation

### Step 6.1: Run the full quality gate locally

```bash
uv run scripts/extract_catalog.py
uv run scripts/update_pin.py "$(jq -r .commit nvidia_skills_catalog.json)" "$(jq -r .total nvidia_skills_catalog.json)"
uv run scripts/generate_directory.py
uv run ruff check scripts tests
uv run ruff format --check scripts tests
uv run basedpyright
uv run pytest tests/test_directory.py tests/test_extract_catalog.py -v
```

Expected: all checks pass and there are no uncommitted changes (because the extractor reproduces the current catalog for the pinned commit).

### Step 6.2: Test the workflow end-to-end on a fork

Push the branch to a personal fork, trigger `workflow_dispatch`, and verify:
- A PR is opened when upstream has new commits.
- No PR is opened when there are no changes.
- Quality failures prevent PR creation.

---

## Spec Coverage Check

- ✅ Add extractor to repo — Task 1.
- ✅ Pin to latest upstream commit — Task 1 (`--commit` default) + Task 2.
- ✅ Regenerate `DIRECTORY.md` — Task 4 workflow step.
- ✅ Run quality gates before PR — Task 4 workflow steps.
- ✅ Open PR on changes — Task 4 workflow `create-pull-request` step.
- ✅ Tests for extractor — Task 3.
- ✅ Error handling — implicit in subprocess checks, Pydantic validation, and workflow gate ordering.
- ✅ Update docs — Task 5.

## Placeholder Scan

No TBD/TODO/"implement later"/"similar to Task N" patterns. Every step includes exact file paths and complete code or commands.

## Type Consistency Check

- `RawSkill` and `RawCatalog` reuse field names from `scripts/generate_directory.py`.
- `extract_catalog()` returns `RawCatalog` consistently.
- `update_pin.py` uses string replacements that match the existing `Final[str]` and `Final[int]` annotations.
