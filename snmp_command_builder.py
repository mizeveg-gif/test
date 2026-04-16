"""
SNMP Command Builder Library

This library builds SNMP configuration commands for Redis stream output.
Supports SNMP v2c and v3 configurations.
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from dataclasses import dataclass, field, asdict
from enum import Enum


class SNMPVersion(str, Enum):
    """SNMP version enumeration."""
    V2C = "v2c"
    V3 = "v3"


class SecurityLevel(str, Enum):
    """SNMP v3 security levels."""
    NO_AUTH_NO_PRIV = "noAuthNoPriv"
    AUTH_NO_PRIV = "authNoPriv"
    AUTH_PRIV = "authPriv"


class AuthProtocol(str, Enum):
    """SNMP v3 authentication protocols."""
    MD5 = "MD5"
    SHA = "SHA"
    SHA_224 = "SHA-224"
    SHA_256 = "SHA-256"
    SHA_384 = "SHA-384"
    SHA_512 = "SHA-512"


class PrivProtocol(str, Enum):
    """SNMP v3 privacy protocols."""
    DES = "DES"
    AES = "AES"
    AES_128 = "AES-128"
    AES_192 = "AES-192"
    AES_256 = "AES-256"


class AccessRights(str, Enum):
    """Access rights for SNMP groups."""
    READ_ONLY = "read-only"
    READ_WRITE = "read-write"


class SecurityModel(str, Enum):
    """Security model for SNMP groups."""
    USM = "usm"


class ViewType(str, Enum):
    """View type enumeration."""
    INCLUDED = "included"
    EXCLUDED = "excluded"


@dataclass
class SNMPGroup:
    """SNMP group configuration."""
    group_name: str
    access_rights: AccessRights
    views: List[str]
    security_model: SecurityModel = SecurityModel.USM
    notify_access: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_name": self.group_name,
            "access_rights": self.access_rights.value,
            "views": self.views,
            "security_model": self.security_model.value,
            "notify_access": self.notify_access
        }


@dataclass
class SNMPView:
    """SNMP view configuration."""
    view_name: str
    subtree: str
    mask: str = "ff"
    type: ViewType = ViewType.INCLUDED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "view_name": self.view_name,
            "subtree": self.subtree,
            "mask": self.mask,
            "type": self.type.value
        }


@dataclass
class SNMPAccess:
    """SNMP access configuration."""
    group: str
    context: str
    security_level: SecurityLevel
    read_view: str
    write_view: str
    notify_view: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group": self.group,
            "context": self.context,
            "security_level": self.security_level.value,
            "read_view": self.read_view,
            "write_view": self.write_view,
            "notify_view": self.notify_view
        }


@dataclass
class SNMPv2Config:
    """SNMP v2c configuration parameters."""
    community_ro: str
    community_rw: str


@dataclass
class SNMPv3Config:
    """SNMP v3 configuration parameters."""
    security_name: str
    security_level: SecurityLevel
    auth_protocol: Optional[AuthProtocol] = None
    auth_password: Optional[str] = None
    priv_protocol: Optional[PrivProtocol] = None
    priv_password: Optional[str] = None
    context_name: Optional[str] = None


@dataclass
class SNMPCommandBuilder:
    """
    Builder for SNMP configuration commands.
    
    This class takes SNMP v2c or v3 configuration parameters and builds
    a command structure suitable for sending via Redis stream.
    """
    id_device: int = 0
    snmp_version: SNMPVersion = SNMPVersion.V2C
    
    # v2c specific
    community_ro: Optional[str] = None
    community_rw: Optional[str] = None
    
    # v3 specific
    v3_security_name: Optional[str] = None
    v3_security_level: Optional[SecurityLevel] = None
    v3_auth_protocol: Optional[AuthProtocol] = None
    v3_auth_password: Optional[str] = None
    v3_priv_protocol: Optional[PrivProtocol] = None
    v3_priv_password: Optional[str] = None
    v3_context_name: Optional[str] = None
    
    # Groups, views, and access lists
    snmp_groups: List[SNMPGroup] = field(default_factory=list)
    snmp_views: List[SNMPView] = field(default_factory=list)
    snmp_access: List[SNMPAccess] = field(default_factory=list)

    def __post_init__(self):
        """Set default groups, views, and access if not provided."""
        if not self.snmp_groups:
            self.snmp_groups = [
                SNMPGroup(
                    group_name="admin_group",
                    access_rights=AccessRights.READ_WRITE,
                    views=["full_view"],
                    security_model=SecurityModel.USM,
                    notify_access=True
                ),
                SNMPGroup(
                    group_name="readonly_group",
                    access_rights=AccessRights.READ_ONLY,
                    views=["restricted_view"],
                    security_model=SecurityModel.USM,
                    notify_access=False
                )
            ]
        
        if not self.snmp_views:
            self.snmp_views = [
                SNMPView(
                    view_name="full_view",
                    subtree="1.3.6.1",
                    mask="ff",
                    type=ViewType.INCLUDED
                ),
                SNMPView(
                    view_name="restricted_view",
                    subtree="1.3.6.1.2.1.1",
                    mask="ff",
                    type=ViewType.INCLUDED
                ),
                SNMPView(
                    view_name="restricted_view",
                    subtree="1.3.6.1.2.1.2",
                    mask="ff",
                    type=ViewType.INCLUDED
                )
            ]
        
        if not self.snmp_access:
            self.snmp_access = [
                SNMPAccess(
                    group="admin_group",
                    context="default",
                    security_level=SecurityLevel.AUTH_PRIV,
                    read_view="full_view",
                    write_view="full_view",
                    notify_view="full_view"
                ),
                SNMPAccess(
                    group="readonly_group",
                    context="default",
                    security_level=SecurityLevel.AUTH_NO_PRIV,
                    read_view="restricted_view",
                    write_view="none",
                    notify_view="restricted_view"
                )
            ]

    @classmethod
    def from_v2_config(
        cls,
        community_ro: str,
        community_rw: str,
        id_device: int = 0,
        snmp_groups: Optional[List[SNMPGroup]] = None,
        snmp_views: Optional[List[SNMPView]] = None,
        snmp_access: Optional[List[SNMPAccess]] = None
    ) -> 'SNMPCommandBuilder':
        """
        Create builder from SNMP v2c configuration.
        
        Args:
            community_ro: Read-only community string
            community_rw: Read-write community string
            id_device: Device ID
            snmp_groups: Optional list of SNMP groups
            snmp_views: Optional list of SNMP views
            snmp_access: Optional list of SNMP access rules
            
        Returns:
            Configured SNMPCommandBuilder instance
        """
        return cls(
            id_device=id_device,
            snmp_version=SNMPVersion.V2C,
            community_ro=community_ro,
            community_rw=community_rw,
            snmp_groups=snmp_groups or [],
            snmp_views=snmp_views or [],
            snmp_access=snmp_access or []
        )

    @classmethod
    def from_v3_config(
        cls,
        security_name: str,
        security_level: SecurityLevel,
        id_device: int = 0,
        auth_protocol: Optional[AuthProtocol] = None,
        auth_password: Optional[str] = None,
        priv_protocol: Optional[PrivProtocol] = None,
        priv_password: Optional[str] = None,
        context_name: Optional[str] = None,
        snmp_groups: Optional[List[SNMPGroup]] = None,
        snmp_views: Optional[List[SNMPView]] = None,
        snmp_access: Optional[List[SNMPAccess]] = None
    ) -> 'SNMPCommandBuilder':
        """
        Create builder from SNMP v3 configuration.
        
        Args:
            security_name: SNMP v3 security name (username)
            security_level: Security level (noAuthNoPriv/authNoPriv/authPriv)
            id_device: Device ID
            auth_protocol: Authentication protocol (required for authNoPriv and authPriv)
            auth_password: Authentication password (required for authNoPriv and authPriv)
            priv_protocol: Privacy protocol (required for authPriv)
            priv_password: Privacy password (required for authPriv)
            context_name: Optional context name
            snmp_groups: Optional list of SNMP groups
            snmp_views: Optional list of SNMP views
            snmp_access: Optional list of SNMP access rules
            
        Returns:
            Configured SNMPCommandBuilder instance
        """
        return cls(
            id_device=id_device,
            snmp_version=SNMPVersion.V3,
            v3_security_name=security_name,
            v3_security_level=security_level,
            v3_auth_protocol=auth_protocol,
            v3_auth_password=auth_password,
            v3_priv_protocol=priv_protocol,
            v3_priv_password=priv_password,
            v3_context_name=context_name,
            snmp_groups=snmp_groups or [],
            snmp_views=snmp_views or [],
            snmp_access=snmp_access or []
        )

    def build(self) -> Dict[str, Any]:
        """
        Build the SNMP configuration command.
        
        Returns:
            Dictionary containing the complete command structure
        """
        data = {
            "snmp_version": self.snmp_version.value,
        }
        
        # Add v2c specific fields
        if self.snmp_version == SNMPVersion.V2C:
            data["community_ro"] = self.community_ro or ""
            data["community_rw"] = self.community_rw or ""
            # v3 fields should be empty/null for v2c
            data["v3_security_name"] = None
            data["v3_security_level"] = None
            data["v3_auth_protocol"] = None
            data["v3_auth_password"] = None
            data["v3_priv_protocol"] = None
            data["v3_priv_password"] = None
            data["v3_context_name"] = None
        else:
            # v2c fields should be empty/null for v3
            data["community_ro"] = None
            data["community_rw"] = None
            data["v3_security_name"] = self.v3_security_name
            data["v3_security_level"] = self.v3_security_level.value if self.v3_security_level else None
            data["v3_auth_protocol"] = self.v3_auth_protocol.value if self.v3_auth_protocol else None
            data["v3_auth_password"] = self.v3_auth_password
            data["v3_priv_protocol"] = self.v3_priv_protocol.value if self.v3_priv_protocol else None
            data["v3_priv_password"] = self.v3_priv_password
            data["v3_context_name"] = self.v3_context_name
        
        # Add groups, views, and access
        data["snmp_groups"] = [group.to_dict() for group in self.snmp_groups]
        data["snmp_views"] = [view.to_dict() for view in self.snmp_views]
        data["snmp_access"] = [access.to_dict() for access in self.snmp_access]
        
        command = {
            "ID_DEVICE": self.id_device,
            "TYPE_COMMANDS": "CONFIG_GENERAL_SNMP_UPDATE",
            "DATA": data,
            "TIME": datetime.utcnow().isoformat() + "Z"
        }
        
        return command

    def to_json(self, indent: int = 2) -> str:
        """
        Build and return the command as a JSON string.
        
        Args:
            indent: JSON indentation level
            
        Returns:
            JSON string representation of the command
        """
        return json.dumps(self.build(), indent=indent)

    def to_redis_stream_format(self) -> tuple:
        """
        Build and return the command in Redis stream format.
        
        Returns:
            Tuple of (stream_name, message_dict) suitable for redis.xadd()
        """
        command = self.build()
        # Flatten for Redis stream - convert nested dict to string
        message = {"command": json.dumps(command)}
        return ("snmp_commands", message)


# Convenience functions for quick usage
def build_snmp_v2_command(
    community_ro: str,
    community_rw: str,
    id_device: int = 0
) -> Dict[str, Any]:
    """
    Quick function to build SNMP v2c command.
    
    Args:
        community_ro: Read-only community string
        community_rw: Read-write community string
        id_device: Device ID
        
    Returns:
        Command dictionary
    """
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro=community_ro,
        community_rw=community_rw,
        id_device=id_device
    )
    return builder.build()


def build_snmp_v3_command(
    security_name: str,
    security_level: SecurityLevel,
    id_device: int = 0,
    auth_protocol: Optional[AuthProtocol] = None,
    auth_password: Optional[str] = None,
    priv_protocol: Optional[PrivProtocol] = None,
    priv_password: Optional[str] = None,
    context_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Quick function to build SNMP v3 command.
    
    Args:
        security_name: SNMP v3 security name
        security_level: Security level
        id_device: Device ID
        auth_protocol: Authentication protocol
        auth_password: Authentication password
        priv_protocol: Privacy protocol
        priv_password: Privacy password
        context_name: Context name
        
    Returns:
        Command dictionary
    """
    builder = SNMPCommandBuilder.from_v3_config(
        security_name=security_name,
        security_level=security_level,
        id_device=id_device,
        auth_protocol=auth_protocol,
        auth_password=auth_password,
        priv_protocol=priv_protocol,
        priv_password=priv_password,
        context_name=context_name
    )
    return builder.build()


__all__ = [
    'SNMPCommandBuilder',
    'SNMPVersion',
    'SecurityLevel',
    'AuthProtocol',
    'PrivProtocol',
    'AccessRights',
    'SecurityModel',
    'ViewType',
    'SNMPGroup',
    'SNMPView',
    'SNMPAccess',
    'SNMPv2Config',
    'SNMPv3Config',
    'build_snmp_v2_command',
    'build_snmp_v3_command'
]
