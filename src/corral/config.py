"""Configuration: an XDG-located TOML file layered over built-in defaults.

Lookup order for the file: $CORRAL_CONFIG, then $XDG_CONFIG_HOME/corral/
config.toml, then ~/.config/corral/config.toml. The XDG path is used on macOS
too, deliberately -- not ~/Library/Application Support.

Every key is optional; a missing file means all defaults. See DEFAULT_TOML
(written by `corral config init`) for the documented shape. `save` writes a
Config back, keeping the file's comments and layout (the TUI's settings).

Models are built-in or custom. The built-ins come from the agent CLIs
installed here, asked once per process: Claude Code's model aliases (the
packaged ones plus any its `--help` names) with the effort levels its
`--help` lists, and the models `codex debug models` lists. When a CLI can't
say, its packaged list (CLAUDE_MODELS, CODEX_MODELS) stands in. Custom
models are the file's [[models]]; one with a built-in's key replaces it, and
`hide_models` drops built-ins. Each model has its own effort levels.

[harnesses.<name>] says how `corral harnesses upgrade` treats Claude Code
(`claude`) and Codex (`codex`); corral.harnesses does the upgrading.
"""

from __future__ import annotations

import functools
import json
import os
import re
import shlex
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

# Effort levels for a custom model of an agent with no built-in models.
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
    source: str = "custom"  # "claude-code" or "codex" (from the CLI), "packaged", "custom"

    @property
    def builtin(self) -> bool:
        return self.source != "custom"

    def args_for(self, effort: str) -> list[str]:
        return [a.replace(EFFORT, effort) for a in self.args]


SOURCE_NAMES = {
    "claude-code": "Claude Code",
    "codex": "Codex",
    "packaged": "packaged",
    "custom": "custom",
}
CLI_TIMEOUT_S = 10
CLAUDE_ALIASES = ("opus", "sonnet", "fable", "haiku")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
_READ_ERRORS = (
    OSError,
    subprocess.SubprocessError,
    ValueError,
    LookupError,
    TypeError,
    AttributeError,
)


def claude_spec(key: str, efforts=CLAUDE_EFFORTS, source: str = "packaged") -> ModelSpec:
    # The alias ("opus") always means Claude Code's latest model of that name.
    args = ("--model", key, "--effort", EFFORT)
    return ModelSpec(key, "claude", key.capitalize(), args, tuple(efforts), source)


def codex_spec(
    key: str, display: str, slug: str, efforts=CODEX_EFFORTS, source: str = "packaged"
) -> ModelSpec:
    args = ("-m", slug, "-c", f"model_reasoning_effort={EFFORT}")
    return ModelSpec(key, "codex", display, args, tuple(efforts), source)


# Used when Claude Code or Codex can't say which models it offers.
CLAUDE_MODELS = tuple(claude_spec(a) for a in CLAUDE_ALIASES)
CODEX_MODELS = (
    codex_spec("sol", "Sol", "gpt-6.1-sol"),
    codex_spec("astra", "Astra", "gpt-6-astra"),
    codex_spec("luna", "Luna", "gpt-6-luna", CODEX_EFFORTS[:-1]),  # no "ultra"
)


def _usable(key: str, display: str, taken: set[str]) -> bool:
    return bool(key) and key not in taken and not any(c in key + display for c in " /•")


def _option_help(text: str, option: str) -> str:
    """The help text of one option in a `--help` listing: its line and the
    wrapped lines under it, up to the next option."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(option):
            block = [line]
            for more in lines[i + 1 :]:
                if more.lstrip().startswith("-") or not more.strip():
                    break
                block.append(more)
            return " ".join(part.strip() for part in block)
    return ""


def parse_claude_help(text: str) -> tuple[ModelSpec, ...]:
    """Claude models from `claude --help`: the packaged aliases plus any
    other alias its --model help names, each with the levels its --effort
    help lists. Empty when the help doesn't list effort levels."""
    levels = re.search(r"\(([a-z]+(?:, [a-z]+)+)\)", _option_help(text, "--effort"))
    if not levels:
        return ()
    efforts = tuple(levels.group(1).split(", "))
    named = re.findall(r"'([a-z]+)'", _option_help(text, "--model"))
    aliases = list(dict.fromkeys([*CLAUDE_ALIASES, *named]))
    return tuple(claude_spec(a, efforts, "claude-code") for a in aliases)


def _run(*argv: str) -> str | None:
    """A CLI's stdout, or None when it isn't installed or fails."""
    exe = shutil.which(argv[0])
    if not exe:
        return None
    try:
        return subprocess.run(
            [exe, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=CLI_TIMEOUT_S,
            check=True,
            stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


@functools.cache
def claude_help() -> str | None:
    """`claude --help`, or None when Claude Code can't say."""
    return _run("claude", "--help")


def claude_models() -> tuple[ModelSpec, ...] | None:
    """The models the installed Claude Code offers, or None when it can't say."""
    text = claude_help()
    return (parse_claude_help(text) or None) if text else None


def parse_codex_catalog(data, taken: set[str] | None = None) -> tuple[ModelSpec, ...]:
    """ModelSpecs for the models a `codex debug models` catalog lists (not
    the hidden ones), in Codex's order. Each family's first model gets the
    short name ("sol", "Sol"); later ones keep their version ("5.6-sol",
    "5.6-Sol"). Keys in `taken` are left alone."""
    entries = data["models"] if isinstance(data, dict) else data
    listed = sorted(
        (m for m in entries if m.get("visibility", "list") == "list"),
        key=lambda m: m.get("priority", 0),
    )
    taken = set(taken or ())
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
        if not _usable(key, display, taken):
            continue
        taken.add(key)
        levels = [str(e["effort"]) for e in m.get("supported_reasoning_levels", [])]
        specs.append(codex_spec(key, display, slug, levels, "codex"))
    return tuple(specs)


@functools.cache
def codex_catalog() -> dict | list | None:
    """The installed Codex's model catalog, or None when it can't say."""
    out = _run("codex", "debug", "models")
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


def codex_models(taken: set[str] | None = None) -> tuple[ModelSpec, ...] | None:
    """The models the installed Codex offers, or None when it can't say."""
    data = codex_catalog()
    if data is None:
        return None
    try:
        return parse_codex_catalog(data, taken) or None
    except _READ_ERRORS:
        return None


def builtin_models() -> tuple[ModelSpec, ...]:
    """Claude Code's models, then Codex's."""
    claude = claude_models() or CLAUDE_MODELS
    codex = codex_models({m.key for m in claude}) or CODEX_MODELS
    return (*claude, *codex)


PERCENT_MIN, PERCENT_MAX = 10, 90

# The agent CLIs corral can upgrade: Claude Code and Codex.
HARNESS_NAMES = ("claude", "codex")


@dataclass(frozen=True)
class HarnessSettings:
    """How `corral harnesses upgrade` treats one harness. `upgrade`: whether
    upgrading all of them includes it. `command`: what upgrades it, or ""
    for the way it was installed (corral.harnesses works that out)."""

    upgrade: bool = True
    command: str = ""


def _default_harnesses() -> dict[str, HarnessSettings]:
    return {name: HarnessSettings() for name in HARNESS_NAMES}


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
    harnesses: dict[str, HarnessSettings] = field(default_factory=_default_harnesses)
    builtin_models: tuple[ModelSpec, ...] = field(default_factory=lambda: builtin_models())
    custom_models: tuple[ModelSpec, ...] = ()  # the file's [[models]]
    hide_models: frozenset[str] = frozenset()  # built-ins not offered
    path: Path | None = None  # file it was loaded from, if any

    @property
    def models(self) -> tuple[ModelSpec, ...]:
        """The models offered: the built-ins in order, each replaced by a
        custom model with its key or dropped if hidden, then the other custom
        models."""
        custom = {m.key: m for m in self.custom_models}
        out = []
        for b in self.builtin_models:
            if b.key in custom:
                out.append(custom.pop(b.key))
            elif b.key not in self.hide_models:
                out.append(b)
        return (*out, *custom.values())

    def replaced(self, model: ModelSpec) -> bool:
        """Whether a custom model replaces this built-in."""
        return any(m.key == model.key for m in self.custom_models)

    def model(self, key: str) -> ModelSpec:
        for m in self.models:
            if m.key == key:
                return m
        known = ", ".join(m.key for m in self.models)
        raise ConfigError(f"unknown model '{key}' (known: {known})")

    def model_by_display(self, display: str) -> ModelSpec | None:
        want = display.strip().lower()
        return next((m for m in self.known_models if m.display.lower() == want), None)

    @property
    def known_models(self) -> tuple[ModelSpec, ...]:
        """The models offered plus hidden built-ins: tabs made with a model
        before it was hidden are still agent tabs."""
        hidden = (m for m in self.builtin_models if m.key in self.hide_models)
        return (*self.models, *hidden)

    def efforts_for(self, tool: str) -> list[str]:
        """Effort levels for a model of `tool` that lists none: those of the
        tool's first built-in model."""
        first = next((m for m in self.builtin_models if m.tool == tool and m.efforts), None)
        return list(first.efforts) if first else list(FALLBACK_EFFORTS)

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

    if "harnesses" in data:
        cfg.harnesses = _default_harnesses()
        for name, h in _expect(data, "harnesses", dict).items():
            where = f"harnesses.{name}"
            if name not in HARNESS_NAMES:
                raise ConfigError(f"{where}: corral upgrades only {', '.join(HARNESS_NAMES)}")
            if not isinstance(h, dict):
                raise ConfigError(f"{where}: expected a table")
            upgrade = _expect(h, "upgrade", bool, f"{where}.") if "upgrade" in h else True
            command = _expect(h, "command", str, f"{where}.") if "command" in h else ""
            try:
                shlex.split(command)
            except ValueError as e:
                raise ConfigError(f"{where}.command: {e}") from None
            cfg.harnesses[name] = HarnessSettings(upgrade, command.strip())

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
        cfg.custom_models = tuple(models)

    if "hide_models" in data:
        cfg.hide_models = frozenset(str(k) for k in _expect(data, "hide_models", list))
    if not cfg.models:
        raise ConfigError("models: at least one model is required")

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
        "harnesses": {
            name: {"upgrade": h.upgrade, "command": h.command}
            for name, h in sorted(cfg.harnesses.items())
        },
        "models": [_model_data(m) for m in cfg.custom_models],
        "hide_models": sorted(cfg.hide_models),
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


def _new_table(value: dict, default: dict) -> dict:
    """A table for a file that lacks it: its sub-tables ([harnesses.claude])
    hold only the keys that differ from the default, and are left out when
    none do."""
    out = {}
    for k, v in value.items():
        if isinstance(v, dict):
            v = {kk: vv for kk, vv in v.items() if vv != default.get(k, {}).get(kk)}
            if not v:
                continue
        out[k] = v
    return out


def _put_table(table, value: dict, default: dict) -> None:
    for k in [k for k in table if k not in value]:
        del table[k]
    for k, v in value.items():
        if isinstance(v, dict) and isinstance(table.get(k), dict):
            _put_table(table[k], v, default.get(k, {}))
        elif isinstance(v, dict):
            if new := _new_table({k: v}, default):
                table[k] = new[k]
        elif (k in table or v != default.get(k)) and _plain(table.get(k)) != v:
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
        if key in ("models", "hide_models") and not value:
            del doc[key]
            continue
        if key == "models":
            if [_plain(t) for t in doc.get("models", [])] != value:
                _put_models(doc, value)
        elif isinstance(value, dict) and isinstance(doc.get(key), dict):
            _put_table(doc[key], value, defaults.get(key, {}))
        elif isinstance(value, dict):
            doc[key] = _new_table(value, defaults.get(key, {}))
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

# Upgrading the agent CLIs: `corral harnesses upgrade`, or the settings
# screen's Harnesses tab. corral upgrades Claude Code and Codex the way each
# was installed (Homebrew, npm, or its own `update` command). `upgrade = false`
# leaves one out when upgrading them all; `command` replaces the upgrade
# command corral works out.
# [harnesses.claude]
# upgrade = true
# command = "claude update"

# Built-in models come from the agent CLIs installed here, each with its own
# effort levels: Claude Code's aliases (opus, sonnet, fable, haiku and any
# other its --help names) and the models `codex debug models` lists, or
# corral's packaged list when one can't say. `corral models` lists them.
# Hide the ones you don't want:
# hide_models = ["5.6-sol", "terra"]

# Custom models, added to the built-ins; one with a built-in's key replaces
# it. `tool` is the herdr agent kind (claude, codex, gemini, opencode, ...).
# `key` is what you type (`corral tab gem/high`), `display` prefixes the tab
# label ("Gemini•high"), and `args` go to the agent binary with {effort}
# substituted. `efforts` are the levels offered, lowest first; without it, a
# model gets those of its agent's first built-in model.
#
# [[models]]
# key = "gem"
# tool = "gemini"
# display = "Gemini"
# args = ["--model", "gemini-3-pro"]
# efforts = ["default"]
"""
