import sqlite3
import time
import datetime
from PyQt5.QtCore import QObject, pyqtSignal

class Database(QObject):
    """
    Управление базой данных SQLite.
    Поддерживает сигналы PyQt для обновления GUI.
    """
    # Сигнал для уведомления о новых данных (используется для графиков)
    data_added = pyqtSignal()

    def __init__(self, db_path="scada_data.db"):
        super().__init__()
        self.db_path = db_path
        # check_same_thread=False позволяет работать с БД из разных потоков (ControlLoop, GUI)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        """Создание таблиц при первом запуске"""
        cursor = self.conn.cursor()
        cursor.executescript("""
            -- Таблица для фиксированных параметров (конвертеры)
            CREATE TABLE IF NOT EXISTS device_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                vin REAL DEFAULT 0.0,
                vout REAL DEFAULT 0.0,
                iin REAL DEFAULT 0.0,
                iout REAL DEFAULT 0.0,
                temp REAL DEFAULT 0.0
            );

            -- Таблица для произвольной телеметрии (обороты ВЭУ, статусы)
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                param TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp REAL NOT NULL
            );

            -- Таблица событий (логи системы)
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp REAL NOT NULL
            );
        """)
        self.conn.commit()

    def add_device_data(self, device_id, vin, vout, iin, iout, temp):
        """Запись стандартных данных устройства"""
        ts = time.time()
        self.conn.execute(
            "INSERT INTO device_data (device_id, timestamp, vin, vout, iin, iout, temp) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (device_id, ts, vin, vout, iin, iout, temp)
        )
        self.conn.commit()
        self.data_added.emit()

    def get_latest_data(self, device_id):
        """Получение последней записи по устройству"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT vin, vout, iin, iout, temp FROM device_data WHERE device_id = ? ORDER BY timestamp DESC LIMIT 1",
            (device_id,)
        )
        row = cursor.fetchone()
        if row:
            return (row[0], row[1], row[2], row[3], row[4])
        return None

    def get_history_for_param(self, device_id, param, limit=100):
        """Получение истории по полям (vin, vout, iin, iout, temp)"""
        valid_params = {'vin', 'vout', 'iin', 'iout', 'temp'}
        if param not in valid_params:
            return []
            
        cursor = self.conn.cursor()
        cursor.execute(
            f"SELECT timestamp, {param} FROM device_data WHERE device_id = ? ORDER BY timestamp DESC LIMIT ?",
            (device_id, limit)
        )
        rows = cursor.fetchall()
        # Возвращаем в хронологическом порядке (ASC)
        return [(datetime.datetime.fromtimestamp(ts), val) for ts, val in rows][::-1]

    def get_telemetry_history(self, device_id, param, limit=100):
        """Получение истории из универсальной таблицы telemetry (для RPM, углов)"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT timestamp, value FROM telemetry WHERE device_id = ? AND param = ? ORDER BY timestamp DESC LIMIT ?",
            (device_id, param, limit)
        )
        rows = cursor.fetchall()
        return [(datetime.datetime.fromtimestamp(ts), val) for ts, val in rows][::-1]

    def add_telemetry(self, device_id, param, value):
        """Универсальный метод записи произвольных параметров"""
        ts = time.time()
        self.conn.execute(
            "INSERT INTO telemetry (device_id, param, value, timestamp) VALUES (?, ?, ?, ?)",
            (device_id, param, value, ts)
        )
        self.conn.commit()
        self.data_added.emit()

    def add_event(self, device_id, message):
        """Запись события в лог БД"""
        ts = time.time()
        self.conn.execute(
            "INSERT INTO events (device_id, message, timestamp) VALUES (?, ?, ?)",
            (device_id, message, ts)
        )
        self.conn.commit()

    def close(self):
        """Корректное закрытие соединения"""
        if self.conn:
            self.conn.close()
