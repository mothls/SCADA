import threading
import logging

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self):
        self._lock = threading.Lock()
        
        # Словарь текущего состояния системы
        self._state = {
            # === Солнечный конвертер ===
            "solar_converter_temp": 0.0,
            "solar_converter_vout": 0.0,
            "solar_converter_iout": 0.0,
            "solar_converter_vin": 0.0,
            "solar_converter_iin": 0.0,
            "solar_converter_output_enabled": False,
            
            # === Ветряной конвертер ===
            "wind_converter_temp": 0.0,
            "wind_converter_vout": 0.0,
            "wind_converter_iout": 0.0,
            "wind_converter_vin": 0.0,
            "wind_converter_iin": 0.0,
            "wind_converter_output_enabled": False,
            
            # === Ветрогенератор (ESP32 / MQTT) ===
            "wind_rpm": 0.0,
            "wind_brake_state": "IDLE",
            "wind_status": "OFFLINE",
            "wind_vout": 0.0,
            "wind_iout": 0.0,
            "wind_power": 0.0,
            "wind_attack_angle": 0.0,
            
            # === Аккумулятор (Датчик Холла COM5) ===
            "battery_voltage": 0.0,
            "battery_current": 0.0,
            "battery_status": "IDLE",  # CHARGING / DISCHARGING / IDLE
        
            # === SOC батареи (добавить сюда) ===
            "battery_soc": 100.0,
            "battery_soc_initialized": False,
            "battery_energy_spent_ah": 0.0,
            
            # === Нагрузка и система ===
            "load_state": "OFF",
            "load_temperature": 25.0,  # <-- ЗАГЛУШКА
            "system_mode": "MANUAL"
        }
        
        self._pending_commands = {}
        self._safety_flags = {}

    # ==================== БАЗОВЫЕ МЕТОДЫ ====================
    def update(self, key, value):
        with self._lock:
            old = self._state.get(key)
            self._state[key] = value
            if old != value:
                logger.debug(f"State updated: {key} = {value}")

    def get(self, key, default=None):
        with self._lock:
            return self._state.get(key, default)

    def get_all(self):
        with self._lock:
            return dict(self._state)

    # ==================== ВЕТРОГЕНЕРАТОР ====================
    def update_wind_telemetry(self, rpm=None, brake_state=None, status=None, 
                            voltage=None, current=None, attack_angle=None):
        with self._lock:
            if rpm is not None: 
                self._state["wind_rpm"] = float(rpm)
            if brake_state is not None: 
                self._state["wind_brake_state"] = str(brake_state).upper()
            if status is not None: 
                self._state["wind_status"] = str(status).upper()
            if voltage is not None: 
                self._state["wind_vout"] = float(voltage)
            if current is not None: 
                self._state["wind_iout"] = float(current)
            if attack_angle is not None:
                self._state["wind_attack_angle"] = float(attack_angle)
            
            # Расчёт мощности
            if self._state["wind_vout"] > 0 and self._state["wind_iout"] > 0:
                self._state["wind_power"] = (
                    self._state["wind_vout"] * self._state["wind_iout"]
                )

    def get_wind_rpm(self):
        with self._lock: 
            return self._state.get("wind_rpm", 0.0)

    def get_wind_brake_state(self):
        with self._lock: 
            return self._state.get("wind_brake_state", "IDLE")

    def get_wind_status(self):
        with self._lock: 
            return self._state.get("wind_status", "OFFLINE")

    def get_wind_power(self):
        with self._lock: 
            return self._state.get("wind_power", 0.0)
    
    def get_wind_attack_angle(self):
        with self._lock:
            return self._state.get("wind_attack_angle", 0.0)

    def is_wind_emergency(self):
        with self._lock:
            return (
                self._state.get("wind_brake_state") == "EMERGENCY" or
                self._state.get("wind_rpm", 0) > 1500
            )

    # ==================== АККУМУЛЯТОР ====================
    def update_battery(self, voltage=None, current=None):
        with self._lock:
            if voltage is not None:
                self._state["battery_voltage"] = float(voltage)
            if current is not None:
                self._state["battery_current"] = float(current)
                # Порог 0.1А для фильтрации шума датчика
                if self._state["battery_current"] > 0.1:
                    self._state["battery_status"] = "CHARGING"
                elif self._state["battery_current"] < -0.1:
                    self._state["battery_status"] = "DISCHARGING"
                else:
                    self._state["battery_status"] = "IDLE"

    def get_battery_voltage(self):
        with self._lock: 
            return self._state.get("battery_voltage", 0.0)

    def get_battery_current(self):
        with self._lock: 
            return self._state.get("battery_current", 0.0)

    def get_battery_status(self):
        with self._lock: 
            return self._state.get("battery_status", "IDLE")

    # ==================== КОМАНДЫ И БЕЗОПАСНОСТЬ ====================
    def set_pending(self, key, value):
        with self._lock: 
            self._pending_commands[key] = value

    def get_pending(self):
        with self._lock: 
            return dict(self._pending_commands)

    def clear_pending(self):
        with self._lock: 
            self._pending_commands.clear()

    def set_safety_flag(self, key, value):
        with self._lock: 
            self._safety_flags[key] = value

    def get_safety_flag(self, key) -> bool: 
        """Получить конкретный флаг безопасности"""
        with self._lock: 
            return self._safety_flags.get(key, False)

    def get_safety_flags(self):
        with self._lock: 
            return dict(self._safety_flags)

    def clear_safety_flag(self, key):
        with self._lock: 
            self._safety_flags.pop(key, None)

    def clear_safety_flags(self):  
        """Очистить все флаги безопасности"""
        with self._lock: 
            self._safety_flags.clear()

    def has_critical_alerts(self):
        with self._lock: 
            return any(self._safety_flags.values()) or self.is_wind_emergency()