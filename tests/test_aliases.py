"""Finder aliases, written with the same Core Foundation calls Finder uses."""

from __future__ import annotations

import ctypes
import os
import sys

import pytest

from corral import aliases, ops, projects

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Finder aliases are macOS only")

SUITABLE_FOR_BOOKMARK_FILE = 1 << 10


def make_alias(alias, target):
    ptr = ctypes.c_void_p
    cf = ctypes.CDLL(aliases._CORE_FOUNDATION)
    cf.CFURLCreateFromFileSystemRepresentation.restype = ptr
    cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
        ptr,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_bool,
    ]
    cf.CFURLCreateBookmarkData.restype = ptr
    cf.CFURLCreateBookmarkData.argtypes = [ptr, ptr, ctypes.c_ulong, ptr, ptr, ptr]
    cf.CFURLWriteBookmarkDataToFile.restype = ctypes.c_bool
    cf.CFURLWriteBookmarkDataToFile.argtypes = [ptr, ptr, ctypes.c_ulong, ptr]

    def url(path):
        raw = os.fsencode(path)
        return cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), path.is_dir())

    data = cf.CFURLCreateBookmarkData(
        None, url(target), SUITABLE_FOR_BOOKMARK_FILE, None, None, None
    )
    assert data
    assert cf.CFURLWriteBookmarkDataToFile(data, url(alias), 0, None)


@pytest.fixture
def linked(root, tmp_path):
    target = tmp_path / "elsewhere" / "real-name"
    (target / ".git").mkdir(parents=True)
    (target / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    make_alias(root / "linked.alias", target)
    return target


def test_an_alias_to_a_folder_is_a_project_under_its_own_name(cfg, linked):
    n = projects.scan(cfg).nodes
    assert n["linked.alias"].path == linked.resolve()
    assert n["linked.alias"].is_repo


def test_other_files_in_the_root_are_not_projects(cfg, root, tmp_path):
    (root / "notes.txt").write_text("just a file\n")
    os.mkfifo(root / "pipe")
    file = tmp_path / "a-file"
    file.write_text("x")
    make_alias(root / "file.alias", file)
    gone = tmp_path / "gone"
    gone.mkdir()
    make_alias(root / "broken.alias", gone)
    gone.rmdir()

    n = projects.scan(cfg).nodes
    assert not {"notes.txt", "pipe", "file.alias", "broken.alias"} & set(n)


def test_an_alias_below_the_top_level_is_not_followed(cfg, root, linked):
    make_alias(root / "shop" / "nested.alias", linked)
    assert "shop/nested.alias" not in projects.scan(cfg).nodes


@pytest.mark.parametrize("via_alias", [True, False])
def test_up_labels_the_workspace_so_the_project_pairs_with_it(herdr, cfg, root, linked, via_alias):
    res = ops.up(herdr, cfg, root / "linked.alias" if via_alias else linked, no_agent=True)
    assert res.label == "linked.alias"
    assert res.path == str(linked.resolve())
    matched = projects.match_workspaces(projects.scan(cfg), herdr.snapshot())
    assert matched["linked.alias"].id == res.workspace


def test_reveal_takes_an_alias_by_label_and_by_path(herdr, cfg, root, linked):
    for target in ("linked.alias", str(root / "linked.alias")):
        res = ops.reveal(herdr, cfg, target, dry_run=True)
        assert res.path == str(linked.resolve())
