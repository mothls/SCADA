from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QLabel, QFrame, QSizePolicy
from PyQt5.QtCore import Qt, pyqtSignal, QPointF
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QCursor
from gui.chart_widget import ChartWidget

class ResizeHandle(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(10)
        self.setMinimumHeight(200)
        self.setStyleSheet("""
            QFrame { background-color: transparent; border-left: 1px dashed #a0a0a0; margin: 2px; }
            QFrame:hover { border-left: 2px dashed #606060; background-color: #f8f8f8; }
        """)
        self.setToolTip("↔ Потяните, чтобы изменить размер панели графиков")
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(2)
        self.setLayout(layout)
        for _ in range(6):
            dot = QLabel("•")
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("color: #c0c0c0; font-size: 12px; font-weight: bold;")
            layout.addWidget(dot)

class RestoreArrow(QWidget):
    restore_requested = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 100)
        self.setVisible(False)
        self.setStyleSheet("background-color: transparent;")
        self.setToolTip("Нажмите, чтобы вернуть мнемосхему")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(100, 149, 237, 50)))
        painter.setPen(QPen(QColor(100, 149, 237, 180), 2))
        painter.drawPie(5, 20, 35, 60, 90 * 16, 180 * 16)
        painter.setPen(QPen(QColor(100, 149, 237, 220), 3))
        painter.setBrush(QBrush(QColor(100, 149, 237, 220)))
        arrow_poly = QPolygonF([QPointF(15, 35), QPointF(15, 65), QPointF(35, 50)])
        painter.drawPolygon(arrow_poly)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.restore_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def enterEvent(self, event):
        self.setStyleSheet("background-color: rgba(100, 149, 237, 80); border-radius: 5px;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("background-color: transparent;")
        super().leaveEvent(event)

class ChartsArea(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.charts = []
        self.used_params = set()
        self.main_layout = QHBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)
        self.restore_arrow = RestoreArrow(self)
        self.restore_arrow.restore_requested.connect(self.request_restore)
        self.main_layout.addWidget(self.restore_arrow)
        self.resize_handle = ResizeHandle(self)
        self.main_layout.addWidget(self.resize_handle)
        self.container = QWidget()
        self.container.setStyleSheet("background-color: #fafafa;")
        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.main_layout.addWidget(self.container, 1)
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(5, 5, 5, 5)
        self.content_layout.setSpacing(5)
        self.container.setLayout(self.content_layout)
        self.empty_label = QLabel("Нет графиков\nВыберите параметр на мнемосхеме\nдля добавления графика")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #808080; font-size: 14px;")
        self.content_layout.addWidget(self.empty_label, alignment=Qt.AlignCenter)
        self._rebuild_layout()

    def request_restore(self):
        pass

    def add_chart(self, param_name, device_id):
        param_key = (param_name, device_id)
        if param_key in self.used_params:
            print(f"[ChartsArea] График {param_name} для {device_id} уже используется")
            return False
        if len(self.charts) >= 4:
            print("[ChartsArea] Достигнут лимит 4 графика")
            return False
            
        chart = ChartWidget(param_name, self.db, device_id)
        chart.closed.connect(lambda c=chart: self.remove_chart(c))
        self.charts.append(chart)
        self.used_params.add(param_key)
        chart.setMinimumHeight(200)
        self._rebuild_layout()
        return True

    def remove_chart(self, chart):
        if chart in self.charts:
            param_key = (chart.param_name, chart.device_id)
            self.charts.remove(chart)
            self.used_params.discard(param_key)
            chart.setParent(None)
            chart.deleteLater()
            self._rebuild_layout()

    def show_restore_arrow(self, show):
        self.restore_arrow.setVisible(show)

    def _rebuild_layout(self):
        n = len(self.charts)
        active_charts = list(self.charts)
        c0 = active_charts[0] if n > 0 else None
        c1 = active_charts[1] if n > 1 else None
        c2 = active_charts[2] if n > 2 else None
        c3 = active_charts[3] if n > 3 else None
        
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            
        self.empty_label.setVisible(n == 0)
        if n == 0:
            self.content_layout.addWidget(self.empty_label, alignment=Qt.AlignCenter)
            return
            
        if n == 1:
            self.content_layout.addWidget(c0)
        elif n == 2:
            splitter = QSplitter(Qt.Vertical)
            splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            splitter.addWidget(c0)
            splitter.addWidget(c1)
            self.content_layout.addWidget(splitter)
        elif n == 3:
            top_splitter = QSplitter(Qt.Vertical)
            top_splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            bottom_splitter = QSplitter(Qt.Horizontal)
            bottom_splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            bottom_splitter.addWidget(c1)
            bottom_splitter.addWidget(c2)
            top_splitter.addWidget(c0)
            top_splitter.addWidget(bottom_splitter)
            self.content_layout.addWidget(top_splitter)
        elif n == 4:
            left_splitter = QSplitter(Qt.Vertical)
            left_splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            left_splitter.addWidget(c0)
            left_splitter.addWidget(c1)
            right_splitter = QSplitter(Qt.Vertical)
            right_splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            right_splitter.addWidget(c2)
            right_splitter.addWidget(c3)
            main_splitter = QSplitter(Qt.Horizontal)
            main_splitter.setStyleSheet("QSplitter::handle { background-color: #c0c0c0; width: 5px; }")
            main_splitter.addWidget(left_splitter)
            main_splitter.addWidget(right_splitter)
            self.content_layout.addWidget(main_splitter)
