import sys
import logging
import serial
from PyQt5.QtWidgets import QApplication
from apscheduler.schedulers.background import BackgroundScheduler

from gui.main_window import MainWindow
from core.modbus_client import ModbusClient
from core.database import Database 
from utils.config import load_config
from core.mqtt_client import MQTTClient

from core.state_manager import StateManager
from core.api_wrapper import API
from core.command_arbitrator import CommandArbitrator
from core.sandbox_runner import SandboxRunner
from core.control_loop import ControlLoop

# ==========================================
# РЕЖИМ РАБОТЫ
# ==========================================
# True  — использовать виртуальные данные (без железа)
# False — использовать реальные Modbus/MQTT устройства
SIMULATION_MODE = True

# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Калибровка датчика Холла (используется только в реальном режиме)
HALL_PORT = "COM5"
HALL_BAUDRATE = 9600
HALL_GAIN = 26.03
HALL_OFFSET = 0.020
HALL_WINDOW = 10


def check_modbus_device(port: str, baudrate: int = 9600, timeout: float = 0.5) -> bool:
    """Проверяет физическую доступность COM-порта"""
    try:
        test_port = serial.Serial(port, baudrate, timeout=timeout)
        test_port.close()
        logger.info(f"Port {port} is available.")
        return True
    except Exception as e:
        logger.warning(f"Device not found on {port} ({e}). Skipping.")
        return False


def main():
    app = QApplication(sys.argv)
    config = load_config()

    # --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ---
    db_path = config['Database']['path']
    db = Database(db_path)
    db.add_event("SYSTEM", "SCADA запущена")
    logger.info("Database initialized.")

    # ==========================================
    # ИНИЦИАЛИЗАЦИЯ УСТРОЙСТВ (реальные или виртуальные)
    # ==========================================
    if SIMULATION_MODE:
        from core.simulation import MockConverter, MockMQTT
        logger.info("="*60)
        logger.info("!!! ЗАПУСК В РЕЖИМЕ СИМУЛЯЦИИ !!!")
        logger.info("="*60)

        solar_modbus = MockConverter("solar_converter", 1)
        wind_modbus = MockConverter("wind_converter", 2)
        clients_dict = {"solar_converter": solar_modbus, "wind_converter": wind_modbus}

        mqtt_client = MockMQTT()
        mqtt_client.connect()
    else:
        # === РЕАЛЬНЫЕ УСТРОЙСТВА ===
        solar_modbus = ModbusClient(
            port=config['Modbus']['solar_port'],
            baudrate=int(config['Modbus']['baudrate']),
            timeout=float(config['Modbus']['timeout']),
            db=None,
            unit=1,
            device_id="solar_converter",
            hall_port=HALL_PORT,
            hall_baudrate=HALL_BAUDRATE,
            hall_gain=HALL_GAIN,
            hall_offset=HALL_OFFSET,
            hall_window=HALL_WINDOW
        )

        clients_dict = {"solar_converter": solar_modbus}
        wind_modbus = None

        wind_port = config['Modbus'].get('wind_port')
        if wind_port and check_modbus_device(wind_port, int(config['Modbus']['baudrate'])):
            logger.info("Wind converter detected. Initializing...")
            wind_modbus = ModbusClient(
                port=wind_port,
                baudrate=int(config['Modbus']['baudrate']),
                timeout=float(config['Modbus']['timeout']),
                db=None,
                unit=2,
                device_id="wind_converter"
            )
            clients_dict["wind_converter"] = wind_modbus
        else:
            logger.info("Running in single-converter mode (Solar only).")

        mqtt_broker = config.get('MQTT', 'broker', fallback='127.0.0.1')
        mqtt_topic = config.get('MQTT', 'topic_prefix', fallback='lab/plug')
        mqtt_client = MQTTClient(broker_ip=mqtt_broker, topic_prefix=mqtt_topic)
        mqtt_client.connect()

    # ==========================================
    # ЯДРО УПРАВЛЕНИЯ
    # ==========================================
    state = StateManager()
    api = API(state, modbus_clients=clients_dict, mqtt_client=mqtt_client)
    arbitrator = CommandArbitrator(state, config)
    sandbox = SandboxRunner(api)

    control_loop = ControlLoop(
        state=state,
        arbitrator=arbitrator,
        sandbox=sandbox,
        mqtt_client=mqtt_client,
        modbus_clients=clients_dict,
        db=db,
        config=config
    )
    control_loop.start()

    scheduler = BackgroundScheduler()
    scheduler.start()
    logger.info("ControlLoop & Scheduler started successfully")

    # --- GUI ---
    window = MainWindow(
        db=db, 
        modbus_clients_dict=clients_dict, 
        scheduler=scheduler, 
        mqtt_client=mqtt_client, 
        sandbox=sandbox,
        state_manager=state,
        api=api
    )
    window.show()

    # ==========================================
    # КОРРЕКТНОЕ ЗАВЕРШЕНИЕ
    # ==========================================
    def on_exit():
        logger.info("Shutting down system...")
        control_loop.stop()
        scheduler.shutdown()
        
        if not SIMULATION_MODE:
            solar_modbus.close()
            if wind_modbus is not None:
                wind_modbus.close()
            mqtt_client.disconnect()
        
        db.add_event("SYSTEM", "SCADA остановлена")
        logger.info("SCADA stopped cleanly")

    app.aboutToQuit.connect(on_exit)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()