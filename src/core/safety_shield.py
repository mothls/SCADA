import time
import logging
from core.state_manager import StateManager

logger = logging.getLogger(__name__)


class SafetyShield:
    """Защитный алгоритм с высшим приоритетом"""
    
    def __init__(self, state: StateManager, config, db=None):
        self._state = state
        self._config = config
        self._db = db
        
        # Пороги температуры (°C)
        self.TEMP_NORMAL = float(config.get("Safety", "temp_normal", fallback=55))
        self.TEMP_WARNING = float(config.get("Safety", "temp_warning", fallback=65))
        self.TEMP_CRITICAL = float(config.get("Safety", "temp_critical", fallback=70))
        
        # Пороги RPM
        self.WIND_RPM_WARNING = float(config.get("Safety", "wind_rpm_warning", fallback=1200))
        self.WIND_RPM_EMERGENCY = float(config.get("Safety", "wind_rpm_emergency", fallback=1500))
        
        # Пороги SOC (%)
        self.SOC_HIGH = float(config.get("Battery", "soc_high", fallback=90))
        self.SOC_LOW = float(config.get("Battery", "soc_low", fallback=10))
        
        # Пороги напряжения АКБ (В)
        self.BAT_VOLTAGE_MAX = float(config.get("Battery", "voltage_max", fallback=14.5))
        self.BAT_VOLTAGE_CHARGE_STOP = float(config.get("Battery", "voltage_charge_stop", fallback=14.3))
        self.BAT_VOLTAGE_MIN = float(config.get("Battery", "voltage_min", fallback=10.5))
        
        # Ток заряда (А)
        self.CHARGE_CURRENT = float(config.get("Battery", "charge_current", fallback=5.0))
        
        # Счётчики попыток
        self._wind_angle_attempts = 0
        self._wind_angle_last_attempt = 0
        self._overtemp_cooldown = {}  # device_id -> timestamp последнего снижения
        
        # EMERGENCY режим
        self._emergency_mode = False
        self._emergency_reason = ""
    
    def evaluate(self) -> dict:
        """
        Главный метод оценки. Возвращает словарь принудительных команд.
        Эти команды имеют высший приоритет и переопределяют всё остальное.
        """
        commands = {}
        
        # Если EMERGENCY — всё отключаем
        if self._emergency_mode:
            return self._emergency_stop(commands)
        
        # 1. Проверка ветра
        self._check_wind(commands)
        
        # 2. Проверка температуры конвертеров
        self._check_temperature(commands)
        
        # 3. Проверка АКБ (SOC и напряжение)
        self._check_battery(commands)
        
        # 4. Проверка перегрузки по току
        self._check_overcurrent(commands)
        
        # 5. Проверка потери связи
        self._check_heartbeats(commands)
        
        return commands
    
    def _check_wind(self, commands: dict):
        """Защита от сильного ветра"""
        rpm = self._state.get("wind_rpm", 0.0)
        
        if rpm >= self.WIND_RPM_EMERGENCY:
            # Критическая скорость — сразу балласт + отключить ветровой конвертер
            commands["wind_brake"] = True
            commands["wind_converter_enable"] = False
            self._state.set_safety_flag("wind_emergency", True)
            self._state.set_safety_flag("wind_emergency_reason", f"RPM={rpm:.0f}")
            logger.critical(f"[SAFETY] WIND EMERGENCY: RPM={rpm:.0f}")
            
            if self._db:
                self._db.add_event("WIND_TURBINE", f"АВАРИЯ: RPM={rpm:.0f}")
            
            # Активируем EMERGENCY если RPM очень высокий
            if rpm >= self.WIND_RPM_EMERGENCY * 1.2:  # 1800+
                self._enter_emergency(f"Wind RPM critical: {rpm:.0f}")
                
        elif rpm >= self.WIND_RPM_WARNING:
            # Предупреждение — пробуем изменить угол атаки
            current_time = time.time()
            
            if self._wind_angle_attempts < 3:
                # Проверяем интервал 5 секунд
                if current_time - self._wind_angle_last_attempt >= 5:
                    # Виртуально меняем угол
                    current_angle = self._state.get("wind_attack_angle", 0.0)
                    new_angle = max(-90, current_angle - 15)  # Уменьшаем на 15°
                    self._state.update("wind_attack_angle", new_angle)
                    self._wind_angle_attempts += 1
                    self._wind_angle_last_attempt = current_time
                    
                    logger.warning(f"[SAFETY] Wind angle attempt {self._wind_angle_attempts}/3: {current_angle}° -> {new_angle}°")
                    
                    if self._db:
                        self._db.add_event("WIND_TURBINE", f"Угол атаки изменён: {new_angle}°")
            else:
                # 3 попытки не помогли — включаем балласт
                commands["wind_brake"] = True
                self._state.set_safety_flag("wind_brake_active", True)
                logger.warning(f"[SAFETY] Wind brake activated after 3 attempts")
                
                if self._db:
                    self._db.add_event("WIND_TURBINE", "Балласт включён (3 попытки угла)")
        else:
            # Норма — сбрасываем счётчики
            if self._wind_angle_attempts > 0:
                logger.info(f"[SAFETY] Wind normalized, resetting counters")
                self._wind_angle_attempts = 0
            
            if self._state.get_safety_flag("wind_brake_active"):
                commands["wind_brake"] = False
                self._state.set_safety_flag("wind_brake_active", False)
                logger.info(f"[SAFETY] Wind brake released")
    
    def _check_temperature(self, commands: dict):
        """Защита от перегрева конвертеров"""
        converters = ["solar_converter", "wind_converter"]
        
        for dev_id in converters:
            temp = self._state.get(f"{dev_id}_temp", 0.0)
            current_time = time.time()
            
            if temp >= self.TEMP_CRITICAL:
                # Критическая температура — отключить конвертер
                commands[f"{dev_id}_enable"] = False
                self._state.set_safety_flag(f"{dev_id}_overtemp", True)
                logger.critical(f"[SAFETY] {dev_id} CRITICAL TEMP: {temp:.1f}°C")
                
                if self._db:
                    self._db.add_event(dev_id, f"КРИТИЧЕСКАЯ ТЕМПЕРАТУРА: {temp:.1f}°C")
                
                # Сбрасываем cooldown
                if dev_id in self._overtemp_cooldown:
                    del self._overtemp_cooldown[dev_id]
                    
            elif temp >= self.TEMP_WARNING:
                # Предупреждение — снижаем мощность на 20%
                # Проверяем cooldown (10 секунд)
                if dev_id not in self._overtemp_cooldown or \
                   current_time - self._overtemp_cooldown[dev_id] >= 10:
                    
                    # Получаем текущие уставки (из StateManager или конфига)
                    # Для упрощения — снижаем ток на 20%
                    current_iout = self._state.get(f"{dev_id}_iout", 0.0)
                    reduced_current = current_iout * 0.8
                    
                    logger.warning(f"[SAFETY] {dev_id} overtemp {temp:.1f}°C, reducing current: {current_iout:.2f}A -> {reduced_current:.2f}A")
                    
                    # Записываем в StateManager (арбитратор потом применит)
                    self._state.update(f"{dev_id}_iout_reduced", reduced_current)
                    self._overtemp_cooldown[dev_id] = current_time
                    
                    if self._db:
                        self._db.add_event(dev_id, f"Перегрев {temp:.1f}°C, снижение тока на 20%")
                
                self._state.set_safety_flag(f"{dev_id}_overtemp_warning", True)
                
            else:
                # Норма
                self._state.set_safety_flag(f"{dev_id}_overtemp", False)
                self._state.set_safety_flag(f"{dev_id}_overtemp_warning", False)
                
                # Сбрасываем reduced ток
                if f"{dev_id}_iout_reduced" in self._state._state:
                    del self._state._state[f"{dev_id}_iout_reduced"]
    
    def _check_battery(self, commands: dict):
        """Защита АКБ от перезаряда и глубокого разряда"""
        soc = self._state.get("battery_soc", 100.0)
        voltage = self._state.get("battery_voltage", 0.0)
        current = self._state.get("battery_current", 0.0)
        load_state = self._state.get("load_state", "OFF")
        
        # === ПЕРЕЗАРЯД (SOC > 90% или напряжение > 14.5В) ===
        if soc >= self.SOC_HIGH or voltage >= self.BAT_VOLTAGE_MAX:
            # Включаем нагрузку (если не включена)
            if load_state != "ON":
                commands["load"] = True
                logger.warning(f"[SAFETY] Battery overcharge: SOC={soc:.1f}%, U={voltage:.2f}V, turning ON load")
            
            # Отключаем конвертеры (если включены)
            if self._state.get("solar_converter_output_enabled", False):
                commands["solar_converter_enable"] = False
                logger.warning(f"[SAFETY] Solar converter disabled (overcharge)")
            
            if self._state.get("wind_converter_output_enabled", False):
                commands["wind_converter_enable"] = False
                logger.warning(f"[SAFETY] Wind converter disabled (overcharge)")
            
            self._state.set_safety_flag("battery_overcharge", True)
            
            if self._db:
                self._db.add_event("BATTERY", f"Перезаряд: SOC={soc:.1f}%, U={voltage:.2f}V")
        
        # === ГЛУБОКИЙ РАЗРЯД (SOC < 10% или напряжение < 10.5В) ===
        elif soc <= self.SOC_LOW or voltage <= self.BAT_VOLTAGE_MIN:
            # Отключаем нагрузку
            if load_state != "OFF":
                commands["load"] = False
                logger.critical(f"[SAFETY] Battery deep discharge: SOC={soc:.1f}%, U={voltage:.2f}V, turning OFF load")
            
            # Включаем конвертеры в режиме зарядки (14.5В, 5А)
            if not self._state.get("solar_converter_output_enabled", False):
                commands["solar_converter_enable"] = True
                commands["solar_converter_voltage"] = self.BAT_VOLTAGE_MAX
                commands["solar_converter_current"] = self.CHARGE_CURRENT
                logger.warning(f"[SAFETY] Solar converter enabled for charging: {self.BAT_VOLTAGE_MAX}V, {self.CHARGE_CURRENT}A")
            
            if not self._state.get("wind_converter_output_enabled", False):
                commands["wind_converter_enable"] = True
                commands["wind_converter_voltage"] = self.BAT_VOLTAGE_MAX
                commands["wind_converter_current"] = self.CHARGE_CURRENT
                logger.warning(f"[SAFETY] Wind converter enabled for charging: {self.BAT_VOLTAGE_MAX}V, {self.CHARGE_CURRENT}A")
            
            self._state.set_safety_flag("battery_deep_discharge", True)
            
            if self._db:
                self._db.add_event("BATTERY", f"Глубокий разряд: SOC={soc:.1f}%, U={voltage:.2f}V")
        
        # === НОРМА (10% < SOC < 90%) ===
        else:
            self._state.set_safety_flag("battery_overcharge", False)
            self._state.set_safety_flag("battery_deep_discharge", False)
            
            # Если напряжение достигло 14.3В во время заряда — отключаем заряд
            if voltage >= self.BAT_VOLTAGE_CHARGE_STOP and current > 0:
                commands["solar_converter_enable"] = False
                commands["wind_converter_enable"] = False
                logger.info(f"[SAFETY] Charge complete: U={voltage:.2f}V, converters disabled")
    
    def _check_overcurrent(self, commands: dict):
        """Защита от перегрузки по току"""
        bat_current = self._state.get("battery_current", 0.0)
        
        # Если ток батареи > 20А или < -20А — авария
        if abs(bat_current) > 20.0:
            commands["load"] = False
            commands["solar_converter_enable"] = False
            commands["wind_converter_enable"] = False
            commands["wind_brake"] = True
            
            self._state.set_safety_flag("overcurrent", True)
            logger.critical(f"[SAFETY] OVERCURRENT: I_bat={bat_current:.2f}A")
            
            if self._db:
                self._db.add_event("SYSTEM", f"ПЕРЕГРУЗКА ПО ТОКУ: {bat_current:.2f}A")
            
            self._enter_emergency(f"Overcurrent: {bat_current:.2f}A")
        else:
            self._state.set_safety_flag("overcurrent", False)
    
    def _check_heartbeats(self, commands: dict):
        """Проверка потери связи с устройствами"""
        # Для простоты — проверяем, что данные обновлялись в последние 10 секунд
        # (можно расширить, добавив last_update_time в StateManager)
        pass
    
    def _enter_emergency(self, reason: str):
        """Вход в EMERGENCY режим"""
        if not self._emergency_mode:
            self._emergency_mode = True
            self._emergency_reason = reason
            logger.critical(f"[SAFETY] EMERGENCY MODE ENTERED: {reason}")
            
            if self._db:
                self._db.add_event("SYSTEM", f"АВАРИЙНЫЙ РЕЖИМ: {reason}")
    
    def _emergency_stop(self, commands: dict) -> dict:
        """Полная аварийная остановка"""
        commands["load"] = False
        commands["solar_converter_enable"] = False
        commands["wind_converter_enable"] = False
        commands["wind_brake"] = True
        
        self._state.set_safety_flag("emergency", True)
        self._state.set_safety_flag("emergency_reason", self._emergency_reason)
        
        return commands
    
    def reset_emergency(self):
        """Ручной сброс EMERGENCY режима"""
        if self._emergency_mode:
            self._emergency_mode = False
            self._emergency_reason = ""
            self._state.set_safety_flag("emergency", False)
            self._state.set_safety_flag("emergency_reason", "")
            
            logger.info("[SAFETY] EMERGENCY mode reset by operator")
            
            if self._db:
                self._db.add_event("SYSTEM", "Аварийный режим сброшен оператором")
