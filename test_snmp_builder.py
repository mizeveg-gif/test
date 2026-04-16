"""
Test script for SNMP Command Builder Library
"""

import json
from snmp_command_builder import (
    SNMPCommandBuilder,
    SNMPVersion,
    SecurityLevel,
    AuthProtocol,
    PrivProtocol,
    build_snmp_v2_command,
    build_snmp_v3_command
)


def test_snmp_v2_basic():
    """Test basic SNMP v2c command building."""
    print("=" * 60)
    print("TEST 1: SNMP v2c Basic Configuration")
    print("=" * 60)
    
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="public",
        community_rw="private",
        id_device=1
    )
    
    command = builder.build()
    print(json.dumps(command, indent=2))
    
    # Verify structure
    assert command["ID_DEVICE"] == 1
    assert command["TYPE_COMMANDS"] == "CONFIG_GENERAL_SNMP_UPDATE"
    assert command["DATA"]["snmp_version"] == "v2c"
    assert command["DATA"]["community_ro"] == "public"
    assert command["DATA"]["community_rw"] == "private"
    assert "snmp_groups" in command["DATA"]
    assert "snmp_views" in command["DATA"]
    assert "snmp_access" in command["DATA"]
    assert "TIME" in command
    
    print("\n✓ SNMP v2c basic test passed!\n")


def test_snmp_v3_auth_priv():
    """Test SNMP v3 with authPriv security level."""
    print("=" * 60)
    print("TEST 2: SNMP v3 authPriv Configuration")
    print("=" * 60)
    
    builder = SNMPCommandBuilder.from_v3_config(
        security_name="admin_user",
        security_level=SecurityLevel.AUTH_PRIV,
        id_device=2,
        auth_protocol=AuthProtocol.SHA_256,
        auth_password="auth_secret_123",
        priv_protocol=PrivProtocol.AES_256,
        priv_password="priv_secret_456",
        context_name="network_context"
    )
    
    command = builder.build()
    print(json.dumps(command, indent=2))
    
    # Verify structure
    assert command["ID_DEVICE"] == 2
    assert command["DATA"]["snmp_version"] == "v3"
    assert command["DATA"]["v3_security_name"] == "admin_user"
    assert command["DATA"]["v3_security_level"] == "authPriv"
    assert command["DATA"]["v3_auth_protocol"] == "SHA-256"
    assert command["DATA"]["v3_auth_password"] == "auth_secret_123"
    assert command["DATA"]["v3_priv_protocol"] == "AES-256"
    assert command["DATA"]["v3_priv_password"] == "priv_secret_456"
    assert command["DATA"]["v3_context_name"] == "network_context"
    
    print("\n✓ SNMP v3 authPriv test passed!\n")


def test_snmp_v3_auth_no_priv():
    """Test SNMP v3 with authNoPriv security level."""
    print("=" * 60)
    print("TEST 3: SNMP v3 authNoPriv Configuration")
    print("=" * 60)
    
    command = build_snmp_v3_command(
        security_name="monitor_user",
        security_level=SecurityLevel.AUTH_NO_PRIV,
        id_device=3,
        auth_protocol=AuthProtocol.SHA,
        auth_password="monitor_pass"
    )
    
    print(json.dumps(command, indent=2))
    
    # Verify structure
    assert command["DATA"]["snmp_version"] == "v3"
    assert command["DATA"]["v3_security_name"] == "monitor_user"
    assert command["DATA"]["v3_security_level"] == "authNoPriv"
    assert command["DATA"]["v3_auth_protocol"] == "SHA"
    assert command["DATA"]["v3_priv_protocol"] is None
    
    print("\n✓ SNMP v3 authNoPriv test passed!\n")


def test_snmp_v3_no_auth_no_priv():
    """Test SNMP v3 with noAuthNoPriv security level."""
    print("=" * 60)
    print("TEST 4: SNMP v3 noAuthNoPriv Configuration")
    print("=" * 60)
    
    command = build_snmp_v3_command(
        security_name="guest_user",
        security_level=SecurityLevel.NO_AUTH_NO_PRIV,
        id_device=4
    )
    
    print(json.dumps(command, indent=2))
    
    # Verify structure
    assert command["DATA"]["snmp_version"] == "v3"
    assert command["DATA"]["v3_security_name"] == "guest_user"
    assert command["DATA"]["v3_security_level"] == "noAuthNoPriv"
    assert command["DATA"]["v3_auth_protocol"] is None
    assert command["DATA"]["v3_priv_protocol"] is None
    
    print("\n✓ SNMP v3 noAuthNoPriv test passed!\n")


def test_to_json():
    """Test JSON output method."""
    print("=" * 60)
    print("TEST 5: JSON Output Method")
    print("=" * 60)
    
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="test_public",
        community_rw="test_private",
        id_device=5
    )
    
    json_output = builder.to_json(indent=2)
    print(json_output)
    
    # Verify it's valid JSON
    parsed = json.loads(json_output)
    assert parsed["ID_DEVICE"] == 5
    
    print("\n✓ JSON output test passed!\n")


def test_redis_stream_format():
    """Test Redis stream format output."""
    print("=" * 60)
    print("TEST 6: Redis Stream Format")
    print("=" * 60)
    
    builder = SNMPCommandBuilder.from_v3_config(
        security_name="redis_user",
        security_level=SecurityLevel.AUTH_PRIV,
        id_device=6,
        auth_protocol=AuthProtocol.MD5,
        auth_password="redis_auth",
        priv_protocol=PrivProtocol.AES
    )
    
    stream_name, message = builder.to_redis_stream_format()
    
    print(f"Stream Name: {stream_name}")
    print(f"Message: {json.dumps(message, indent=2)}")
    
    # Verify format
    assert stream_name == "snmp_commands"
    assert "command" in message
    parsed_command = json.loads(message["command"])
    assert parsed_command["ID_DEVICE"] == 6
    
    print("\n✓ Redis stream format test passed!\n")


def test_custom_groups_views_access():
    """Test custom groups, views, and access configuration."""
    print("=" * 60)
    print("TEST 7: Custom Groups, Views, and Access")
    print("=" * 60)
    
    from snmp_command_builder import SNMPGroup, SNMPView, SNMPAccess, AccessRights, ViewType
    
    custom_groups = [
        SNMPGroup(
            group_name="custom_admin",
            access_rights=AccessRights.READ_WRITE,
            views=["custom_full"],
            notify_access=True
        )
    ]
    
    custom_views = [
        SNMPView(
            view_name="custom_full",
            subtree="1.3.6.1.2.1",
            mask="ff",
            type=ViewType.INCLUDED
        )
    ]
    
    custom_access = [
        SNMPAccess(
            group="custom_admin",
            context="custom_context",
            security_level=SecurityLevel.AUTH_PRIV,
            read_view="custom_full",
            write_view="custom_full",
            notify_view="custom_full"
        )
    ]
    
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="custom_public",
        community_rw="custom_private",
        id_device=7,
        snmp_groups=custom_groups,
        snmp_views=custom_views,
        snmp_access=custom_access
    )
    
    command = builder.build()
    print(json.dumps(command, indent=2))
    
    # Verify custom configuration
    assert len(command["DATA"]["snmp_groups"]) == 1
    assert command["DATA"]["snmp_groups"][0]["group_name"] == "custom_admin"
    assert len(command["DATA"]["snmp_views"]) == 1
    assert command["DATA"]["snmp_views"][0]["view_name"] == "custom_full"
    assert len(command["DATA"]["snmp_access"]) == 1
    assert command["DATA"]["snmp_access"][0]["group"] == "custom_admin"
    
    print("\n✓ Custom configuration test passed!\n")


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SNMP COMMAND BUILDER LIBRARY - TEST SUITE")
    print("=" * 60 + "\n")
    
    try:
        test_snmp_v2_basic()
        test_snmp_v3_auth_priv()
        test_snmp_v3_auth_no_priv()
        test_snmp_v3_no_auth_no_priv()
        test_to_json()
        test_redis_stream_format()
        test_custom_groups_views_access()
        
        print("=" * 60)
        print("ALL TESTS PASSED SUCCESSFULLY!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        raise


if __name__ == "__main__":
    run_all_tests()
