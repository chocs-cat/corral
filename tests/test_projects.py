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


def test_match_workspaces_pairs_projects_as_ls_does(cfg, herdr, root, tmp_path):
    api = root / "shop" / "api"
    ws, _, _ = herdr.create_workspace(str(api), "shop/api")
    legacy, _, _ = herdr.create_workspace(str(root / "shop" / "web-app"), "web-app")
    herdr.create_workspace(str(tmp_path), "unrelated")
    matched = projects.match_workspaces(projects.scan(cfg), herdr.snapshot())
    assert {rel: w.id for rel, w in matched.items()} == {"shop/api": ws, "shop/web-app": legacy}


def test_match_workspaces_finds_a_legacy_label_by_its_pane(cfg, herdr, root):
    api = root / "shop" / "api"
    ws, _, _ = herdr.create_workspace(str(api.resolve()), "api")
    matched = projects.match_workspaces(projects.scan(cfg), herdr.snapshot())
    assert {rel: w.id for rel, w in matched.items()} == {"shop/api": ws}


def _plain_folders(root: Path) -> None:
    """Plain folders around the fixture's repos (DEC-24): nested in plain
    top-level folders, inside a repo, pruned and hidden."""
    for rel in (
        "scratch/drafts/2025",
        "Archive/notes",
        "shop/services/notes",
        "shop/api/src",
        "Archive/2024/game-jam/src",
        "scratch/node_modules/x",
        "scratch/.cache",
    ):
        (root / rel).mkdir(parents=True)


PLAIN = ["scratch/drafts", "scratch/drafts/2025", "Archive/notes", "shop/services/notes"]


def test_plain_nested_folders_stay_hidden_by_default(cfg, root):
    _plain_folders(root)
    n = projects.scan(cfg).nodes
    for rel in PLAIN:
        assert rel not in n
    assert n["scratch"].children == []


def test_nested_folders_lists_plain_folders_with_no_repo_above(cfg, root):
    _plain_folders(root)
    cfg.nested_folders = True
    n = projects.scan(cfg).nodes
    drafts = n["scratch/drafts"]
    assert (drafts.depth, drafts.parent, drafts.is_repo, drafts.branch) == (1, "scratch", False, "")
    assert drafts.children == ["scratch/drafts/2025"]
    assert n["scratch/drafts/2025"].depth == 2
    assert n["scratch"].children == ["scratch/drafts"]
    assert n["scratch"].repos_below == 0
    assert n["Archive/notes"].parent == "Archive"
    assert n["Archive"].children == ["Archive/2024", "Archive/notes"]
    # a repo above: shop is one, so nothing plain below it is listed
    assert "Archive/2024/game-jam/src" not in n  # below a nested repo
    for rel in ("shop/notes", "shop/services", "shop/services/notes", "shop/api/src"):
        assert rel not in n
    for rel in ("scratch/node_modules", "scratch/node_modules/x", "scratch/.cache"):
        assert rel not in n  # pruned and hidden folders stay skipped
    assert "cSolveWordle/node_modules" not in n
    assert "Archive/2024/game-jam" in n
    assert n["shop"].children == ["shop/api", "shop/web-app"]


def test_nested_folders_stops_at_the_scan_depth(cfg, root):
    _plain_folders(root)
    cfg.nested_folders = True
    cfg.scan_depth = 1
    n = projects.scan(cfg).nodes
    assert "scratch/drafts" in n
    assert "scratch/drafts/2025" not in n
