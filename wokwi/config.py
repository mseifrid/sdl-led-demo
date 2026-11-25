# Settings for the simulated device. Edit this file inside YOUR Wokwi copy.
# Use the same values as the .env file next to the notebook.
#
# Warning: saved Wokwi projects can be opened by anyone with the link, so use a
# broker login made for this class, never a personal password.

PICO_ID = "change-me"  # pick something unique, e.g. "wokwi-yourname"

MQTT_HOST = "broker.hivemq.com"  # your broker's host name
MQTT_PORT = 8883                 # 8883 = encrypted (TLS)
MQTT_TLS = True
MQTT_USER = ""                   # leave "" for a public broker with no login
MQTT_PASS = ""

# Wokwi's simulated Wi-Fi network: no password. Leave as is.
WIFI_SSID = "Wokwi-GUEST"
WIFI_PASS = ""
