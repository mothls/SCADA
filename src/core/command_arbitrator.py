import logging
from core.state_manager import StateManager

logger = logging.getLogger(__name__)


class CommandArbitrator:
    """
    Арбитратор команд. Формирует финальные команды для исполнения.
    
    Приоритет (от высшего к низшему):
    1. EMERGENCY режим (полная остановка)
    2. Команды от SafetyShield (защитный алгоритм)
    3. Рекомендации от GUI (pending)
    4. Текущее состояние (оставляем как есть)
    """
    
    def __init__(self, state: StateManager, config: dict):
        self._state = state
        self._config = config

    def arbitrate(self) -> dict:
        pending = self._state.get_pending()
        safety = self._state.get_safety_flags()
        safety_commands = self._state.get("safety_commands", {}) or {}
        final = {}

        # ============================================
        # 0. EMERGENCY РЕЖИМ — всё OFF, балласт ON
        # ============================================
        if safety.get("emergency", False):
            reason = safety.get("emergency_reason", "неизвестно")
            logger.critical(f"[ARBITRATOR] EMERGENCY MODE: {reason}")
            final["load"] = False
            final["solar_converter_enable"] = False
            final["wind_converter_enable"] = False
            final["wind_brake"] = True
            self._state.clear_pending()
            return final

        # ============================================
        # 1. ЗАЩИТНЫЙ КОНТУР (высший приоритет)
        # ============================================
        
        # 1.1. Старые флаги (обратная совместимость)
        force_off = safety.get("force_load_off", False)
        reason = safety.get("force_load_off_reason", "")
        if force_off:
            final["load"] = False
            logger.warning(f"[ARBITRATOR] LOAD forced OFF. Reason: {reason}")

        # 1.2. Новые команды от SafetyShield
        if safety_commands:
            # Нагрузка
            if "load" in safety_commands:
                final["load"] = safety_commands["load"]
                logger.info(f"[ARBITRATOR] Safety: LOAD = {safety_commands['load']}")
            
            # Солнечный конвертер
            if "solar_converter_enable" in safety_commands:
                final["solar_converter_enable"] = safety_commands["solar_converter_enable"]
                logger.info(f"[ARBITRATOR] Safety: SOLAR = {safety_commands['solar_converter_enable']}")
            
            # Ветровой конвертер
            if "wind_converter_enable" in safety_commands:
                final["wind_converter_enable"] = safety_commands["wind_converter_enable"]
                logger.info(f"[ARBITRATOR] Safety: WIND = {safety_commands['wind_converter_enable']}")
            
            # Балласт
            if "wind_brake" in safety_commands:
                final["wind_brake"] = safety_commands["wind_brake"]
                logger.info(f"[ARBITRATOR] Safety: BRAKE = {safety_commands['wind_brake']}")
            
            # Уставки солнечного конвертера
            if "solar_converter_voltage" in safety_commands and "solar_converter_current" in safety_commands:
                final["solar_converter_voltage"] = safety_commands["solar_converter_voltage"]
                final["solar_converter_current"] = safety_commands["solar_converter_current"]
                logger.info(f"[ARBITRATOR] Safety: SOLAR LIMITS = {safety_commands['solar_converter_voltage']}V, {safety_commands['solar_converter_current']}A")
            
            # Уставки ветрового конвертера
            if "wind_converter_voltage" in safety_commands and "wind_converter_current" in safety_commands:
                final["wind_converter_voltage"] = safety_commands["wind_converter_voltage"]
                final["wind_converter_current"] = safety_commands["wind_converter_current"]
                logger.info(f"[ARBITRATOR] Safety: WIND LIMITS = {safety_commands['wind_converter_voltage']}V, {safety_commands['wind_converter_current']}A")

        # ============================================
        # 2. РЕКОМЕНДАЦИЯ (студент или GUI)
        # ============================================
        
        # Нагрузка: если защита не переопределила — берём из pending
        if "load" not in final:
            rec = pending.get("load")
            if rec is not None:
                final["load"] = rec
                logger.debug(f"[ARBITRATOR] Pending: LOAD = {rec}")
            else:
                # Если нет новой команды, оставляем текущее состояние
                final["load"] = self._state.get("load_state") == "ON"

        self._state.clear_pending()
        return final