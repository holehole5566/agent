"""Tests for DM policy."""

from dm_policy import DMPolicy


def test_open_mode_allows_all():
    policy = DMPolicy(mode="open")
    allowed, reply = policy.check("anyone")
    assert allowed is True
    assert reply == ""


def test_allowlist_allows_listed():
    policy = DMPolicy(mode="allowlist", allowlist=["user1", "user2"])
    allowed, _ = policy.check("user1")
    assert allowed is True


def test_allowlist_blocks_unlisted():
    policy = DMPolicy(mode="allowlist", allowlist=["user1"])
    allowed, reply = policy.check("user99")
    assert allowed is False
    assert "allowlist" in reply.lower()


def test_pairing_rejects_without_code():
    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    allowed, reply = policy.check("new_user", "hello")
    assert allowed is False
    assert "pairing code" in reply.lower()


def test_pairing_accepts_correct_code():
    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    allowed, reply = policy.check("new_user", "secret123")
    assert allowed is True
    assert "Paired" in reply


def test_pairing_remembers_paired_user():
    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    policy.check("user1", "secret123")  # pair first

    # Now regular message should work
    allowed, reply = policy.check("user1", "hello")
    assert allowed is True
    assert reply == ""


def test_pairing_allowlist_bypass():
    policy = DMPolicy(mode="pairing", pairing_code="secret", allowlist=["vip"])
    allowed, reply = policy.check("vip", "hello")
    assert allowed is True


def test_unknown_mode():
    policy = DMPolicy(mode="invalid")
    allowed, reply = policy.check("anyone")
    assert allowed is False
    assert "Unknown" in reply
