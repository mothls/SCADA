import time
import threading
import serial
import logging
from collections import deque

# Подавляем спам APScheduler
logging.getLogger('apscheduler.executors.default').setLevel(logging.ERROR)
logging.getLogger('apscheduler.schedulers.base').setLevel(logging.ERROR)

class ModbusClient:
    def __init__(self, port, baudrate, timeout, db=None, unit=1, device_id="unknown",
                 hall_port=None, hall_baudrate=9600, hall_gain=0.716, 
                 hall_offset=0.006, hall_window=10):
        self.logger = logging.getLogger(f"ModbusClient.{device_id}")
        
        # --- Modbus настройки ---
        self.port = port
        self.baudrate = baudrate
        self.timeout = min(float(timeout), 0.15)
        self.db = db
        self.unit = unit
        self.device_id = device_id
        
        self._port_lock = threading.Lock()
        self._poll_lock = threading.Lock()
        self._ser = None
        self._cached_output_enabled = False 
        
        # --- Датчик Холла (QNHC6 + LM358) настройки ---
        self.hall_port = hall_port
        self.hall_baudrate = hall_baudrate
        self.hall_gain = hall_gain
        self.hall_offset = hall_offset
        self.hall_window_size = hall_window
        
        self.hall_ser = None
        self.hall_buffer = deque(maxlen=self.hall_window_size)
        self.hall_current_avg = 0.0
        self.hall_voltage_avg = 0.0  # Напряжение активного канала шины
        self.hall_v0 = 0.0
        self.hall_v1 = 0.0
        self._hall_lock = threading.Lock()
        
        self.connect()
        if self.hall_port:
            self._connect_hall()
            
        self.logger.info(f"Initialized | Modbus: {self.port} | Hall (QNHC6): {self.hall_port or 'OFF'}")

    # ==================== НИЗКОУРОВНЕВЫЕ MODBUS ====================
    
    def _calculate_crc(self, data):
        """Расчёт CRC16 Modbus"""
        crc = 0xFFFF
        for b in data:
            crc ^= b
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc

    def _send_request(self, request):
        """Отправка кадра и чтение ответа через COM-порт"""
        with self._port_lock:
            if self._ser is None:
                return None
            try:
                self._ser.reset_input_buffer()
                self._ser.write(request)
                return self._ser.read(32)
            except Exception as e:
                self.logger.debug(f"Serial send error: {e}")
                return None

    def _read_holding_register(self, reg):
        """Функция 0x03: Чтение одного регистра"""
        if self._ser is None: return None
        req = bytearray([self.unit, 0x03, (reg >> 8) & 0xFF, reg & 0xFF, 0x00, 0x01])
        crc = self._calculate_crc(req)
        req.append(crc & 0xFF)
        req.append((crc >> 8) & 0xFF)
        
        resp = self._send_request(req)
        if resp and len(resp) >= 5 and resp[1] == 0x03:
            return (resp[3] << 8) | resp[4]
        return None

    def _write_single_register(self, reg, value):
        """Функция 0x06: Запись одного регистра"""
        if self._ser is None: return False
        req = bytearray([self.unit, 0x06, (reg >> 8) & 0xFF, reg & 0xFF,
                         (value >> 8) & 0xFF, value & 0xFF])
        crc = self._calculate_crc(req)
        req.append(crc & 0xFF)
        req.append((crc >> 8) & 0xFF)
        
        resp = self._send_request(req)
        return resp and len(resp) == 8 and resp[0] == self.unit and resp[1] == 0x06

    def _write_multiple_registers(self, start_reg, values):
        """Функция 0x10: Запись нескольких регистров подряд"""
        if self._ser is None or not values: 
            return False
        n_regs = len(values)
        byte_count = n_regs * 2
        
        req = bytearray([
            self.unit, 0x10,
            (start_reg >> 8) & 0xFF, start_reg & 0xFF,
            (n_regs >> 8) & 0xFF, n_regs & 0xFF,
            byte_count
        ])
        for val in values:
            req.append((val >> 8) & 0xFF)
            req.append(val & 0xFF)
            
        crc = self._calculate_crc(req)
        req.append(crc & 0xFF)
        req.append((crc >> 8) & 0xFF)
        
        resp = self._send_request(req)
        return resp and len(resp) == 8 and resp[0] == self.unit and resp[1] == 0x10

    # ==================== ПОДКЛЮЧЕНИЕ ====================
    
    def connect(self):
        try:
            self._ser = serial.Serial(
                port=self.port, baudrate=self.baudrate, timeout=self.timeout,
                parity='N', bytesize=8, stopbits=1
            )
            self.logger.info(f"Modbus connected to {self.port}")
        except Exception as e:
            self.logger.error(f"Modbus connection failed {self.port}: {e}")
            self._ser = None

    def _connect_hall(self):
        if not self.hall_port: return
        try:
            self.hall_ser = serial.Serial(
                port=self.hall_port, baudrate=self.hall_baudrate, timeout=0.5,
                parity='N', bytesize=8, stopbits=1
            )
            time.sleep(0.5)
            self.hall_ser.reset_input_buffer()
            self.logger.info(f"? QNHC6 Hall sensor connected to {self.hall_port}")
        except Exception as e:
            self.logger.error(f"? Hall sensor connection failed {self.hall_port}: {e}")
            self.hall_ser = None

    def close(self):
        for ser_attr in ['_ser', 'hall_ser']:
            ser = getattr(self, ser_attr, None)
            if ser and ser.is_open:
                try: ser.close()
                except: pass
            setattr(self, ser_attr, None)

    # ==================== ДАТЧИК ХОЛЛА (QNHC6 + LM358) ====================
    
    def _update_hall_current(self):
        """
        Логика специально под схему: QNHC6 (±12В, выход 0В при 0А) + LM358 (инвертор -1x).
        A0 = прямой сигнал, A1 = инвертированный.
        АЦП Arduino не читает отрицательное напряжение -> неактивный канал всегда ~0В.
        """
        if not self.hall_ser or not self.hall_ser.is_open:
            return
            
        try:
            while self.hall_ser.in_waiting > 0:
                line = self.hall_ser.readline().decode('ascii', errors='ignore').strip()
                if not line: continue
                
                # ВРЕМЕННЫЙ ЛОГ – увидишь сырые данные
                self.logger.debug(f"[HALL RAW] {line}")
                
                parts = line.split(',')
                if len(parts) != 2:
                    self.logger.debug(f"[HALL] Bad format (not 2 floats): {line}")
                    continue
                    
                try:
                    v0 = float(parts[0])
                    v1 = float(parts[1])
                except ValueError as e:
                    self.logger.debug(f"[HALL] Float conversion error: {line} - {e}")
                    continue
                
                with self._hall_lock:
                    self.hall_v0 = v0
                    self.hall_v1 = v1
                
                # --- ОПРЕДЕЛЕНИЕ НАПРАВЛЕНИЯ ТОКА ---
                if v0 > v1:
                    # Активен прямой канал (A0) -> ток ПОЛОЖИТЕЛЬНЫЙ (ЗАРЯД)
                    instant_current = -((v0 + self.hall_offset) * self.hall_gain)
                    active_voltage = v0
                elif v1 > v0:
                    # Активен инвертированный канал (A1) -> ток ОТРИЦАТЕЛЬНЫЙ (РАЗРЯД)
                    instant_current = (v1 + self.hall_offset) * self.hall_gain
                    active_voltage = v1
                else:
                    instant_current = 0.0
                    active_voltage = 0.0
                
                with self._hall_lock:
                    self.hall_voltage_avg = active_voltage
                    self.hall_buffer.append(instant_current)
                    if self.hall_buffer:
                        self.hall_current_avg = sum(self.hall_buffer) / len(self.hall_buffer)
                
                self.logger.debug(f"[HALL] V0={v0:.3f}V V1={v1:.3f}V -> U_bus={active_voltage:.3f}V I={instant_current:.3f}A")
                    
        except Exception as e:
            self.logger.warning(f"[HALL] Read error: {e}")

    def get_hall_current(self):
        with self._hall_lock: return self.hall_current_avg

    def get_hall_voltage(self):
        """Возвращает напряжение активной фазы шины (для расчёта мощности/SoC)"""
        with self._hall_lock: return self.hall_voltage_avg

    def read_battery_current_raw(self):
        return self.get_hall_current()

    def read_battery_voltage(self):
        """Возвращает напряжение шины с активного канала Холла"""
        return self.get_hall_voltage()

    # ==================== УПРАВЛЕНИЕ ПРЕДЕЛАМИ DPM8600 ====================
    
    def set_voltage_limit(self, voltage_volts: float) -> bool:
        """Установка уставки напряжения (регистр 0x0000, radix 2)"""
        if not (0.0 <= voltage_volts <= 60.0):
            self.logger.error(f"Voltage {voltage_volts}V out of range (0-60V)")
            return False
        raw = int(round(voltage_volts * 100))
        ok = self._write_single_register(0x0000, raw)
        if ok: self.logger.info(f"Voltage limit set: {voltage_volts:.2f}V")
        return ok

    def set_current_limit(self, current_amps: float) -> bool:
        """Установка уставки тока (регистр 0x0001, radix 3)"""
        if not (0.0 <= current_amps <= 30.0):
            self.logger.error(f"Current {current_amps}A out of range (0-30A)")
            return False
        raw = int(round(current_amps * 1000))
        ok = self._write_single_register(0x0001, raw)
        if ok: self.logger.info(f"Current limit set: {current_amps:.3f}A")
        return ok

    def set_voltage_and_current(self, voltage_volts: float, current_amps: float) -> bool:
        """Одновременная установка V и I через Function 0x10"""
        if not (0.0 <= voltage_volts <= 60.0) or not (0.0 <= current_amps <= 30.0):
            self.logger.error(f"Values out of range: {voltage_volts}V, {current_amps}A")
            return False
        v_raw = int(round(voltage_volts * 100))
        i_raw = int(round(current_amps * 1000))
        ok = self._write_multiple_registers(0x0000, [v_raw, i_raw])
        if ok: self.logger.info(f"V&I limits set: {voltage_volts:.2f}V, {current_amps:.3f}A")
        return ok

    def get_voltage_limit(self) -> float:
        val = self._read_holding_register(0x0000)
        return val / 100.0 if val is not None else None

    def get_current_limit(self) -> float:
        val = self._read_holding_register(0x0001)
        return val / 1000.0 if val is not None else None

    def output_enable(self, enable: bool) -> bool:
        """Вкл/выкл выхода (регистр 0x0002)"""
        val = 1 if enable else 0
        ok = self._write_single_register(0x0002, val)
        if ok:
            self._cached_output_enabled = enable
            self.logger.info(f"Output {'ENABLED' if enable else 'DISABLED'}")
        return ok

    # Алиасы для обратной совместимости
    write_voltage_setpoint = set_voltage_limit
    write_current_setpoint = set_current_limit
    write_output_enable = output_enable

    # ==================== СТАНДАРТНОЕ ЧТЕНИЕ КОНВЕРТЕРА ====================
    
    def read_voltage_out(self):
        val = self._read_holding_register(0x1001)
        return val / 100.0 if val is not None else None

    def read_current_out(self):
        val = self._read_holding_register(0x1002)
        return val / 1000.0 if val is not None else None

    def read_temperature(self):
        val = self._read_holding_register(0x1003)
        return val if val is not None else None

    def read_status(self):
        val = self._read_holding_register(0x1000)
        return val if val is not None else None

    def read_output_enabled(self):
        return self._cached_output_enabled

    def read_voltage_in(self): return None
    def read_current_in(self): return 0.0

    # ==================== ОСНОВНОЙ ЦИКЛ ОПРОСА ====================
    
    def poll(self):
        if self._ser is None or self.db is None: return
        if not self._poll_lock.acquire(blocking=False): return 
        
        try:
            # 1. Обновление данных с датчика Холла (COM5)
            self._update_hall_current()
            
            # 2. Чтение параметров конвертера DPM8600
            vout = self.read_voltage_out()
            iout = self.read_current_out()
            temp = self.read_temperature()
            
            status_reg = self._read_holding_register(0x0002)
            if status_reg is not None:
                self._cached_output_enabled = (status_reg == 1)
                
            # 3. Запись в БД
            self.db.add_device_data(
                device_id=self.device_id,
                vin=0.0, 
                vout=vout if vout is not None else 0.0,
                iin=0.0, 
                iout=iout if iout is not None else 0.0,
                temp=temp if temp is not None else 0.0
            )
            
        except Exception as e:
            self.logger.error(f"Poll failed [{self.device_id}]: {e}")
        finally:
            self._poll_lock.release()
