"""Configuration: an XDG-located TOML file layered over built-in defaults.

Lookup order for the file: $CORRAL_CONFIG, then $XDG_CONFIG_HOME/corral/
config.toml, then ~/.config/corral/config.toml. The XDG path is used on macOS
too, deliberately -- not ~/Library/Application Support.

Every key is optional; a missing file means all defaults. See DEFAULT_TOML
(written by `corral config init`) for the documented shape. `save` writes a
Config back, keeping the file's comments and layout (the TUI's settings).

The default Codex models come from the installed Codex's own catalog
(`codex debug models`), read once per process; without Codex, or if its
output can't be read, corral uses the packaged CODEX_MODELS instead.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Whitespace

EFFORT = "{effort}"

DEFAULT_PRUNE = frozenset(
    {
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "venv",
        "env",
        "__pycache__",
        "site-packages",
        "Pods",
        "DerivedData",
        "bower_components",
    }
)

DEFAULT_EFFORTS: dict[str, list[str]] = {
    "claude": ["low", "medium", "high", "xhigh", "max"],
    "codex": ["low", "medium", "high", "xhigh", "max", "ultra"],
}
FALLBACK_EFFORTS = ["low", "medium", "high"]


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class ModelSpec:
    key: str  # what you type: "sonnet"
    tool: str  # herdr agent kind: "claude", "codex", ...
    display: str  # tab label prefix: "Sonnet"
    args: tuple[str, ...]  # agent args; "{effort}" is substituted
    efforts: tuple[str, ...] = ()  # this model's levels; () = the tool's

    def args_for(self, effort: str) -> list[str]:
        return [a.replace(EFFORT, effort) for a in self.args]


CLAUDE_MODELS = (
    ModelSpec("sonnet", "claude", "Sonnet", ("--model", "sonnet", "--effort", EFFORT)),
    ModelSpec("opus", "claude", "Opus", ("--model", "opus", "--effort", EFFORT)),
    ModelSpec("haiku", "claude", "Haiku", ("--model", "haiku", "--effort", EFFORT)),
)


def codex_spec(key: str, display: str, slug: str, efforts=()) -> ModelSpec:
    args = ("-m", slug, "-c", f"model_reasoning_effort={EFFORT}")
    return ModelSpec(key, "codex", display, args, tuple(efforts))


# Used when the installed Codex can't say which models it offers.
CODEX_MODELS = (
    codex_spec("sol", "Sol", "gpt-6.1-sol"),
    codex_spec("astra", "Astra", "gpt-6-astra"),
    codex_spec("luna", "Luna", "gpt-6-luna", ("low", "medium", "high", "xhigh", "max")),
)
# Whatever model the user's Codex config picks.
CODEX_DEFAULT = ModelSpec("codex", "codex", "Codex", ("-c", f"model_reasoning_effort={EFFORT}"))
CODEX_TIMEOUT_S = 10


def parse_codex_catalog(data) -> tuple[ModelSpec, ...]:
    """ModelSpecs for the models a `codex debug models` catalog lists (not
    the hidden ones), in Codex's order. Each family's first model gets the
    short name ("sol", "Sol"); later ones keep their version ("5.6-sol",
    "5.6-Sol")."""
    entries = data["models"] if isinstance(data, dict) else data
    listed = sorted(
        (m for m in entries if m.get("visibility", "list") == "list"),
        key=lambda m: m.get("priority", 0),
    )
    taken = {m.key for m in CLAUDE_MODELS} | {CODEX_DEFAULT.key}
    specs = []
    for m in listed:
        slug = str(m["slug"])
        name = slug.removeprefix("gpt-")
        family = name.rsplit("-", 1)[-1]
        if family.isalpha() and family not in taken:
            key, display = family, family.capitalize()
        else:
            key = name
            display = str(m.get("display_name") or name).removeprefix("GPT-")
        if key in taken or any(c in key for c in " /•") or any(c in display for c in "/•"):
            continue
        taken.add(key)
        levels = [str(e["effort"]) for e in m.get("supported_reasoning_levels", [])]
        specs.append(codex_spec(key, display, slug, levels))
    return tuple(specs)


@functools.cache
def codex_models() -> tuple[ModelSpec, ...] | None:
    """The models the installed Codex offers, or None when it can't say."""
    exe = shutil.which("codex")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "debug", "models"],
            capture_output=True,
            text=True,
            timeout=CODEX_TIMEOUT_S,
            check=True,
            stdin=subprocess.DEVNULL,
        ).stdout
        return parse_codex_catalog(json.loads(out)) or None
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        LookupError,
        TypeError,
        AttributeError,
    ):
        return None


def default_models() -> tuple[ModelSpec, ...]:
    return (*CLAUDE_MODELS, *(codex_models() or CODEX_MODELS), CODEX_DEFAULT)


PERCENT_MIN, PERCENT_MAX = 10, 90


@dataclass(frozen=True)
class Utility:
    """The utility tab: one pane on top, two below. Each is a command to run,
    or "" for a plain shell. Missing commands degrade to a shell. The sizes
    are percentages: the top pane's share of the tab's height, and the
    bottom-left pane's share of the bottom row's width."""

    enabled: bool = True
    top: str = "yazi"
    bottom_left: str = ""
    bottom_right: str = "lazygit"
    top_percent: int = 50
    bottom_left_percent: int = 35

    def panes(self) -> dict[str, str]:
        """Pane name -> command, top first."""
        return {"top": self.top, "bottom_left": self.bottom_left, "bottom_right": self.bottom_right}


@dataclass
class Config:
    root: Path = field(default_factory=lambda: Path("~/Code").expanduser())
    scan_depth: int = 3
    prune: frozenset[str] = DEFAULT_PRUNE
    default_agents: tuple[str, ...] = ("sonnet/medium",)
    refresh_seconds: float = 3.0
    agent_timeout_ms: int = 60000
    utility: Utility = field(default_factory=Utility)
    models: tuple[ModelSpec, ...] = field(default_factory=lambda: default_models())
    efforts: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_EFFORTS))
    path: Path | None = None  # file it was loaded from, if any

    def model(self, key: str) -> ModelSpec:
        for m in self.models:
            if m.key == key:
                return m
        known = ", ".join(m.key for m in self.models)
        raise ConfigError(f"unknown model '{key}' (known: {known})")

    def model_by_display(self, display: str) -> ModelSpec | None:
        want = display.strip().lower()
        return next((m for m in self.models if m.display.lower() == want), None)

    def efforts_for(self, tool: str) -> list[str]:
        return self.efforts.get(tool, FALLBACK_EFFORTS)

    def efforts_of(self, model: ModelSpec) -> list[str]:
        """The model's own effort levels, else its tool's."""
        return list(model.efforts) or self.efforts_for(model.tool)


def config_path() -> Path:
    if env := os.environ.get("CORRAL_CONFIG"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "corral" / "config.toml"


def load_file(path: Path | None = None) -> Config:
    """The config file (if present) over the defaults, and nothing else:
    --root and $CORRAL_ROOT override a session, but never belong in the file."""
    path = path or config_path()
    data: dict = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"{path}: {e}") from e
    cfg = from_dict(data)
    cfg.path = path if path.is_file() else None
    return cfg


def load(path: Path | None = None, root: str | None = None) -> Config:
    """Load the config file (if present) over the defaults. `root` (from a CLI
    flag) beats $CORRAL_ROOT, which beats the file's `root`."""
    cfg = load_file(path)
    override = root_override(root)
    if override:
        cfg.root = Path(override).expanduser()
    return cfg


def root_override(root: str | None = None) -> str | None:
    """The root that beats the file's for this session, if any."""
    return root or os.environ.get("CORRAL_ROOT") or None


def _expect(data: dict, key: str, kind: type | tuple[type, ...], where: str = ""):
    v = data[key]
    if not isinstance(v, kind):
        raise ConfigError(f"{where}{key}: expected {getattr(kind, '__name__', kind)}")
    return v


def _percent(table: dict, key: str, default: int) -> int:
    if key not in table:
        return default
    v = table[key]
    if isinstance(v, bool) or not isinstance(v, int) or not PERCENT_MIN <= v <= PERCENT_MAX:
        raise ConfigError(f"utility.{key}: expected a whole number, {PERCENT_MIN} to {PERCENT_MAX}")
    return v


def from_dict(data: dict) -> Config:
    cfg = Config()
    if "root" in data:
        cfg.root = Path(_expect(data, "root", str)).expanduser()
    if "scan_depth" in data:
        cfg.scan_depth = _expect(data, "scan_depth", int)
    if "prune" in data:
        cfg.prune = frozenset(_expect(data, "prune", list))
    if "prune_extra" in data:
        cfg.prune = cfg.prune | frozenset(_expect(data, "prune_extra", list))
    if "default_agents" in data:
        cfg.default_agents = tuple(_expect(data, "default_agents", list))
    if "refresh_seconds" in data:
        cfg.refresh_seconds = float(_expect(data, "refresh_seconds", (int, float)))
    if "agent_timeout_ms" in data:
        cfg.agent_timeout_ms = _expect(data, "agent_timeout_ms", int)

    if "utility" in data:
        u = _expect(data, "utility", dict)
        base = Utility()
        cfg.utility = Utility(
            enabled=bool(u.get("enabled", base.enabled)),
            top=str(u.get("top", base.top)),
            bottom_left=str(u.get("bottom_left", base.bottom_left)),
            bottom_right=str(u.get("bottom_right", base.bottom_right)),
            top_percent=_percent(u, "top_percent", base.top_percent),
            bottom_left_percent=_percent(u, "bottom_left_percent", base.bottom_left_percent),
        )

    if "models" in data:
        models = []
        for i, m in enumerate(_expect(data, "models", list)):
            where = f"models[{i}]."
            if not isinstance(m, dict):
                raise ConfigError(f"models[{i}]: expected a table")
            for k in ("key", "tool", "display"):
                if k not in m:
                    raise ConfigError(f"{where}{k} is required")
            args = m.get("args", [])
            if isinstance(args, str):
                args = args.split()
            levels = m.get("efforts", [])
            if not isinstance(levels, list):
                raise ConfigError(f"{where}efforts: expected array")
            models.append(
                ModelSpec(
                    key=str(m["key"]),
                    tool=str(m["tool"]),
                    display=str(m["display"]),
                    args=tuple(str(a) for a in args),
                    efforts=tuple(str(e) for e in levels),
                )
            )
        keys = [m.key for m in models]
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            raise ConfigError(f"models: duplicate key(s): {', '.join(dupes)}")
        if not models:
            raise ConfigError("models: at least one model is required")
        cfg.models = tuple(models)

    if "efforts" in data:
        eff = _expect(data, "efforts", dict)
        cfg.efforts = {**DEFAULT_EFFORTS, **{k: list(v) for k, v in eff.items()}}

    for spec in cfg.default_agents:
        cfg.model(spec.partition("/")[0])  # fail early on a bad default
    return cfg


# --- writing -----------------------------------------------------------------


def tilde(path: Path) -> str:
    """~/Code rather than /Users/me/Code, for paths under home."""
    home = Path.home()
    if path == home:
        return "~"
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def to_data(cfg: Config) -> dict:
    """cfg as TOML data -- the inverse of from_dict."""
    u = cfg.utility
    data: dict = {
        "root": tilde(cfg.root),
        "scan_depth": cfg.scan_depth,
        "default_agents": list(cfg.default_agents),
        "refresh_seconds": float(cfg.refresh_seconds),
        "agent_timeout_ms": cfg.agent_timeout_ms,
        "utility": {
            "enabled": u.enabled,
            "top": u.top,
            "bottom_left": u.bottom_left,
            "bottom_right": u.bottom_right,
            "top_percent": u.top_percent,
            "bottom_left_percent": u.bottom_left_percent,
        },
        "efforts": {tool: list(levels) for tool, levels in cfg.efforts.items()},
        "models": [_model_data(m) for m in cfg.models],
    }
    if cfg.prune != DEFAULT_PRUNE:
        if cfg.prune > DEFAULT_PRUNE:
            data["prune_extra"] = sorted(cfg.prune - DEFAULT_PRUNE)
        else:
            data["prune"] = sorted(cfg.prune)
    return data


def _model_data(m: ModelSpec) -> dict:
    data = {"key": m.key, "tool": m.tool, "display": m.display, "args": list(m.args)}
    if m.efforts:
        data["efforts"] = list(m.efforts)
    return data


def _plain(item):
    return item.unwrap() if hasattr(item, "unwrap") else item


def _put_table(table, value: dict, default: dict) -> None:
    for k in [k for k in table if k not in value]:
        del table[k]
    for k, v in value.items():
        if (k in table or v != default.get(k)) and _plain(table.get(k)) != v:
            table[k] = v


def _put_models(doc, models: list[dict]) -> None:
    """Update [[models]]: in place while the keys and their order are
    unchanged; otherwise rebuild it in the new order, reusing each surviving
    table (and the comments in it), one blank line apart."""
    old = doc.get("models")
    tables = list(old) if isinstance(old, list) else []
    if [str(t.get("key")) for t in tables] == [m["key"] for m in models]:
        for t, m in zip(tables, models, strict=True):
            _put_table(t, m, {})
        return
    by_key = {str(t.get("key")): t for t in tables}
    aot = tomlkit.aot()
    for m in models:
        t = by_key.get(m["key"]) or tomlkit.table()
        _put_table(t, m, {})
        body = t.value.body
        while body and body[-1][0] is None and isinstance(body[-1][1], Whitespace):
            body.pop()  # the aot puts one blank line between tables itself
        aot.append(t)
    doc["models"] = aot


def save(cfg: Config, path: Path) -> None:
    """Write cfg to path, keeping the file's comments and layout.

    A key is written if the file already has it or its value differs from
    the default, so saving an untouched default leaves the file alone. A new
    file starts from DEFAULT_TOML. Invalid settings raise ConfigError before
    anything is written; a symlinked file is written through the link."""
    data = to_data(cfg)
    from_dict(data)  # validate
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else DEFAULT_TOML
        doc = tomlkit.parse(text)
    except (OSError, TOMLKitError) as e:
        raise ConfigError(f"{path}: {e}") from e
    defaults = to_data(Config())
    for key in ("prune", "prune_extra"):
        if key in doc and key not in data:
            del doc[key]
    for key, value in data.items():
        if key not in doc and value == defaults.get(key):
            continue
        if key == "models":
            if [_plain(t) for t in doc.get("models", [])] != value:
                _put_models(doc, value)
        elif isinstance(value, dict) and isinstance(doc.get(key), dict):
            _put_table(doc[key], value, defaults.get(key, {}))
        elif _plain(doc.get(key)) != value:
            doc[key] = value
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".corral-tmp")
    try:
        tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
        tmp.replace(target)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise ConfigError(f"{path}: {e}") from e


DEFAULT_TOML = """\
# corral configuration -- every key is optional.
# Location: $CORRAL_CONFIG, else $XDG_CONFIG_HOME/corral/config.toml,
# else ~/.config/corral/config.toml.

# Directory whose subdirectories are your projects. Overridden by --root or
# $CORRAL_ROOT.
root = "~/Code"

# How many levels below a top-level project to look for nested git repos.
scan_depth = 3

# Directory names never descended into. `prune` replaces the built-in list;
# `prune_extra` adds to it. Hidden directories are always skipped.
# prune_extra = ["third_party"]

# Agent tabs a new workspace gets, as "model/effort" specs.
default_agents = ["sonnet/medium"]

# How often the TUI polls herdr, and how long to wait for an agent to start.
refresh_seconds = 3.0
agent_timeout_ms = 60000

# The utility tab: a pane on top, two below. Each value is a command, or ""
# for a plain shell. A command that isn't installed falls back to a shell;
# `corral tools` shows what's missing and `corral tools install` installs
# yazi (a terminal file manager) and lazygit (a terminal UI for git).
# top_percent is the top pane's share of the tab's height, and
# bottom_left_percent the bottom-left pane's share of the bottom row (10-90).
[utility]
enabled = true
top = "yazi"
bottom_left = ""
bottom_right = "lazygit"
top_percent = 50
bottom_left_percent = 35

# Effort levels offered per agent tool (herdr agent kind).
[efforts]
claude = ["low", "medium", "high", "xhigh", "max"]
codex = ["low", "medium", "high", "xhigh", "max", "ultra"]

# The model matrix. Left out, it is Sonnet, Opus and Haiku, the models your
# installed Codex offers (`codex debug models`; GPT-6 Sol, Astra and Luna if
# Codex can't say), and "codex" for whatever model your Codex config picks.
# `corral models` lists them. Defining any [[models]] replaces that list.
#
# `tool` is the herdr agent kind (claude, codex, gemini, opencode, ...).
# `key` is what you type (`corral tab opus/high`), `display` prefixes the tab
# label ("Opus•high"), and `args` go to the agent binary with {effort}
# substituted. `efforts`, optional, replaces the tool's levels for one model.
#
# [[models]]
# key = "opus"
# tool = "claude"
# display = "Opus"
# args = ["--model", "opus", "--effort", "{effort}"]
#
# [[models]]
# key = "luna"
# tool = "codex"
# display = "Luna"
# args = ["-m", "gpt-6-luna", "-c", "model_reasoning_effort={effort}"]
# efforts = ["low", "medium", "high", "xhigh", "max"]
"""
