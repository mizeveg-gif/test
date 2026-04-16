#!/usr/bin/env python3
"""
SNMP Configuration Service
Сервис подписывается на Redis stream 'commands' и обрабатывает команды
для конфигурации NET-SNMP на основе полученных данных.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional
import redis
from pathlib import Path

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/var/log/snmp_config_service.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


class SNMPConfigService:
    """Сервис для конфигурации NET-SNMP через Redis stream."""
    
    # Пути к файлам конфигурации NET-SNMP
    SNMPD_CONF_PATH = '/etc/snmp/snmpd.conf'
    SNMPD_CONF_BACKUP = '/etc/snmp/snmpd.conf.backup'
    
    # Типы команд которые обрабатываем
    SUPPORTED_COMMANDS = {
        'CONFIG_GENERAL_SNMP_UPDATE': 'update_snmp_config',
        'CONFIG_SNMP_RESTART': 'restart_snmp',
        'CONFIG_SNMP_STATUS': 'get_snmp_status',
    }
    
    def __init__(self, redis_host: str = 'localhost', redis_port: int = 6379,
                 redis_db: int = 0, redis_password: Optional[str] = None,
                 stream_name: str = 'commands', consumer_group: str = 'snmp_config_group',
                 consumer_name: str = 'snmp_consumer_1'):
        """
        Инициализация сервиса.
        
        :param redis_host: Хост Redis
        :param redis_port: Порт Redis
        :param redis_db: База данных Redis
        :param redis_password: Пароль Redis (опционально)
        :param stream_name: Имя stream для подписки
        :param consumer_group: Имя группы потребителей
        :param consumer_name: Имя потребителя
        """
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        
        self.redis_client = self._connect_redis()
        self._ensure_stream_and_group()
        
        logger.info(f"SNMP Config Service initialized. Stream: {stream_name}, "
                   f"Group: {consumer_group}, Consumer: {consumer_name}")
    
    def _connect_redis(self) -> redis.Redis:
        """Подключение к Redis."""
        try:
            client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                password=self.redis_password,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            client.ping()
            logger.info("Successfully connected to Redis")
            return client
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    def _ensure_stream_and_group(self):
        """Создание stream и группы потребителей если они не существуют."""
        try:
            # Пытаемся создать группу потребителей
            # Если stream не существует, создаем его с помощью добавления временного сообщения
            try:
                self.redis_client.xgroup_create(
                    name=self.stream_name,
                    groupname=self.consumer_group,
                    id='0',
                    mkstream=True
                )
                logger.info(f"Created stream '{self.stream_name}' and group '{self.consumer_group}'")
            except redis.exceptions.ResponseError as e:
                if 'BUSYGROUP' in str(e):
                    logger.debug(f"Group '{self.consumer_group}' already exists")
                else:
                    raise
        except Exception as e:
            logger.error(f"Error ensuring stream and group: {e}")
            raise
    
    def process_commands(self, block_timeout: int = 5000, max_messages: int = 10):
        """
        Основной цикл обработки команд из stream.
        
        :param block_timeout: Время блокировки в мс при ожидании сообщений
        :param max_messages: Максимальное количество сообщений для обработки за раз
        """
        logger.info("Starting command processing loop...")
        
        while True:
            try:
                # Чтение сообщений из stream
                messages = self.redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: '>'},
                    count=max_messages,
                    block=block_timeout
                )
                
                if not messages:
                    continue
                
                for stream_name, stream_messages in messages:
                    for message_id, message_data in stream_messages:
                        self._process_message(message_id, message_data)
                        
            except redis.ConnectionError as e:
                logger.error(f"Redis connection error: {e}")
                logger.info("Reconnecting to Redis...")
                time.sleep(5)
                self.redis_client = self._connect_redis()
            except Exception as e:
                logger.error(f"Error processing messages: {e}", exc_info=True)
                time.sleep(1)
    
    def _process_message(self, message_id: str, message_data: Dict[str, Any]):
        """
        Обработка отдельного сообщения.
        
        :param message_id: ID сообщения в stream
        :param message_data: Данные сообщения
        """
        try:
            logger.info(f"Processing message {message_id}: {message_data}")
            
            # Извлекаем данные команды
            # Сообщение может быть в формате JSON строки или уже распарсенным
            if isinstance(message_data, dict):
                # Если это dict, возможно данные в поле 'data' или это уже распарсенный JSON
                data_str = message_data.get('data', message_data.get('DATA', ''))
                if isinstance(data_str, str):
                    try:
                        command_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        command_data = message_data
                else:
                    command_data = message_data
            else:
                command_data = json.loads(str(message_data))
            
            # Получаем тип команды
            type_command = command_data.get('TYPE_COMMANDS', '')
            
            if type_command not in self.SUPPORTED_COMMANDS:
                logger.warning(f"Unsupported command type: {type_command}")
                self._acknowledge_message(message_id)
                return
            
            # Вызываем соответствующий метод обработки
            method_name = self.SUPPORTED_COMMANDS[type_command]
            handler_method = getattr(self, method_name)
            
            logger.info(f"Executing handler: {method_name}")
            result = handler_method(command_data)
            
            # Подтверждаем обработку сообщения
            self._acknowledge_message(message_id)
            
            # Логируем результат
            if result:
                logger.info(f"Command {type_command} executed successfully: {result}")
            else:
                logger.info(f"Command {type_command} executed successfully")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in message {message_id}: {e}")
            self._handle_failed_message(message_id, f"Invalid JSON: {e}")
        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}", exc_info=True)
            self._handle_failed_message(message_id, str(e))
    
    def _acknowledge_message(self, message_id: str):
        """Подтверждение обработки сообщения (XACK)."""
        try:
            self.redis_client.xack(self.stream_name, self.consumer_group, message_id)
            logger.debug(f"Acknowledged message {message_id}")
        except Exception as e:
            logger.error(f"Error acknowledging message {message_id}: {e}")
    
    def _handle_failed_message(self, message_id: str, error: str):
        """Обработка неудачного сообщения (перемещение в поток ошибок)."""
        try:
            # Можно добавить логику перемещения в другой stream для повторной обработки
            error_stream = f"{self.stream_name}:errors"
            self.redis_client.xadd(error_stream, {
                'original_id': message_id,
                'error': error,
                'timestamp': datetime.now().isoformat()
            })
            logger.warning(f"Message {message_id} moved to error stream: {error}")
            # Все равно подтверждаем чтобы не блокировать очередь
            self._acknowledge_message(message_id)
        except Exception as e:
            logger.error(f"Error handling failed message: {e}")
    
    def update_snmp_config(self, command_data: Dict[str, Any]) -> bool:
        """
        Обновление конфигурации SNMP на основе полученных данных.
        
        :param command_data: Данные команды с конфигурацией
        :return: True если успешно
        """
        logger.info("Updating SNMP configuration...")
        
        data = command_data.get('DATA', {})
        
        # Создаем резервную копию текущей конфигурации
        self._backup_config()
        
        # Генерируем новую конфигурацию
        config_lines = self._generate_snmpd_conf(data)
        
        # Записываем новую конфигурацию
        self._write_config(config_lines)
        
        # Перезапускаем службу SNMP
        self._restart_snmp_service()
        
        logger.info("SNMP configuration updated successfully")
        return True
    
    def _backup_config(self):
        """Создание резервной копии конфигурации."""
        try:
            if os.path.exists(self.SNMPD_CONF_PATH):
                import shutil
                shutil.copy2(self.SNMPD_CONF_PATH, self.SNMPD_CONF_BACKUP)
                logger.info(f"Backup created: {self.SNMPD_CONF_BACKUP}")
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")
    
    def _generate_snmpd_conf(self, data: Dict[str, Any]) -> list:
        """
        Генерация строк конфигурации snmpd.conf.
        
        :param data: Данные конфигурации из команды
        :return: Список строк конфигурации
        """
        lines = []
        lines.append("# Auto-generated by SNMP Config Service")
        lines.append(f"# Generated at: {datetime.now().isoformat()}")
        lines.append("")
        
        snmp_version = data.get('snmp_version', 'v2c')
        
        # Конфигурация для SNMP v2c
        if snmp_version == 'v2c':
            community_ro = data.get('community_ro', 'public')
            community_rw = data.get('community_rw', 'private')
            
            lines.append("# SNMP v2c Configuration")
            lines.append(f"rocommunity {community_ro} default")
            lines.append(f"rwcommunity {community_rw} default")
            lines.append("")
        
        # Конфигурация для SNMP v3
        elif snmp_version == 'v3':
            lines.append("# SNMP v3 Configuration")
            
            v3_security_name = data.get('v3_security_name', 'snmpuser')
            v3_security_level = data.get('v3_security_level', 'authPriv')
            v3_auth_protocol = data.get('v3_auth_protocol', 'SHA')
            v3_auth_password = data.get('v3_auth_password', '')
            v3_priv_protocol = data.get('v3_priv_protocol', 'AES')
            v3_priv_password = data.get('v3_priv_password', '')
            v3_context_name = data.get('v3_context_name', '')
            
            # Создаем пользователя с аутентификацией и приватностью
            auth_flag = ''
            priv_flag = ''
            
            if v3_security_level in ['authNoPriv', 'authPriv']:
                auth_flag = f'-a {v3_auth_protocol} -A {v3_auth_password}'
            
            if v3_security_level == 'authPriv' and v3_priv_password:
                priv_flag = f'-x {v3_priv_protocol} -X {v3_priv_password}'
            
            # Добавляем пользователя (эта команда должна выполняться через net-snmp-create-v3-user)
            # В конфиге только указываем права доступа
            lines.append(f"# User: {v3_security_name}")
            lines.append(f"# Security Level: {v3_security_level}")
            if auth_flag:
                lines.append(f"# Auth: {v3_auth_protocol}")
            if priv_flag:
                lines.append(f"# Priv: {v3_priv_protocol}")
            lines.append("")
            
            # Обрабатываем группы
            snmp_groups = data.get('snmp_groups', [])
            for group in snmp_groups:
                group_name = group.get('group_name', 'default_group')
                access_rights = group.get('access_rights', 'read-only')
                security_model = group.get('security_model', 'usm')
                notify_access = group.get('notify_access', False)
                
                # Создаем группу
                model_char = 'v' if security_model == 'usm' else security_model[0].upper()
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                sec_level = level_map.get(group.get('security_level', v3_security_level), 'auth')
                
                lines.append(f"group {group_name} {model_char} {sec_level}")
            
            lines.append("")
            
            # Обрабатываем представления (views)
            snmp_views = data.get('snmp_views', [])
            view_names = set()
            for view in snmp_views:
                view_name = view.get('view_name', 'default_view')
                subtree = view.get('subtree', '1.3.6.1')
                mask = view.get('mask', '')
                view_type = view.get('type', 'included')
                
                include_char = 'i' if view_type == 'included' else 'e'
                mask_part = f' {mask}' if mask else ''
                
                lines.append(f"view {view_name} {include_char} {subtree}{mask_part}")
                view_names.add(view_name)
            
            lines.append("")
            
            # Обрабатываем правила доступа (access)
            snmp_access = data.get('snmp_access', [])
            for access in snmp_access:
                group = access.get('group', 'default_group')
                context = access.get('context', 'default')
                sec_level = access.get('security_level', 'authNoPriv')
                read_view = access.get('read_view', 'default_view')
                write_view = access.get('write_view', 'none')
                notify_view = access.get('notify_view', 'none')
                
                # Преобразуем уровень безопасности
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                level = level_map.get(sec_level, 'auth')
                
                lines.append(f"access {group} \"{context}\" {level} {read_view} {write_view} {notify_view}")
            
            lines.append("")
            
            # Если есть пароль аутентификации, добавляем комментарий о создании пользователя
            if v3_auth_password:
                lines.append("# IMPORTANT: Create SNMP v3 user with the following command:")
                cmd = f"net-snmp-create-v3-user -{v3_security_level[0].lower()} "
                if v3_auth_password:
                    cmd += f"-a {v3_auth_protocol} -A {v3_auth_password} "
                if v3_priv_password and v3_security_level == 'authPriv':
                    cmd += f"-x {v3_priv_protocol} -X {v3_priv_password} "
                cmd += v3_security_name
                lines.append(f"# {cmd}")
                lines.append("")
        
        # Системная информация
        lines.append("# System Information")
        lines.append("sysLocation Default Location")
        lines.append("sysContact Default Contact")
        lines.append("")
        
        # Разрешаем все интерфейсы
        lines.append("# Allow all interfaces")
        lines.append("agentAddress udp:161")
        lines.append("")
        
        # Логирование
        lines.append("# Logging")
        lines.append("dontLogTCPwrappersConnects yes")
        
        return lines
    
    def _write_config(self, config_lines: list):
        """Запись конфигурации в файл."""
        try:
            # Убеждаемся что директория существует
            config_dir = os.path.dirname(self.SNMPD_CONF_PATH)
            Path(config_dir).mkdir(parents=True, exist_ok=True)
            
            with open(self.SNMPD_CONF_PATH, 'w') as f:
                f.write('\n'.join(config_lines))
            
            # Устанавливаем правильные права
            os.chmod(self.SNMPD_CONF_PATH, 0o640)
            
            logger.info(f"Configuration written to {self.SNMPD_CONF_PATH}")
        except Exception as e:
            logger.error(f"Error writing configuration: {e}")
            raise
    
    def _restart_snmp_service(self):
        """Перезапуск службы SNMP."""
        try:
            import subprocess
            
            # Пробуем разные методы перезапуска
            commands = [
                ['systemctl', 'restart', 'snmpd'],
                ['service', 'snmpd', 'restart'],
                ['/etc/init.d/snmpd', 'restart']
            ]
            
            for cmd in commands:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        logger.info(f"SNMP service restarted using {' '.join(cmd)}")
                        return
                    else:
                        logger.debug(f"Command {' '.join(cmd)} failed: {result.stderr}")
                except FileNotFoundError:
                    continue
                except subprocess.TimeoutExpired:
                    logger.warning(f"Command {' '.join(cmd)} timed out")
            
            logger.warning("Could not restart SNMP service - may need manual restart")
            
        except Exception as e:
            logger.error(f"Error restarting SNMP service: {e}")
            # Не выбрасываем исключение, так как конфигурация уже записана
    
    def restart_snmp(self, command_data: Dict[str, Any]) -> bool:
        """Перезапуск службы SNMP."""
        logger.info("Restarting SNMP service...")
        self._restart_snmp_service()
        return True
    
    def get_snmp_status(self, command_data: Dict[str, Any]) -> Dict[str, Any]:
        """Получение статуса SNMP службы."""
        import subprocess
        
        status = {
            'running': False,
            'config_file': self.SNMPD_CONF_PATH,
            'config_exists': os.path.exists(self.SNMPD_CONF_PATH),
            'backup_exists': os.path.exists(self.SNMPD_CONF_BACKUP)
        }
        
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', 'snmpd'],
                capture_output=True,
                text=True,
                timeout=5
            )
            status['running'] = result.stdout.strip() == 'active'
            status['status'] = result.stdout.strip()
        except Exception as e:
            status['status_error'] = str(e)
        
        logger.info(f"SNMP status: {status}")
        return status


def main():
    """Точка входа сервиса."""
    # Чтение конфигурации из переменных окружения
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', '6379'))
    redis_db = int(os.getenv('REDIS_DB', '0'))
    redis_password = os.getenv('REDIS_PASSWORD')
    stream_name = os.getenv('REDIS_STREAM_NAME', 'commands')
    consumer_group = os.getenv('CONSUMER_GROUP', 'snmp_config_group')
    consumer_name = os.getenv('CONSUMER_NAME', f'snmp_consumer_{os.getpid()}')
    
    logger.info(f"Starting SNMP Config Service with config: "
               f"Redis={redis_host}:{redis_port}, Stream={stream_name}")
    
    try:
        service = SNMPConfigService(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_password=redis_password,
            stream_name=stream_name,
            consumer_group=consumer_group,
            consumer_name=consumer_name
        )
        
        # Запуск обработки команд
        service.process_commands()
        
    except KeyboardInterrupt:
        logger.info("Service stopped by user")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
