import time
import math
import random
import logging

logger = logging.getLogger(__name__)


class MockConverter:
    def __init__(self, device_id, unit):
        self.device_id = device_id
        self.unit = unit
        self._cached_output_enabled = True
        self.start_time = time.time()
        self.hall_ser = "mock_serial" if device_id == "solar_converter" else None

    def read_voltage_out(self):
        t = time.time() - self.start_time
        return 24.0 + 0.5 * math.sin(t / 10.0)

    def read_current_out(self):
        t = time.time() - self.start_time
        return 4.0 + 2.0 * math.sin(t / 5.0)

    def read_temperature(self):
        return 45.0 + random.uniform(-1, 1)

    def _read_holding_register(self, addr):
        return 1 if self._cached_output_enabled else 0

    def output_enable(self, state):
        self._cached_output_enabled = state
        return True

    def read_output_enabled(self):
        return self._cached_output_enabled

    def write_output_enable(self, state):
        return self.output_enable(state)

    def _update_hall_current(self):
        pass

    def get_hall_current(self):
        if self.device_id != "solar_converter":
            return 0.0
        t = time.time() - self.start_time
        return 1.5 * math.sin(t / 7.0)

    def close(self):
        pass


class MockMQTT:
    def __init__(self):
        self.start_time = time.time()
        self._load_state = "OFF"

    def connect(self):
        logger.info("[SIMULATION] Mock MQTT connected")

    def disconnect(self):
        logger.info("[SIMULATION] Mock MQTT disconnected")

    def get_state(self):
        if int(time.time() - self.start_time) % 30 < 15:
            self._load_state = "ON"
        else:
            self._load_state = "OFF"
        return self._load_state

    def set_state(self, state):
        self._load_state = "ON" if state else "OFF"
        logger.info("[SIMULATION] Load state changed to %s", self._load_state)

    def get_wind_rpm(self):
        t = time.time() - self.start_time
        return 800.0 + 300.0 * math.sin(t / 15.0)

    def get_wind_brake_state(self):
        return "IDLE"

    def get_wind_status(self):
        return "ONLINE"