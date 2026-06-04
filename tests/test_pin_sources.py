"""Tests for git-aware source pinning."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from reasons_lib.network import Network
from reasons_lib.check_stale import (
    check_stale,
    get_file_commit_sha,
    file_changed_since,
    hash_file,
    pin_source_url,
    pin_sources,
    pin_update,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a temp git repo with one committed file."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=tmp_path, capture_output=True, check=True)
    f = tmp_path / "source.md"
    f.write_text("initial content")
    subprocess.run(["git", "add", "source.md"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


def _get_head_sha(repo_path):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_path,
        capture_output=True, text=True,
    )
    return result.stdout.strip()


def _commit_change(repo_path, filename, content, message="change"):
    (repo_path / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo_path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, capture_output=True, check=True)


class TestGetFileCommitSha:
    def test_returns_sha_for_tracked_file(self, git_repo):
        sha = get_file_commit_sha(git_repo / "source.md")
        assert sha is not None
        assert len(sha) == 40

    def test_returns_none_for_untracked_file(self, git_repo):
        (git_repo / "untracked.md").write_text("hello")
        sha = get_file_commit_sha(git_repo / "untracked.md")
        assert sha is None

    def test_returns_none_outside_git(self, tmp_path):
        f = tmp_path / "file.md"
        f.write_text("hello")
        sha = get_file_commit_sha(f)
        assert sha is None

    def test_sha_changes_after_commit(self, git_repo):
        sha1 = get_file_commit_sha(git_repo / "source.md")
        _commit_change(git_repo, "source.md", "changed content")
        sha2 = get_file_commit_sha(git_repo / "source.md")
        assert sha1 != sha2


class TestFileChangedSince:
    def test_no_change_since_head(self, git_repo):
        sha = _get_head_sha(git_repo)
        assert not file_changed_since(git_repo / "source.md", sha)

    def test_detects_change(self, git_repo):
        sha = _get_head_sha(git_repo)
        _commit_change(git_repo, "source.md", "new content")
        assert file_changed_since(git_repo / "source.md", sha)

    def test_ignores_changes_to_other_files(self, git_repo):
        sha = _get_head_sha(git_repo)
        _commit_change(git_repo, "other.md", "other content")
        assert not file_changed_since(git_repo / "source.md", sha)


class TestPinSourceUrl:
    def test_rewrites_branch_url(self):
        url = "https://github.com/owner/repo/blob/main/path/to/file.py"
        sha = "abc123def456" * 3 + "abcd"
        result = pin_source_url(url, sha)
        assert result == f"https://github.com/owner/repo/blob/{sha}/path/to/file.py"

    def test_preserves_non_github_url(self):
        url = "https://example.com/docs/file.md"
        result = pin_source_url(url, "abc123")
        assert result == url

    def test_rewrites_any_branch(self):
        url = "https://github.com/owner/repo/blob/feature-branch/src/main.py"
        sha = "a" * 40
        result = pin_source_url(url, sha)
        assert f"/blob/{sha}/src/main.py" in result


class TestPinSources:
    def test_pins_node_with_source(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="")
        results = pin_sources(net, db_dir=git_repo)
        assert len(results) == 1
        assert results[0]["node_id"] == "belief-1"
        assert len(results[0]["pinned_sha"]) == 40
        assert results[0]["was_empty"] is True
        node = net.nodes["belief-1"]
        assert node.metadata["pinned_sha"] == results[0]["pinned_sha"]
        assert "verified_at" in node.metadata

    def test_backfills_source_hash(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="")
        pin_sources(net, db_dir=git_repo)
        assert net.nodes["belief-1"].source_hash != ""

    def test_skips_already_pinned(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="")
        net.nodes["belief-1"].metadata["pinned_sha"] = "existing"
        results = pin_sources(net, db_dir=git_repo)
        assert len(results) == 0

    def test_force_re_pins(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="")
        net.nodes["belief-1"].metadata["pinned_sha"] = "old-sha"
        results = pin_sources(net, db_dir=git_repo, force=True)
        assert len(results) == 1
        assert results[0]["was_empty"] is False

    def test_skips_out_nodes(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="")
        net.nodes["belief-1"].truth_value = "OUT"
        results = pin_sources(net, db_dir=git_repo)
        assert len(results) == 0

    def test_skips_nodes_without_source(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief")
        results = pin_sources(net, db_dir=git_repo)
        assert len(results) == 0

    def test_skips_nonexistent_source(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="nonexistent.md", source_hash="")
        results = pin_sources(net, db_dir=git_repo)
        assert len(results) == 0

    def test_pin_urls_rewrites_source_url(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="",
                      source_url="https://github.com/owner/repo/blob/main/source.md")
        results = pin_sources(net, db_dir=git_repo, pin_urls=True)
        assert len(results) == 1
        sha = results[0]["pinned_sha"]
        assert f"/blob/{sha}/source.md" in net.nodes["belief-1"].source_url


class TestPinUpdate:
    def test_updates_pinned_sha(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md",
                      source_hash=hash_file(git_repo / "source.md"))
        net.nodes["belief-1"].metadata["pinned_sha"] = "old" * 10
        results = pin_update(net, ["belief-1"], db_dir=git_repo)
        assert len(results) == 1
        assert "error" not in results[0]
        assert results[0]["old_sha"] == "old" * 10
        assert len(results[0]["new_sha"]) == 40
        assert net.nodes["belief-1"].metadata["pinned_sha"] == results[0]["new_sha"]

    def test_error_on_missing_node(self, git_repo):
        net = Network()
        results = pin_update(net, ["nonexistent"], db_dir=git_repo)
        assert results[0]["error"] == "not found"

    def test_error_on_no_source(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief")
        results = pin_update(net, ["belief-1"], db_dir=git_repo)
        assert results[0]["error"] == "no source"

    def test_error_on_source_not_found(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief", source="gone.md")
        results = pin_update(net, ["belief-1"], db_dir=git_repo)
        assert results[0]["error"] == "source not found"

    def test_refreshes_source_hash(self, git_repo):
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash="stale-hash")
        results = pin_update(net, ["belief-1"], db_dir=git_repo)
        expected_hash = hash_file(git_repo / "source.md")
        assert net.nodes["belief-1"].source_hash == expected_hash


class TestCheckStaleGitAware:
    def test_fresh_when_no_commits_since_pin(self, git_repo):
        sha = _get_head_sha(git_repo)
        content_hash = hash_file(git_repo / "source.md")
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash=content_hash)
        net.nodes["belief-1"].metadata["pinned_sha"] = sha
        results, upgraded = check_stale(net, db_dir=git_repo, git_aware=True)
        assert len(results) == 0

    def test_stale_when_content_changed(self, git_repo):
        sha = _get_head_sha(git_repo)
        content_hash = hash_file(git_repo / "source.md")
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash=content_hash)
        net.nodes["belief-1"].metadata["pinned_sha"] = sha
        _commit_change(git_repo, "source.md", "changed content")
        results, upgraded = check_stale(net, db_dir=git_repo, git_aware=True)
        assert len(results) == 1
        assert results[0]["reason"] == "content_changed"

    def test_auto_bumps_sha_when_content_unchanged(self, git_repo):
        sha = _get_head_sha(git_repo)
        content_hash = hash_file(git_repo / "source.md")
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash=content_hash)
        net.nodes["belief-1"].metadata["pinned_sha"] = sha
        # Change file, commit, then revert to original
        _commit_change(git_repo, "source.md", "temporary change")
        _commit_change(git_repo, "source.md", "initial content")
        new_head = _get_head_sha(git_repo)
        results, upgraded = check_stale(net, db_dir=git_repo, git_aware=True)
        assert len(results) == 0
        assert upgraded == 1
        assert net.nodes["belief-1"].metadata["pinned_sha"] == new_head

    def test_falls_back_to_hash_without_pinned_sha(self, git_repo):
        content_hash = hash_file(git_repo / "source.md")
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash=content_hash)
        _commit_change(git_repo, "source.md", "changed content")
        results, upgraded = check_stale(net, db_dir=git_repo, git_aware=True)
        assert len(results) == 1
        assert results[0]["reason"] == "content_changed"

    def test_git_false_ignores_pinned_sha(self, git_repo):
        sha = _get_head_sha(git_repo)
        content_hash = hash_file(git_repo / "source.md")
        net = Network()
        net.add_node("belief-1", "Test belief",
                      source="source.md", source_hash=content_hash)
        net.nodes["belief-1"].metadata["pinned_sha"] = sha
        results, upgraded = check_stale(net, db_dir=git_repo, git_aware=False)
        assert len(results) == 0
