"""Tests for shared.vault_guard.VaultGuard."""

import pytest
from pathlib import Path

from nexus.shared.config import VaultPaths
from nexus.shared.vault_guard import VaultGuard, _is_under
from nexus.shared.interfaces import VaultWriteError


@pytest.fixture
def vault_root(tmp_path):
    kb = tmp_path / ".knowledge-base"
    (kb / "00-Inbox").mkdir(parents=True)
    (kb / "01-Processing").mkdir(parents=True)
    (kb / "02-Library").mkdir(parents=True)
    return kb


@pytest.fixture
def guard(vault_root):
    return VaultGuard(VaultPaths(vault_root=vault_root))


class TestVaultGuardAssertWritable:
    def test_processing_is_allowed(self, guard, vault_root):
        target = vault_root / "01-Processing" / "npc-test.md"
        guard.assert_writable(target)  # must not raise

    def test_campaigns_is_allowed(self, guard, vault_root):
        target = vault_root / "03-Campaigns" / "session-01.md"
        guard.assert_writable(target)  # must not raise

    def test_library_raises(self, guard, vault_root):
        target = vault_root / "02-Library" / "npc-villain.md"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_library_subdirectory_raises(self, guard, vault_root):
        target = vault_root / "02-Library" / "npcs" / "villain.md"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_inbox_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "newfile.txt"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_inbox_images_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "images" / "portrait.png"
        with pytest.raises(VaultWriteError):
            guard.assert_writable(target)

    def test_error_message_mentions_path(self, guard, vault_root):
        target = vault_root / "02-Library" / "test.md"
        try:
            guard.assert_writable(target)
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "02-Library" in str(e)


class TestVaultGuardAssertNotInboxDelete:
    def test_inbox_file_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "original.pdf"
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(target)

    def test_inbox_images_raises(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "images" / "portrait.jpg"
        with pytest.raises(VaultWriteError):
            guard.assert_not_inbox_delete(target)

    def test_processing_is_allowed(self, guard, vault_root):
        target = vault_root / "01-Processing" / "draft.md"
        guard.assert_not_inbox_delete(target)  # must not raise

    def test_library_is_allowed(self, guard, vault_root):
        target = vault_root / "02-Library" / "entity.md"
        guard.assert_not_inbox_delete(target)  # must not raise

    def test_error_message_mentions_inbox(self, guard, vault_root):
        target = vault_root / "00-Inbox" / "doc.txt"
        try:
            guard.assert_not_inbox_delete(target)
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "00-Inbox" in str(e)


class TestIsUnderHelper:
    def test_direct_child(self, tmp_path):
        assert _is_under(tmp_path / "child.txt", tmp_path) is True

    def test_nested_child(self, tmp_path):
        assert _is_under(tmp_path / "a" / "b" / "c.txt", tmp_path) is True

    def test_sibling_not_under(self, tmp_path):
        parent = tmp_path / "parent"
        sibling = tmp_path / "sibling" / "file.txt"
        assert _is_under(sibling, parent) is False

    def test_same_path_is_under(self, tmp_path):
        assert _is_under(tmp_path, tmp_path) is True

    def test_parent_not_under_child(self, tmp_path):
        child = tmp_path / "child"
        assert _is_under(tmp_path, child) is False


class TestVaultGuardAssertNotSelfApproved:
    def test_reviewed_true_raises(self, guard):
        with pytest.raises(VaultWriteError, match="reviewed"):
            guard.assert_not_self_approved({"reviewed": True, "status": "draft"})

    def test_status_approved_raises(self, guard):
        with pytest.raises(VaultWriteError, match="status"):
            guard.assert_not_self_approved({"reviewed": False, "status": "approved"})

    def test_both_forbidden_raises_on_first(self, guard):
        with pytest.raises(VaultWriteError):
            guard.assert_not_self_approved({"reviewed": True, "status": "approved"})

    def test_draft_status_is_allowed(self, guard):
        guard.assert_not_self_approved({"reviewed": False, "status": "draft"})

    def test_review_status_is_allowed(self, guard):
        guard.assert_not_self_approved({"reviewed": False, "status": "review"})

    def test_reviewed_false_is_allowed(self, guard):
        guard.assert_not_self_approved({"reviewed": False})

    def test_missing_fields_is_allowed(self, guard):
        guard.assert_not_self_approved({})

    def test_error_message_contains_field_name(self, guard):
        try:
            guard.assert_not_self_approved({"reviewed": True})
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "reviewed" in str(e)

    def test_error_message_contains_approved_value(self, guard):
        try:
            guard.assert_not_self_approved({"status": "approved"})
            pytest.fail("Expected VaultWriteError")
        except VaultWriteError as e:
            assert "approved" in str(e)


class TestVaultWriteErrorIsPermissionError:
    def test_subclass(self):
        exc = VaultWriteError("test")
        assert isinstance(exc, PermissionError)
