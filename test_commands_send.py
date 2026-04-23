from redis_common import (
    RedisSCADAStreams, 
    CommandType, 
    ProtocolType, 
    MsgType, 
    AlarmType
)
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

import time
import random
# ========== Подключение ==========
scada = RedisSCADAStreams(host='192.168.3.228', port=6380)

while True:
    #scada.add_raw_data_simple(
       # device_id="plc_003",
      #  protocol = ProtocolType.MODBUS,
     #   msg_type = MsgType.AO,
     #)
    #print("send")
    builder = SNMPCommandBuilder.from_v2_config(
        community_ro="public",
        community_rw="private",
        id_device=0
    )
    
    command = builder.build()
    scada.add_command_simple(device_id=command['ID_DEVICE'], command_type=CommandType.CONFIG_GENERAL_SNMP_UPDATE, data=command['DATA'])
    print("send")
    time.sleep(1)
    


