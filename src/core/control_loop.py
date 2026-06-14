import time
import threading
import logging
from core.state_manager import StateManager
from core.command_arbitrator import CommandArbitrator
from core.sandbox_runner import SandboxRunner

logger = logging.getLogger(__name__)


class ControlLoop:
    def __init__(self, state: StateManager, arbitrator: CommandArbitrator,
                 sandbox: SandboxRunner, mqtt_client, modbus_clients, db, config):
        self._state = state
        self._arbitrator = arbitrator
        self._sandbox = sandbox
        self._mqtt = mqtt_client
        self._modbus = modbus_clients
        self._db = db
        self._config = config
        self._running = False
        self._thread = None
        self._safety_shield = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("ControlLoop started (1 Hz)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()
        logger.info("ControlLoop stopped")

    def _run(self):
        while self._running:
            try:
                self._gather_state()
                self._check_safety()
                self._run_student_script()
                final = self._arbitrator.arbitrate()
                self._execute(final)
            except Exception as e:
                logger.error(f"ControlLoop error: {e}", exc_info=True)
            time.sleep(1.0)

    def _gather_wind_telemetry(self):
        if not self._mqtt:
            return
        try:
            wind_rpm = self._mqtt.get_wind_rpm()
            wind_brake = self._mqtt.get_wind_brake_state()
            wind_status = self._mqtt.get_wind_status()
            
            if wind_rpm is not None:
                self._state.update_wind_telemetry(
                    rpm=wind_rpm,
                    brake_state=wind_brake,
                    status=wind_status
                )
                
                if self._db and wind_rpm >= 0:
                    self._db.add_telemetry(
                        device_id="wind_turbine",
                        param="rpm",
                        value=float(wind_rpm)
                    )
        except Exception as e:
            logger.warning(f"Failed to gather wind telemetry: {e}")

    def _gather_battery_state(self):
        try:
            hall_client = self._modbus.get("solar_converter")
            
            if not hall_client or not hasattr(hall_client, 'hall_ser') or not hall_client.hall_ser:
                return

            hall_client._update_hall_current()
            bat_current = hall_client.get_hall_current()

            bat_voltage = self._state.get("solar_converter_vout", 0.0)
            if bat_voltage < 1.0:
                bat_voltage = self._state.get("wind_converter_vout", 0.0)
            if bat_voltage < 1.0:
                bat_voltage = 0.0

            if bat_current > 0.05:
                bat_status = "CHARGING"
            elif bat_current < -0.05:
                bat_status = "DISCHARGING"
            else:
                bat_status = "IDLE"

            self._state.update("battery_voltage", bat_voltage)
            self._state.update("battery_current", bat_current)
            self._state.update("battery_status", bat_status)
            
            # Запись батареи в БД
            if self._db:
                self._db.add_device_data("battery", 0.0, bat_voltage, 0.0, bat_current, 0.0)
            
            logger.debug(f"[BAT] U={bat_voltage:.2f}V | I={bat_current:.3f}A | Status={bat_status}")

        except Exception as e:
            logger.error(f"[BAT] Gather error: {e}")

    def _calculate_load_current(self):
        """Расчет тока нагрузки по 1-му закону Кирхгофа"""
        try:
            i_solar = self._state.get("solar_converter_iout", 0.0)
            i_wind = self._state.get("wind_converter_iout", 0.0)
            i_bat = self._state.get("battery_current", 0.0)
            u_bus = self._state.get("battery_voltage", 0.0)

            i_load = i_solar + i_wind - i_bat
            i_load = max(0.0, i_load)

            self._state.update("load_current", i_load)
            
            if self._db:
                # Позиционные аргументы!
                self._db.add_device_data("load", 0.0, u_bus, 0.0, i_load, 0.0)
                
            logger.debug(f"[KIRCHHOFF] I_load = {i_solar:.2f} + {i_wind:.2f} - ({i_bat:.2f}) = {i_load:.3f}A")
            
        except Exception as e:
            logger.error(f"[KIRCHHOFF] Calculation error: {e}")

    def _update_battery_soc(self):
        """Расчёт SOC (State of Charge) батареи методом кулонометрии"""
        try:
            i_bat = self._state.get("battery_current", 0.0)
            u_bus = self._state.get("battery_voltage", 0.0)
            
            c_nom = float(self._config.get("Battery", "nominal_capacity_ah", fallback=60))
            eta = float(self._config.get("Battery", "charge_efficiency", fallback=0.95))

            if not self._state.get("battery_soc_initialized"):
                soc = self._estimate_soc_from_voltage(u_bus)
                self._state.update("battery_soc", soc)
                self._state.update("battery_soc_initialized", True)
                logger.info(f"[SOC] Initialized: {soc:.1f}%")
                return

            dt_hours = 1.0 / 3600.0

            if i_bat > 0:
                delta_ah = i_bat * eta * dt_hours
            else:
                delta_ah = i_bat * dt_hours

            soc = self._state.get("battery_soc", 100.0)
            soc += (delta_ah / c_nom) * 100.0

            soc = max(0.0, min(100.0, soc))

            # Автокалибровка по напряжению
            if u_bus >= 14.4 and i_bat < 0.1:
                soc = 100.0
            elif u_bus <= 10.5:
                soc = 0.0

            self._state.update("battery_soc", soc)
            logger.debug(f"[SOC] Updated: {soc:.2f}% (I_bat={i_bat:.3f}A)")

            if int(time.time()) % 60 == 0:
                self._save_soc_to_file(soc)
                
        except Exception as e:
            logger.error(f"[SOC] Update error: {e}")

    def _estimate_soc_from_voltage(self, voltage):
        """Оценка SOC по напряжению (OCV-таблица для свинцового АКБ)"""
        saved_soc = self._load_soc_from_file()
        if saved_soc is not None:
            logger.info(f"[SOC] Loaded from file: {saved_soc:.1f}%")
            return saved_soc
        
        ocv_table = [
            (12.7, 100.0),
            (12.5, 75.0),
            (12.3, 50.0),
            (12.1, 25.0),
            (11.9, 0.0)
        ]
        
        for i in range(len(ocv_table) - 1):
            v1, soc1 = ocv_table[i]
            v2, soc2 = ocv_table[i + 1]
            if v2 <= voltage <= v1:
                soc = soc2 + (voltage - v2) * (soc1 - soc2) / (v1 - v2)
                logger.info(f"[SOC] Estimated from voltage {voltage:.2f}V: {soc:.1f}%")
                return soc
        
        if voltage > 12.7:
            return 100.0
        return 0.0

    def _save_soc_to_file(self, soc):
        """Сохранение SOC в файл"""
        import json
        try:
            with open("soc_state.json", "w") as f:
                json.dump({"soc": soc, "timestamp": time.time()}, f)
            logger.debug(f"[SOC] Saved to file: {soc:.2f}%")
        except Exception as e:
            logger.error(f"[SOC] Save failed: {e}")

    def _load_soc_from_file(self):
        """Загрузка SOC из файла при старте"""
        import json
        try:
            with open("soc_state.json", "r") as f:
                data = json.load(f)
                soc = data.get("soc", None)
                timestamp = data.get("timestamp", 0)
                age_hours = (time.time() - timestamp) / 3600
                if age_hours < 24:
                    return soc
                else:
                    logger.info(f"[SOC] File too old ({age_hours:.1f}h), ignoring")
                    return None
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"[SOC] Load failed: {e}")
            return None

    def _gather_state(self):
        self._gather_wind_telemetry()
        
        if self._mqtt:
            load_state = self._mqtt.get_state()
            if load_state is not None:
                self._state.update("load_state", load_state)
        
        for dev_id, client in self._modbus.items():
            try:
                vout = client.read_voltage_out()
                iout = client.read_current_out()
                temp = client.read_temperature()
                
                status_reg = client._read_holding_register(0x0002)
                if status_reg is not None:
                    client._cached_output_enabled = (status_reg == 1)
                
                self._state.update(f"{dev_id}_vout", vout if vout is not None else 0.0)
                self._state.update(f"{dev_id}_iout", iout if iout is not None else 0.0)
                self._state.update(f"{dev_id}_temp", temp if temp is not None else 0.0)
                self._state.update(f"{dev_id}_vin", 0.0)
                self._state.update(f"{dev_id}_iin", 0.0)
                self._state.update(f"{dev_id}_output_enabled", client._cached_output_enabled)
                
                if self._db:
                    # Позиционные аргументы!
                    self._db.add_device_data(
                        dev_id,
                        0.0,
                        vout if vout is not None else 0.0,
                        0.0,
                        iout if iout is not None else 0.0,
                        temp if temp is not None else 0.0
                    )
            except Exception as e:
                logger.debug(f"Modbus read error for {dev_id}: {e}")

        self._gather_battery_state()
        self._calculate_load_current()
        self._update_battery_soc()

    def _check_safety(self):
        """Вызов защитного алгоритма SafetyShield"""
        # Ленивая инициализация SafetyShield
        if self._safety_shield is None:
            from core.safety_shield import SafetyShield
            self._safety_shield = SafetyShield(self._state, self._config, self._db)
            logger.info("[SAFETY] SafetyShield initialized")
        
        # Получаем принудительные команды от щита
        safety_commands = self._safety_shield.evaluate()
        
        # Сохраняем в StateManager для арбитратора
        if safety_commands:
            self._state.update("safety_commands", safety_commands)
            logger.debug(f"[SAFETY] Commands: {safety_commands}")

    def _run_student_script(self):
        status, _ = self._sandbox.get_status()
        if status == "RUNNING":
            self._sandbox.execute_cycle()

    def _execute(self, final: dict):
        """Исполнение финальных команд от арбитратора"""
        
        # 1. Управление нагрузкой (через MQTT)
        if "load" in final:
            current_state = self._state.get("load_state") == "ON"
            if final["load"] != current_state:
                if self._mqtt:
                    self._mqtt.set_state(final["load"])
                    action = "ON" if final["load"] else "OFF"
                    logger.info(f"[EXEC] LOAD set to {action}")
                    if self._db:
                        self._db.add_event("LOAD", f"Команда: {action}")
                else:
                    logger.error("MQTT not available for load control")
        
        # 2. Управление солнечным конвертером (через Modbus)
        if "solar_converter_enable" in final:
            client = self._modbus.get("solar_converter")
            if client:
                enable = final["solar_converter_enable"]
                success = client.output_enable(enable)
                if success:
                    self._state.update("solar_converter_output_enabled", enable)
                    action = "ON" if enable else "OFF"
                    logger.info(f"[EXEC] SOLAR CONVERTER {action}")
                    if self._db:
                        self._db.add_event("SOLAR_CONVERTER", f"Выход {action}")
                    
                    # Если включаем с уставками — применяем их
                    if enable and "solar_converter_voltage" in final and "solar_converter_current" in final:
                        voltage = final["solar_converter_voltage"]
                        current = final["solar_converter_current"]
                        client.set_voltage_and_current(voltage, current)
                        logger.info(f"[EXEC] SOLAR LIMITS: {voltage}V, {current}A")
        
        # 3. Управление ветровым конвертером (через Modbus)
        if "wind_converter_enable" in final:
            client = self._modbus.get("wind_converter")
            if client:
                enable = final["wind_converter_enable"]
                success = client.output_enable(enable)
                if success:
                    self._state.update("wind_converter_output_enabled", enable)
                    action = "ON" if enable else "OFF"
                    logger.info(f"[EXEC] WIND CONVERTER {action}")
                    if self._db:
                        self._db.add_event("WIND_CONVERTER", f"Выход {action}")
                    
                    # Если включаем с уставками — применяем их
                    if enable and "wind_converter_voltage" in final and "wind_converter_current" in final:
                        voltage = final["wind_converter_voltage"]
                        current = final["wind_converter_current"]
                        client.set_voltage_and_current(voltage, current)
                        logger.info(f"[EXEC] WIND LIMITS: {voltage}V, {current}A")
        
        # 4. Управление балластом ветрогенератора (через MQTT)
        if "wind_brake" in final:
            if self._mqtt:
                enable = final["wind_brake"]
                cmd = "BRAKE_ON" if enable else "BRAKE_OFF"
                topic = "cmnd/lab/wind_turbine/brake_cmd"
                self._mqtt.client.publish(topic, cmd, qos=1)
                action = "ВКЛ" if enable else "ВЫКЛ"
                logger.info(f"[EXEC] WIND BRAKE {action}")
                if self._db:
                    self._db.add_event("WIND_TURBINE", f"Балласт {action}")