import importlib.util
import sys
import threading
import logging
import traceback
from core.api_wrapper import API

logger = logging.getLogger(__name__)

class SandboxRunner:
    """
    Безопасный исполнитель пользовательских скриптов с поддержкой циклического выполнения.
    Загружает модуль один раз в память и предоставляет методы для run/loop/stop.
    """
    def __init__(self, api: API):
        self.api = api
        self._module = None          # Храним загруженный модуль в памяти
        self._lock = threading.Lock()
        self._error = None
        self._status = "IDLE"        # Возможные состояния: IDLE, RUNNING, ERROR

    def load(self, script_path: str) -> bool:
        """
        Загружает скрипт один раз и вызывает run(api).
        Возвращает True при успешной загрузке.
        """
        with self._lock:
            self._error = None
            self._status = "RUNNING"
            
        try:
            # 1. Загрузка модуля из файла
            spec = importlib.util.spec_from_file_location("student_script", script_path)
            if not spec or not spec.loader:
                raise RuntimeError("Неверный путь или формат скрипта")
                
            self._module = importlib.util.module_from_spec(spec)
            sys.modules["student_script"] = self._module
            
            # 2. Формирование безопасного окружения (WhiteList)
            restricted_builtins = {
                "__builtins__": {
                    "print": print, "len": len, "range": range, "int": int,
                    "float": float, "str": str, "bool": bool, "list": list,
                    "dict": dict, "tuple": tuple, "set": set, "min": min, "max": max,
                    "abs": abs, "round": round, "sum": sum, "enumerate": enumerate,
                    "zip": zip, "map": map, "filter": filter, "sorted": sorted,
                    "reversed": reversed, "True": True, "False": False, "None": None,
                    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
                    "KeyError": KeyError, "IndexError": IndexError
                }
            }
            self._module.__dict__.update(restricted_builtins)
            
            # 3. Выполнение кода
            spec.loader.exec_module(self._module)
            
            # 4. Вызов функции инициализации (если есть)
            if hasattr(self._module, "run"):
                self._module.run(self.api)
            else:
                logger.warning("Script has no run() function. Skipping init.")
                
            with self._lock:
                self._status = "RUNNING"
            return True
            
        except Exception as e:
            self._error = str(e)
            self._status = "ERROR"
            logger.error(f"Sandbox load failed:\n{traceback.format_exc()}")
            with self._lock:
                self._status = "IDLE"
                self._module = None
            return False

    def execute_cycle(self):
        """
        Вызывается ControlLoop каждую секунду.
        Выполняет функцию loop(api), если модуль загружен.
        """
        with self._lock:
            if self._status != "RUNNING" or not self._module:
                logger.debug("[DEBUG] execute_cycle skipped: not running or no module")
                return
                
        try:
            logger.debug("[DEBUG] Calling loop() function")
            if hasattr(self._module, "loop"):
                self._module.loop(self.api)
            else:
                logger.warning("[DEBUG] No loop() function in module!")
        except Exception as e:
            self._error = str(e)
            self._status = "ERROR"
            logger.error(f"Cycle execution error:\n{traceback.format_exc()}")

    def stop(self):
        """
        Останавливает скрипт: вызывает stop(api) и очищает память.
        """
        with self._lock:
            if self._module and hasattr(self._module, "stop"):
                try:
                    self._module.stop(self.api)
                except Exception as e:
                    logger.error(f"Stop callback error: {e}")
                    
            self._module = None
            self._status = "IDLE"
            self._error = None
        logger.info("Sandbox stopped and cleared.")

    def get_status(self):
        """Возвращает текущий статус и последнюю ошибку (потокобезопасно)"""
        with self._lock:
            return self._status, self._error
