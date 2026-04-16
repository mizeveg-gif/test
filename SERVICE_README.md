# SNMP Configuration Service

Сервис для автоматической конфигурации NET-SNMP через команды из Redis stream.

## Описание

Сервис подписывается на Redis stream `commands` и обрабатывает команды для настройки SNMP. 
Поддерживает конфигурацию SNMP v2c и SNMP v3 с полным управлением группами, представлениями (views) и правами доступа.

## Возможности

- ✅ Подписка на Redis stream с использованием consumer groups
- ✅ Обработка команд конфигурации SNMP v2c и v3
- ✅ Автоматическая генерация файла `/etc/snmp/snmpd.conf`
- ✅ Создание резервных копий конфигурации
- ✅ Автоматический перезапуск службы snmpd
- ✅ Логирование всех операций
- ✅ Обработка ошибок и перемещение проблемных сообщений в error stream
- ✅ Поддержка Docker и docker-compose

## Поддерживаемые команды

### CONFIG_GENERAL_SNMP_UPDATE
Обновление полной конфигурации SNMP на основе переданных данных.

### CONFIG_SNMP_RESTART
Перезапуск службы SNMP без изменения конфигурации.

### CONFIG_SNMP_STATUS
Получение текущего статуса службы SNMP.

## Установка

### Вариант 1: Установка через pip

```bash
# Установка зависимостей
pip install -r requirements.txt

# Копирование файла конфигурации
cp config.env.example /etc/snmp-config-service/config.env

# Редактирование конфигурации
nano /etc/snmp-config-service/config.env

# Копирование сервиса в системную директорию
sudo cp snmp_config_service.py /opt/snmp-config-service/
sudo cp snmp_config_service.service /etc/systemd/system/

# Перезагрузка systemd и запуск сервиса
sudo systemctl daemon-reload
sudo systemctl enable snmp_config_service
sudo systemctl start snmp_config_service

# Проверка статуса
sudo systemctl status snmp_config_service
```

### Вариант 2: Запуск через Docker Compose

```bash
# Запуск всех сервисов
docker-compose up -d

# Просмотр логов
docker-compose logs -f snmp-config-service

# Остановка
docker-compose down
```

## Конфигурация

Переменные окружения (или файл `config.env`):

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| REDIS_HOST | localhost | Хост Redis |
| REDIS_PORT | 6379 | Порт Redis |
| REDIS_DB | 0 | База данных Redis |
| REDIS_PASSWORD | - | Пароль Redis (опционально) |
| REDIS_STREAM_NAME | commands | Имя stream для подписки |
| CONSUMER_GROUP | snmp_config_group | Имя группы потребителей |
| CONSUMER_NAME | snmp_consumer_<pid> | Имя потребителя |

## Формат команды

Команды отправляются в Redis stream в формате JSON:

```json
{
  "ID_DEVICE": 1,
  "TYPE_COMMANDS": "CONFIG_GENERAL_SNMP_UPDATE",
  "DATA": {
    "snmp_version": "v2c",
    "community_ro": "public",
    "community_rw": "private"
  },
  "TIME": "2024-01-01T12:00:00"
}
```

### Пример для SNMP v3

```json
{
  "ID_DEVICE": 2,
  "TYPE_COMMANDS": "CONFIG_GENERAL_SNMP_UPDATE",
  "DATA": {
    "snmp_version": "v3",
    "v3_security_name": "admin",
    "v3_security_level": "authPriv",
    "v3_auth_protocol": "SHA",
    "v3_auth_password": "authPassword123",
    "v3_priv_protocol": "AES",
    "v3_priv_password": "privPassword123",
    "snmp_groups": [
      {
        "group_name": "admin_group",
        "access_rights": "read-write",
        "security_model": "usm",
        "security_level": "authPriv"
      }
    ],
    "snmp_views": [
      {
        "view_name": "full_view",
        "subtree": "1.3.6.1",
        "type": "included"
      }
    ],
    "snmp_access": [
      {
        "group": "admin_group",
        "context": "default",
        "security_level": "authPriv",
        "read_view": "full_view",
        "write_view": "full_view",
        "notify_view": "full_view"
      }
    ]
  },
  "TIME": "2024-01-01T12:00:00"
}
```

## Отправка команд

### Через Python

```python
import redis
import json
from datetime import datetime

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

command = {
    'ID_DEVICE': 1,
    'TYPE_COMMANDS': 'CONFIG_GENERAL_SNMP_UPDATE',
    'DATA': {
        'snmp_version': 'v2c',
        'community_ro': 'public',
        'community_rw': 'private'
    },
    'TIME': datetime.now().isoformat()
}

# Отправка в stream
r.xadd('commands', {'data': json.dumps(command)})
```

### Через redis-cli

```bash
redis-cli XADD commands '*' data '{"ID_DEVICE":1,"TYPE_COMMANDS":"CONFIG_GENERAL_SNMP_UPDATE","DATA":{"snmp_version":"v2c","community_ro":"public"},"TIME":"2024-01-01T12:00:00"}'
```

### Использование библиотеки snmp_command_builder

```python
from snmp_command_builder import SNMPCommandBuilder, build_snmp_v2_command

# Быстрое создание команды v2
command = build_snmp_v2_command(
    device_id=1,
    community_ro='public',
    community_rw='private'
)

# Отправка через Redis
import redis
r = redis.Redis(host='localhost', port=6379)
r.xadd('commands', {'data': command.to_json()})
```

## Архитектура

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────────┐
│ Command Sender  │────▶│ Redis Stream │────▶│ SNMP Config      │
│ (библиотека или │     │  commands    │     │ Service          │
│  другой сервис) │     │              │     │                  │
└─────────────────┘     └──────────────┘     └──────────────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────┐
                                         │ /etc/snmp/       │
                                         │ snmpd.conf       │
                                         └──────────────────┘
                                                    │
                                                    ▼
                                         ┌──────────────────┐
                                         │ systemctl        │
                                         │ restart snmpd    │
                                         └──────────────────┘
```

## Логи

Логи сервиса записываются в:
- Файл: `/var/log/snmp_config_service.log`
- Systemd journal: `journalctl -u snmp_config_service -f`
- Docker: `docker-compose logs -f snmp-config-service`

## Обработка ошибок

- Неверный формат JSON → сообщение перемещается в `commands:errors`
- Ошибка подключения к Redis → автоматическое переподключение
- Ошибка перезапуска snmpd → конфигурация сохраняется, предупреждение в лог
- Неподдерживаемая команда → предупреждение в лог, сообщение подтверждается

## Безопасность

- Сервис требует прав root для записи в `/etc/snmp/` и перезапуска службы
- Рекомендуется использовать отдельного пользователя Redis с ограниченными правами
- Для SNMP v3 используйте сложные пароли и уровень безопасности authPriv
- Файлы конфигурации создаются с правами 640

## Мониторинг

Проверка статуса сервиса:

```bash
# Systemd
systemctl is-active snmp_config_service

# Docker
docker-compose ps

# Отправка команды статуса
redis-cli XADD commands '*' data '{"TYPE_COMMANDS":"CONFIG_SNMP_STATUS","TIME":"'$(date -Iseconds)'"}'
```

## Требования

- Python 3.8+
- Redis 5+
- NET-SNMP (snmpd)
- Права root для работы с конфигурацией SNMP

## Лицензия

MIT
