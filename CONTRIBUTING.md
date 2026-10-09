# Contributing

## Setup

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check               # types (ty is pinned: it's pre-1.0)
uv run corral --help          # the dev install
```

The code is laid out in layers, each depending only on the ones above it:

| Module | Role |
|---|---|
| `herdr.py` | typed wrapper over the `herdr` CLI; raises `HerdrError(code, message)` |
| `config.py` | XDG TOML config over built-in defaults, including the built-in models read from Claude Code and Codex; `save` writes it back, keeping comments (tomlkit) |
| `labels.py` | `Model•effort[-N]` tab labels and agent names |
| `projects.py` | scanning the root, workspace matching |
| `tools.py` | the utility tab's programs (yazi, lazygit): status and installing them |
| `harnesses.py` | the agent CLIs (Claude Code, Codex): versions, install method, upgrading them |
| `ops.py` | the operations: `up`, `tab`, `stop`, `close` |
| `cli.py` | argparse front end, human and `--json` output |
| `tui/app.py` | the Textual app; calls `ops` in worker threads |
| `tui/dialogs.py` | modal dialogs: agent picker, stop picker, confirm |
| `tui/settings.py` | the settings screen (`,`) over `config.save` |
| `tui/upgrades.py` | the upgrades screen (`U`): harness versions and upgrading them |

The CLI and the TUI both go through `ops`, so put behaviour changes there.
Tests use `tests/fake_herdr.py`, an in-memory herdr with the same methods as
`Herdr`.

## Roadmap and decisions

Planned work and ideas are [GitHub issues](https://github.com/chocs-cat/corral/issues);
look there before starting something, and open one for anything you won't
finish now. Settled design questions are in [docs/decisions.md](docs/decisions.md).
Coding agents also follow [AGENTS.md](AGENTS.md).

Work on a branch and open a pull request; `master` only takes merges, and
only once the **CI passed** check is green. That check needs lint (ruff and
ty), the tests on Linux and macOS with Python 3.11 to 3.13, and a packaging
check that installs the built wheel and sdist and runs `corral`. PR titles
must be Conventional Commits. Dependabot opens grouped update PRs weekly
(`ci(deps)`, `build(deps)`), which don't trigger a release on their own.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/). The
version and changelog are generated from them:

- `feat: …` → minor bump
- `fix: …` → patch bump
- `feat!: …` or a `BREAKING CHANGE:` footer → major bump (minor while < 1.0)
- `docs:`, `refactor:`, `test:`, `ci:`, `build:`, `chore:` → no release on their own, and not listed in the changelog

Pull request titles are checked for this format in CI.

## Releasing

Releases are automated with [release-please](https://github.com/googleapis/release-please):

1. Merge conventional commits to `master`.
2. release-please opens or updates a **release PR** that bumps the version
   (in `pyproject.toml`, `uv.lock`, `src/corral/__init__.py` and
   `.claude-plugin/plugin.json`) and adds a section to `CHANGELOG.md`.
3. Merging that PR tags `vX.Y.Z` and creates the GitHub release. The
   `publish` job then builds the package and uploads it to PyPI, and the
   `formula` workflow writes the Homebrew formula, pushes it to
   [chocs-cat/homebrew-tap](https://github.com/chocs-cat/homebrew-tap), and
   installs it from there on macOS to check it.

Don't edit versions or `CHANGELOG.md` by hand. To force a specific version,
add a `Release-As: 1.0.0` footer to a commit.

### One-time setup

- **PyPI trusted publishing:** on pypi.org, add a pending publisher for
  project `corral-herdr`: owner `chocs-cat`, repo `corral`, workflow `release.yml`,
  environment `pypi`.
- **GitHub environment:** create an environment named `pypi` in the repo
  settings. Optionally require approval there.
- **Actions permissions:** in Settings → Actions → General, allow GitHub
  Actions to create pull requests.
- **Homebrew tap:** a `TAP_TOKEN` secret, a fine-grained personal access token
  for `chocs-cat/homebrew-tap` only, with **Contents** read/write. It's an
  organization secret, shared with the other repos whose releases write to
  the tap.
- **CI on release PRs:** a PR opened with the built-in `GITHUB_TOKEN` waits
  for a maintainer to approve its CI run ("action required"). The release
  workflow uses the `RELEASE_PLEASE_TOKEN` secret instead when it exists: a
  fine-grained personal access token for this repo only, with **Contents**
  and **Pull requests** read/write. Release PRs are then opened under your
  name and CI runs on them by itself. Renew the token before it expires; if
  it lapses, release-please fails until you replace it or delete the secret.

### Homebrew

The formula is `Formula/corral-herdr.rb` in
[chocs-cat/homebrew-tap](https://github.com/chocs-cat/homebrew-tap), written by
`scripts/formula.py`: don't edit it in the tap, change the script's template.
It builds from the PyPI sdist, with a `resource` for each runtime dependency
at the version the release's `uv.lock` pins. To redo a version's formula, run
the **Formula** workflow by hand with that version. Locally, point `--root` at
a checkout of its tag, which the lock comes from:
`uv run --script scripts/formula.py X.Y.Z --root ../corral-vX.Y.Z > corral-herdr.rb`.
