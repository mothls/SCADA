import time
import logging
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QToolTip
from PyQt5.QtCore import pyqtSignal, Qt, QPointF, QDateTime
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QDateTimeAxis, QValueAxis
from PyQt5.QtGui import QPainter, QPen, QColor
import datetime

logger = logging.getLogger(__name__)

class ChartWidget(QWidget):
    closed = pyqtSignal()

    def __init__(self, param_name, db, device_id, parent=None):
        super().__init__(parent)
        self.param_name = param_name
        self.db = db
        self.device_id = device_id
       
        
        self.setup_ui()
        self.update_data()
        if self.db:
            self.db.data_added.connect(self.update_data)

    def setup_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setStyleSheet("border: 1px solid gray; border-radius: 5px; margin: 2px;")
        header = QHBoxLayout()
        self.title_label = QLabel(self.param_name)
        self.title_label.setStyleSheet("font-weight: bold;")
        header.addWidget(self.title_label)
        header.addStretch()
        close_btn = QPushButton("✖")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.close_clicked)
        header.addWidget(close_btn)
        layout.addLayout(header)
        
        self.chart = QChart()
        self.chart.setTitle(f"{self.param_name} (последние 100 измерений)")
        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.Antialiasing)
        self.chart_view.setRubberBand(QChartView.RectangleRubberBand)
        
        self.axis_x = QDateTimeAxis()
        self.axis_x.setFormat("hh:mm:ss")
        self.axis_x.setTitleText("Время")
        self.axis_y = QValueAxis()
        
        if "Ток" in self.param_name: self.axis_y.setTitleText("Ток (А)")
        elif "Напряжение" in self.param_name: self.axis_y.setTitleText("Напряжение (В)")
        elif "Температура" in self.param_name: self.axis_y.setTitleText("Температура (°C)")
        elif "Частота вращения" in self.param_name: self.axis_y.setTitleText("Скорость (об/мин)")
        elif "Угол атаки" in self.param_name: self.axis_y.setTitleText("Угол (°)")
        else: self.axis_y.setTitleText("Значение")
        
        self.chart.addAxis(self.axis_x, Qt.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignLeft)
        self.chart_view.setMouseTracking(True)
        self.chart_view.mouseMoveEvent = self.on_mouse_move
        layout.addWidget(self.chart_view)
        self.setMinimumSize(300, 200)

    def on_mouse_move(self, event):
        pos = event.pos()
        point = self.chart_view.mapToScene(pos)
        if not point.isNull():
            for series in self.chart.series():
                for point_data in series.points():
                    pixel_point = self.chart_view.mapFromScene(point_data)
                    if (pixel_point - pos).manhattanLength() < 5:
                        timestamp = QDateTime.fromMSecsSinceEpoch(int(point_data.x()))
                        value = point_data.y()
                        tooltip = f"Время: {timestamp.toString('hh:mm:ss')}\nЗначение: {value:.2f}"
                        QToolTip.showText(event.globalPos(), tooltip)
                        return
        QToolTip.hideText()

    def update_data(self):
        
        if self.param_name == "Угол атаки":
            self.chart.setTitle(f"{self.param_name} (Заглушка: данные пока не поступают)")
            self.chart.removeAllSeries()
            series = QLineSeries()
            series.append(QDateTime.currentDateTime().addSecs(-60).toMSecsSinceEpoch(), 0)
            series.append(QDateTime.currentDateTime().toMSecsSinceEpoch(), 0)
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)
            self.axis_y.setRange(-10, 10)
            self.axis_x.setRange(QDateTime.currentDateTime().addSecs(-60), QDateTime.currentDateTime())
            return

        param_map = {
            "Ток входной": "iin",
            "Ток выходной": "iout",
            "Ток нагрузки (расч.)": "iout",
            "Напряжение входное": "vin",
            "Напряжение выходное": "vout",
            "Температура": "temp",
            "Частота вращения": "rpm"
        }
        
        db_param = param_map.get(self.param_name)
        
        if not db_param:
            return

        # Читаем данные из БД
        if self.device_id == "wind_turbine" and db_param == "rpm":
            history = self.db.get_telemetry_history(self.device_id, db_param, limit=100)
        else:
            logger.debug(f"[CHART] Reading history for {self.device_id}/{db_param}")
            history = self.db.get_history_for_param(self.device_id, db_param, limit=100)
            
        logger.debug(f"[CHART] Got {len(history) if history else 0} records from DB")
        
        if not history:
            # Рисуем пустой график с осями
            series = QLineSeries()
            now = QDateTime.currentDateTime()
            series.append(now.addSecs(-60).toMSecsSinceEpoch(), 0)
            series.append(now.toMSecsSinceEpoch(), 0)
            self.chart.removeAllSeries()
            self.chart.addSeries(series)
            series.attachAxis(self.axis_x)
            series.attachAxis(self.axis_y)
            self.chart.setTitle(f"{self.param_name} (Нет данных)")
            self.axis_x.setRange(now.addSecs(-60), now)
            self.axis_y.setRange(-1, 1)
            return

        # Есть данные - рисуем график
        series = QLineSeries()
        values = []
        for ts, val in history:
            qdatetime = QDateTime(ts)
            series.append(qdatetime.toMSecsSinceEpoch(), val)
            values.append(val)
            logger.debug(f"[CHART] Point: {ts} -> {val}")
            
        self.chart.removeAllSeries()
        self.chart.addSeries(series)
        series.attachAxis(self.axis_x)
        series.attachAxis(self.axis_y)
        
        # Настраиваем оси
        min_ts = history[0][0]
        max_ts = history[-1][0]
        delta = (max_ts - min_ts) * 0.05
        self.axis_x.setRange(QDateTime(min_ts - delta), QDateTime(max_ts + delta))
        
        min_val = min(values)
        max_val = max(values)
        delta_val = (max_val - min_val) * 0.05 if max_val != min_val else 1.0
        self.axis_y.setRange(min_val - delta_val, max_val + delta_val)
        
        self.chart.setTitle(f"{self.param_name} ({len(history)} точек)")

    def close_clicked(self):
        self.closed.emit()
        self.deleteLater()
