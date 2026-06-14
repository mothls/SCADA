def run(api):
    api.system.log("=== ПОЛНАЯ ДИАГНОСТИКА СИСТЕМЫ ===")
    
    # СОЛНЕЧНЫЙ КОНВЕРТЕР
    api.system.log(" SOLAR CONVERTER:")
    api.system.log(f"   Температура : {api.sensors.get_solar_temperature():.1f} °C")
    api.system.log(f"   V_out (напр): {api.sensors.get_solar_voltage_out():.2f} V")
    api.system.log(f"   I_out (ток) : {api.sensors.get_solar_current_out():.3f} A")
    api.system.log(f"   P_out (мощ) : {api.sensors.get_solar_power_out():.2f} W")
    api.system.log(f"   Реле выхода : {'ВКЛ' if api.sensors.is_solar_output_enabled() else 'ВЫКЛ'}")
    
    #  ВЕТРОВОЙ КОНВЕРТЕР
    api.system.log(" WIND CONVERTER:")
    api.system.log(f"   Температура : {api.sensors.get_wind_temperature():.1f} °C")
    api.system.log(f"   V_out (напр): {api.sensors.get_wind_voltage_out():.2f} V")
    api.system.log(f"   I_out (ток) : {api.sensors.get_wind_current_out():.3f} A")
    api.system.log(f"   P_out (мощ) : {api.sensors.get_wind_power_out():.2f} W")
    api.system.log(f"   Реле выхода : {'ВКЛ' if api.sensors.is_wind_output_enabled() else 'ВЫКЛ'}")
    
    #  НАГРУЗКА
    api.system.log(f" LOAD STATE  : {api.sensors.get_load_state()}")
    
    api.system.log("=== КОНЕЦ ДИАГНОСТИКИ ===")
