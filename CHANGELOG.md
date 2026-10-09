# Changelog

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
