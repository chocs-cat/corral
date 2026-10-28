# Changelog

## [0.11.0](https://github.com/chocs-cat/corral/compare/v0.10.1...v0.11.0) (2026-10-28)


### ⚠ BREAKING CHANGES

* **config:** `corral config show --json` prints `utility` as `{"enabled": …, "panes": [...]}`, with the shorthand expanded and `split`, `direction` and `percent` null on the first pane. The old `top`, `bottom_left`, `bottom_right`, `top_percent` and `bottom_left_percent` keys are no longer in it. Config files that use them keep working.

### Features

* **config:** the utility tab is a list of panes, and lazygit skips folders outside git ([#67](https://github.com/chocs-cat/corral/issues/67)) ([23e0ed9](https://github.com/chocs-cat/corral/commit/23e0ed98863f89c38dab6a76526854ef650dbc58))
* **tui:** the settings screen picks the utility tab's layout from presets ([33f4b45](https://github.com/chocs-cat/corral/commit/33f4b45ab707877dc139706da00c7ea51c37a166)), closes [#21](https://github.com/chocs-cat/corral/issues/21)


### Bug Fixes

* **config:** saving keeps dotted utility and harnesses keys out of the tables it adds ([#74](https://github.com/chocs-cat/corral/issues/74)) ([20250e5](https://github.com/chocs-cat/corral/commit/20250e59486b2b64e067757855d3db8d2b5ba408)), closes [#72](https://github.com/chocs-cat/corral/issues/72)
* **config:** saving no longer breaks a config that writes [utility], panes or [[models]] as inline tables ([33f4b45](https://github.com/chocs-cat/corral/commit/33f4b45ab707877dc139706da00c7ea51c37a166)), closes [#68](https://github.com/chocs-cat/corral/issues/68)

## [0.10.1](https://github.com/chocs-cat/corral/compare/v0.10.0...v0.10.1) (2026-10-25)


### Bug Fixes

* **herdr:** corral --fresh starts a stopped herdr server ([#63](https://github.com/chocs-cat/corral/issues/63)) ([560eb35](https://github.com/chocs-cat/corral/commit/560eb35389c39cb49a3f7011dd185840ac19f038)), closes [#62](https://github.com/chocs-cat/corral/issues/62)

## [0.10.0](https://github.com/chocs-cat/corral/compare/v0.9.0...v0.10.0) (2026-10-23)


### Features

* **cli:** corral --fresh starts herdr over with one Control Center workspace ([#60](https://github.com/chocs-cat/corral/issues/60)) ([07160b5](https://github.com/chocs-cat/corral/commit/07160b5786747d10feedaae121f59e0926be1cf1)), closes [#56](https://github.com/chocs-cat/corral/issues/56) [#59](https://github.com/chocs-cat/corral/issues/59)

## [0.9.0](https://github.com/chocs-cat/corral/compare/v0.8.0...v0.9.0) (2026-10-19)


### Features

* corral reveal opens a folder in the file manager ([#49](https://github.com/chocs-cat/corral/issues/49)) ([307a606](https://github.com/chocs-cat/corral/commit/307a6066c212bbb574094ca0be19a4ff5f41c4e0))
* **tui:** r reveals the selected project's folder ([#52](https://github.com/chocs-cat/corral/issues/52)) ([032f017](https://github.com/chocs-cat/corral/commit/032f0172b4cd7194c4f80e4aeb8306daefd3ab48))

## [0.8.0](https://github.com/chocs-cat/corral/compare/v0.7.0...v0.8.0) (2026-10-15)


### Features

* list nested folders that aren't git repos (opt-in) ([#41](https://github.com/chocs-cat/corral/issues/41)) ([6169b75](https://github.com/chocs-cat/corral/commit/6169b75521c14bffd581ac0e72e47e929a97e06b)), closes [#39](https://github.com/chocs-cat/corral/issues/39)

## [0.7.0](https://github.com/chocs-cat/corral/compare/v0.6.0...v0.7.0) (2026-10-09)


### Features

* **harnesses:** upgrade Claude Code and Codex ([#33](https://github.com/chocs-cat/corral/issues/33)) ([a3bdb9d](https://github.com/chocs-cat/corral/commit/a3bdb9d27d69867cc27cd7f870577e0887dee048))

## [0.6.0](https://github.com/chocs-cat/corral/compare/v0.5.1...v0.6.0) (2026-10-08)


### ⚠ BREAKING CHANGES

* **config:** [[models]] no longer replaces the default list, the [efforts] table is no longer read, and the generic "codex" model is gone.

### Features

* **config:** built-in models from Claude Code and Codex, kept apart from custom ones ([#31](https://github.com/chocs-cat/corral/issues/31)) ([7ec5b1b](https://github.com/chocs-cat/corral/commit/7ec5b1b74ffc2c7d436ba83e88e1fb6ad727b372))

## [0.5.1](https://github.com/chocs-cat/corral/compare/v0.5.0...v0.5.1) (2026-09-27)


### Bug Fixes

* point project URLs and the Homebrew tap at chocs-cat ([#25](https://github.com/chocs-cat/corral/issues/25)) ([7108a68](https://github.com/chocs-cat/corral/commit/7108a6865fb3d74722d34b9e76480d299adb2de8))

## [0.5.0](https://github.com/johnfoland/corral/compare/v0.4.0...v0.5.0) (2026-09-27)


### Features

* size the utility tab's panes and install yazi/lazygit from corral ([#22](https://github.com/johnfoland/corral/issues/22)) ([3f7fd7b](https://github.com/johnfoland/corral/commit/3f7fd7b3435c646c10bcaec97a4bdc22e6979e0f))

## [0.4.0](https://github.com/johnfoland/corral/compare/v0.3.0...v0.4.0) (2026-09-26)


### ⚠ BREAKING CHANGES

* `corral up --fill` and `--force-fill` are gone, and up's JSON result drops the `closed` and `kept_running` fields.

### Features

* remove fill and force-fill ([#17](https://github.com/johnfoland/corral/issues/17)) ([a756a99](https://github.com/johnfoland/corral/commit/a756a99f3395d03386b86bd9ac32ae82be7d21e0))


### Bug Fixes

* **tui:** keep the header one line on click; separate the root with • ([#18](https://github.com/johnfoland/corral/issues/18)) ([d5df227](https://github.com/johnfoland/corral/commit/d5df227829b28ec6d53683c05b21bbbb71aa0708))

## [0.3.0](https://github.com/johnfoland/corral/compare/v0.2.0...v0.3.0) (2026-09-26)


### Features

* list the home directory as a project, first, labelled ~ ([#15](https://github.com/johnfoland/corral/issues/15)) ([68764a0](https://github.com/johnfoland/corral/commit/68764a06b3cdab1aa7f260b0e94934d0415d5092))

## [0.2.0](https://github.com/johnfoland/corral/compare/v0.1.1...v0.2.0) (2026-09-25)


### Features

* **tui:** settings screen for every config option ([b312330](https://github.com/johnfoland/corral/commit/b312330ed462a24fdb7876c1c0ad61becf665abb))


### Bug Fixes

* **tui:** keep the project list's keys from acting behind dialogs ([a9e9dfa](https://github.com/johnfoland/corral/commit/a9e9dfa56fbc6f0c4baf06a6c28a006375b123e1))

## [0.1.1](https://github.com/johnfoland/corral/compare/v0.1.0...v0.1.1) (2026-09-25)


### Documentation

* install from Homebrew as johnfoland/tap/corral-herdr ([e14e8fd](https://github.com/johnfoland/corral/commit/e14e8fd4b79aa9749d52dffff176f1e10114b4e9))

## 0.1.0 (2026-09-25)


### Features

* initial corral release ([cbb4ff1](https://github.com/johnfoland/corral/commit/cbb4ff1dc0e5a169d9c999cd857f77f6ef71d155))


### Bug Fixes

* publish to PyPI as corral-herdr ([a6d4cab](https://github.com/johnfoland/corral/commit/a6d4cab405cfacb0444d105bd405a32ae2f9c42c))
* **tui:** don't crash when a refresh outlives the widgets ([8311947](https://github.com/johnfoland/corral/commit/8311947be4076687ce5b554c0aacfcd81c73aa1f))
