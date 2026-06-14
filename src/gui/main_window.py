import sys
from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QSplitter, QMenuBar, QAction, QMessageBox, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from gui.mnemonic_widget import MnemonicWidget
from gui.charts_area import ChartsArea
from gui.algorithm_manager import AlgorithmManager

class MainWindow(QMainWindow):
    log_signal = pyqtSignal(str)
    
    def __init__(self, db, modbus_clients_dict, scheduler, mqtt_client=None, sandbox=None, state_manager=None, api=None):
        super().__init__()
        self.db = db
        self.modbus_clients = modbus_clients_dict
        self.scheduler = scheduler
        self.mqtt_client = mqtt_client
        self.sandbox = sandbox
        self.state_manager = state_manager
        self.api = api
        self.setWindowTitle("SCADA Ветро-солнечная установка (Dual Converter + API)")
        self.setMinimumSize(1400, 800)
        self.create_menu()
        self.create_status_bar()
        self.create_central_widget()
        self.showMaximized()
        QTimer.singleShot(400, self._set_initial_splitter_position)
        
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.update_system_status_ui)
        self.status_timer.start(1000)
        
        self.log_signal.connect(self._on_log_received)
        self._bind_api_logs()

    def _on_log_received(self, msg: str):
        try:
            if hasattr(self, 'algo_manager') and hasattr(self.algo_manager, 'log'):
                self.algo_manager.log.append(f"[SCRIPT] {msg}")
        except Exception as e:
            print(f"[ERROR] GUI update failed: {e}")

    def _bind_api_logs(self):
        if not self.api:
            return
        def emit_log(msg: str):
            self.log_signal.emit(msg)
        self.api.system.set_log_callback(emit_log)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(200, self._set_initial_splitter_position)

    def _set_initial_splitter_position(self):
        if not hasattr(self, 'splitter'): return
        total = self.splitter.width()
        self.splitter.setSizes([int(total * 0.4), int(total * 0.3), int(total * 0.3)])

    def create_menu(self):
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("Настройки")
        self.start_action = QAction("▶ Запуск опроса", self)
        self.start_action.triggered.connect(self.start_research)
        settings_menu.addAction(self.start_action)
        self.pause_action = QAction("⏸ Пауза опроса", self)
        self.pause_action.triggered.connect(self.pause_research)
        settings_menu.addAction(self.pause_action)
        
        algo_menu = menubar.addMenu("Алгоритмы")
        run_algo_action = QAction("▶ Запустить активный скрипт", self)
        run_algo_action.triggered.connect(self.run_algorithm)
        algo_menu.addAction(run_algo_action)
        stop_algo_action = QAction("⏹ Остановить скрипт", self)
        stop_algo_action.triggered.connect(self.stop_algorithm)
        algo_menu.addAction(stop_algo_action)
        
        help_menu = menubar.addMenu("Справка")
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_status_bar(self):
        self.status_bar = self.statusBar()
        self.lbl_connection = QLabel("🟢 Подключение: АКТИВНО")
        self.lbl_connection.setStyleSheet("color: green; font-weight: bold;")
        self.lbl_ballast = QLabel("⚡ Балласт: ВЫКЛ")
        self.lbl_ballast.setStyleSheet("color: gray;")
        self.lbl_battery = QLabel("🔋 АКБ: Норма")
        self.lbl_battery.setStyleSheet("color: green;")
        self.lbl_load = QLabel(" Нагрузка: ВЫКЛ")
        self.lbl_load.setStyleSheet("color: gray;")
        self.lbl_safety = QLabel("🛡 Защита: OK")
        self.lbl_safety.setStyleSheet("color: green; font-weight: bold;")
        self.lbl_algo = QLabel("📜 Скрипт: IDLE")
        self.lbl_algo.setStyleSheet("color: gray;")
        self.lbl_records = QLabel("📊 Записей: 0")
        for lbl in [self.lbl_connection, self.lbl_ballast, self.lbl_battery,
                    self.lbl_load, self.lbl_safety, self.lbl_algo, self.lbl_records]:
            self.status_bar.addPermanentWidget(lbl)
        self.db.data_added.connect(self.update_record_count)
        self._record_count = 0

    def update_system_status_ui(self):
        if self.state_manager:
            flags = self.state_manager.get_safety_flags()
            if flags.get("force_load_off"):
                self.lbl_safety.setText(" Защита: АКТИВНА (Override)")
                self.lbl_safety.setStyleSheet("color: white; background-color: red; font-weight: bold; padding: 2px;")
            else:
                self.lbl_safety.setText("🛡 Защита: OK")
                self.lbl_safety.setStyleSheet("color: green; font-weight: bold;")
        if self.sandbox:
            status, err = self.sandbox.get_status()
            if status == "RUNNING":
                self.lbl_algo.setText("📜 Скрипт: RUNNING")
                self.lbl_algo.setStyleSheet("color: white; background-color: blue; font-weight: bold; padding: 2px;")
            elif status == "ERROR":
                self.lbl_algo.setText(" Скрипт: ERROR")
                self.lbl_algo.setStyleSheet("color: white; background-color: darkred; font-weight: bold; padding: 2px;")
            else:
                self.lbl_algo.setText("📜 Скрипт: IDLE")
                self.lbl_algo.setStyleSheet("color: gray;")

    def update_record_count(self):
        self._record_count += 1
        self.lbl_records.setText(f"📊 Записей: {self._record_count}")

    def update_safety_status(self, ballast_active=False, battery_current=0):
        if ballast_active:
            self.lbl_ballast.setText("⚡ Балласт: ВКЛ (АВАРИЯ)")
            self.lbl_ballast.setStyleSheet("color: white; background-color: red; font-weight: bold; padding: 2px;")
        else:
            self.lbl_ballast.setText("⚡ Балласт: ВЫКЛ")
            self.lbl_ballast.setStyleSheet("color: gray;")
        if abs(battery_current) > 18:
            self.lbl_battery.setText("🔋 АКБ: ПЕРЕГРУЗКА!")
            self.lbl_battery.setStyleSheet("color: white; background-color: orange; font-weight: bold; padding: 2px;")
        elif battery_current < 0:
            self.lbl_battery.setText("🔋 АКБ: Разряд")
            self.lbl_battery.setStyleSheet("color: orange;")
        else:
            self.lbl_battery.setText("🔋 АКБ: Заряд")
            self.lbl_battery.setStyleSheet("color: green;")

    def create_central_widget(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        central.setLayout(layout)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setStyleSheet("""
            QSplitter::handle { background-color: #b0b0b0; width: 5px; }
            QSplitter::handle:hover { background-color: #808080; }
        """)
        self.mnemonic = MnemonicWidget(self.db, self.modbus_clients, mqtt_client=self.mqtt_client, state_manager=self.state_manager)
        self.mnemonic.setMinimumWidth(400)
        self.charts_area = ChartsArea(self.db)
        self.charts_area.setMinimumWidth(300)
        self.algo_manager = AlgorithmManager(self.sandbox)
        self.algo_manager.setMinimumWidth(300)
        self.splitter.addWidget(self.mnemonic)
        self.splitter.addWidget(self.charts_area)
        self.splitter.addWidget(self.algo_manager)
        layout.addWidget(self.splitter)
        self.mnemonic.param_selected.connect(self.add_chart)

    def restore_mnemonic(self):
        pass

    def add_chart(self, param_name, device_id):
        if not self.charts_area.add_chart(param_name, device_id):
            QMessageBox.information(self, "Информация",
                f"Не удалось добавить график '{param_name}'.\nЛимит: 4 графика.")

    def start_research(self):
        jobs = ['solar_poll', 'wind_poll']
        resumed = False
        for job_id in jobs:
            job = self.scheduler.get_job(job_id)
            if job:
                self.scheduler.resume_job(job_id)
                resumed = True
        if resumed:
            self.db.add_event("SYSTEM", "Сбор данных возобновлён")
            self.lbl_connection.setText("🟢 Подключение: АКТИВНО")
            self.lbl_connection.setStyleSheet("color: green; font-weight: bold;")

    def pause_research(self):
        jobs = ['solar_poll', 'wind_poll']
        paused = False
        for job_id in jobs:
            job = self.scheduler.get_job(job_id)
            if job:
                self.scheduler.pause_job(job_id)
                paused = True
        if paused:
            self.db.add_event("SYSTEM", "Сбор данных приостановлен")
            self.lbl_connection.setText("🟡 Подключение: ПАУЗА")
            self.lbl_connection.setStyleSheet("color: orange; font-weight: bold;")

    def run_algorithm(self):
        if self.algo_manager:
            self.algo_manager.run_script()
        else:
            QMessageBox.warning(self, "Ошибка", "Менеджер алгоритмов не инициализирован")

    def stop_algorithm(self):
        if self.algo_manager:
            self.algo_manager.stop_script()
        else:
            QMessageBox.warning(self, "Ошибка", "Менеджер алгоритмов не инициализирован")

    def show_about(self):
        QMessageBox.about(self, "О программе",
            "SCADA Ветро-солнечная установка v3.0 (API)\n"
            "Технологии: Python 3.8+, PyQt5, SQLite, MQTT, Modbus\n"
            "Архитектура: Монолитная SCADA с изолированной песочницей для скриптов.")

    def closeEvent(self, event):
        reply = QMessageBox.question(self, 'Выход', 'Остановить сбор данных и выйти?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.status_timer.stop()
            if self.sandbox: self.sandbox.stop()
            event.accept()
        else:
            event.ignore()
