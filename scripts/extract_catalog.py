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
"""Extract ``nvidia_skills_catalog.json`` from the upstream NVIDIA/skills repo."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import ClassVar, Final, Protocol, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_directory import Catalog, Skill  # noqa: E402

DEFAULT_UPSTREAM_URL: Final[str] = "https://github.com/NVIDIA/skills.git"
DEFAULT_OUTPUT: Final[Path] = REPO_ROOT / "nvidia_skills_catalog.json"

FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


class _SkillGrouping(BaseModel):
    """A single category grouping inside ``skills.sh.json``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    title: str
    skills: list[str]


class _SkillsShJson(BaseModel):
    """Typed shape of ``skills.sh.json``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    groupings: list[_SkillGrouping]


class _ComponentSkillEntry(BaseModel):
    """A single skill entry inside a ``components.d/*.yml`` file."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    catalog_dir: str


class _Component(BaseModel):
    """Typed shape of a ``components.d/*.yml`` file."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str
    skills: list[_ComponentSkillEntry]


class _MarketplaceMetadata(BaseModel):
    """Typed shape of a skill's marketplace metadata block."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    product_primary: str = Field(alias="product.primary")


class _MarketplaceSkill(BaseModel):
    """Typed shape of a single skill entry in ``metadata.json``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    path: str
    metadata: _MarketplaceMetadata


class _MarketplaceMetadataJson(BaseModel):
    """Typed shape of ``.github/scripts/marketplace/metadata.json``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    skills: list[_MarketplaceSkill]


class _FrontmatterMetadata(BaseModel):
    """Typed shape of the optional ``metadata`` block in a ``SKILL.md``."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    author: str = ""
    tags: list[str] | str = []


class _SkillFrontmatter(BaseModel):
    """Typed shape of a ``SKILL.md`` YAML frontmatter block."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="allow")

    name: str = ""
    description: str = ""
    license: str = ""
    version: str = ""
    author: str = ""
    tags: list[str] | str | None = None
    metadata: _FrontmatterMetadata = _FrontmatterMetadata()


def _run_git(*args: str, cwd: Path) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repo_name_from_url(url: str) -> str:
    """Derive a lowercased ``owner/repo`` string from a Git remote URL.

    Supports ``https://`` and ``git@`` forms, with or without a ``.git`` suffix.
    """
    if url.startswith(("https://", "http://")):
        netloc_and_path = url.split("://", 1)[1]
        path = netloc_and_path.split("/", 1)[1] if "/" in netloc_and_path else ""
    elif url.startswith("git@"):
        path = url.split(":", 1)[1] if ":" in url else ""
    else:
        return url.lower()
    path = path.removesuffix(".git")
    return path.lower()


def _load_frontmatter(skill_path: Path) -> _SkillFrontmatter:
    """Parse YAML frontmatter from a ``SKILL.md`` file."""
    text = skill_path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        msg = f"No YAML frontmatter found in {skill_path}"
        raise ValueError(msg)
    data = yaml.safe_load(match.group(1))  # pyright: ignore[reportAny]
    return _SkillFrontmatter.model_validate(data)


def _build_category_mapping(repo_dir: Path) -> dict[str, str]:
    """Map skill slug to primary category title from ``skills.sh.json``."""
    data = _SkillsShJson.model_validate_json(
        (repo_dir / "skills.sh.json").read_text(encoding="utf-8"),
    )
    mapping: dict[str, str] = {}
    for grouping in data.groupings:
        for slug in grouping.skills:
            mapping[slug] = grouping.title
    return mapping


def _build_product_mapping(repo_dir: Path) -> dict[str, str]:
    """Map skill slug to product name from ``components.d/*.yml``."""
    mapping: dict[str, str] = {}
    for path in sorted((repo_dir / "components.d").glob("*.yml")):
        component = _Component.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")),
        )
        for skill in component.skills:
            mapping[skill.catalog_dir] = component.name
    return mapping


def _build_marketplace_product_mapping(repo_dir: Path) -> dict[str, str]:
    """Map skill slug to marketplace product from upstream ``metadata.json``."""
    metadata_path = repo_dir / ".github" / "scripts" / "marketplace" / "metadata.json"
    data = _MarketplaceMetadataJson.model_validate_json(
        metadata_path.read_text(encoding="utf-8"),
    )
    mapping: dict[str, str] = {}
    for skill in data.skills:
        slug = Path(skill.path).name
        if slug and skill.metadata.product_primary:
            mapping[slug] = skill.metadata.product_primary
    return mapping


def _extract_skills(repo_dir: Path, commit: str) -> list[Skill]:
    """Discover and parse all skill records from the cloned repository."""
    category_map = _build_category_mapping(repo_dir)
    product_map = _build_product_mapping(repo_dir)
    marketplace_map = _build_marketplace_product_mapping(repo_dir)

    skills_dir = repo_dir / "skills"
    skill_paths = sorted(skills_dir.glob("*/SKILL.md"))

    records: list[Skill] = []
    for skill_path in skill_paths:
        slug = skill_path.parent.name
        frontmatter = _load_frontmatter(skill_path)

        name = frontmatter.name or slug
        description = frontmatter.description
        if not description:
            msg = f"Missing description for skill {slug}"
            raise ValueError(msg)

        license_ = frontmatter.license
        if not license_:
            msg = f"Missing license for skill {slug}"
            raise ValueError(msg)

        version = frontmatter.version
        author = frontmatter.author or frontmatter.metadata.author
        tags: list[str] | str | None = frontmatter.metadata.tags or frontmatter.tags
        if tags is None:
            tags = []

        primary_category = category_map.get(slug, "")
        product = product_map.get(slug, "")
        if not product:
            product = primary_category
        marketplace_product = marketplace_map.get(slug, "") or product

        entry_url = (
            f"https://github.com/NVIDIA/skills/blob/{commit}/skills/{slug}/SKILL.md"
        )

        record = {
            "slug": slug,
            "name": name,
            "description": description,
            "product": product,
            "marketplace_product": marketplace_product,
            "primary_category": primary_category,
            "all_categories": [primary_category] if primary_category else [],
            "license": license_,
            "version": version,
            "author": author,
            "tags": tags,
            "entry_url": entry_url,
        }
        records.append(Skill.model_validate(record))

    return records


class _ExtractorArgs(Protocol):
    """Typed shape of parsed extractor CLI arguments."""

    upstream_url: str
    commit: str | None
    output: Path


def main() -> None:
    """CLI entry point for the upstream catalog extractor."""
    parser = argparse.ArgumentParser(
        description="Extract NVIDIA skills catalog from upstream repository.",
    )
    _ = parser.add_argument(
        "--upstream-url",
        default=DEFAULT_UPSTREAM_URL,
        help="URL of the upstream NVIDIA/skills Git repository.",
    )
    _ = parser.add_argument(
        "--commit",
        default=None,
        help="Upstream commit to extract. Defaults to HEAD of the default branch.",
    )
    _ = parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path for the extracted catalog JSON.",
    )
    args = cast("_ExtractorArgs", cast("object", parser.parse_args()))

    with tempfile.TemporaryDirectory(prefix="nvidia-skills-") as tmpdir:
        tmp_path = Path(tmpdir)
        repo_dir = tmp_path / "skills"
        _ = _run_git("clone", args.upstream_url, str(repo_dir), cwd=tmp_path)
        if args.commit:
            _ = _run_git("checkout", args.commit, cwd=repo_dir)
        commit = _run_git("rev-parse", "HEAD", cwd=repo_dir)

        skills = _extract_skills(repo_dir, commit)
        repo_name = _repo_name_from_url(args.upstream_url)

        catalog = Catalog.model_validate(
            {
                "repo": repo_name,
                "commit": commit,
                "total": len(skills),
                "skills": skills,
            }
        )

    _ = args.output.write_text(
        catalog.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(skills)} skills to {args.output}")


if __name__ == "__main__":
    main()
