def loop(api):
    U_SHUTDOWN = 14.3   # Порог отключения, Вольт
    U_RESTART  = 13.5   # Порог повторного включения (гистерезис 0.8В)
    V_LIMIT    = 24.0   # Уставка напряжения конвертера
    I_LIMIT    = 4.0    # Уставка тока конвертера

    # 1. Считываем текущее напряжение шины
    u_bus = api.sensors.get_solar_voltage_out()
    api.system.log(f"?? Шина: U={u_bus:.2f}V")

    # 2. Проверяем, нужен ли аварийный сброс
    if u_bus >= U_SHUTDOWN:
        api.system.log(f"?? ПЕРЕЗАРЯД! U={u_bus:.2f}V >= {U_SHUTDOWN}V > ОТКЛЮЧАЕМ конвертер")
        api.actuators.disable_solar_output()
        api.system.log("? Выход солнечного конвертера ВЫКЛЮЧЕН")
        return False

    # 3. Проверяем, можно ли снова включить (гистерезис)
    if u_bus < U_RESTART:
        api.system.log(f" Напряжение упало до {u_bus:.2f}V < {U_RESTART}V > включаем заряд")
        res = api.set_solar_limits(voltage=V_LIMIT, current=I_LIMIT)
        if res["success"]:
            api.system.log(f"? {res['message']}")
        else:
            api.system.log(f"? Ошибка: {res.get('error')}")
        return True

    # 4. Нормальный режим — напряжение в допустимых пределах
    api.system.log(f"?? Напряжение в норме ({U_RESTART}V < U < {U_SHUTDOWN}V)")
    return True
