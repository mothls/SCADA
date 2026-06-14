import configparser
import os

def load_config(config_file='config.ini'):
    # Определяем путь к корню проекта (два уровня выше от utils)
    utils_dir = os.path.dirname(os.path.abspath(__file__))  # .../src/utils
    src_dir = os.path.dirname(utils_dir)                   # .../src
    project_root = os.path.dirname(src_dir)                # .../ (корень)
    config_path = os.path.join(project_root, config_file)

    config = configparser.ConfigParser()
    if os.path.exists(config_path):
        config.read(config_path)
        print(f"[DEBUG] Config loaded from {config_path}")
    else:
        print(f"[DEBUG] Config file not found at {config_path}, using defaults")
        config['Modbus'] = {'port': 'COM3', 'baudrate': '9600', 'timeout': '1'}
        config['MQTT'] = {'broker': '192.168.1.34', 'port': '1883'}
        config['Database'] = {'path': 'scada.db'}
    return config
