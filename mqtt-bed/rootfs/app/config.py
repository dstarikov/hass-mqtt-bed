# mqtt-bed config

# 7C:EC:79:FF:6D:02
BED_ADDRESS = "DC:BB:48:42:D9:3E"

MQTT_USERNAME = "mqttbed"
MQTT_PASSWORD = "mqtt-bed"
MQTT_SERVER = "homeassistant.local"
MQTT_SERVER_PORT = 1883
MQTT_TOPIC = "bed"

# Bed controller type, supported values are "serta", "jiecang" and "dewertokin"
BED_TYPE = "dewertokin"

# Don't worry about these unless you want to
MQTT_CHECKIN_TOPIC = "checkIn/bed"
MQTT_CHECKIN_PAYLOAD = "OK"
MQTT_ONLINE_PAYLOAD = "online"
MQTT_QOS = 0

# Extra debug messages
DEBUG = 1
