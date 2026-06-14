from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QFileDialog, QMessageBox
from PyQt5.QtCore import QTimer

class AlgorithmManager(QWidget):
    """
    Виджет управления пользовательскими алгоритмами.
    Предоставляет интерфейс для загрузки, запуска и остановки скриптов.
    """
    def __init__(self, sandbox_runner, parent=None):
        super().__init__(parent)
        self.sandbox = sandbox_runner
        self.script_path = None
        self.setup_ui()

    def setup_ui(self):
        """Создание интерфейса виджета"""
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Кнопки управления
        controls = QHBoxLayout()
        self.btn_load = QPushButton("📂 Загрузить скрипт")
        self.btn_run = QPushButton("▶ Запустить")
        self.btn_stop = QPushButton("⏹ Остановить")
        
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(False)
        
        controls.addWidget(self.btn_load)
        controls.addWidget(self.btn_run)
        controls.addWidget(self.btn_stop)
        layout.addLayout(controls)

        # Индикатор статуса
        self.lbl_status = QLabel("Статус: IDLE")
        self.lbl_status.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.lbl_status)

        # Область логов
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Логи выполнения скрипта...")
        self.log.setMaximumHeight(300)
        layout.addWidget(self.log)

        # Привязка сигналов
        self.btn_load.clicked.connect(self.load_script)
        self.btn_run.clicked.connect(self.run_script)
        self.btn_stop.clicked.connect(self.stop_script)

        # Таймер обновления статуса (1 Гц)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_status)
        self.timer.start(1000)

    def load_script(self):
        """Открывает диалог выбора файла скрипта"""
        path, _ = QFileDialog.getOpenFileName(
            self, 
            "Выберите скрипт", 
            ".", 
            "Python Files (*.py)"
        )
        if path:
            self.script_path = path
            filename = path.split('/')[-1]
            self.lbl_status.setText(f"Загружен: {filename}")
            self.btn_run.setEnabled(True)
            self.log.append(f"[INFO] Script loaded: {path}")

    def run_script(self):
        """Загружает и запускает скрипт (вызывает run(api))"""
        if self.script_path:
            self.log.append("[INFO] Loading & starting script...")
            success = self.sandbox.load(self.script_path)
            if success:
                self.btn_run.setEnabled(False)
                self.btn_stop.setEnabled(True)
                self.btn_load.setEnabled(False)
                self.log.append("[INFO] Script started successfully.")
            else:
                self.log.append("[ERROR] Failed to load script.")
                status, err = self.sandbox.get_status()
                if err:
                    self.log.append(f"[ERROR] {err}")

    def stop_script(self):
        """Останавливает скрипт (вызывает stop(api))"""
        self.sandbox.stop()
        self.log.append("[INFO] Script stopped.")
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_load.setEnabled(True)
        self.lbl_status.setText("Статус: IDLE")

    def update_status(self):
        """Обновляет индикатор статуса каждую секунду"""
        status, err = self.sandbox.get_status()
        self.lbl_status.setText(f"Статус: {status}")
        
        if err:
            self.log.append(f"[ERROR] {err}")
            self.sandbox._error = None  # сброс после показа
