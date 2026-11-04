import pytest

from nxxt_level.group import GroupError, GroupRegistry, Member, Strip


def make_group():
    group = GroupRegistry("home")
    group.add_member(Member("pc", "Windows PC", "windows"))
    group.add_member(Member("laptop", "Arch Laptop", "linux",
                            capabilities={"battery_monitoring"}))
    group.set_member_online("pc", True)
    group.set_member_online("laptop", True)
    group.add_strip(Strip("strip-mac", "Living Room Strip"))
    return group


def test_sudo_is_manual_and_never_auto_nominated():
    group = make_group()
    assert group.sudo_member_id is None
    group.claim_sudo("laptop")
    assert group.sudo_member_id == "laptop"
    group.release_sudo("laptop")
    assert group.sudo_member_id is None
    assert group.members["pc"].online


def test_only_one_member_can_hold_sudo():
    group = make_group()
    group.claim_sudo("pc")
    with pytest.raises(GroupError):
        group.claim_sudo("laptop")


def test_offline_member_cannot_claim_sudo():
    group = make_group()
    group.set_member_online("laptop", False)
    with pytest.raises(GroupError):
        group.claim_sudo("laptop")


def test_sudo_must_release_before_member_removal():
    group = make_group()
    group.claim_sudo("pc")
    with pytest.raises(GroupError):
        group.remove_member("pc")
    group.release_sudo("pc")
    group.remove_member("pc")


def test_endpoint_controls_only_assigned_outlets():
    group = make_group()
    group.members["laptop"].assigned_outlets["strip-mac"] = {2}
    assert group.can_control_outlet("laptop", "strip-mac", 2)
    assert not group.can_control_outlet("laptop", "strip-mac", 1)
    group.claim_sudo("laptop")
    assert group.can_control_outlet("laptop", "strip-mac", 1)


def test_strip_and_outlet_names_are_group_shared():
    group = make_group()
    group.rename_strip("strip-mac", "Office Strip")
    group.rename_outlet("strip-mac", 2, "Laptop Charger")
    strip = group.strips["strip-mac"]
    assert strip.display_name == "Office Strip"
    assert strip.outlet_names[2] == "Laptop Charger"
    assert strip.outlet_names[1] == "Outlet 1"


def test_outlet_names_validate_channel_and_length():
    group = make_group()
    with pytest.raises(GroupError):
        group.rename_outlet("strip-mac", 5, "Invalid")
    with pytest.raises(GroupError):
        group.rename_outlet("strip-mac", 1, " ")


def test_battery_capability_is_optional():
    group = make_group()
    assert "battery_monitoring" not in group.members["pc"].capabilities
    assert "battery_monitoring" in group.members["laptop"].capabilities
