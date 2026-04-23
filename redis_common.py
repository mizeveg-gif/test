# redis_scada.py

import redis
import json
from datetime import datetime
from typing import Optional, List, Dict, Any, Generator
from dataclasses import dataclass, asdict
from enum import Enum
import uuid


# ========== Enums для типов ==========

class AlarmType(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class ProtocolType(str, Enum):
    NONE = "none"
    MODBUS = "modbus"
    OPCUA = "opcua"
    MQTT = "mqtt"
    S7 = "s7"


class MsgType(str, Enum):
    SYTEM = "system"
    DO = "digitalInput"
    DI = "digitalOutput"
    AO = "analogOutput"
    AI = "analogInput"


class CommandType(str, Enum):
    MODBUSREAD = "modbusRead"
    MODBUSWRITE = "modbuswrite"
    CONFIG_GENERAL_SNMP_UPDATE = "CONFIG_GENERAL_SNMP_UPDATE"
    EXECUTE = "execute"
    STOP = "stop"


# ========== Data Classes для сообщений ==========

@dataclass
class CommandMessage:
    """Команда для устройства"""
    id_msg: str
    id_device: str
    type_commands: CommandType
    data_command: Dict[str, Any]
    time: str
    
    @classmethod
    def create(cls, device_id: str, command_type: CommandType, data: Dict[str, Any]):
        return cls(
            id_msg=str(uuid.uuid4()),
            id_device=device_id,
            type_commands=command_type,
            data_command=data,
            time=datetime.now().isoformat()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['type_commands'] = self.type_commands.value
        result['data_command'] = json.dumps(self.data_command)
        return result


@dataclass
class RawDataMessage:
    """Сырые данные с устройства"""
    id_msg: str
    id_device: str
    type_protocol: ProtocolType
    type_msg: MsgType
    data: Dict[str, Any]
    time: str
    
    @classmethod
    def create(cls, device_id: str, protocol: ProtocolType, msg_type: MsgType, data: Dict[str, Any]):
        return cls(
            id_msg=str(uuid.uuid4()),
            id_device=device_id,
            type_protocol=protocol,
            type_msg=msg_type,
            data=data,
            time=datetime.now().isoformat()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['type_protocol'] = self.type_protocol.value
        result['type_msg'] = self.type_msg.value
        result['data'] = json.dumps(self.data)
        return result


@dataclass
class AlarmMessage:
    """Аварийное сообщение"""
    id_msg: str
    id_device: str
    type_alarm: AlarmType
    data: Dict[str, Any]
    time: str
    
    @classmethod
    def create(cls, device_id: str, alarm_type: AlarmType, data: Dict[str, Any]):
        return cls(
            id_msg=str(uuid.uuid4()),
            id_device=device_id,
            type_alarm=alarm_type,
            data=data,
            time=datetime.now().isoformat()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['type_alarm'] = self.type_alarm.value
        result['data'] = json.dumps(self.data)
        return result


# ========== Основной класс для работы с Redis Streams ==========

class RedisSCADAStreams:
    """Управление Redis Streams для SCADA системы"""
    
    # Имена потоков
    STREAM_COMMANDS = "stream:commands"
    STREAM_RAW_DATA = "stream:raw_data"
    STREAM_ALARMS = "stream:alarms"
    
    def __init__(self, host: str = '192.168.3.222', port: int = 6379, db: int = 0, password: str = None):
        """Подключение к Redis"""
        self.r = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            decode_responses=True
        )
        
        # Проверка подключения
        assert self.r.ping(), "Redis не доступен"
        print(f"✅ Connected to Redis at {host}:{port}")
    
    # ========== Commands Stream ==========
    
    def add_command(self, command: CommandMessage) -> str:
        """Добавить команду в поток"""
        return self.r.xadd(
            self.STREAM_COMMANDS,
            command.to_dict(),
            maxlen=10000,  # храним последние 10000 команд
            approximate=True
        )
    
    def add_command_simple(self, device_id: str, command_type: CommandType, data: Dict[str, Any]) -> str:
        """Упрощенное добавление команды"""
        command = CommandMessage.create(device_id, command_type, data)
        return self.add_command(command)
    
    def get_commands(self, count: int = 10, last_only: bool = True) -> List[Dict]:
        """Получить последние команды"""
        if last_only:
            results = self.r.xrevrange(self.STREAM_COMMANDS, '+', '-', count=count)
        else:
            results = self.r.xrange(self.STREAM_COMMANDS, '-', '+', count=count)
        
        return self._parse_messages(results)
    
    def get_commands_by_device(self, device_id: str, count: int = 10) -> List[Dict]:
        """Получить команды для конкретного устройства"""
        all_commands = self.get_commands(count=count * 10, last_only=True)
        return [cmd for cmd in all_commands if cmd.get('id_device') == device_id][:count]
    
    # ========== Raw Data Stream ==========
    
    def add_raw_data(self, raw_data: RawDataMessage) -> str:
        """Добавить сырые данные в поток"""
        return self.r.xadd(
            self.STREAM_RAW_DATA,
            raw_data.to_dict(),
            maxlen=50000,  # храним последние 50000 записей
            approximate=True
        )
    
    def add_raw_data_simple(self, device_id: str, protocol: ProtocolType, 
                            msg_type: MsgType, data: Dict[str, Any]) -> str:
        """Упрощенное добавление сырых данных"""
        raw_msg = RawDataMessage.create(device_id, protocol, msg_type, data)
        return self.add_raw_data(raw_msg)
    
    def get_raw_data(self, count: int = 10, last_only: bool = True) -> List[Dict]:
        """Получить последние сырые данные"""
        if last_only:
            results = self.r.xrevrange(self.STREAM_RAW_DATA, '+', '-', count=count)
        else:
            results = self.r.xrange(self.STREAM_RAW_DATA, '-', '+', count=count)
        
        return self._parse_messages(results)
    
    def get_raw_data_by_device(self, device_id: str, count: int = 10) -> List[Dict]:
        """Получить сырые данные для конкретного устройства"""
        all_data = self.get_raw_data(count=count * 10, last_only=True)
        return [data for data in all_data if data.get('id_device') == device_id][:count]
    
    def get_raw_data_by_protocol(self, protocol: ProtocolType, count: int = 10) -> List[Dict]:
        """Получить сырые данные по типу протокола"""
        all_data = self.get_raw_data(count=count * 10, last_only=True)
        return [data for data in all_data if data.get('type_protocol') == protocol.value][:count]
    
    # ========== Alarms Stream ==========
    
    def add_alarm(self, alarm: AlarmMessage) -> str:
        """Добавить аварию в поток"""
        return self.r.xadd(
            self.STREAM_ALARMS,
            alarm.to_dict(),
            maxlen=10000,
            approximate=True
        )
    
    def add_alarm_simple(self, device_id: str, alarm_type: AlarmType, data = Dict[str, Any]) -> str:
        """Упрощенное добавление аварии"""
        alarm = AlarmMessage.create(device_id, alarm_type, data)
        return self.add_alarm(alarm)
    
    def get_alarms(self, count: int = 10, last_only: bool = True) -> List[Dict]:
        """Получить последние аварии"""
        if last_only:
            results = self.r.xrevrange(self.STREAM_ALARMS, '+', '-', count=count)
        else:
            results = self.r.xrange(self.STREAM_ALARMS, '-', '+', count=count)
        
        return self._parse_messages(results)
    
    def get_alarms_by_device(self, device_id: str, count: int = 10) -> List[Dict]:
        """Получить аварии для конкретного устройства"""
        all_alarms = self.get_alarms(count=count * 10, last_only=True)
        return [alarm for alarm in all_alarms if alarm.get('id_device') == device_id][:count]
    
    def get_alarms_by_type(self, alarm_type: AlarmType, count: int = 10) -> List[Dict]:
        """Получить аварии по типу"""
        all_alarms = self.get_alarms(count=count * 10, last_only=True)
        return [alarm for alarm in all_alarms if alarm.get('type_alarm') == alarm_type.value][:count]
    
    # ========== Consumer Groups (для распределенной обработки) ==========
    
    def create_consumer_group(self, stream_name: str, group_name: str, start_id: str = '0'):
        """Создать группу потребителей"""
        try:
            self.r.xgroup_create(stream_name, group_name, id=start_id, mkstream=True)
            print(f"✅ Consumer group '{group_name}' created for '{stream_name}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
            print(f"ℹ️ Consumer group '{group_name}' already exists")
    
    def consume_stream(self, stream_name: str, group_name: str, consumer_name: str, 
                       count: int = 10, block: int = 1000) -> Generator:
        """
        Потребитель для обработки сообщений из потока
        Использование:
            for msg_id, data in consumer:
                process(data)
                r.xack(stream, group, msg_id)
        """
        while True:
            try:
                messages = self.r.xreadgroup(
                    group_name, consumer_name,
                    {stream_name: '>'},  # '>' - только новые сообщения
                    count=count,
                    block=block
                )
                
                if messages:
                    for stream_name, entries in messages:
                        for msg_id, data in entries:
                            yield msg_id, data
                else:
                    yield None, None
                    
            except redis.exceptions.ConnectionError:
                print("⚠️ Connection lost, reconnecting...")
                break
    
    # ========== Вспомогательные методы ==========
    
    def _parse_messages(self, results: List) -> List[Dict]:
        """Распарсить сообщения из Redis"""
        messages = []
        for msg_id, data in results:
            msg = {'id': msg_id}
            msg.update(data)
            
            # Распарсить JSON поля
            if 'data_command' in data:
                try:
                    msg['data_command'] = json.loads(data['data_command'])
                except:
                    pass
            
            if 'data' in data:
                try:
                    msg['data'] = json.loads(data['data'])
                except:
                    pass
            
            messages.append(msg)
        
        return messages
    
    def get_stream_length(self, stream_name: str) -> int:
        """Количество сообщений в потоке"""
        return self.r.xlen(stream_name)
    
    def trim_stream(self, stream_name: str, maxlen: int = 10000):
        """Ограничить размер потока"""
        self.r.xtrim(stream_name, maxlen=maxlen, approximate=True)
    
    def get_stream_info(self, stream_name: str) -> Dict:
        """Информация о потоке"""
        return self.r.xinfo_stream(stream_name)
    
    def delete_stream(self, stream_name: str):
        """Удалить поток (осторожно!)"""
        self.r.delete(stream_name)
