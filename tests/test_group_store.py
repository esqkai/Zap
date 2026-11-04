import pytest

from nxxt_level.group import GroupRegistry, Member, Strip
from nxxt_level.group_store import GroupStore


def sample_group():
    group = GroupRegistry("home")
    group.add_member(Member(
        "laptop-1", "Arch Laptop", "linux",
        capabilities={"battery_monitoring"},
        assigned_outlets={"strip-1": {2}},
        charger_assignments={"strip-1": 2},
    ))
    group.add_member(Member("desktop-1", "Windows PC", "windows"))
    group.add_strip(Strip("strip-1", "Office Strip", {
        1: "Desktop", 2: "Laptop Charger", 3: "Speakers", 4: "Spare",
    }))
    group.set_member_online("laptop-1", True)
    group.set_member_online("desktop-1", True)
    group.claim_sudo("desktop-1")
    group.set_push_notifications(False, "desktop-1")
    return group


def test_round_trip_persists_group_names_capabilities_assignments_and_settings(tmp_path):
    store = GroupStore(str(tmp_path / "state" / "groups.sqlite3"))
    original = sample_group()
    store.save(original)
    loaded = store.load("home")

    assert loaded is not None
    assert loaded.group_id == "home"
    assert loaded.members["laptop-1"].display_name == "Arch Laptop"
    assert loaded.members["laptop-1"].capabilities == {"battery_monitoring"}
    assert loaded.members["laptop-1"].assigned_outlets == {"strip-1": {2}}
    assert loaded.members["laptop-1"].charger_assignments == {"strip-1": 2}
    assert loaded.strips["strip-1"].display_name == "Office Strip"
    assert loaded.strips["strip-1"].outlet_names[2] == "Laptop Charger"
    assert loaded.sudo_member_id == "desktop-1"
    assert loaded.push_notifications_enabled is False


def test_presence_is_not_restored_after_restart(tmp_path):
    store = GroupStore(str(tmp_path / "groups.sqlite3"))
    group = sample_group()
    store.save(group)
    loaded = store.load("home")
    assert loaded is not None
    assert all(not member.online for member in loaded.members.values())


def test_unknown_group_returns_none(tmp_path):
    store = GroupStore(str(tmp_path / "groups.sqlite3"))
    assert store.load("missing") is None


def test_delete_group(tmp_path):
    store = GroupStore(str(tmp_path / "groups.sqlite3"))
    store.save(sample_group())
    assert store.delete("home")
    assert store.load("home") is None
    assert not store.delete("home")
