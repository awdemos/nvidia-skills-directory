"""Unit tests for ``scripts/extract_catalog.py``."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003
from typing import Final

import pytest
import yaml
from scripts.extract_catalog import (
    _build_category_mapping,  # pyright: ignore[reportPrivateUsage]
    _build_product_mapping,  # pyright: ignore[reportPrivateUsage]
    _extract_skills,  # pyright: ignore[reportPrivateUsage]
    _load_frontmatter,  # pyright: ignore[reportPrivateUsage]
    extract_catalog,
)
from scripts.generate_directory import Catalog, Skill

TEST_COMMIT: Final[str] = "366564ddf68ad55b3c12a2faee3d2fd3d3de3b36"


@pytest.fixture
def mock_upstream(tmp_path: Path) -> Path:
    """Build a minimal mock upstream repo tree in ``tmp_path``."""
    repo = tmp_path / "upstream"
    skills_dir = repo / "skills"

    cudaq_skill = skills_dir / "cudaq-guide" / "SKILL.md"
    cudf_skill = skills_dir / "accelerated-computing-cudf" / "SKILL.md"
    vision_skill = skills_dir / "no-metadata-tags" / "SKILL.md"

    cudaq_skill.parent.mkdir(parents=True)
    cudf_skill.parent.mkdir(parents=True)
    vision_skill.parent.mkdir(parents=True)

    _ = cudaq_skill.write_text(
        """---
name: CUDA-Q Guide
title: CUDA-Q Guide
description: Learn CUDA-Q quantum computing.
version: "1.0"
author: NVIDIA Quantum Team
tags:
  - quantum
  - cudaq
license: Apache-2.0
compatibility: nvidia-hopper
metadata:
  author: NVIDIA Quantum Team
  tags:
    - quantum
    - cudaq
---

# CUDA-Q Guide

Content here.
""",
        encoding="utf-8",
    )

    _ = cudf_skill.write_text(
        """---
name: cuDF Accelerated Computing
description: GPU-accelerated DataFrames with cuDF.
license: Apache-2.0
metadata:
  author: NVIDIA Data Science Team
  tags:
    - data-science
    - cudf
    - rapids
---

# cuDF Accelerated Computing

Content here.
""",
        encoding="utf-8",
    )

    _ = vision_skill.write_text(
        """---
name: Vision AI Skill
description: Computer vision examples and workflows.
license: MIT
tags:
  - vision
  - ai
---

# Vision AI Skill

Content here.
""",
        encoding="utf-8",
    )

    _ = (repo / "skills.sh.json").write_text(
        json.dumps(
            {
                "groupings": [
                    {"title": "Quantum Computing", "skills": ["cudaq-guide"]},
                    {
                        "title": "Data Science",
                        "skills": ["accelerated-computing-cudf"],
                    },
                    {"title": "Vision AI", "skills": ["no-metadata-tags"]},
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    components_dir = repo / "components.d"
    components_dir.mkdir(parents=True)
    _ = (components_dir / "cuda-q.yml").write_text(
        yaml.safe_dump({"name": "CUDA-Q", "skills": [{"catalog_dir": "cudaq-guide"}]}),
        encoding="utf-8",
    )
    _ = (components_dir / "cudf.yml").write_text(
        yaml.safe_dump(
            {"name": "cuDF", "skills": [{"catalog_dir": "accelerated-computing-cudf"}]}
        ),
        encoding="utf-8",
    )
    _ = (components_dir / "vision.yml").write_text(
        yaml.safe_dump(
            {"name": "Vision", "skills": [{"catalog_dir": "no-metadata-tags"}]}
        ),
        encoding="utf-8",
    )

    metadata_dir = repo / ".github" / "scripts" / "marketplace"
    metadata_dir.mkdir(parents=True)
    _ = (metadata_dir / "metadata.json").write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "path": "skills/cudaq-guide",
                        "metadata": {"product.primary": "CUDA-Q"},
                    },
                    {
                        "path": "skills/accelerated-computing-cudf",
                        "metadata": {"product.primary": "cuDF"},
                    },
                    {
                        "path": "skills/no-metadata-tags",
                        "metadata": {"product.primary": "Vision"},
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return repo


class TestLoadFrontmatter:
    """Tests for the frontmatter parser."""

    def test_parses_complete_frontmatter(self, mock_upstream: Path) -> None:
        frontmatter = _load_frontmatter(
            mock_upstream / "skills" / "cudaq-guide" / "SKILL.md"
        )
        assert frontmatter.name == "CUDA-Q Guide"
        assert frontmatter.description == "Learn CUDA-Q quantum computing."
        assert frontmatter.version == "1.0"
        assert frontmatter.author == "NVIDIA Quantum Team"
        assert frontmatter.license == "Apache-2.0"
        assert frontmatter.metadata.author == "NVIDIA Quantum Team"
        assert frontmatter.metadata.tags == ["quantum", "cudaq"]

    def test_ignores_top_level_tags_when_metadata_tags_missing(
        self, mock_upstream: Path
    ) -> None:
        frontmatter = _load_frontmatter(
            mock_upstream / "skills" / "no-metadata-tags" / "SKILL.md"
        )
        assert frontmatter.tags == ["vision", "ai"]
        assert frontmatter.metadata.tags is None


class TestBuildCategoryMapping:
    """Tests for ``_build_category_mapping``."""

    def test_returns_slug_to_category_map(self, mock_upstream: Path) -> None:
        mapping = _build_category_mapping(mock_upstream)
        assert mapping == {
            "cudaq-guide": "Quantum Computing",
            "accelerated-computing-cudf": "Data Science",
            "no-metadata-tags": "Vision AI",
        }


class TestBuildProductMapping:
    """Tests for ``_build_product_mapping``."""

    def test_returns_slug_to_product_map(self, mock_upstream: Path) -> None:
        mapping = _build_product_mapping(mock_upstream)
        assert mapping == {
            "cudaq-guide": "CUDA-Q",
            "accelerated-computing-cudf": "cuDF",
            "no-metadata-tags": "Vision",
        }


class TestExtractSkills:
    """Tests for skill discovery and record construction."""

    def test_discovers_all_three_slugs(self, mock_upstream: Path) -> None:
        skills: list[Skill] = _extract_skills(mock_upstream, TEST_COMMIT)
        assert sorted(skill.slug for skill in skills) == [
            "accelerated-computing-cudf",
            "cudaq-guide",
            "no-metadata-tags",
        ]

    def test_builds_expected_records(self, mock_upstream: Path) -> None:
        skills: list[Skill] = _extract_skills(mock_upstream, TEST_COMMIT)
        by_slug = {skill.slug: skill for skill in skills}

        cudaq = by_slug["cudaq-guide"]
        assert cudaq.name == "CUDA-Q Guide"
        assert cudaq.product == "CUDA-Q"
        assert cudaq.marketplace_product == "CUDA-Q"
        assert cudaq.primary_category == "Quantum Computing"
        assert cudaq.all_categories == ["Quantum Computing"]
        assert cudaq.license == "Apache-2.0"
        assert cudaq.version == "1.0"
        assert cudaq.author == "NVIDIA Quantum Team"
        assert cudaq.tags == ["quantum", "cudaq"]
        assert cudaq.entry_url == (
            f"https://github.com/NVIDIA/skills/blob/{TEST_COMMIT}"
            "/skills/cudaq-guide/SKILL.md"
        )

        cudf = by_slug["accelerated-computing-cudf"]
        assert cudf.name == "cuDF Accelerated Computing"
        assert cudf.product == "cuDF"
        assert cudf.marketplace_product == "cuDF"
        assert cudf.primary_category == "Data Science"
        assert cudf.license == "Apache-2.0"
        assert cudf.version == ""
        assert cudf.author == "NVIDIA Data Science Team"
        assert cudf.tags == ["data-science", "cudf", "rapids"]

        vision = by_slug["no-metadata-tags"]
        assert vision.name == "Vision AI Skill"
        assert vision.product == "Vision"
        assert vision.marketplace_product == "Vision"
        assert vision.primary_category == "Vision AI"
        assert vision.license == "MIT"
        assert vision.author == ""
        assert vision.tags == []


class TestExtractCatalog:
    """Tests for the top-level ``extract_catalog`` function."""

    def test_writes_valid_catalog_json(
        self, mock_upstream: Path, tmp_path: Path
    ) -> None:
        output = tmp_path / "catalog.json"
        extract_catalog(
            mock_upstream,
            TEST_COMMIT,
            output,
            "https://github.com/NVIDIA/skills.git",
        )

        catalog = Catalog.model_validate_json(output.read_text(encoding="utf-8"))
        assert catalog.repo == "nvidia/skills"
        assert catalog.commit == TEST_COMMIT
        assert catalog.total == 3
        assert {skill.slug for skill in catalog.skills} == {
            "cudaq-guide",
            "accelerated-computing-cudf",
            "no-metadata-tags",
        }
