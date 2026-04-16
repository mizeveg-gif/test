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
import argparse
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
    
    # Типы команд которые обрабатываем
    SUPPORTED_COMMANDS = {
        'CONFIG_GENERAL_SNMP_UPDATE': 'update_snmp_config',
        'CONFIG_SNMP_RESTART': 'restart_snmp',
        'CONFIG_SNMP_STATUS': 'get_snmp_status',
    }
    
    def __init__(self, redis_host: str = 'localhost', redis_port: int = 6379,
                 redis_db: int = 0, redis_password: Optional[str] = None,
                 stream_name: str = 'commands', consumer_group: str = 'snmp_config_group',
                 consumer_name: str = 'snmp_consumer_1', config_path: str = '/etc/snmp'):
        """
        Инициализация сервиса.

        :param redis_host: Хост Redis
        :param redis_port: Порт Redis
        :param redis_db: База данных Redis
        :param redis_password: Пароль Redis (опционально)
        :param stream_name: Имя stream для подписки
        :param consumer_group: Имя группы потребителей
        :param consumer_name: Имя потребителя
        :param config_path: Путь к директории конфигурации SNMP
        """
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_password = redis_password
        self.stream_name = stream_name
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.config_path = Path(config_path)
        self.snmpd_conf_path = self.config_path / 'snmpd.conf'
        self.snmpd_conf_backup = self.config_path / 'snmpd.conf.backup'

        self.redis_client = self._connect_redis()
        self._ensure_stream_and_group()

        logger.info(f"SNMP Config Service initialized. Stream: {stream_name}, "
                   f"Group: {consumer_group}, Consumer: {consumer_name}, ConfigPath: {config_path}")
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
                        
            except redis.exceptions.TimeoutError:
                # Штатный таймаут при отсутствии сообщений (из-за block), игнорируем
                logger.debug("Read timeout (no new messages), continuing...")
                continue
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
            
            # Нормализация ключей сообщения (поддержка разных регистров)
            # Redis может возвращать ключи в нижнем или верхнем регистре
            normalized_data = {}
            for k, v in message_data.items():
                normalized_data[k.lower()] = v
            
            # Извлекаем данные команды
            # Сообщение может быть в формате JSON строки или уже распарсенным
            data_str = normalized_data.get('data', normalized_data.get('data_command', ''))
            
            if isinstance(data_str, str):
                try:
                    command_data = json.loads(data_str)
                except json.JSONDecodeError:
                    command_data = normalized_data
            else:
                command_data = data_str if data_str else normalized_data
            
            # Получаем тип команды (поддержка разных вариантов написания)
            # Важно: type_commands берем из исходного normalized_data, а не из распарсенного command_data
            type_command = normalized_data.get('type_commands', normalized_data.get('TYPE_COMMANDS', ''))
            
            if type_command not in self.SUPPORTED_COMMANDS:
                logger.warning(f"Unsupported command type: {type_command}. Available keys: {list(command_data.keys())}")
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
        Использует секционный подход: обновляет только соответствующие секции,
        сохраняя остальные настройки (passpersist скрипты и др.).
        
        :param command_data: Данные команды с конфигурацией
        :return: True если успешно
        """
        logger.info("Updating SNMP configuration...")
        
        data = command_data.get('DATA', {})
        snmp_version = data.get('snmp_version', 'v2c')
        
        # Создаем резервную копию текущей конфигурации
        self._backup_config()
        
        # Генерируем новые секции конфигурации
        new_sections = self._generate_snmpd_conf(data)
        
        # Читаем текущую конфигурацию
        existing_lines = self._read_current_config()
        
        # Извлекаем существующие секции и остальные строки
        existing_sections, header_lines, section_positions = self._extract_sections(existing_lines)
        
        # Если настраиваем v2, удаляем секцию v3, и наоборот
        if snmp_version == 'v2c':
            if 'SNMP_V3_CONFIG' in existing_sections:
                del existing_sections['SNMP_V3_CONFIG']
        elif snmp_version == 'v3':
            if 'SNMP_V2_CONFIG' in existing_sections:
                del existing_sections['SNMP_V2_CONFIG']
        
        # Объединяем существующие секции с новыми
        merged_sections = {**existing_sections, **new_sections}
        
        # Формируем итоговую конфигурацию
        final_config = self._merge_config(header_lines, merged_sections, section_positions)
        
        # Записываем новую конфигурацию
        try:
            with open(str(self.snmpd_conf_path), 'w') as f:
                f.write(final_config)
            logger.info(f"Configuration written to {self.snmpd_conf_path}")
            
            # Перезапускаем службу SNMP
            self._restart_snmp_service()
            
            return True
        except Exception as e:
            logger.error(f"Error writing configuration: {e}")
            # Восстанавливаем из бэкапа при ошибке
            self._restore_from_backup()
            return False
    
    def _backup_config(self):
        """Создание резервной копии конфигурации."""
        try:
            if os.path.exists(str(self.snmpd_conf_path)):
                import shutil
                shutil.copy2(str(self.snmpd_conf_path), str(self.snmpd_conf_backup))
                logger.info(f"Backup created: {str(self.snmpd_conf_backup)}")
        except Exception as e:
            logger.warning(f"Could not create backup: {e}")
    
    def _generate_snmpd_conf(self, data: Dict[str, Any]) -> dict:
        """
        Генерация секций конфигурации snmpd.conf.
        Возвращает словарь с именами секций и их содержимым.
        
        :param data: Данные конфигурации из команды
        :return: Dict {section_name: [lines]}
        """
        sections = {}
        
        snmp_version = data.get('snmp_version', 'v2c')
        
        # Секция для SNMP v2c
        if snmp_version == 'v2c':
            community_ro = data.get('community_ro', 'public')
            community_rw = data.get('community_rw', 'private')
            
            lines = []
            lines.append("# SNMP v2c Configuration - Auto-generated")
            lines.append(f"# Generated at: {datetime.now().isoformat()}")
            lines.append(f"rocommunity {community_ro} default")
            lines.append(f"rwcommunity {community_rw} default")
            
            sections['SNMP_V2_CONFIG'] = lines
        
        # Секция для SNMP v3
        elif snmp_version == 'v3':
            lines = []
            lines.append("# SNMP v3 Configuration - Auto-generated")
            lines.append(f"# Generated at: {datetime.now().isoformat()}")
            
            v3_security_name = data.get('v3_security_name', 'snmpuser')
            v3_security_level = data.get('v3_security_level', 'authPriv')
            v3_auth_protocol = data.get('v3_auth_protocol', 'SHA')
            v3_auth_password = data.get('v3_auth_password', '')
            v3_priv_protocol = data.get('v3_priv_protocol', 'AES')
            v3_priv_password = data.get('v3_priv_password', '')
            v3_context_name = data.get('v3_context_name', '')
            
            lines.append(f"# User: {v3_security_name}")
            lines.append(f"# Security Level: {v3_security_level}")
            if v3_auth_protocol:
                lines.append(f"# Auth: {v3_auth_protocol}")
            if v3_priv_protocol:
                lines.append(f"# Priv: {v3_priv_protocol}")
            lines.append("")
            
            # Обрабатываем группы
            snmp_groups = data.get('snmp_groups', [])
            group_lines = []
            for group in snmp_groups:
                group_name = group.get('group_name', 'default_group')
                security_model = group.get('security_model', 'usm')
                
                model_char = 'v' if security_model == 'usm' else security_model[0].upper()
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                sec_level = level_map.get(group.get('security_level', v3_security_level), 'auth')
                
                group_lines.append(f"group {group_name} {model_char} {sec_level}")
            
            if group_lines:
                lines.extend(group_lines)
                lines.append("")
            
            # Обрабатываем представления (views)
            snmp_views = data.get('snmp_views', [])
            view_lines = []
            for view in snmp_views:
                view_name = view.get('view_name', 'default_view')
                subtree = view.get('subtree', '1.3.6.1')
                mask = view.get('mask', '')
                view_type = view.get('type', 'included')
                
                include_char = 'i' if view_type == 'included' else 'e'
                mask_part = f' {mask}' if mask else ''
                
                view_lines.append(f"view {view_name} {include_char} {subtree}{mask_part}")
            
            if view_lines:
                lines.extend(view_lines)
                lines.append("")
            
            # Обрабатываем правила доступа (access)
            snmp_access = data.get('snmp_access', [])
            access_lines = []
            for access in snmp_access:
                group = access.get('group', 'default_group')
                context = access.get('context', 'default')
                sec_level = access.get('security_level', 'authNoPriv')
                read_view = access.get('read_view', 'default_view')
                write_view = access.get('write_view', 'none')
                notify_view = access.get('notify_view', 'none')
                
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                level = level_map.get(sec_level, 'auth')
                
                access_lines.append(f"access {group} \"{context}\" {level} {read_view} {write_view} {notify_view}")
            
            if access_lines:
                lines.extend(access_lines)
                lines.append("")
            
            # Команда для создания пользователя
            if v3_auth_password:
                user_cmd_lines = []
                user_cmd_lines.append("# IMPORTANT: Create SNMP v3 user with the following command:")
                cmd = f"net-snmp-create-v3-user -{v3_security_level[0].lower()} "
                if v3_auth_protocol and v3_auth_password:
                    cmd += f"-a {v3_auth_protocol} -A {v3_auth_password} "
                if v3_priv_protocol and v3_priv_password and v3_security_level == 'authPriv':
                    cmd += f"-x {v3_priv_protocol} -X {v3_priv_password} "
                cmd += v3_security_name
                user_cmd_lines.append(f"# {cmd}")
                lines.extend(user_cmd_lines)
            
            sections['SNMP_V3_CONFIG'] = lines
        
        return sections
    
    def _read_current_config(self) -> list:
        """Чтение текущего файла конфигурации."""
        if not os.path.exists(str(self.snmpd_conf_path)):
            return []
        
        try:
            with open(str(self.snmpd_conf_path), 'r') as f:
                return f.readlines()
        except Exception as e:
            logger.error(f"Error reading config file: {e}")
            return []
    
    def _extract_sections(self, config_lines: list) -> tuple[dict, list, dict]:
        """
        Извлечение маркированных секций из конфигурации.
        Возвращает:
        - dict с существующими секциями
        - list строк вне секций (заголовок и другие настройки)
        - dict с позициями секций (start_line, end_line)
        """
        sections = {}
        other_lines = []
        section_positions = {}
        
        current_section = None
        current_section_start = None
        current_section_lines = []
        outside_section_lines = []
        
        SECTION_START_MARKER = "### BEGIN AUTO-GENERATED:"
        SECTION_END_MARKER = "### END AUTO-GENERATED ###"
        
        for i, line in enumerate(config_lines):
            stripped = line.rstrip('\n\r')
            
            # Проверка начала секции
            if stripped.startswith(SECTION_START_MARKER):
                section_name = stripped.replace(SECTION_START_MARKER, "").strip()
                current_section = section_name
                current_section_start = i
                current_section_lines = [stripped]
                continue
            
            # Проверка конца секции
            if stripped == SECTION_END_MARKER and current_section:
                current_section_lines.append(stripped)
                sections[current_section] = current_section_lines
                section_positions[current_section] = {
                    'start': current_section_start,
                    'end': i
                }
                current_section = None
                current_section_start = None
                current_section_lines = []
                continue
            
            # Добавление строки в текущую секцию или в другие строки
            if current_section:
                current_section_lines.append(stripped)
            else:
                outside_section_lines.append(stripped)
        
        return sections, outside_section_lines, section_positions
    
    def _generate_snmpd_conf(self, data: Dict[str, Any]) -> dict:
        """
        Генерация секций конфигурации snmpd.conf.
        Возвращает словарь с именами секций и их содержимым.
        Если версия SNMP изменилась, старая секция помечается на удаление (пустой список).
        
        :param data: Данные конфигурации из команды
        :return: Dict {section_name: [lines]}
        """
        sections = {}
        
        snmp_version = data.get('snmp_version', 'v2c')
        
        # Помечаем другую версию на удаление
        if snmp_version == 'v2c':
            sections['SNMP_V3_CONFIG'] = []  # Удаляем V3 секцию если она есть
        elif snmp_version == 'v3':
            sections['SNMP_V2_CONFIG'] = []  # Удаляем V2 секцию если она есть
        
        # Секция для SNMP v2c
        if snmp_version == 'v2c':
            community_ro = data.get('community_ro', 'public')
            community_rw = data.get('community_rw', 'private')
            
            lines = []
            lines.append("# SNMP v2c Configuration - Auto-generated")
            lines.append(f"# Generated at: {datetime.now().isoformat()}")
            lines.append(f"rocommunity {community_ro} default")
            lines.append(f"rwcommunity {community_rw} default")
            
            sections['SNMP_V2_CONFIG'] = lines
        
        # Секция для SNMP v3
        elif snmp_version == 'v3':
            lines = []
            lines.append("# SNMP v3 Configuration - Auto-generated")
            lines.append(f"# Generated at: {datetime.now().isoformat()}")
            
            v3_security_name = data.get('v3_security_name', 'snmpuser')
            v3_security_level = data.get('v3_security_level', 'authPriv')
            v3_auth_protocol = data.get('v3_auth_protocol', 'SHA')
            v3_auth_password = data.get('v3_auth_password', '')
            v3_priv_protocol = data.get('v3_priv_protocol', 'AES')
            v3_priv_password = data.get('v3_priv_password', '')
            v3_context_name = data.get('v3_context_name', '')
            
            lines.append(f"# User: {v3_security_name}")
            lines.append(f"# Security Level: {v3_security_level}")
            if v3_auth_protocol:
                lines.append(f"# Auth: {v3_auth_protocol}")
            if v3_priv_protocol:
                lines.append(f"# Priv: {v3_priv_protocol}")
            lines.append("")
            
            # Обрабатываем группы
            snmp_groups = data.get('snmp_groups', [])
            group_lines = []
            for group in snmp_groups:
                group_name = group.get('group_name', 'default_group')
                security_model = group.get('security_model', 'usm')
                
                model_char = 'v' if security_model == 'usm' else security_model[0].upper()
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                sec_level = level_map.get(group.get('security_level', v3_security_level), 'auth')
                
                group_lines.append(f"group {group_name} {model_char} {sec_level}")
            
            if group_lines:
                lines.extend(group_lines)
                lines.append("")
            
            # Обрабатываем представления (views)
            snmp_views = data.get('snmp_views', [])
            view_lines = []
            for view in snmp_views:
                view_name = view.get('view_name', 'default_view')
                subtree = view.get('subtree', '1.3.6.1')
                mask = view.get('mask', '')
                view_type = view.get('type', 'included')
                
                include_char = 'i' if view_type == 'included' else 'e'
                mask_part = f' {mask}' if mask else ''
                
                view_lines.append(f"view {view_name} {include_char} {subtree}{mask_part}")
            
            if view_lines:
                lines.extend(view_lines)
                lines.append("")
            
            # Обрабатываем правила доступа (access)
            snmp_access = data.get('snmp_access', [])
            access_lines = []
            for access in snmp_access:
                group = access.get('group', 'default_group')
                context = access.get('context', 'default')
                sec_level = access.get('security_level', 'authNoPriv')
                read_view = access.get('read_view', 'default_view')
                write_view = access.get('write_view', 'none')
                notify_view = access.get('notify_view', 'none')
                
                level_map = {
                    'noAuthNoPriv': 'noauth',
                    'authNoPriv': 'auth',
                    'authPriv': 'priv'
                }
                level = level_map.get(sec_level, 'auth')
                
                access_lines.append(f"access {group} \"{context}\" {level} {read_view} {write_view} {notify_view}")
            
            if access_lines:
                lines.extend(access_lines)
                lines.append("")
            
            # Команда для создания пользователя
            if v3_auth_password:
                user_cmd_lines = []
                user_cmd_lines.append("# IMPORTANT: Create SNMP v3 user with the following command:")
                cmd = f"net-snmp-create-v3-user -{v3_security_level[0].lower()} "
                if v3_auth_protocol and v3_auth_password:
                    cmd += f"-a {v3_auth_protocol} -A {v3_auth_password} "
                if v3_priv_protocol and v3_priv_password and v3_security_level == 'authPriv':
                    cmd += f"-x {v3_priv_protocol} -X {v3_priv_password} "
                cmd += v3_security_name
                user_cmd_lines.append(f"# {cmd}")
                lines.extend(user_cmd_lines)
            
            sections['SNMP_V3_CONFIG'] = lines
        
        return sections
    
    def _merge_config(self, existing_lines: list, new_sections: dict) -> list:
        """
        Объединение существующей конфигурации с новыми секциями.
        Если секция существует - заменяем её, если нет - добавляем в конец.
        Если секция передана как пустой список - удаляем её.
        """
        SECTION_START_MARKER = "### BEGIN AUTO-GENERATED:"
        SECTION_END_MARKER = "### END AUTO-GENERATED ###"
        
        existing_sections, other_lines, section_positions = self._extract_sections(existing_lines)
        
        # Начинаем с других строк (вне секций)
        result_lines = other_lines[:]
        
        # Отслеживаем какие секции уже обработаны
        processed_sections = set()
        
        # Сортируем позиции секций по начальной линии
        sorted_positions = sorted(section_positions.items(), key=lambda x: x[1]['start'])
        
        for section_name, positions in sorted_positions:
            # Если у нас есть новая версия этой секции
            if section_name in new_sections:
                section_content = new_sections[section_name]
                
                # Если секция пустая - удаляем её (не добавляем в результат)
                if section_content == []:
                    processed_sections.add(section_name)
                    continue
                
                # Добавляем обновлённую секцию
                result_lines.append(SECTION_START_MARKER + section_name)
                for line in section_content:
                    if not (line.startswith(SECTION_START_MARKER) or line == SECTION_END_MARKER):
                        result_lines.append(line)
                result_lines.append(SECTION_END_MARKER)
                result_lines.append("")  # Пустая строка после секции
                processed_sections.add(section_name)
            else:
                # Сохраняем старую секцию как есть
                section_content = existing_sections[section_name]
                result_lines.extend(section_content)
                result_lines.append("")
        
        # Добавляем новые секции которых не было в оригинале
        for section_name, section_content in new_sections.items():
            if section_name not in processed_sections and section_content != []:
                result_lines.append(SECTION_START_MARKER + section_name)
                for line in section_content:
                    if not (line.startswith(SECTION_START_MARKER) or line == SECTION_END_MARKER):
                        result_lines.append(line)
                result_lines.append(SECTION_END_MARKER)
                result_lines.append("")
        
        return result_lines
    
    def _write_config(self, config_lines: list):
        """Запись конфигурации в файл."""
        try:
            # Убеждаемся что директория существует
            config_dir = os.path.dirname(str(self.snmpd_conf_path))
            Path(config_dir).mkdir(parents=True, exist_ok=True)
            
            with open(str(self.snmpd_conf_path), 'w') as f:
                f.write('\n'.join(config_lines))
            
            # Устанавливаем правильные права
            os.chmod(str(self.snmpd_conf_path), 0o640)
            
            logger.info(f"Configuration written to {str(self.snmpd_conf_path)}")
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
            'config_file': str(self.snmpd_conf_path),
            'config_exists': os.path.exists(str(self.snmpd_conf_path)),
            'backup_exists': os.path.exists(str(self.snmpd_conf_backup))
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
    parser = argparse.ArgumentParser(description='SNMP Config Service - listens to Redis stream and configures NET-SNMP')
    parser.add_argument('--redis-host', default=os.getenv('REDIS_HOST', 'localhost'), help='Redis host')
    parser.add_argument('--redis-port', type=int, default=int(os.getenv('REDIS_PORT', '6379')), help='Redis port')
    parser.add_argument('--redis-db', type=int, default=int(os.getenv('REDIS_DB', '0')), help='Redis database')
    parser.add_argument('--redis-password', default=os.getenv('REDIS_PASSWORD'), help='Redis password')
    parser.add_argument('--stream-name', default=os.getenv('REDIS_STREAM_NAME', 'commands'), help='Redis stream name')
    parser.add_argument('--consumer-group', default=os.getenv('CONSUMER_GROUP', 'snmp_config_group'), help='Consumer group name')
    parser.add_argument('--config-path', default=os.getenv('SNMP_CONFIG_PATH', '/etc/snmp'), help='Path to SNMP config directory')
    
    args = parser.parse_args()
    
    redis_host = args.redis_host
    redis_port = args.redis_port
    redis_db = args.redis_db
    redis_password = args.redis_password
    stream_name = args.stream_name
    consumer_group = args.consumer_group
    consumer_name = os.getenv('CONSUMER_NAME', f'snmp_consumer_{os.getpid()}')
    
    logger.info(f"Starting SNMP Config Service with config: "
               f"Redis={redis_host}:{redis_port}, Stream={stream_name}, ConfigPath={args.config_path}")
    
    try:
        service = SNMPConfigService(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_db=redis_db,
            redis_password=redis_password,
            stream_name=stream_name,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            config_path=args.config_path
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
