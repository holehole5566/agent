"""Tests for DM policy."""

from dm_policy import DMPolicy, ALLOWLIST_FILE


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


def test_pairing_accepts_correct_code(tmp_path, monkeypatch):
    import dm_policy
    monkeypatch.setattr(dm_policy, "ALLOWLIST_FILE", tmp_path / "allowlist.json")

    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    allowed, reply = policy.check("new_user", "secret123")
    assert allowed is True
    assert "Paired" in reply


def test_pairing_persists_to_allowlist(tmp_path, monkeypatch):
    import dm_policy
    allowlist_path = tmp_path / "allowlist.json"
    monkeypatch.setattr(dm_policy, "ALLOWLIST_FILE", allowlist_path)

    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    policy.check("user1", "secret123")

    # User should be in the allowlist now
    assert "user1" in policy.allowlist

    # File should exist on disk
    assert allowlist_path.exists()

    # New policy instance should load the saved allowlist
    policy2 = DMPolicy(mode="pairing", pairing_code="secret123")
    # Need to patch the load path too
    monkeypatch.setattr(dm_policy, "ALLOWLIST_FILE", allowlist_path)
    policy2._load_allowlist()
    assert "user1" in policy2.allowlist


def test_pairing_remembers_paired_user(tmp_path, monkeypatch):
    import dm_policy
    monkeypatch.setattr(dm_policy, "ALLOWLIST_FILE", tmp_path / "allowlist.json")

    policy = DMPolicy(mode="pairing", pairing_code="secret123")
    policy.check("user1", "secret123")  # pair first

    # Now regular message should work (user is on allowlist)
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


def test_pairing_auto_generates_code():
    policy = DMPolicy(mode="pairing", pairing_code="")
    assert len(policy.pairing_code) == 8
    assert policy.pairing_code != ""


def test_pairing_keeps_explicit_code():
    policy = DMPolicy(mode="pairing", pairing_code="mycode")
    assert policy.pairing_code == "mycode"
