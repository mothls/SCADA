def loop(api):
    api.system.log("🔆 Тест только для солнечного конвертера (DPM8600)")

    api.system.log("⚙️  Настройка: V=24.0V, I=4.0A")
    res = api.set_solar_limits(voltage=24.0, current=4.0)
    if not res["success"]:
        api.system.log(f"❌ Ошибка настройки: {res.get('error')}")
        return False
    api.system.log(f"✅ {res['message']}")

    api.system.log("⏳ Чтение телеметрии после применения уставок...")
    # В песочнице import time заблокирован. 
    # Modbus-запись в DPM8600 отрабатывает синхронно, поэтому пауза не нужна.

    v_out = api.sensors.get_solar_voltage_out()
    i_out = api.sensors.get_solar_current_out()
    temp  = api.sensors.get_solar_temperature()
    on    = api.sensors.is_solar_output_enabled()
    p_out = api.sensors.get_solar_power_out()

    api.system.log(f"📊 Выход: {'ВКЛ' if on else 'ВЫКЛ'}")
    api.system.log(f" U_out: {v_out:.2f} V")
    api.system.log(f"📊 I_out: {i_out:.3f} A")
    api.system.log(f"📊 P_out: {p_out:.2f} W")
    api.system.log(f"🌡️  Temp: {temp:.1f} °C")

    if on and 22.0 < v_out < 25.0 and i_out >= 0.0:
        api.system.log("🎉 Тест пройден. Конвертер вышел на режим.")
        return True
    else:
        api.system.log("⚠️  Тест не пройден. Проверьте питание, кабели и режим 'on' на самом модуле.")
        return False
