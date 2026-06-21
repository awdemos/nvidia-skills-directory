# NVIDIA Skills Directory — OpenCode Skill

A lightweight skill that teaches OpenCode agents how to navigate the official NVIDIA skills catalog.

## Install

```bash
mkdir -p ~/.config/opencode/skills
ln -s "$(pwd)" ~/.config/opencode/skills/nvidia-skills-directory
```

Or copy the directory instead of symlinking if you prefer.

## What it does

When this skill is active, agents know to consult `DIRECTORY.md` in `https://github.com/awdemos/nvidia-skills-directory` to answer questions about NVIDIA skills, products, and entry points.
