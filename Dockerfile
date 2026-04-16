FROM python:3.9-slim

WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y \
    snmpd \
    snmp \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Копирование requirements и установка зависимостей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода сервиса
COPY snmp_config_service.py .

# Создание директории для логов
RUN mkdir -p /var/log && touch /var/log/snmp_config_service.log

# Порт по умолчанию не нужен, сервис работает через Redis
EXPOSE 161/udp

# Запуск сервиса
CMD ["python", "snmp_config_service.py"]
