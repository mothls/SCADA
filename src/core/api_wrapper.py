from core.state_manager import StateManager

class Sensors:
    """Датчики системы (чтение параметров из кэша StateManager)"""
    def __init__(self, state: StateManager):
        self._state = state

    # === СОЛНЕЧНЫЙ КОНВЕРТЕР ===
    def get_solar_temperature(self) -> float: return self._state.get("solar_converter_temp", 0.0)
    def get_solar_voltage_out(self) -> float: return self._state.get("solar_converter_vout", 0.0)
    def get_solar_current_out(self) -> float: return self._state.get("solar_converter_iout", 0.0)
    def get_solar_voltage_in(self) -> float: return self._state.get("solar_converter_vin", 0.0)
    def get_solar_current_in(self) -> float: return self._state.get("solar_converter_iin", 0.0)
    def get_solar_power_out(self) -> float: return self.get_solar_voltage_out() * self.get_solar_current_out()
    def is_solar_output_enabled(self) -> bool: return self._state.get("solar_converter_output_enabled", False)

    # === ВЕТРОВОЙ КОНВЕРТЕР ===
    def get_wind_temperature(self) -> float: return self._state.get("wind_converter_temp", 0.0)
    def get_wind_voltage_out(self) -> float: return self._state.get("wind_converter_vout", 0.0)
    def get_wind_current_out(self) -> float: return self._state.get("wind_converter_iout", 0.0)
    def get_wind_voltage_in(self) -> float: return self._state.get("wind_converter_vin", 0.0)
    def get_wind_current_in(self) -> float: return self._state.get("wind_converter_iin", 0.0)
    def get_wind_power_out(self) -> float: return self.get_wind_voltage_out() * self.get_wind_current_out()
    def is_wind_output_enabled(self) -> bool: return self._state.get("wind_converter_output_enabled", False)

    # === НАГРУЗКА (розетка) ===
    def get_load_state(self) -> str: return self._state.get("load_state", "UNKNOWN")
    def is_load_on(self) -> bool: return self.get_load_state() == "ON"
    def get_load_temperature(self) -> float:return self._state.get("load_temperature", 25.0)
    def get_load_power(self) -> float:    
        u = self.get_battery_voltage()
        i = self._state.get("load_current", 0.0)
        return u * i   
    # === АККУМУЛЯТОР ===
    def get_battery_voltage(self) -> float: return self._state.get("battery_voltage", 0.0)
    def get_battery_current(self) -> float: return self._state.get("battery_current", 0.0)  
    def get_battery_status(self) -> str: return self._state.get("battery_status", "IDLE")
    def get_battery_soc(self) -> float:return self._state.get("battery_soc", 0.0)
    def get_battery_capacity_remaining(self) -> float:
        soc = self.get_battery_soc()
        c_nom = 60.0  # или брать из конфига
        return (soc / 100.0) * c_nom
    # === ВЕТРОГЕНЕРАТОР (RPM, балласт, угол) ===
    def get_wind_rpm(self) -> float:
        """Частота вращения ротора (из MQTT)"""
        return self._state.get("wind_rpm", 0.0)
    
    def get_wind_brake_state(self) -> str:
        """Состояние балласта (из MQTT)"""
        return self._state.get("wind_brake_state", "IDLE")
    
    def get_wind_attack_angle(self) -> float:
        """Угол атаки лопастей (заглушка)"""
        return self._state.get("wind_attack_angle", 0.0)

class Actuators:
    """Исполнительные устройства (управление через Modbus/MQTT)"""
    def __init__(self, state: StateManager, modbus_clients: dict = None, mqtt_client=None):
        self._state = state
        self._modbus = modbus_clients or {}
        self._mqtt = mqtt_client

    # === УПРАВЛЕНИЕ РОЗЕТКОЙ (через арбитр + MQTT) ===
    def suggest_load(self, on: bool): 
        self._state.set_pending("load", on)
    
    def turn_load_on(self): self.suggest_load(True)
    def turn_load_off(self): self.suggest_load(False)

    # === УПРАВЛЕНИЕ КОНВЕРТЕРАМИ (прямой Modbus) ===
    def enable_solar_output(self):
        if "solar_converter" in self._modbus:
            success = self._modbus["solar_converter"].output_enable(True)
            if success: self._state.update("solar_converter_output_enabled", True)
            return success
        return False

    def disable_solar_output(self):
        if "solar_converter" in self._modbus:
            success = self._modbus["solar_converter"].output_enable(False)
            if success: self._state.update("solar_converter_output_enabled", False)
            return success
        return False

    def enable_wind_output(self):
        if "wind_converter" in self._modbus:
            success = self._modbus["wind_converter"].output_enable(True)
            if success: self._state.update("wind_converter_output_enabled", True)
            return success
        return False

    def disable_wind_output(self):
        if "wind_converter" in self._modbus:
            success = self._modbus["wind_converter"].output_enable(False)
            if success: self._state.update("wind_converter_output_enabled", False)
            return success
        return False

    # === ВСПОМОГАТЕЛЬНЫЙ МЕТОД ДЛЯ УСТАНОВКИ ПРЕДЕЛОВ ===
    def _set_converter_limits(self, dev_id: str, voltage: float, current: float) -> dict:
        client = self._modbus.get(dev_id)
        if not client:
            return {"success": False, "error": f"Клиент {dev_id} не найден"}
        try:
            ok = client.set_voltage_and_current(voltage, current)
            if ok:
                client.output_enable(True)  # Авто-включение после установки уставок
            return {"success": ok, "message": f"{dev_id}: V={voltage:.2f}V, I={current:.3f}A"}
        except Exception as e:
            return {"success": False, "error": str(e)} 

        # === УПРАВЛЕНИЕ ВЕТРОГЕНЕРАТОРОМ ===
    def set_wind_attack_angle(self, angle: float) -> dict:
        """Установка угла атаки лопастей (заглушка - нет реального привода)"""
        if not (-90 <= angle <= 90):
            return {"success": False, "error": "Диапазон: -90..90 градусов"}
        self._state.update("wind_attack_angle", angle)
        return {"success": True, "message": f"Угол атаки установлен: {angle}°"}

    def set_wind_brake(self, enabled: bool) -> dict:
        """Включение/выключение балласта ветрогенератора (через MQTT)"""
        if not self._mqtt:
            return {"success": False, "error": "MQTT не подключен"}
        try:
            cmd = "BRAKE_ON" if enabled else "BRAKE_OFF"
            topic = f"cmnd/lab/wind_turbine/brake_cmd"
            self._mqtt.client.publish(topic, cmd, qos=1)
            self._state.update("wind_brake_setpoint", cmd)
            return {"success": True, "message": f"Балласт: {cmd}"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class System:
    def __init__(self):
        self._log_callback = None

    def set_log_callback(self, callback):
        self._log_callback = callback

    def log(self, msg: str):
        print(f"[API SYSTEM LOG] {msg}") 
        if self._log_callback:
            try:
                self._log_callback(msg)
            except Exception as e:
                print(f"[ERROR] Log callback failed: {e}")


class API:
    """
    Единый программный интерфейс для студенческих алгоритмов.
    """
    def __init__(self, state: StateManager, modbus_clients: dict = None, mqtt_client=None):
        self.sensors = Sensors(state)
        self.actuators = Actuators(state, modbus_clients, mqtt_client)
        self.system = System()

    # ==================== УДОБНЫЕ МЕТОДЫ ДЛЯ ПЕСОЧНИЦЫ ====================
    
    def set_solar_limits(self, voltage: float, current: float) -> dict:
        if not (0 <= voltage <= 60) or not (0 <= current <= 30):
            return {"success": False, "error": "Диапазон: 0-60V, 0-30A"}
        return self.actuators._set_converter_limits("solar_converter", voltage, current)

    def set_wind_limits(self, voltage: float, current: float) -> dict:
        if not (0 <= voltage <= 60) or not (0 <= current <= 30):
            return {"success": False, "error": "Диапазон: 0-60V, 0-30A"}
        return self.actuators._set_converter_limits("wind_converter", voltage, current) 
    
    def set_wind_attack_angle(self, angle: float) -> dict:
        """Установка угла атаки лопастей"""
        return self.actuators.set_wind_attack_angle(angle)
    
    def enable_wind_brake(self) -> dict:
        """Включить балласт ветрогенератора"""
        return self.actuators.set_wind_brake(True)
    
    def disable_wind_brake(self) -> dict:
        """Выключить балласт ветрогенератора"""
        return self.actuators.set_wind_brake(False)
