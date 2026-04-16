"""
SNMP Configuration Service

This service subscribes to the Redis stream 'stream:commands' and processes
SNMP configuration commands to configure NET-SNMP daemon.

Supports SNMP v2c and v3 configurations.
"""

import os
import sys
import json
import time
import signal
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from redis_common import (
    RedisSCADAStreams,
    CommandType,
    CommandMessage
)

# Configure logging
def setup_logging():
    """Setup logging with fallback to current directory if /var/log is not accessible."""
    log_file_path = '/var/log/snmp_config_service.log'
    handlers = [logging.StreamHandler(sys.stdout)]
    
    # Try to use /var/log, fallback to current directory if permission denied
    try:
        file_handler = logging.FileHandler(log_file_path, mode='a')
        handlers.append(file_handler)
        logger_temp = logging.getLogger('SNMPConfigServiceTemp')
        logger_temp.addHandler(file_handler)
        logger_temp.info("Logging to /var/log/snmp_config_service.log")
    except PermissionError:
        # Fallback to current directory
        log_file_path = os.path.join(os.getcwd(), 'snmp_config_service.log')
        file_handler = logging.FileHandler(log_file_path, mode='a')
        handlers.append(file_handler)
        logger_temp = logging.getLogger('SNMPConfigServiceTemp')
        logger_temp.addHandler(file_handler)
        logger_temp.warning(f"Cannot write to /var/log, using {log_file_path}")
    except Exception as e:
        # Final fallback to current directory
        log_file_path = os.path.join(os.getcwd(), 'snmp_config_service.log')
        file_handler = logging.FileHandler(log_file_path, mode='a')
        handlers.append(file_handler)
        logger_temp = logging.getLogger('SNMPConfigServiceTemp')
        logger_temp.addHandler(file_handler)
        logger_temp.warning(f"Logging error: {e}, using {log_file_path}")
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    return logging.getLogger('SNMPConfigService')

logger = setup_logging()


class SNMPVersion(str, Enum):
    """SNMP version enumeration."""
    V2C = "v2c"
    V3 = "v3"


class SecurityLevel(str, Enum):
    """SNMP v3 security levels."""
    NO_AUTH_NO_PRIV = "noAuthNoPriv"
    AUTH_NO_PRIV = "authNoPriv"
    AUTH_PRIV = "authPriv"


@dataclass
class SNMPConfig:
    """SNMP configuration data."""
    snmp_version: str
    community_ro: Optional[str] = None
    community_rw: Optional[str] = None
    v3_security_name: Optional[str] = None
    v3_security_level: Optional[str] = None
    v3_auth_protocol: Optional[str] = None
    v3_auth_password: Optional[str] = None
    v3_priv_protocol: Optional[str] = None
    v3_priv_password: Optional[str] = None
    v3_context_name: Optional[str] = None
    snmp_groups: List[Dict[str, Any]] = None
    snmp_views: List[Dict[str, Any]] = None
    snmp_access: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.snmp_groups is None:
            self.snmp_groups = []
        if self.snmp_views is None:
            self.snmp_views = []
        if self.snmp_access is None:
            self.snmp_access = []


class SNMPConfigurator:
    """
    Configures NET-SNMP daemon based on received configuration.
    
    This class generates snmpd.conf and snmpd.conf files for NET-SNMP
    and restarts the SNMP daemon to apply changes.
    """
    
    # Default paths for NET-SNMP configuration
    SNMPCONF_PATH = "/etc/snmp"
    SNMPCONF_FILE = "snmpd.conf"
    BACKUP_SUFFIX = ".backup"
    
    def __init__(self, config_path: str = None):
        """
        Initialize the configurator.
        
        Args:
            config_path: Path to SNMP configuration directory. 
                        Defaults to /etc/snmp
        """
        self.config_path = Path(config_path) if config_path else Path(self.SNMPCONF_PATH)
        self.config_file = self.config_path / self.SNMPCONF_FILE
        logger.info(f"SNMPConfigurator initialized with config path: {self.config_path}")
    
    def backup_config(self) -> bool:
        """Create a backup of the current configuration."""
        try:
            if self.config_file.exists():
                backup_file = self.config_file.with_suffix(
                    self.config_file.suffix + self.BACKUP_SUFFIX
                )
                backup_file.write_text(self.config_file.read_text())
                logger.info(f"Configuration backed up to {backup_file}")
                return True
            else:
                logger.warning("No existing configuration to backup")
                return False
        except Exception as e:
            logger.error(f"Failed to backup configuration: {e}")
            return False
    
    def generate_snmpd_conf(self, config: SNMPConfig) -> str:
        """
        Generate snmpd.conf content from configuration.
        
        Args:
            config: SNMP configuration data
            
        Returns:
            String content of snmpd.conf file
        """
        lines = [
            "# Auto-generated by SNMP Config Service",
            f"# Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]
        
        if config.snmp_version == SNMPVersion.V2C.value:
            # SNMP v2c configuration
            lines.append("# SNMP v2c Configuration")
            
            if config.community_ro:
                lines.append(f"rocommunity {config.community_ro} default")
                logger.info(f"Configured read-only community: {config.community_ro}")
            
            if config.community_rw:
                lines.append(f"rwcommunity {config.community_rw} default")
                logger.info(f"Configured read-write community: {config.community_rw}")
        
        elif config.snmp_version == SNMPVersion.V3.value:
            # SNMP v3 configuration
            lines.append("# SNMP v3 Configuration")
            
            if config.v3_security_name:
                # Create user based on security level
                auth_proto = config.v3_auth_protocol or ""
                auth_pass = config.v3_auth_password or ""
                priv_proto = config.v3_priv_protocol or ""
                priv_pass = config.v3_priv_password or ""
                
                if config.v3_security_level == SecurityLevel.AUTH_PRIV.value:
                    # authPriv - authentication and privacy
                    lines.append(
                        f"createUser {config.v3_security_name} {auth_proto} "
                        f"\"{auth_pass}\" {priv_proto} \"{priv_pass}\""
                    )
                    lines.append(
                        f"rouser {config.v3_security_name} priv"
                    )
                    logger.info(
                        f"Configured SNMP v3 user {config.v3_security_name} "
                        f"with authPriv (auth={auth_proto}, priv={priv_proto})"
                    )
                
                elif config.v3_security_level == SecurityLevel.AUTH_NO_PRIV.value:
                    # authNoPriv - authentication only
                    lines.append(
                        f"createUser {config.v3_security_name} {auth_proto} "
                        f"\"{auth_pass}\""
                    )
                    lines.append(
                        f"rouser {config.v3_security_name} auth"
                    )
                    logger.info(
                        f"Configured SNMP v3 user {config.v3_security_name} "
                        f"with authNoPriv (auth={auth_proto})"
                    )
                
                elif config.v3_security_level == SecurityLevel.NO_AUTH_NO_PRIV.value:
                    # noAuthNoPriv - no security
                    lines.append(
                        f"rouser {config.v3_security_name}"
                    )
                    logger.info(
                        f"Configured SNMP v3 user {config.v3_security_name} "
                        f"with noAuthNoPriv"
                    )
                
                # Add context name if specified
                if config.v3_context_name:
                    lines.append(f"context {config.v3_context_name}")
                    logger.info(f"Configured context: {config.v3_context_name}")
        
        # Add views if present
        if config.snmp_views:
            lines.append("")
            lines.append("# SNMP Views")
            for view in config.snmp_views:
                view_name = view.get('view_name', '')
                subtree = view.get('subtree', '')
                mask = view.get('mask', 'ff')
                view_type = view.get('type', 'included')
                
                if view_type == 'excluded':
                    lines.append(f"view {view_name} excluded {subtree} {mask}")
                else:
                    lines.append(f"view {view_name} included {subtree} {mask}")
                logger.info(f"Configured view: {view_name} for subtree {subtree}")
        
        # Add groups if present
        if config.snmp_groups:
            lines.append("")
            lines.append("# SNMP Groups")
            for group in config.snmp_groups:
                group_name = group.get('group_name', '')
                access_rights = group.get('access_rights', 'read-only')
                security_model = group.get('security_model', 'usm')
                notify_access = group.get('notify_access', True)
                
                # Map access rights to snmpd.conf syntax
                if access_rights == 'read-write':
                    access_str = 'rw'
                else:
                    access_str = 'ro'
                
                lines.append(f"group {group_name} {security_model} {access_str}")
                logger.info(
                    f"Configured group: {group_name} with {access_str} access"
                )
        
        # Add access control if present
        if config.snmp_access:
            lines.append("")
            lines.append("# SNMP Access Control")
            for access in config.snmp_access:
                group = access.get('group', '')
                context = access.get('context', 'default')
                sec_level = access.get('security_level', 'authPriv')
                read_view = access.get('read_view', '')
                write_view = access.get('write_view', '')
                notify_view = access.get('notify_view', '')
                
                # Map security level to prefix
                if sec_level == 'authPriv':
                    prefix = 'authpriv'
                elif sec_level == 'authNoPriv':
                    prefix = 'authnopriv'
                else:
                    prefix = 'noauthnopriv'
                
                lines.append(
                    f"access {group} \"{context}\" {prefix} exactly "
                    f"{read_view} {write_view} {notify_view}"
                )
                logger.info(
                    f"Configured access for group {group} with security {sec_level}"
                )
        
        # Add system information
        lines.append("")
        lines.append("# System Information")
        lines.append("sysLocation Unknown")
        lines.append("sysContact admin@example.com")
        
        # Allow listening on all interfaces
        lines.append("")
        lines.append("# Network Configuration")
        lines.append("agentAddress udp:161")
        lines.append("master agentx")
        
        return "\n".join(lines)
    
    def apply_config(self, config: SNMPConfig) -> bool:
        """
        Apply SNMP configuration.
        
        Args:
            config: SNMP configuration data
            
        Returns:
            True if configuration was applied successfully, False otherwise
        """
        try:
            # Ensure config directory exists
            self.config_path.mkdir(parents=True, exist_ok=True)
            
            # Backup existing config
            self.backup_config()
            
            # Generate new configuration
            conf_content = self.generate_snmpd_conf(config)
            
            # Write configuration file
            self.config_file.write_text(conf_content)
            logger.info(f"Configuration written to {self.config_file}")
            
            # Set proper permissions
            os.chmod(self.config_file, 0o644)
            
            # Restart SNMP daemon
            return self.restart_snmpd()
            
        except Exception as e:
            logger.error(f"Failed to apply configuration: {e}")
            return False
    
    def restart_snmpd(self) -> bool:
        """
        Restart the SNMP daemon.
        
        Returns:
            True if restart was successful, False otherwise
        """
        try:
            # Try different service managers
            commands_to_try = [
                ["systemctl", "restart", "snmpd"],
                ["service", "snmpd", "restart"],
                ["/etc/init.d/snmpd", "restart"]
            ]
            
            for cmd in commands_to_try:
                try:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        logger.info("SNMP daemon restarted successfully")
                        return True
                    else:
                        logger.warning(
                            f"Command {' '.join(cmd)} failed: {result.stderr}"
                        )
                except FileNotFoundError:
                    continue
                except subprocess.TimeoutExpired:
                    logger.warning(f"Command {' '.join(cmd)} timed out")
                    continue
            
            logger.error("Failed to restart SNMP daemon with any method")
            return False
            
        except Exception as e:
            logger.error(f"Error restarting SNMP daemon: {e}")
            return False
    
    def validate_config(self, config: SNMPConfig) -> bool:
        """
        Validate SNMP configuration before applying.
        
        Args:
            config: SNMP configuration data
            
        Returns:
            True if configuration is valid, False otherwise
        """
        try:
            if config.snmp_version not in [SNMPVersion.V2C.value, SNMPVersion.V3.value]:
                logger.error(f"Invalid SNMP version: {config.snmp_version}")
                return False
            
            if config.snmp_version == SNMPVersion.V2C.value:
                if not config.community_ro and not config.community_rw:
                    logger.error(
                        "SNMP v2c requires at least one community string"
                    )
                    return False
            
            elif config.snmp_version == SNMPVersion.V3.value:
                if not config.v3_security_name:
                    logger.error("SNMP v3 requires security_name")
                    return False
                
                # Validate security level requirements
                if config.v3_security_level == SecurityLevel.AUTH_PRIV.value:
                    if not config.v3_auth_protocol or not config.v3_auth_password:
                        logger.error(
                            "AUTH_PRIV requires auth_protocol and auth_password"
                        )
                        return False
                    if not config.v3_priv_protocol or not config.v3_priv_password:
                        logger.error(
                            "AUTH_PRIV requires priv_protocol and priv_password"
                        )
                        return False
                
                elif config.v3_security_level == SecurityLevel.AUTH_NO_PRIV.value:
                    if not config.v3_auth_protocol or not config.v3_auth_password:
                        logger.error(
                            "AUTH_NO_PRIV requires auth_protocol and auth_password"
                        )
                        return False
            
            logger.info("Configuration validation passed")
            return True
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False


class SNMPConfigService:
    """
    Main service that subscribes to Redis stream and processes SNMP commands.
    """
    
    def __init__(
        self,
        redis_host: str = '192.168.3.228',
        redis_port: int = 6380,
        consumer_group: str = 'snmp_config_group',
        consumer_name: str = None
    ):
        """
        Initialize the service.
        
        Args:
            redis_host: Redis server host
            redis_port: Redis server port
            consumer_group: Redis consumer group name
            consumer_name: Consumer name (defaults to hostname)
        """
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name or f"snmp_consumer_{os.getpid()}"
        
        # Initialize Redis connection
        logger.info(
            f"Connecting to Redis at {redis_host}:{redis_port}"
        )
        self.scada = RedisSCADAStreams(
            host=redis_host,
            port=redis_port
        )
        
        # Initialize configurator
        self.configurator = SNMPConfigurator()
        
        # Running flag
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        logger.info(f"SNMPConfigService initialized with consumer: {self.consumer_name}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
    
    def create_consumer_group(self):
        """Create Redis consumer group if it doesn't exist."""
        try:
            self.scada.create_consumer_group(
                self.scada.STREAM_COMMANDS,
                self.consumer_group
            )
            logger.info(f"Consumer group '{self.consumer_group}' ready")
        except Exception as e:
            logger.error(f"Failed to create consumer group: {e}")
            raise
    
    def process_command(self, data: Dict[str, Any]) -> bool:
        """
        Process a single command from the stream.
        
        Args:
            data: Command data from Redis stream
            
        Returns:
            True if command was processed successfully, False otherwise
        """
        try:
            # Parse command data
            id_device = data.get('id_device', 'unknown')
            type_commands = data.get('type_commands', '')
            
            # Parse data_command field (it's JSON string)
            data_command_raw = data.get('data_command', '{}')
            try:
                data_command = json.loads(data_command_raw)
            except json.JSONDecodeError:
                data_command = data_command_raw
            
            logger.info(
                f"Processing command from device {id_device}: {type_commands}"
            )
            
            # Check if this is an SNMP configuration command
            if type_commands == CommandType.CONFIG_GENERAL_SNMP_UPDATE.value:
                logger.info(f"Processing SNMP configuration for device {id_device}")
                
                # Create SNMPConfig object from command data
                config = SNMPConfig(
                    snmp_version=data_command.get('snmp_version', ''),
                    community_ro=data_command.get('community_ro'),
                    community_rw=data_command.get('community_rw'),
                    v3_security_name=data_command.get('v3_security_name'),
                    v3_security_level=data_command.get('v3_security_level'),
                    v3_auth_protocol=data_command.get('v3_auth_protocol'),
                    v3_auth_password=data_command.get('v3_auth_password'),
                    v3_priv_protocol=data_command.get('v3_priv_protocol'),
                    v3_priv_password=data_command.get('v3_priv_password'),
                    v3_context_name=data_command.get('v3_context_name'),
                    snmp_groups=data_command.get('snmp_groups', []),
                    snmp_views=data_command.get('snmp_views', []),
                    snmp_access=data_command.get('snmp_access', [])
                )
                
                # Validate configuration
                if not self.configurator.validate_config(config):
                    logger.error("Configuration validation failed")
                    return False
                
                # Apply configuration
                if self.configurator.apply_config(config):
                    logger.info(
                        f"Successfully configured SNMP for device {id_device}"
                    )
                    return True
                else:
                    logger.error("Failed to apply SNMP configuration")
                    return False
            
            else:
                logger.debug(f"Ignoring non-SNMP command: {type_commands}")
                return True
                
        except Exception as e:
            logger.error(f"Error processing command: {e}", exc_info=True)
            return False
    
    def run(self):
        """Main service loop."""
        logger.info("Starting SNMP Config Service...")
        
        # Create consumer group
        self.create_consumer_group()
        
        # Start consuming messages
        logger.info(
            f"Subscribed to {self.scada.STREAM_COMMANDS} "
            f"(group: {self.consumer_group}, consumer: {self.consumer_name})"
        )
        
        while self.running:
            try:
                # Consume messages from stream
                messages = self.scada.r.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {self.scada.STREAM_COMMANDS: '>'},
                    count=10,
                    block=5000  # Block for 5 seconds
                )
                
                if messages:
                    for stream_name, entries in messages:
                        for msg_id, data in entries:
                            logger.debug(f"Processing message {msg_id}")
                            
                            # Process the command
                            success = self.process_command(data)
                            
                            # Acknowledge the message
                            try:
                                self.scada.r.xack(
                                    self.scada.STREAM_COMMANDS,
                                    self.consumer_group,
                                    msg_id
                                )
                                logger.debug(f"Acknowledged message {msg_id}")
                            except Exception as e:
                                logger.error(
                                    f"Failed to acknowledge message {msg_id}: {e}"
                                )
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                # Wait before retrying
                time.sleep(5)
        
        logger.info("SNMP Config Service stopped")


def main():
    """Entry point for the service."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='SNMP Configuration Service'
    )
    parser.add_argument(
        '--redis-host',
        default='192.168.3.228',
        help='Redis server host'
    )
    parser.add_argument(
        '--redis-port',
        type=int,
        default=6380,
        help='Redis server port'
    )
    parser.add_argument(
        '--consumer-group',
        default='snmp_config_group',
        help='Redis consumer group name'
    )
    parser.add_argument(
        '--consumer-name',
        default=None,
        help='Consumer name (default: auto-generated)'
    )
    parser.add_argument(
        '--config-path',
        default=None,
        help='Path to SNMP configuration directory'
    )
    
    args = parser.parse_args()
    
    # Override config path if specified
    if args.config_path:
        SNMPConfigurator.SNMPCONF_PATH = args.config_path
    
    # Create and run service
    service = SNMPConfigService(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        consumer_group=args.consumer_group,
        consumer_name=args.consumer_name
    )
    
    try:
        service.run()
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    except Exception as e:
        logger.error(f"Service crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
