# SNMP Command Builder Library

Библиотека для построения команд конфигурации SNMP v2c и SNMP v3 для отправки через Redis stream.

## Установка

Просто скопируйте файл `snmp_command_builder.py` в ваш проект.

```bash
pip install # не требуется, библиотека использует только стандартные модули Python
```

## Быстрый старт

### SNMP v2c конфигурация

```python
from snmp_command_builder import build_snmp_v2_command
import json

# Простое создание команды для SNMP v2c
command = build_snmp_v2_command(
    community_ro="public",
    community_rw="private",
    id_device=1
)

print(json.dumps(command, indent=2))
```

### SNMP v3 конфигурация

```python
from snmp_command_builder import build_snmp_v3_command, SecurityLevel, AuthProtocol, PrivProtocol
import json

# SNMP v3 с authPriv (аутентификация + шифрование)
command = build_snmp_v3_command(
    security_name="admin_user",
    security_level=SecurityLevel.AUTH_PRIV,
    id_device=2,
    auth_protocol=AuthProtocol.SHA_256,
    auth_password="auth_secret",
    priv_protocol=PrivProtocol.AES_256,
    priv_password="priv_secret",
    context_name="network_context"
)

print(json.dumps(command, indent=2))
```

## Продвинутое использование

### Использование builder'а напрямую

```python
from snmp_command_builder import SNMPCommandBuilder

builder = SNMPCommandBuilder.from_v2_config(
    community_ro="public",
    community_rw="private",
    id_device=1
)

# Получить как dict
command = builder.build()

# Получить как JSON строку
json_string = builder.to_json(indent=2)

# Получить формат для Redis stream
stream_name, message = builder.to_redis_stream_format()
```

### Отправка в Redis stream

```python
import redis
from snmp_command_builder import SNMPCommandBuilder

# Подключение к Redis
r = redis.Redis(host='localhost', port=6379)

# Создание команды
builder = SNMPCommandBuilder.from_v3_config(
    security_name="admin",
    security_level=SecurityLevel.AUTH_PRIV,
    auth_protocol=AuthProtocol.SHA,
    auth_password="password123",
    priv_protocol=PrivProtocol.AES,
    priv_password="password456"
)

# Отправка в Redis stream
stream_name, message = builder.to_redis_stream_format()
r.xadd(stream_name, message)
```

### Кастомные группы, представления и доступ

```python
from snmp_command_builder import (
    SNMPCommandBuilder,
    SNMPGroup,
    SNMPView,
    SNMPAccess,
    AccessRights,
    ViewType,
    SecurityLevel
)

custom_groups = [
    SNMPGroup(
        group_name="my_admin_group",
        access_rights=AccessRights.READ_WRITE,
        views=["my_view"],
        notify_access=True
    )
]

custom_views = [
    SNMPView(
        view_name="my_view",
        subtree="1.3.6.1.2.1",
        mask="ff",
        type=ViewType.INCLUDED
    )
]

custom_access = [
    SNMPAccess(
        group="my_admin_group",
        context="default",
        security_level=SecurityLevel.AUTH_PRIV,
        read_view="my_view",
        write_view="my_view",
        notify_view="my_view"
    )
]

builder = SNMPCommandBuilder.from_v2_config(
    community_ro="public",
    community_rw="private",
    id_device=1,
    snmp_groups=custom_groups,
    snmp_views=custom_views,
    snmp_access=custom_access
)

command = builder.build()
```

## API Reference

### Enumerations

#### `SNMPVersion`
- `V2C` - SNMP v2c
- `V3` - SNMP v3

#### `SecurityLevel` (SNMP v3)
- `NO_AUTH_NO_PRIV` - noAuthNoPriv
- `AUTH_NO_PRIV` - authNoPriv
- `AUTH_PRIV` - authPriv

#### `AuthProtocol` (SNMP v3)
- `MD5`, `SHA`, `SHA_224`, `SHA_256`, `SHA_384`, `SHA_512`

#### `PrivProtocol` (SNMP v3)
- `DES`, `AES`, `AES_128`, `AES_192`, `AES_256`

#### `AccessRights`
- `READ_ONLY`, `READ_WRITE`

#### `ViewType`
- `INCLUDED`, `EXCLUDED`

### Data Classes

#### `SNMPGroup`
- `group_name`: str
- `access_rights`: AccessRights
- `views`: List[str]
- `security_model`: SecurityModel (default: USM)
- `notify_access`: bool (default: True)

#### `SNMPView`
- `view_name`: str
- `subtree`: str
- `mask`: str (default: "ff")
- `type`: ViewType (default: INCLUDED)

#### `SNMPAccess`
- `group`: str
- `context`: str
- `security_level`: SecurityLevel
- `read_view`: str
- `write_view`: str
- `notify_view`: str

### Основные классы и функции

#### `SNMPCommandBuilder`

Главный класс для построения команд.

**Методы класса:**
- `from_v2_config(community_ro, community_rw, id_device=0, ...)` - создать для SNMP v2c
- `from_v3_config(security_name, security_level, id_device=0, ...)` - создать для SNMP v3

**Методы экземпляра:**
- `build()` - вернуть команду как dict
- `to_json(indent=2)` - вернуть команду как JSON строку
- `to_redis_stream_format()` - вернуть tuple (stream_name, message) для Redis

#### `build_snmp_v2_command(community_ro, community_rw, id_device=0)`
Быстрая функция для создания SNMP v2c команды.

#### `build_snmp_v3_command(security_name, security_level, id_device=0, ...)`
Быстрая функция для создания SNMP v3 команды.

## Формат выходных данных

Библиотека генерирует команду следующего формата:

```json
{
  "ID_DEVICE": 0,
  "TYPE_COMMANDS": "CONFIG_GENERAL_SNMP_UPDATE",
  "DATA": {
    "snmp_version": "v2c/v3",
    "community_ro": "read-only community",
    "community_rw": "read-write community",
    "v3_security_name": "security name",
    "v3_security_level": "noAuthNoPriv/authNoPriv/authPriv",
    "v3_auth_protocol": "MD5/SHA/...",
    "v3_auth_password": "auth password",
    "v3_priv_protocol": "DES/AES/...",
    "v3_priv_password": "priv password",
    "v3_context_name": "context name",
    "snmp_groups": [...],
    "snmp_views": [...],
    "snmp_access": [...]
  },
  "TIME": "2026-04-16T08:36:12.187470Z"
}
```

## Тестирование

Запустите тесты:

```bash
python test_snmp_builder.py
```

## Лицензия

MIT
