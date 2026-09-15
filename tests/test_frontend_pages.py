"""
Every page goes through the sign-in gate.

Pages must never load data directly: the gate loads it after sign-in, then the
engine and the page's own scripts. These checks read the files, so they hold on
any machine without a browser.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.build_pages_site import CONTEXT, MAGIC

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
PAGES = sorted(FRONTEND.glob("*.html"))
GATE = ["access-config.js", "sealed.js", "access.js"]


def _scripts(page: Path) -> list[str]:
    return re.findall(r'<script src="([^"]+)"', page.read_text())


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.name)
class TestPages:
    def test_loads_the_gate_and_nothing_else(self, page) -> None:
        assert _scripts(page) == GATE

    def test_has_no_inline_scripts(self, page) -> None:
        assert not re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", page.read_text())

    def test_app_scripts_exist_and_exclude_data(self, page) -> None:
        match = re.search(r'<script src="access.js"[^>]*data-app="([^"]*)"', page.read_text())
        assert match, "access.js must list the page's scripts in data-app"
        listed = match.group(1).split()
        assert "engine.js" in listed and "components.js" in listed
        assert listed.index("engine.js") < listed.index("components.js")
        for script in listed:
            assert not script.startswith("data/"), script
            assert (FRONTEND / script).is_file(), script

    def test_explains_itself_without_javascript(self, page) -> None:
        assert "<noscript>" in page.read_text()


def test_page_scripts_start_through_the_gate() -> None:
    """A script loaded after the page has parsed never sees DOMContentLoaded."""
    for script in FRONTEND.glob("*.js"):
        if script.name == "access.js":
            continue
        assert 'addEventListener("DOMContentLoaded"' not in script.read_text(), script.name


def test_the_repository_copy_signs_in_through_a_server() -> None:
    assert 'mode: "server"' in (FRONTEND / "access-config.js").read_text()


def test_browser_and_build_agree_on_the_sealed_format() -> None:
    sealed_js = (FRONTEND / "sealed.js").read_text()
    assert f'const MAGIC = "{MAGIC.decode()}"' in sealed_js
    assert f'const CONTEXT = "{CONTEXT}"' in sealed_js
