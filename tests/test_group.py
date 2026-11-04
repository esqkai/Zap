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


def test_laptop_charger_pairing_and_exclusive_outlet_assignment():
    group = make_group()
    group.assign_charger("laptop", "strip-mac", 2)
    assert group.members["laptop"].charger_assignments["strip-mac"] == 2
    with pytest.raises(GroupError):
        group.assign_charger("pc", "strip-mac", 2)


def test_battery_events_use_assigned_names_and_route_only_to_sudo():
    group = make_group()
    group.rename_strip("strip-mac", "Office Strip")
    group.rename_outlet("strip-mac", 2, "Laptop Charger")
    group.assign_charger("laptop", "strip-mac", 2)
    assert group.notification_recipients() == []
    group.claim_sudo("pc")
    event = group.build_battery_event("laptop", "strip-mac", 24, "charger_on")
    assert event["outlet_name"] == "Laptop Charger"
    assert event["strip_name"] == "Office Strip"
    assert event["recipients"] == ["pc"]
    assert "Arch Laptop battery is at 24%" in event["message"]
    assert "switched on Laptop Charger" in event["message"]


def test_battery_automation_requires_capability_and_assignment():
    group = make_group()
    with pytest.raises(GroupError):
        group.build_battery_event("pc", "strip-mac", 50, "charger_on")
    with pytest.raises(GroupError):
        group.build_battery_event("laptop", "strip-mac", 50, "charger_on")
    group.assign_charger("laptop", "strip-mac", 1)
    with pytest.raises(GroupError):
        group.build_battery_event("laptop", "strip-mac", 101, "charger_on")


def test_notifications_only_go_to_current_sudo_and_can_be_disabled():
    group = make_group()
    group.claim_sudo("pc")
    assert group.notification_recipients() == ["pc"]
    group.set_push_notifications(False, "pc")
    assert group.notification_recipients() == []
    with pytest.raises(GroupError):
        group.set_push_notifications(True, "laptop")
