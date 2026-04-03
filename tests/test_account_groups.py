"""
Unit tests for Phase 10 Feature C — Account Groups.

Covers: AccountGroup model, AccountGroupRepository, AccountGroupService.
"""
import sqlite3
import unittest
from datetime import datetime, timezone

from oh.db.migrations import run_migrations
from oh.models.account_group import AccountGroup, GroupMembership, GroupSummary
from oh.repositories.account_group_repo import AccountGroupRepository
from oh.services.account_group_service import AccountGroupService


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed_accounts(conn, count=3):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO oh_devices (device_id, device_name, first_discovered_at, last_synced_at) "
        "VALUES (?, ?, ?, ?)",
        ("dev-001", "Phone1", now, now),
    )
    ids = []
    for i in range(count):
        cursor = conn.execute(
            "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
            "VALUES (?, ?, ?, ?)",
            ("dev-001", f"user{i}", now, now),
        )
        ids.append(cursor.lastrowid)
    conn.commit()
    return ids


# -----------------------------------------------------------------------
# Model tests
# -----------------------------------------------------------------------

class TestAccountGroupModel(unittest.TestCase):
    def test_create_group(self):
        g = AccountGroup(name="Client A", color="#FF0000")
        self.assertEqual(g.name, "Client A")
        self.assertEqual(g.color, "#FF0000")
        self.assertEqual(g.member_count, 0)
        self.assertIsNone(g.id)

    def test_default_color(self):
        g = AccountGroup(name="Test")
        self.assertEqual(g.color, "#5B8DEF")

    def test_group_summary(self):
        g = AccountGroup(name="Test", id=1)
        s = GroupSummary(group=g, total_accounts=10, active_accounts=8, avg_health=72.5)
        self.assertEqual(s.total_accounts, 10)
        self.assertEqual(s.avg_health, 72.5)


# -----------------------------------------------------------------------
# Repository tests
# -----------------------------------------------------------------------

class TestAccountGroupRepo(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.repo = AccountGroupRepository(self.conn)
        self.account_ids = _seed_accounts(self.conn, 5)

    def tearDown(self):
        self.conn.close()

    def test_create_group(self):
        g = self.repo.create_group("Client A", "#FF0000", "First client")
        self.assertIsNotNone(g.id)
        self.assertEqual(g.name, "Client A")
        self.assertEqual(g.color, "#FF0000")

    def test_get_all_groups(self):
        self.repo.create_group("Group 1")
        self.repo.create_group("Group 2")
        groups = self.repo.get_all_groups()
        self.assertEqual(len(groups), 2)

    def test_update_group(self):
        g = self.repo.create_group("Old Name")
        self.repo.update_group(g.id, "New Name", "#00FF00", "Updated")
        updated = self.repo.get_group(g.id)
        self.assertEqual(updated.name, "New Name")
        self.assertEqual(updated.color, "#00FF00")

    def test_delete_group(self):
        g = self.repo.create_group("To Delete")
        self.repo.delete_group(g.id)
        self.assertIsNone(self.repo.get_group(g.id))

    def test_unique_name(self):
        self.repo.create_group("Unique")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.create_group("Unique")

    def test_add_members(self):
        g = self.repo.create_group("Test Group")
        added = self.repo.add_members(g.id, self.account_ids[:3])
        self.assertEqual(added, 3)

        members = self.repo.get_members(g.id)
        self.assertEqual(len(members), 3)

    def test_add_duplicate_member(self):
        g = self.repo.create_group("Test Group")
        self.repo.add_members(g.id, [self.account_ids[0]])
        # Adding same member again should not fail
        added = self.repo.add_members(g.id, [self.account_ids[0]])
        members = self.repo.get_members(g.id)
        self.assertEqual(len(members), 1)

    def test_remove_members(self):
        g = self.repo.create_group("Test Group")
        self.repo.add_members(g.id, self.account_ids[:3])
        removed = self.repo.remove_members(g.id, self.account_ids[:2])
        self.assertEqual(removed, 2)

        members = self.repo.get_members(g.id)
        self.assertEqual(len(members), 1)

    def test_get_groups_for_account(self):
        g1 = self.repo.create_group("Group 1")
        g2 = self.repo.create_group("Group 2")
        self.repo.add_members(g1.id, [self.account_ids[0]])
        self.repo.add_members(g2.id, [self.account_ids[0]])

        groups = self.repo.get_groups_for_account(self.account_ids[0])
        self.assertEqual(len(groups), 2)

    def test_get_membership_map(self):
        g1 = self.repo.create_group("Group 1")
        g2 = self.repo.create_group("Group 2")
        self.repo.add_members(g1.id, [self.account_ids[0], self.account_ids[1]])
        self.repo.add_members(g2.id, [self.account_ids[1]])

        mmap = self.repo.get_membership_map()
        self.assertIn(self.account_ids[0], mmap)
        self.assertIn(self.account_ids[1], mmap)
        self.assertEqual(len(mmap[self.account_ids[0]]), 1)
        self.assertEqual(len(mmap[self.account_ids[1]]), 2)
        self.assertNotIn(self.account_ids[2], mmap)

    def test_member_count_in_get_all(self):
        g = self.repo.create_group("Counted")
        self.repo.add_members(g.id, self.account_ids[:4])
        groups = self.repo.get_all_groups()
        self.assertEqual(groups[0].member_count, 4)

    def test_cascade_delete(self):
        g = self.repo.create_group("Cascade")
        self.repo.add_members(g.id, self.account_ids[:3])
        self.repo.delete_group(g.id)

        # Members should be gone too
        rows = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM account_group_members WHERE group_id = ?",
            (g.id,),
        ).fetchone()
        self.assertEqual(rows["cnt"], 0)

    def test_get_group_not_found(self):
        result = self.repo.get_group(99999)
        self.assertIsNone(result)


# -----------------------------------------------------------------------
# Service tests
# -----------------------------------------------------------------------

class TestAccountGroupService(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.repo = AccountGroupRepository(self.conn)
        self.service = AccountGroupService(self.repo)
        self.account_ids = _seed_accounts(self.conn, 3)

    def tearDown(self):
        self.conn.close()

    def test_create_and_list(self):
        self.service.create_group("Service Group", "#AABB00")
        groups = self.service.get_all_groups()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].name, "Service Group")

    def test_assign_and_unassign(self):
        g = self.service.create_group("Test")
        added = self.service.assign_accounts(g.id, self.account_ids)
        self.assertEqual(added, 3)

        removed = self.service.unassign_accounts(g.id, self.account_ids[:1])
        self.assertEqual(removed, 1)

        members = self.service.get_members(g.id)
        self.assertEqual(len(members), 2)

    def test_get_group(self):
        g = self.service.create_group("Find Me")
        found = self.service.get_group(g.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "Find Me")

    def test_delete_group(self):
        g = self.service.create_group("Delete Me")
        self.service.delete_group(g.id)
        groups = self.service.get_all_groups()
        self.assertEqual(len(groups), 0)


if __name__ == "__main__":
    unittest.main()
