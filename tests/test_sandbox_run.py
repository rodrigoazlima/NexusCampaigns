"""Tests for nexus.tasks.sandbox_run.

Covers the pure diff/classify/apply logic and the scope-resolution helpers.
Does not mock a container runtime end-to-end (build/run/extract are thin
subprocess wrappers) - the security-relevant surface is scope resolution,
classification, and the apply-time guard checks, so that's what's covered.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nexus.shared.models import (
    AgentRegistryEntry,
    AgentSharedStateSpec,
    RegistryConfig,
    SandboxConfig,
)
from nexus.shared.interfaces import VaultWriteError
from nexus.tasks import sandbox_run as sr


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestNormalizeStatePath:
    def test_state_prefix_gets_agent_folder(self):
        assert sr._normalize_state_path("vision", "state/processed.json") == "agents/vision/state/processed.json"

    def test_non_state_prefix_passed_through(self):
        assert sr._normalize_state_path("vision", "system/state/shared.json") == "system/state/shared.json"

    def test_strips_whitespace(self):
        assert sr._normalize_state_path("vision", "  state/x.json  ") == "agents/vision/state/x.json"


class TestShouldSkip:
    def test_dockerfile_skipped(self):
        assert sr._should_skip("Dockerfile") is True

    def test_pycache_dir_skipped(self):
        assert sr._should_skip("agents/vision/tools/__pycache__/mod.cpython-311.pyc") is True

    def test_pyc_suffix_skipped(self):
        assert sr._should_skip("agents/vision/tools/mod.pyc") is True

    def test_normal_file_not_skipped(self):
        assert sr._should_skip("agents/vision/state/processed.json") is False


class TestClassify:
    def test_file_under_commit_scope_dir(self):
        cls, reason = sr._classify(
            ".knowledge-base/01-Processing/npc-test.md", [".knowledge-base/01-Processing"], [], []
        )
        assert (cls, reason) == ("knowledge-base", None)

    def test_scope_entry_matches_exact_path_not_just_prefix(self):
        # a scope dir named "01-Processing" must not match "01-Processing-extra"
        cls, reason = sr._classify(
            ".knowledge-base/01-Processing-extra/x.md", [".knowledge-base/01-Processing"], [], []
        )
        assert cls == "other"

    def test_state_allowlist_hit(self):
        cls, reason = sr._classify("agents/vision/state/processed.json", [], ["agents/vision/state/processed.json"], [])
        assert (cls, reason) == ("state", None)

    def test_state_readonly_hit(self):
        cls, reason = sr._classify("agents/lore/state/processed.json", [], [], ["agents/lore/state/processed.json"])
        assert (cls, reason) == ("other", "read-only shared state")

    def test_unclassified_path(self):
        cls, reason = sr._classify("random/file.txt", [".knowledge-base/01-Processing"], [], [])
        assert (cls, reason) == ("other", "outside declared commit_scope/state_files")


class TestMakeDiff:
    def test_text_diff_contains_changed_lines(self):
        binary, diff = sr._make_diff("note.md", b"line1\n", b"line1\nline2\n")
        assert binary is False
        assert "+line2" in diff

    def test_binary_content_short_circuits(self):
        binary, diff = sr._make_diff("image.png", b"\xff\xfe\x00", b"\xff\xfe\x01")
        assert binary is True
        assert diff == ""

    def test_long_diff_gets_truncated(self):
        before = "".join(f"l{i}\n" for i in range(500))
        after = "".join(f"l{i}x\n" for i in range(500))
        _, diff = sr._make_diff("big.md", before.encode(), after.encode())
        assert "truncated" in diff
        assert len(diff.splitlines()) == sr._DIFF_TRUNCATE_LINES + 1


class TestIsLibraryPath:
    def test_exact_library_dir(self):
        assert sr._is_library_path(".knowledge-base/02-Library") is True

    def test_file_inside_library(self):
        assert sr._is_library_path(".knowledge-base/02-Library/npc-villain.md") is True

    def test_processing_not_library(self):
        assert sr._is_library_path(".knowledge-base/01-Processing/npc-villain.md") is False

    def test_similarly_named_dir_is_not_a_prefix_match(self):
        assert sr._is_library_path(".knowledge-base/02-Library-archive/x.md") is False


class TestRewriteLocalhost:
    def test_replaces_localhost(self):
        assert sr._rewrite_localhost("http://localhost:1234/v1", "host.containers.internal") == \
            "http://host.containers.internal:1234/v1"

    def test_replaces_loopback_ip(self):
        assert sr._rewrite_localhost("http://127.0.0.1:1234", "host.docker.internal") == \
            "http://host.docker.internal:1234"


class TestHostGatewayName:
    def test_docker(self):
        assert sr._host_gateway_name("docker") == "host.docker.internal"

    def test_podman(self):
        assert sr._host_gateway_name("podman") == "host.containers.internal"


class TestRelabelNoApply:
    def test_dry_run_relabels_applied_as_would_apply(self):
        changes = [{"status": "applied"}]
        sr._relabel_no_apply(changes, exit_code=0, dry_run=True)
        assert changes[0]["status"] == "would-apply"

    def test_dry_run_relabels_dropped_as_would_drop(self):
        changes = [{"status": "dropped", "reason": "outside scope"}]
        sr._relabel_no_apply(changes, exit_code=0, dry_run=True)
        assert changes[0]["status"] == "would-drop"
        assert changes[0]["reason"] == "outside scope"  # unchanged

    def test_failed_run_drops_previously_applied(self):
        changes = [{"status": "applied"}]
        sr._relabel_no_apply(changes, exit_code=1, dry_run=False)
        assert changes[0]["status"] == "dropped"
        assert "container exited 1" in changes[0]["reason"]

    def test_failed_run_leaves_already_dropped_alone(self):
        changes = [{"status": "dropped", "reason": "outside scope"}]
        sr._relabel_no_apply(changes, exit_code=1, dry_run=False)
        assert changes[0]["reason"] == "outside scope"  # not overwritten


# ---------------------------------------------------------------------------
# Filesystem-parametrized helpers (dirs passed as args, no monkeypatch needed)
# ---------------------------------------------------------------------------

class TestWalkRelpaths:
    def test_missing_root_is_empty(self, tmp_path):
        assert sr._walk_relpaths(tmp_path / "nope") == set()

    def test_skips_dockerfile_and_pycache(self, tmp_path):
        (tmp_path / "Dockerfile").write_text("FROM x")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "m.pyc").write_text("x")
        (tmp_path / "keep.md").write_text("hi")
        assert sr._walk_relpaths(tmp_path) == {"keep.md"}


class TestDiffAndClassify:
    def _mk(self, root, relpath, content):
        p = root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def test_unchanged_file_is_ignored(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, ".knowledge-base/01-Processing/x.md", "same")
        self._mk(after, ".knowledge-base/01-Processing/x.md", "same")
        changes = sr._diff_and_classify(before, after, [".knowledge-base/01-Processing"], [], [], allow_deletes=False)
        assert changes == []

    def test_new_in_scope_file_is_applied(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(after, ".knowledge-base/01-Processing/x.md", "new")
        changes = sr._diff_and_classify(before, after, [".knowledge-base/01-Processing"], [], [], allow_deletes=False)
        assert changes[0]["status"] == "applied"
        assert changes[0]["class"] == "knowledge-base"

    def test_delete_dropped_when_deletes_not_allowed(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, ".knowledge-base/01-Processing/x.md", "old")
        changes = sr._diff_and_classify(before, after, [".knowledge-base/01-Processing"], [], [], allow_deletes=False)
        assert changes[0]["status"] == "dropped"
        assert "delete not enabled" in changes[0]["reason"]

    def test_delete_applied_when_deletes_allowed(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, ".knowledge-base/01-Processing/x.md", "old")
        changes = sr._diff_and_classify(before, after, [".knowledge-base/01-Processing"], [], [], allow_deletes=True)
        assert changes[0]["status"] == "applied"

    def test_state_deletion_never_applied_even_with_allow_deletes(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, "agents/vision/state/processed.json", "{}")
        changes = sr._diff_and_classify(before, after, [], ["agents/vision/state/processed.json"], [], allow_deletes=True)
        assert changes[0]["status"] == "dropped"
        assert "state deletions are never applied" in changes[0]["reason"]

    def test_readonly_shared_state_change_is_dropped(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, "agents/lore/state/processed.json", "{}")
        self._mk(after, "agents/lore/state/processed.json", "{\"x\":1}")
        changes = sr._diff_and_classify(before, after, [], [], ["agents/lore/state/processed.json"], allow_deletes=False)
        assert changes[0]["status"] == "dropped"
        assert changes[0]["reason"] == "read-only shared state"

    def test_out_of_scope_change_is_dropped(self, tmp_path):
        before, after = tmp_path / "before", tmp_path / "after"
        self._mk(before, "random/file.txt", "a")
        self._mk(after, "random/file.txt", "b")
        changes = sr._diff_and_classify(before, after, [".knowledge-base/01-Processing"], [], [], allow_deletes=False)
        assert changes[0]["status"] == "dropped"
        assert changes[0]["reason"] == "outside declared commit_scope/state_files"


# ---------------------------------------------------------------------------
# Staging copy helpers
# ---------------------------------------------------------------------------

class TestCopyScopeDir:
    def test_copies_existing_dir_contents(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_PROJECT_ROOT", tmp_path / "project")
        src = tmp_path / "project" / ".knowledge-base" / "01-Processing"
        src.mkdir(parents=True)
        (src / "note.md").write_text("hi", encoding="utf-8")
        staging = tmp_path / "staging"

        sr._copy_scope_dir(".knowledge-base/01-Processing", staging)

        assert (staging / ".knowledge-base" / "01-Processing" / "note.md").read_text() == "hi"

    def test_missing_dir_creates_empty_placeholder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_PROJECT_ROOT", tmp_path / "project")
        staging = tmp_path / "staging"

        sr._copy_scope_dir(".knowledge-base/01-Processing", staging)

        dst = staging / ".knowledge-base" / "01-Processing"
        assert dst.is_dir()
        assert list(dst.iterdir()) == []


class TestCopyStateFile:
    def test_missing_state_file_is_left_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_PROJECT_ROOT", tmp_path / "project")
        staging = tmp_path / "staging"

        sr._copy_state_file("agents/vision/state/processed.json", staging)

        # must NOT fabricate a directory in its place
        assert not (staging / "agents" / "vision" / "state" / "processed.json").exists()
        assert not (staging / "agents").exists()

    def test_existing_state_file_is_copied(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_PROJECT_ROOT", tmp_path / "project")
        src = tmp_path / "project" / "agents" / "vision" / "state" / "processed.json"
        src.parent.mkdir(parents=True)
        src.write_text("{}", encoding="utf-8")
        staging = tmp_path / "staging"

        sr._copy_state_file("agents/vision/state/processed.json", staging)

        assert (staging / "agents" / "vision" / "state" / "processed.json").read_text() == "{}"


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------

class TestReadDeclaredStateFiles:
    def test_missing_agent_md_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_AGENTS_DIR", tmp_path / "agents")
        assert sr._read_declared_state_files("vision") == []

    def test_parses_and_normalizes_state_files_block(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        monkeypatch.setattr(sr, "_AGENTS_DIR", agents_dir)
        agent_dir = agents_dir / "vision"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "state_files:\n"
            "  - state/processed-images.json\n"
            "  - # state/ignored-comment.json\n"
            "  - system/state/shared.json\n",
            encoding="utf-8",
        )
        assert sr._read_declared_state_files("vision") == [
            "agents/vision/state/processed-images.json",
            "system/state/shared.json",
        ]


class TestResolveScopes:
    def test_combines_commit_scope_and_state_sources(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "vision"
        agent_dir.mkdir(parents=True)
        (agent_dir / "AGENT.md").write_text(
            "state_files:\n  - state/processed.json\n", encoding="utf-8"
        )
        monkeypatch.setattr(sr, "_AGENTS_DIR", agents_dir)
        monkeypatch.setattr(sr, "read_agent_commit_scope", lambda task_id: [".knowledge-base/01-Processing"])

        registry = RegistryConfig(
            vault_root=".knowledge-base",
            agents={
                "vision": AgentRegistryEntry(
                    status="active",
                    shared_state=AgentSharedStateSpec(
                        reads=["agents/lore/state/processed.json"],
                        updates=["system/state/shared-queue.json"],
                    ),
                )
            },
        )
        monkeypatch.setattr(sr, "load_registry", lambda project_root: registry)

        commit_scope, allowlist, readonly = sr._resolve_scopes("vision", "vision-agent")

        assert commit_scope == [".knowledge-base/01-Processing"]
        assert allowlist == ["agents/vision/state/processed.json", "system/state/shared-queue.json"]
        assert readonly == ["agents/lore/state/processed.json"]

    def test_readonly_excludes_anything_already_in_allowlist(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_AGENTS_DIR", tmp_path / "agents")
        monkeypatch.setattr(sr, "read_agent_commit_scope", lambda task_id: [])
        registry = RegistryConfig(
            vault_root=".knowledge-base",
            agents={
                "vision": AgentRegistryEntry(
                    status="active",
                    shared_state=AgentSharedStateSpec(
                        reads=["system/state/shared.json"],
                        updates=["system/state/shared.json"],
                    ),
                )
            },
        )
        monkeypatch.setattr(sr, "load_registry", lambda project_root: registry)

        _, allowlist, readonly = sr._resolve_scopes("vision", "vision-agent")

        assert allowlist == ["system/state/shared.json"]
        assert readonly == []


class TestAllowDeletes:
    def test_override_true_short_circuits(self, monkeypatch):
        monkeypatch.setattr(sr, "load_registry", lambda project_root: (_ for _ in ()).throw(AssertionError("should not be called")))
        assert sr._allow_deletes("vision", True) is True

    def test_override_false_short_circuits(self, monkeypatch):
        monkeypatch.setattr(sr, "load_registry", lambda project_root: (_ for _ in ()).throw(AssertionError("should not be called")))
        assert sr._allow_deletes("vision", False) is False

    def test_registry_sandbox_allow_deletes_true(self, monkeypatch):
        registry = RegistryConfig(
            vault_root=".knowledge-base",
            agents={"vision": AgentRegistryEntry(status="active", sandbox=SandboxConfig(allow_deletes=True))},
        )
        monkeypatch.setattr(sr, "load_registry", lambda project_root: registry)
        assert sr._allow_deletes("vision", None) is True

    def test_no_sandbox_config_defaults_false(self, monkeypatch):
        registry = RegistryConfig(vault_root=".knowledge-base", agents={"vision": AgentRegistryEntry(status="active")})
        monkeypatch.setattr(sr, "load_registry", lambda project_root: registry)
        assert sr._allow_deletes("vision", None) is False

    def test_unknown_agent_defaults_false(self, monkeypatch):
        registry = RegistryConfig(vault_root=".knowledge-base", agents={})
        monkeypatch.setattr(sr, "load_registry", lambda project_root: registry)
        assert sr._allow_deletes("vision", None) is False


class TestAgentJsonDispatchType:
    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "_AGENTS_DIR", tmp_path / "agents")
        assert sr._agent_json_dispatch_type("vision", "vision-agent") is None

    def test_reads_dispatch_type_for_task(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "vision"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.json").write_text(
            json.dumps({"tasks": {"vision-agent": {"dispatch": {"type": "claude-api"}}}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sr, "_AGENTS_DIR", agents_dir)
        assert sr._agent_json_dispatch_type("vision", "vision-agent") == "claude-api"

    def test_malformed_json_returns_none(self, tmp_path, monkeypatch):
        agents_dir = tmp_path / "agents"
        agent_dir = agents_dir / "vision"
        agent_dir.mkdir(parents=True)
        (agent_dir / "agent.json").write_text("{not valid json", encoding="utf-8")
        monkeypatch.setattr(sr, "_AGENTS_DIR", agents_dir)
        assert sr._agent_json_dispatch_type("vision", "vision-agent") is None


# ---------------------------------------------------------------------------
# Apply - the security-relevant surface
# ---------------------------------------------------------------------------

@pytest.fixture
def apply_env(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    vault_root = project_root / ".knowledge-base"
    (vault_root / "02-Library").mkdir(parents=True)
    (vault_root / "01-Processing").mkdir(parents=True)
    monkeypatch.setattr(sr, "_PROJECT_ROOT", project_root)
    monkeypatch.setattr(sr, "_VAULT_ROOT", vault_root)
    monkeypatch.setattr(sr, "_APPLY_LOCK", tmp_path / "sandbox-apply")
    return project_root, vault_root


def _draft_md(fm: dict, body: str = "body") -> str:
    lines = "\n".join(f"{k}: {v}" for k, v in fm.items())
    return f"---\n{lines}\n---\n{body}"


class TestApplyChanges:
    def test_applies_normal_knowledge_base_draft(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        after_dir = tmp_path / "after"
        relpath = ".knowledge-base/01-Processing/npc-test.md"
        (after_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (after_dir / relpath).write_text(_draft_md({"status": "draft", "reviewed": False}), encoding="utf-8")
        changes = [{"path": relpath, "class": "knowledge-base", "status": "applied"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "applied"
        assert (project_root / relpath).read_text(encoding="utf-8").endswith("body")

    def test_blocks_direct_library_write(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        relpath = ".knowledge-base/02-Library/npc-test.md"
        after_dir = tmp_path / "after"
        (after_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (after_dir / relpath).write_text(_draft_md({"status": "draft"}), encoding="utf-8")
        changes = [{"path": relpath, "class": "knowledge-base", "status": "applied"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "dropped"
        assert "02-Library" in changes[0]["reason"]
        assert not (project_root / relpath).exists()

    def test_blocks_self_approved_frontmatter(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        relpath = ".knowledge-base/01-Processing/npc-test.md"
        after_dir = tmp_path / "after"
        (after_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (after_dir / relpath).write_text(_draft_md({"status": "approved", "reviewed": False}), encoding="utf-8")
        changes = [{"path": relpath, "class": "knowledge-base", "status": "applied"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "dropped"
        assert "status" in changes[0]["reason"]
        assert not (project_root / relpath).exists()

    def test_state_class_bypasses_frontmatter_guard(self, tmp_path, apply_env):
        # class == "state" files never go through the knowledge-base guard checks,
        # even if they happen to be markdown with approved-looking frontmatter.
        project_root, vault_root = apply_env
        relpath = "agents/vision/state/processed.md"
        after_dir = tmp_path / "after"
        (after_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (after_dir / relpath).write_text(_draft_md({"status": "approved"}), encoding="utf-8")
        changes = [{"path": relpath, "class": "state", "status": "applied"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "applied"
        assert (project_root / relpath).exists()

    def test_delete_removes_existing_target(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        relpath = ".knowledge-base/01-Processing/npc-old.md"
        target = project_root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("stale", encoding="utf-8")
        after_dir = tmp_path / "after"  # no file here => deletion
        changes = [{"path": relpath, "class": "knowledge-base", "status": "applied"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "applied"
        assert not target.exists()

    def test_non_applied_changes_are_untouched(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        relpath = ".knowledge-base/01-Processing/npc-test.md"
        after_dir = tmp_path / "after"
        (after_dir / relpath).parent.mkdir(parents=True, exist_ok=True)
        (after_dir / relpath).write_text(_draft_md({"status": "draft"}), encoding="utf-8")
        changes = [{"path": relpath, "class": "knowledge-base", "status": "dropped", "reason": "outside scope"}]

        sr._apply_changes(changes, after_dir, MagicMock())

        assert changes[0]["status"] == "dropped"
        assert not (project_root / relpath).exists()

    def test_lock_file_is_released_after_apply(self, tmp_path, apply_env):
        project_root, vault_root = apply_env
        sr._apply_changes([], tmp_path / "after", MagicMock())
        assert not sr._APPLY_LOCK.with_name(sr._APPLY_LOCK.name + ".lock").exists()


# ---------------------------------------------------------------------------
# Container runtime detection
# ---------------------------------------------------------------------------

class TestDetectRuntime:
    def test_preferred_used_when_available(self, monkeypatch):
        monkeypatch.setattr(sr.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert sr._detect_runtime("docker") == "docker"

    def test_falls_back_to_docker_when_podman_missing(self, monkeypatch):
        monkeypatch.setattr(sr.shutil, "which", lambda name: None if name == "podman" else f"/usr/bin/{name}")
        assert sr._detect_runtime(None) == "docker"

    def test_prefers_podman_over_docker(self, monkeypatch):
        monkeypatch.setattr(sr.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert sr._detect_runtime(None) == "podman"

    def test_raises_when_neither_available(self, monkeypatch):
        monkeypatch.setattr(sr.shutil, "which", lambda name: None)
        with pytest.raises(sr.SandboxPreflightError):
            sr._detect_runtime(None)


class TestPreflight:
    def test_ok_when_info_succeeds(self, monkeypatch):
        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: MagicMock(returncode=0, stderr=""))
        sr._preflight("docker")  # must not raise

    def test_raises_when_info_fails(self, monkeypatch):
        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: MagicMock(returncode=1, stderr="daemon not running"))
        with pytest.raises(sr.SandboxPreflightError, match="daemon not running"):
            sr._preflight("docker")


class TestImageExists:
    def test_true_on_zero_exit(self, monkeypatch):
        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: MagicMock(returncode=0))
        assert sr._image_exists("docker", "some-tag") is True

    def test_false_on_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(sr.subprocess, "run", lambda *a, **k: MagicMock(returncode=1))
        assert sr._image_exists("docker", "some-tag") is False


# ---------------------------------------------------------------------------
# Container log forwarding
# ---------------------------------------------------------------------------

class TestForwardContainerLog:
    def test_appends_content_to_master_log(self, tmp_path, monkeypatch):
        master_log = tmp_path / "automation.log"
        monkeypatch.setattr(sr, "_MASTER_LOG", master_log)
        after_dir = tmp_path / "after"
        container_log = after_dir / sr._CONTAINER_MASTER_LOG_REL
        container_log.parent.mkdir(parents=True)
        container_log.write_text("[2026-01-01] --- DONE ---\n", encoding="utf-8")
        master_log.write_text("existing\n", encoding="utf-8")

        sr._forward_container_log(after_dir, MagicMock())

        assert master_log.read_text(encoding="utf-8") == "existing\n[2026-01-01] --- DONE ---\n"

    def test_missing_container_log_is_a_noop(self, tmp_path, monkeypatch):
        master_log = tmp_path / "automation.log"
        master_log.write_text("existing\n", encoding="utf-8")
        monkeypatch.setattr(sr, "_MASTER_LOG", master_log)

        sr._forward_container_log(tmp_path / "after", MagicMock())

        assert master_log.read_text(encoding="utf-8") == "existing\n"

    def test_empty_container_log_is_a_noop(self, tmp_path, monkeypatch):
        master_log = tmp_path / "automation.log"
        monkeypatch.setattr(sr, "_MASTER_LOG", master_log)
        after_dir = tmp_path / "after"
        container_log = after_dir / sr._CONTAINER_MASTER_LOG_REL
        container_log.parent.mkdir(parents=True)
        container_log.write_text("   \n", encoding="utf-8")

        sr._forward_container_log(after_dir, MagicMock())

        assert not master_log.exists()
