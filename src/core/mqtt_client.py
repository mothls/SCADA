import logging
import threading
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

class MQTTClient:
    def __init__(self, broker_ip="127.0.0.1", broker_port=1883, topic_prefix="lab/plug"):
        self.broker = broker_ip
        self.port = broker_port
        self.topic_prefix = topic_prefix.rstrip("/")
        
        # >>> ИНТЕГРАЦИЯ ВЭУ: Расширение состояния для телеметрии ветрогенератора
        self._state = {
            "power": None,           # Для розетки Sonoff
            "wind_rpm": None,        # Скорость ветрогенератора
            "wind_brake": None,      # Состояние балласта
            "wind_status": None      # Статус подключения ESP32
        }
        self._lock = threading.Lock()

        logger.debug(f"MQTT Client init: broker={self.broker}, topic_prefix={self.topic_prefix}")
        
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_publish = self._on_publish

    def connect(self):
        logger.info(f"Connecting to {self.broker}:{self.port}...")
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_start()
            logger.debug("MQTT loop started")
        except Exception as e:
            logger.error(f"MQTT connect failed: {e}")

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
            logger.info("MQTT disconnected")
        except Exception as e:
            logger.error(f"MQTT disconnect error: {e}")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            topic = f"stat/{self.topic_prefix}/POWER"
            logger.info(f"Connected! Subscribing to: {topic}")
            self.client.subscribe(topic)
            
            # >>> ИНТЕГРАЦИЯ ВЭУ: Подписка на топики ветрогенератора
            self.client.subscribe("lab/wind_turbine/rpm", qos=1)
            self.client.subscribe("lab/wind_turbine/brake_cmd", qos=1)
            self.client.subscribe("lab/wind_turbine/status", qos=1)
            logger.info("Subscribed to wind turbine topics")
        else:
            logger.error(f"MQTT connect failed with code: {reason_code}")

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        logger.debug(f"Subscription confirmed: mid={mid}, reason={reason_codes}")

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        logger.debug(f"Publish confirmed: mid={mid}")

    def _on_message(self, client, userdata, msg):
        """Обработчик входящих MQTT-сообщений (исправленная версия)"""
        try:
            payload = msg.payload.decode().strip()
            logger.debug(f"MQTT message: {msg.topic} = {payload}")
            
            # Существующая логика для розетки
            if msg.topic.endswith("/POWER"):
                with self._lock:
                    self._state["power"] = payload.upper()
            
            # >>> НОВАЯ ЛОГИКА для ветрогенератора
            elif msg.topic == "lab/wind_turbine/rpm":
                rpm = float(payload)
                with self._lock:
                    self._state["wind_rpm"] = rpm
                logger.debug(f"Wind RPM updated: {rpm}")
                
            elif msg.topic == "lab/wind_turbine/brake_cmd":
                with self._lock:
                    self._state["wind_brake"] = payload.upper()
                logger.debug(f"Wind brake state: {payload}")
                
            elif msg.topic == "lab/wind_turbine/status":
                with self._lock:
                    self._state["wind_status"] = payload.upper()
                logger.debug(f"Wind status: {payload}")
                
        except ValueError as e:
            logger.warning(f"MQTT value parse error: {e}, payload: {payload}")
        except Exception as e:
            logger.error(f"MQTT parse error: {e}")
    
    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        logger.warning(f"MQTT disconnected: {reason_code}")

    # ==================== МЕТОДЫ ДЛЯ РОЗЕТКИ (существующие) ====================
    def get_state(self):
        with self._lock:
            return self._state.get("power")

    def set_state(self, on: bool):
        cmd = "ON" if on else "OFF"
        topic = f"cmnd/{self.topic_prefix}/POWER"
        self.client.publish(topic, cmd, qos=1)
        logger.info(f"MQTT command sent: {topic} = {cmd}")
        with self._lock:
            self._state["power"] = cmd

    # ==================== МЕТОДЫ ДЛЯ ВЭУ (НОВЫЕ) ====================
    def get_wind_rpm(self):
        """Получение текущей частоты вращения ротора"""
        with self._lock:
            return self._state.get("wind_rpm")

    def get_wind_brake_state(self):
        """Получение состояния балластной нагрузки"""
        with self._lock:
            return self._state.get("wind_brake")

    def get_wind_status(self):
        """Получение статуса подключения контроллера ВЭУ"""
        with self._lock:
            return self._state.get("wind_status")
