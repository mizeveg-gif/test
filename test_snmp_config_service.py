"""
Test script for SNMP Config Service

This script tests the SNMP configuration service by sending test commands
to the Redis stream.
"""

import time
import json
from redis_common import (
    RedisSCADAStreams, 
    CommandType
)
from snmp_command_builder import (
    SNMPCommandBuilder,
    SNMPVersion,
    SecurityLevel,
    AuthProtocol,
    PrivProtocol
)


def test_v2c_configuration():
    """Test SNMP v2c configuration."""
    print("\n=== Testing SNMP v2c Configuration ===")
    
    scada = RedisSCADAStreams(host='192.168.3.228', port=6380)
    
    # Create v2c configuration
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="public_test",
        community_rw="private_test",
        id_device=1
    )
    
    command = builder.build()
    print(f"Command to send:\n{json.dumps(command, indent=2)}")
    
    # Send to Redis stream
    msg_id = scada.add_command_simple(
        device_id=command['ID_DEVICE'],
        command_type=CommandType.CONFIG_GENERAL_SNMP_UPDATE,
        data=command['DATA']
    )
    
    print(f"✅ Sent v2c configuration command with ID: {msg_id}")
    return msg_id


def test_v3_auth_no_priv():
    """Test SNMP v3 authNoPriv configuration."""
    print("\n=== Testing SNMP v3 authNoPriv Configuration ===")
    
    scada = RedisSCADAStreams(host='192.168.3.228', port=6380)
    
    # Create v3 configuration with authNoPriv
    builder = SNMPCommandBuilder.from_v3_config(
        security_name="test_user_auth",
        security_level=SecurityLevel.AUTH_NO_PRIV,
        id_device=2,
        auth_protocol=AuthProtocol.SHA_256,
        auth_password="test_auth_password"
    )
    
    command = builder.build()
    print(f"Command to send:\n{json.dumps(command, indent=2)}")
    
    # Send to Redis stream
    msg_id = scada.add_command_simple(
        device_id=command['ID_DEVICE'],
        command_type=CommandType.CONFIG_GENERAL_SNMP_UPDATE,
        data=command['DATA']
    )
    
    print(f"✅ Sent v3 authNoPriv configuration command with ID: {msg_id}")
    return msg_id


def test_v3_auth_priv():
    """Test SNMP v3 authPriv configuration."""
    print("\n=== Testing SNMP v3 authPriv Configuration ===")
    
    scada = RedisSCADAStreams(host='192.168.3.228', port=6380)
    
    # Create v3 configuration with authPriv
    builder = SNMPCommandBuilder.from_v3_config(
        security_name="test_user_secure",
        security_level=SecurityLevel.AUTH_PRIV,
        id_device=3,
        auth_protocol=AuthProtocol.SHA_256,
        auth_password="secure_auth_pass",
        priv_protocol=PrivProtocol.AES_256,
        priv_password="secure_priv_pass",
        context_name="test_context"
    )
    
    command = builder.build()
    print(f"Command to send:\n{json.dumps(command, indent=2)}")
    
    # Send to Redis stream
    msg_id = scada.add_command_simple(
        device_id=command['ID_DEVICE'],
        command_type=CommandType.CONFIG_GENERAL_SNMP_UPDATE,
        data=command['DATA']
    )
    
    print(f"✅ Sent v3 authPriv configuration command with ID: {msg_id}")
    return msg_id


def test_custom_views_and_groups():
    """Test configuration with custom views and groups."""
    print("\n=== Testing Custom Views and Groups ===")
    
    from snmp_command_builder import (
        SNMPGroup,
        SNMPView,
        SNMPAccess,
        AccessRights,
        ViewType,
        SecurityModel
    )
    
    scada = RedisSCADAStreams(host='192.168.3.228', port=6380)
    
    # Define custom groups
    custom_groups = [
        SNMPGroup(
            group_name="custom_admin",
            access_rights=AccessRights.READ_WRITE,
            views=["full_view"],
            security_model=SecurityModel.USM,
            notify_access=True
        ),
        SNMPGroup(
            group_name="custom_monitor",
            access_rights=AccessRights.READ_ONLY,
            views=["system_view"],
            security_model=SecurityModel.USM,
            notify_access=False
        )
    ]
    
    # Define custom views
    custom_views = [
        SNMPView(
            view_name="full_view",
            subtree="1.3.6.1",
            mask="ff",
            type=ViewType.INCLUDED
        ),
        SNMPView(
            view_name="system_view",
            subtree="1.3.6.1.2.1.1",
            mask="ff",
            type=ViewType.INCLUDED
        ),
        SNMPView(
            view_name="system_view",
            subtree="1.3.6.1.2.1.2",
            mask="ff",
            type=ViewType.INCLUDED
        )
    ]
    
    # Define custom access rules
    custom_access = [
        SNMPAccess(
            group="custom_admin",
            context="default",
            security_level=SecurityLevel.AUTH_PRIV,
            read_view="full_view",
            write_view="full_view",
            notify_view="full_view"
        ),
        SNMPAccess(
            group="custom_monitor",
            context="default",
            security_level=SecurityLevel.AUTH_NO_PRIV,
            read_view="system_view",
            write_view="none",
            notify_view="system_view"
        )
    ]
    
    # Create builder with custom configuration
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="custom_public",
        community_rw="custom_private",
        id_device=4,
        snmp_groups=custom_groups,
        snmp_views=custom_views,
        snmp_access=custom_access
    )
    
    command = builder.build()
    print(f"Command to send:\n{json.dumps(command, indent=2)}")
    
    # Send to Redis stream
    msg_id = scada.add_command_simple(
        device_id=command['ID_DEVICE'],
        command_type=CommandType.CONFIG_GENERAL_SNMP_UPDATE,
        data=command['DATA']
    )
    
    print(f"✅ Sent custom configuration command with ID: {msg_id}")
    return msg_id


def main():
    """Run all tests."""
    print("=" * 60)
    print("SNMP Config Service - Test Suite")
    print("=" * 60)
    
    try:
        # Run tests
        test_v2c_configuration()
        time.sleep(1)
        
        test_v3_auth_no_priv()
        time.sleep(1)
        
        test_v3_auth_priv()
        time.sleep(1)
        
        test_custom_views_and_groups()
        
        print("\n" + "=" * 60)
        print("✅ All test commands sent successfully!")
        print("=" * 60)
        print("\nNow start the snmp_config_service.py to process these commands:")
        print("  python snmp_config_service.py")
        print()
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
