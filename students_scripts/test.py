# student_scripts/control_converters.py

def run(api):
    api.system.log(" Управление конвертерами")
    
    # Включаем солнечный конвертер
    if api.actuators.enable_solar_output():
        api.system.log(" Солнечный конвертер ВКЛ")
    else:
        api.system.log(" Ошибка включения солнечного")
    
    # Проверяем статус
    if api.sensors.is_solar_output_enabled():
        api.system.log(f" Solar: V={api.sensors.get_solar_voltage_out():.2f}V")
