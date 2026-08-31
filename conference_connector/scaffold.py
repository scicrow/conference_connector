"""Project scaffolding: `init` and `install-skill`.

Both exist so a `pip install` user never has to clone the repo or curl a raw file to
get started -- the config template and the conference-scout skill ship inside the
package (see pyproject.toml's package-data), and these commands copy them out.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from conference_connector.paths import config_dir, data_dir, outputs_dir

PACKAGE_ROOT = Path(__file__).resolve().parent
TEMPLATE_CONFIG = PACKAGE_ROOT / "templates" / "config.example.yaml"
TEMPLATE_ADAPTER = PACKAGE_ROOT / "templates" / "adapter_template.py"
SKILL_SRC = PACKAGE_ROOT / "skills" / "conference-scout"


def _copy_template(src: Path, dest: Path, force: bool, label: str) -> None:
    if dest.exists() and not force:
        print(f"{dest} already exists -- leaving it alone (use --force to overwrite).")
        return
    if not src.exists():
        print(f"{label} template missing from the install at {src}.")
        return
    shutil.copyfile(src, dest)
    print(f"Wrote {dest}")


def init(force: bool = False) -> None:
    """Create config/, data/, outputs/ and drop in a starter config.yaml and adapter."""
    for d in (config_dir(), data_dir() / "raw", data_dir() / "interim",
              data_dir() / "processed", outputs_dir()):
        d.mkdir(parents=True, exist_ok=True)

    _copy_template(TEMPLATE_CONFIG, config_dir() / "config.yaml", force, "Config")
    _copy_template(TEMPLATE_ADAPTER, Path.cwd() / "my_adapter.py", force, "Adapter")

    print(
        "\nNext:\n"
        "  1. Rewrite config.yaml for yourself -- your research threads and their\n"
        "     keywords are what shape the results, and the placeholder text matches\n"
        "     nothing. Easiest path: `conference_connector install-skill`, then let an\n"
        "     agent interview you and write it.\n"
        "  2. `conference_connector recon <your conference URL>` -- find where the data\n"
        "     actually lives before writing any parsing code.\n"
        "  3. Edit my_adapter.py (three marked EDIT points), then run `python\n"
        "     my_adapter.py` to parse from cache and validate before wiring it in.\n"
    )


def _skill_dest(scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "skills" / "conference-scout"
    return Path.cwd() / ".claude" / "skills" / "conference-scout"


def install_skill(scope: str = "project", force: bool = False) -> None:
    """Copy the bundled conference-scout skill into a Claude Code skills directory."""
    if not SKILL_SRC.exists():
        print(f"Skill missing from the install at {SKILL_SRC}.")
        return

    dest = _skill_dest(scope)
    if dest.exists():
        if not force:
            print(f"{dest} already exists -- use --force to overwrite.")
            return
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILL_SRC, dest)
    print(f"Installed conference-scout skill to {dest}")
    print(
        "Start a Claude Code session in your project directory and ask it to scout a "
        "conference; it will pick the skill up from there."
    )
