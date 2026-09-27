"""scripts/formula.py, which writes the Homebrew formula after a release."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from packaging.requirements import Requirement

from corral import __version__

ROOT = Path(__file__).parent.parent
PYPROJECT_0_1_0 = '[project]\nname = "corral-herdr"\nversion = "0.1.0"\n'


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("formula", ROOT / "scripts" / "formula.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["formula"] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


formula = _load()


def test_render():
    corral = formula.Sdist("corral-herdr", "https://files/corral_herdr-0.5.1.tar.gz", "a" * 64)
    text = formula.render(
        corral,
        [
            formula.Sdist("textual", "https://files/textual-8.2.8.tar.gz", "c" * 64),
            formula.Sdist("markdown-it-py", "https://files/markdown_it_py-4.2.0.tar.gz", "b" * 64),
        ],
    )
    assert text.startswith("class CorralHerdr < Formula\n  include Language::Python::Virtualenv\n")
    assert '  url "https://files/corral_herdr-0.5.1.tar.gz"\n  sha256 "' + "a" * 64 in text
    assert '  depends_on "python@3.14"\n' in text
    assert 'conflicts_with "corral", because: "both install a `corral` binary"' in text
    assert text.index('resource "markdown-it-py"') < text.index('resource "textual"')
    assert '    url "https://files/textual-8.2.8.tar.gz"\n    sha256 "' + "c" * 64 in text
    assert 'shell_output("#{bin}/corral --version")' in text
    assert 'assert_match "\\"project\\": \\"demo\\"", projects' in text
    assert text.endswith("  end\nend\n")


def test_platform_markers():
    def needed(line: str) -> bool:
        return formula.needed(Requirement(line), "3.14")

    assert needed("rich==15.0.0")
    assert needed("appnope==0.1.4 ; sys_platform == 'darwin'")
    assert not needed("colorama==0.4.6 ; sys_platform == 'win32'")
    assert not needed("tomli==2.2.1 ; python_full_version < '3.11'")


def test_pins_are_the_locked_runtime_dependencies():
    pins = {r.name: str(r.specifier) for r in formula.pins()}
    assert pins["textual"].startswith("==")
    assert "pytest" not in pins  # dev dependencies stay out
    assert "corral-herdr" not in pins


def test_checkout_version(tmp_path):
    assert formula.checkout_version() == __version__
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_0_1_0)
    assert formula.checkout_version(tmp_path) == "0.1.0"


def test_refuses_another_versions_checkout(tmp_path):
    (tmp_path / "pyproject.toml").write_text(PYPROJECT_0_1_0)
    with pytest.raises(SystemExit, match=r"is 0\.1\.0, not 0\.5\.1"):
        formula.main(["0.5.1", "--root", str(tmp_path)])
