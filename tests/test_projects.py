from pathlib import Path

from corral import projects


def test_scan_finds_nested_repos_and_leading_folders(cfg):
    tree = projects.scan(cfg)
    assert tree.tops == ["~", "Archive", "courses", "cSolveWordle", "MCPs", "scratch", "shop"]
    n = tree.nodes
    assert n["shop"].children == ["shop/api", "shop/web-app"]
    assert n["shop"].repos_below == 2
    assert n["shop"].branch == "master"
    assert n["shop/api"].branch == "develop"
    assert n["shop/api"].depth == 1
    assert n["Archive"].is_repo is False
    assert n["Archive/2024"].children == ["Archive/2024/game-jam"]
    assert "shop/notes" not in n  # not a repo, no repos below
    assert n["cSolveWordle"].children == []  # hidden and pruned dirs skipped
    assert tree.ancestors("Archive/2024/game-jam") == ["Archive/2024", "Archive"]


def test_scan_depth_limit(cfg):
    cfg.scan_depth = 1
    n = projects.scan(cfg).nodes
    assert "shop/api" in n
    assert "Archive/2024" not in n  # its repo is at depth 2


def test_label_for(cfg, root, tmp_path):
    assert projects.label_for(root / "courses", root) == "courses"
    assert projects.label_for(root / "shop" / "api", root) == "shop/api"
    assert projects.label_for(tmp_path / "elsewhere", root) == "elsewhere"
    assert projects.label_for(tmp_path / "home", root) == "~"
    assert projects.label_for(tmp_path / "home", tmp_path / "home") == "~"


def test_home_is_listed_first(cfg, home):
    n = projects.scan(cfg).nodes
    assert next(iter(n)) == "~"
    assert n["~"].path == home.resolve()
    assert n["~"].is_home
    assert n["~"].children == []


def test_home_as_root_lists_its_folders_under_tilde(cfg, home):
    (home / "Code").mkdir()
    cfg.root = home
    tree = projects.scan(cfg)
    assert tree.tops == ["~", "Code"]


def test_home_inside_the_root_is_not_listed_twice(cfg, tmp_path):
    cfg.root = tmp_path
    tree = projects.scan(cfg)
    assert "~" not in tree.nodes
    assert "home" in tree.tops


def test_find_workspace_home_by_legacy_basename(herdr, home):
    ws, _, _ = herdr.create_workspace(str(home.resolve()), "home")
    found = projects.find_workspace(herdr.snapshot(), "~", home)
    assert found
    assert found.id == ws


def test_find_workspace_by_label_then_legacy_basename(herdr, root):
    api = root / "shop" / "api"
    ws, _, _ = herdr.create_workspace(str(api.resolve()), "api")  # legacy basename label
    snap = herdr.snapshot()
    found = projects.find_workspace(snap, "shop/api", api)
    assert found
    assert found.id == ws
    assert projects.find_workspace(snap, "shop/web-app", root / "shop/web-app") is None
    # a basename match in a different directory is not the same project
    assert projects.find_workspace(snap, "other/api", Path("/nowhere/api")) is None
    ws2, _, _ = herdr.create_workspace(str(api), "shop/api")
    found = projects.find_workspace(herdr.snapshot(), "shop/api", api)
    assert found
    assert found.id == ws2
