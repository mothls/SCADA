import os
import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMenu,
                             QAction, QPushButton, QToolTip)
from PyQt5.QtCore import Qt, QRect, QTimer, pyqtSignal, QPoint
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QCursor, QBrush

class IOSSwitch(QPushButton):
    toggled = pyqtSignal(bool)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(50, 30)
        self._checked = False
        self.setChecked(False)
        self.clicked.connect(self._on_click)
        self.update_style()

    def _on_click(self):
        self._checked = self.isChecked()
        self.update_style()
        self.toggled.emit(self._checked)

    def setChecked(self, checked):
        super().setChecked(checked)
        self._checked = checked
        self.update_style()

    def update_style(self):
        bg = "#4cd964" if self._checked else "#e5e5e5"
        self.setStyleSheet(f"""
            QPushButton {{ background-color: {bg}; border-radius: 15px; border: none; }}
            QPushButton::indicator {{ width: 26px; height: 26px; background-color: white; border-radius: 13px; margin: 2px; }}
        """)

class InfoPopup(QFrame):
    param_selected = pyqtSignal(str, str)

    def __init__(self, zone_name, device_id, db, modbus_client, mqtt_client=None, state_manager=None, pos=None, parent=None):
        super().__init__(None, Qt.Popup | Qt.FramelessWindowHint)
        self.zone_name = zone_name
        self.device_id = device_id
        self.db = db
        self.modbus_client = modbus_client
        self.mqtt_client = mqtt_client
        self.state_manager = state_manager
        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("background-color: #ffffcc; border: 1px solid black; padding: 5px;")
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        top_layout = QHBoxLayout()
        self.title_label = QLabel(f"<b>{zone_name}</b>")
        self.title_label.setStyleSheet("font-size: 14px;")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        self.switch_btn = IOSSwitch()
        self.switch_btn.toggled.connect(self.on_switch_toggled)
        top_layout.addWidget(self.switch_btn)
        layout.addLayout(top_layout)
        
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.currents_label = QLabel()
        self.voltages_label = QLabel()
        layout.addWidget(self.status_label)
        layout.addWidget(self.currents_label)
        layout.addWidget(self.voltages_label)
        
        btn_start = QPushButton("Начать запись графика")
        btn_start.setCursor(Qt.PointingHandCursor)
        btn_start.clicked.connect(self.show_param_menu)
        layout.addWidget(btn_start)
        
        self.update_data()
        if pos:
            self.move(pos.x() + 15, pos.y() + 15)
        self.adjustSize()

    def update_data(self):
        if not self.isVisible():
            return
        try:
            if self.device_id == "load":
                state = self.state_manager.get("load_state") if self.state_manager else None
                self.switch_btn.blockSignals(True)
                self.switch_btn.setChecked(state == "ON")
                self.switch_btn.blockSignals(False)
                self.status_label.setText(f"Состояние: <b>{'ВКЛ' if state == 'ON' else 'ВЫКЛ' if state == 'OFF' else 'Нет связи'}</b>")
                load_current = self.state_manager.get("load_current", 0.0) if self.state_manager else 0.0
                self.currents_label.setText(f"Ток нагрузки: <b>{load_current:.2f} А</b>")
                self.voltages_label.setText("Питание через Wi-Fi розетку")
                
            elif self.device_id == "wind_turbine":
                if not self.state_manager:
                    self.status_label.setText("⚠ StateManager не инициализирован")
                    self.switch_btn.setVisible(False)
                    return
                    
                rpm = self.state_manager.get("wind_rpm", 0.0)
                angle = self.state_manager.get("wind_attack_angle", 0.0)
                status_raw = self.state_manager.get("wind_status", "OFFLINE")
                self.switch_btn.setVisible(False)
                
                status_text = "Активен" if status_raw and status_raw.upper() == "ONLINE" else "Нет связи"
                status_color = "green" if status_text == "Активен" else "red"
                self.status_label.setText(f"Контроллер ESP32: <span style='color:{status_color}; font-weight:bold;'>{status_text.upper()}</span>")
                self.currents_label.setText(f"Частота вращения: <b>{rpm:.1f} об/мин</b>")
                self.voltages_label.setText(f"Угол атаки: <b>{angle:.1f}°</b>")
                
            elif self.device_id == "battery":
                if not self.state_manager:
                    self.status_label.setText("⚠ StateManager не инициализирован")
                    self.switch_btn.setVisible(False)
                    return
                    
                self.switch_btn.setVisible(False)
                current = self.state_manager.get_battery_current()
                voltage = self.state_manager.get_battery_voltage()
                status = self.state_manager.get_battery_status()
                soc = self.state_manager.get("battery_soc", 0.0)  # ← НОВАЯ СТРОКА
                
                status_text = "Заряжается" if status == "CHARGING" else ("Разряжается" if status == "DISCHARGING" else "Не активна")
                status_color = "green" if status == "CHARGING" else ("orange" if status == "DISCHARGING" else "gray")
                
                # Определяем цвет SOC
                if soc >= 50:
                    soc_color = "green"
                elif soc >= 20:
                    soc_color = "orange"
                else:
                    soc_color = "red"
                
                self.status_label.setText(f"SOC: <span style='color:{soc_color}; font-weight:bold; font-size:16px;'>{soc:.1f}%</span>")
                self.currents_label.setText(f"Режим: <b>{status_text}</b> | Ток: <b>{current:.2f} A</b>")
                self.voltages_label.setText(f"Напряжение: <b>{voltage:.2f} V</b>")
                
            else:
                latest = self.db.get_latest_data(self.device_id)
                if latest:
                    vin, vout, iin, iout, temp = latest
                    self.status_label.setText(f"<span style='color:green; font-weight:bold;'>● Активен</span>")
                    self.currents_label.setText(f"Ток: <b>{iin:.2f}</b> A (вх) | <b>{iout:.2f}</b> A (вых)")
                    self.voltages_label.setText(f"Напр.: <b>{vin:.2f}</b> V (вх) | <b>{vout:.2f}</b> V (вых)<br>Темп.: <b>{temp:.1f}</b> °C")
                else:
                    self.status_label.setText(f"<span style='color:red'>● Нет данных</span>")
                    self.currents_label.setText("")
                    self.voltages_label.setText("")
                    
                if self.modbus_client:
                    enabled = self.modbus_client.read_output_enabled()
                    if enabled is not None:
                        self.switch_btn.blockSignals(True)
                        self.switch_btn.setChecked(enabled)
                        self.switch_btn.blockSignals(False)
        except Exception as e:
            print(f"[Popup] Error: {e}")

    def on_switch_toggled(self, checked):
        if self.device_id == "load":
            if not self.state_manager:
                QToolTip.showText(QCursor.pos(), "State Manager не инициализирован")
                self.switch_btn.setChecked(not checked)
                return
            try:
                self.state_manager.set_pending("load", checked)
                self.db.add_event("LOAD", f"GUI рекомендует {'ON' if checked else 'OFF'}")
            except Exception as e:
                QToolTip.showText(QCursor.pos(), f"Ошибка: {e}")
                self.switch_btn.setChecked(not checked)
        else:
            if not self.modbus_client:
                QToolTip.showText(QCursor.pos(), "Нет связи")
                self.switch_btn.setChecked(not checked)
                return
            try:
                ok = self.modbus_client.write_output_enable(checked)
                if ok:
                    self.update_data()
                else:
                    QToolTip.showText(QCursor.pos(), "Ошибка записи")
                    self.switch_btn.setChecked(not checked)
            except Exception as e:
                self.switch_btn.setChecked(not checked)

    def show_param_menu(self):
        menu = QMenu()
        
        if self.device_id == "wind_turbine":
            params = ["Ток выходной", "Напряжение выходное", "Частота вращения", "Угол атаки"]
        elif self.device_id == "battery":
            params = ["Ток выходной", "Напряжение выходное"]
        else:
            params = ["Ток входной", "Ток выходной", "Напряжение входное", "Напряжение выходное", "Температура"]
            
        for param in params:
            action = QAction(param, self)
            action.triggered.connect(lambda checked, p=param: self.param_selected.emit(p, self.device_id))
            menu.addAction(action)
        menu.exec_(QCursor.pos())
        self.close()

class MnemonicWidget(QWidget):
    param_selected = pyqtSignal(str, str)

    def __init__(self, db, modbus_clients_dict, mqtt_client=None, state_manager=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.modbus_clients = modbus_clients_dict
        self.mqtt_client = mqtt_client
        self.state_manager = state_manager
        self.original_image_size = None
        self.active_zones = {
            "Солнечный конвертер": {"rect": QRect(716, 775, 100, 100), "id": "solar_converter"},
            "Ветро конвертер":     {"rect": QRect(178, 775, 100, 100),  "id": "wind_converter"},
            "Электрическая нагрузка": {"rect": QRect(878, 528, 100, 36), "id": "load"},
            "Ветрогенератор (RPM)": {"rect": QRect(27, 10, 151, 100), "id": "wind_turbine"},
            "Аккумуляторная батарея": {"rect": QRect(900, 10, 100, 100), "id": "battery"}
        }
        self.current_hover_zone = None
        self.active_popup = None
        self.hover_tooltip = None
        self.status_colors = {}
        self.pixmap = QPixmap()
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)
        self.drag_start = QPoint()
        self.is_dragging = False
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        self.image_path = os.path.join(project_root, "resources", "mnemonic_shem.jpg")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.initUI()
        
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_all_statuses_and_tooltips)
        self.update_timer.start(1000)
        self.update_all_statuses_and_tooltips()

    def initUI(self):
        if os.path.exists(self.image_path):
            self.pixmap = QPixmap(self.image_path)
            self.original_image_size = self.pixmap.size()
            for zone_name in self.active_zones:
                self.status_colors[zone_name] = QColor(150, 150, 150)
            self.fit_to_view()
        else:
            self.pixmap = QPixmap(800, 600)
            self.pixmap.fill(Qt.lightGray)

    def fit_to_view(self):
        if self.pixmap.isNull() or self.width() == 0:
            return
        scale_w = self.width() / self.pixmap.width()
        scale_h = self.height() / self.pixmap.height()
        self.scale_factor = min(scale_w, scale_h) * 0.95
        scaled_w = self.pixmap.width() * self.scale_factor
        scaled_h = self.pixmap.height() * self.scale_factor
        self.offset.setX(int((self.width() - scaled_w) / 2))
        self.offset.setY(int((self.height() - scaled_h) / 2))
        self.update()

    def update_all_statuses_and_tooltips(self):
        for zone_name, zone_data in self.active_zones.items():
            self._calculate_zone_status(zone_name, zone_data["id"])
        self.update()
        if self.active_popup and not self.active_popup.isHidden():
            try:
                self.active_popup.update_data()
            except RuntimeError:
                self.active_popup = None
        if self.hover_tooltip and self.hover_tooltip.isVisible():
            self.update_hover_tooltip()

    def _calculate_zone_status(self, zone_name, device_id):
        if device_id == "load":
            if self.state_manager:
                state = self.state_manager.get("load_state")
                if state == "ON":
                    self.status_colors[zone_name] = QColor(0, 200, 0)
                elif state == "OFF":
                    self.status_colors[zone_name] = QColor(200, 0, 0)
                else:
                    self.status_colors[zone_name] = QColor(150, 150, 150)
            return
            
        if device_id == "wind_turbine":
            if self.state_manager:
                status = self.state_manager.get("wind_status")
                rpm = self.state_manager.get("wind_rpm", 0.0)
                if status and status.upper() == "ONLINE":
                    if rpm < 1000:
                        self.status_colors[zone_name] = QColor(0, 200, 0)
                    elif rpm < 1500:
                        self.status_colors[zone_name] = QColor(255, 165, 0)
                    else:
                        self.status_colors[zone_name] = QColor(255, 0, 0)
                else:
                    self.status_colors[zone_name] = QColor(255, 0, 0)
            return

        if device_id == "battery":
            if self.state_manager:
                status = self.state_manager.get_battery_status()
                if status == "CHARGING":
                    self.status_colors[zone_name] = QColor(0, 200, 0)
                elif status == "DISCHARGING":
                    self.status_colors[zone_name] = QColor(255, 165, 0)
                else:
                    self.status_colors[zone_name] = QColor(150, 150, 150)
            return

        history = self.db.get_history_for_param(device_id, 'vout', limit=70)
        now = datetime.datetime.now()
        one_minute_ago = now - datetime.timedelta(minutes=1)
        valid_count = sum(1 for ts, val in history if ts and val is not None and ts >= one_minute_ago)
        if valid_count == 0:
            self.status_colors[zone_name] = QColor(255, 0, 0)
        elif valid_count < 30:
            self.status_colors[zone_name] = QColor(255, 165, 0)
        else:
            self.status_colors[zone_name] = QColor(0, 200, 0)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.save()
        painter.translate(self.offset)
        painter.scale(self.scale_factor, self.scale_factor)
        if not self.pixmap.isNull():
            painter.drawPixmap(0, 0, self.pixmap)
        for zone_name, zone_data in self.active_zones.items():
            rect = zone_data["rect"]
            if zone_name == self.current_hover_zone:
                painter.setPen(QPen(QColor(255, 255, 0, 200), 3 / self.scale_factor))
                painter.setBrush(QColor(255, 255, 0, 40))
                painter.drawRect(rect)
            color = self.status_colors.get(zone_name, QColor(150, 150, 150))
            indicator_x = rect.right() - 25
            indicator_y = rect.top() + 5
            indicator_rect = QRect(indicator_x, indicator_y, 20, 20)
            painter.setPen(QPen(Qt.white, 2 / self.scale_factor))
            painter.setBrush(QBrush(color))
            painter.drawEllipse(indicator_rect)
        painter.restore()

    def wheelEvent(self, event):
        if self.pixmap.isNull():
            return
        cursor_pos = event.pos()
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.1 if delta > 0 else 0.9
        new_scale = self.scale_factor * factor
        if new_scale < 0.1 or new_scale > 5.0:
            return
        pos_before = (cursor_pos - self.offset) / self.scale_factor
        self.scale_factor = new_scale
        new_offset_f = cursor_pos - pos_before * self.scale_factor
        self.offset = QPoint(int(new_offset_f.x()), int(new_offset_f.y()))
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos_in_image_f = (event.pos() - self.offset) / self.scale_factor
            clicked_zone = None
            clicked_id = None
            for name, data in self.active_zones.items():
                if data["rect"].contains(pos_in_image_f):
                    clicked_zone = name
                    clicked_id = data["id"]
                    break
            if clicked_zone:
                if self.active_popup:
                    self.active_popup.close()
                self.active_popup = None
                client = self.modbus_clients.get(clicked_id)
                try:
                    self.active_popup = InfoPopup(clicked_zone, clicked_id, self.db, client, self.mqtt_client, self.state_manager, event.globalPos())
                    self.active_popup.param_selected.connect(self.on_param_selected)
                    self.active_popup.destroyed.connect(self._on_popup_destroyed)
                    self.active_popup.show()
                except Exception as e:
                    print(f"[ERROR] Popup creation failed: {e}")
            else:
                self.is_dragging = True
                self.drag_start = event.pos() - self.offset
                self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def _on_popup_destroyed(self):
        self.active_popup = None

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.is_dragging:
            self.offset = pos - self.drag_start
            self.update()
            return
        pos_in_image_f = (pos - self.offset) / self.scale_factor
        hovered = None
        for name, data in self.active_zones.items():
            if data["rect"].contains(pos_in_image_f):
                hovered = name
                break
        if hovered != self.current_hover_zone:
            self.current_hover_zone = hovered
            self.update()
            if hovered:
                self.show_hover_tooltip(hovered, pos)
            else:
                self.hide_hover_tooltip()
        elif hovered and self.hover_tooltip and self.hover_tooltip.isVisible():
            self.hover_tooltip.move(pos.x() + 15, pos.y() + 15)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_dragging:
            self.is_dragging = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.fit_to_view()
            self.update()
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.current_hover_zone = None
        self.update()
        self.hide_hover_tooltip()
        super().leaveEvent(event)

    def show_hover_tooltip(self, zone_name, cursor_pos):
        if self.active_popup:
            return
        if self.hover_tooltip is None:
            self.hover_tooltip = QFrame(self)
            self.hover_tooltip.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
            self.hover_tooltip.setAttribute(Qt.WA_TranslucentBackground, False)
            self.hover_tooltip.setFrameShape(QFrame.StyledPanel)
            self.hover_tooltip.setStyleSheet("QFrame { background-color: rgba(255, 255, 220, 240); border: 1px solid #aaa; border-radius: 4px; padding: 4px; } QLabel { color: #333; font-size: 11px; }")
            layout = QVBoxLayout()
            layout.setContentsMargins(4, 2, 4, 2)
            layout.setSpacing(1)
            self.hover_tooltip.setLayout(layout)
            self.hover_status = QLabel()
            self.hover_currents = QLabel()
            self.hover_voltages = QLabel()
            font = self.hover_status.font()
            font.setBold(True)
            self.hover_status.setFont(font)
            layout.addWidget(self.hover_status)
            layout.addWidget(self.hover_currents)
            layout.addWidget(self.hover_voltages)
        self.update_hover_tooltip()
        self.hover_tooltip.move(cursor_pos.x() + 15, cursor_pos.y() + 15)
        self.hover_tooltip.show()
        self.hover_tooltip.adjustSize()
        self.hover_tooltip.raise_()

    def hide_hover_tooltip(self):
        if self.hover_tooltip:
            self.hover_tooltip.hide()

    def update_hover_tooltip(self):
        if not self.hover_tooltip or not self.hover_tooltip.isVisible() or not self.current_hover_zone:
            return
        try:
            device_id = self.active_zones[self.current_hover_zone]["id"]
            
            if device_id == "wind_turbine":
                if self.state_manager:
                    rpm = self.state_manager.get("wind_rpm", 0.0)
                    angle = self.state_manager.get("wind_attack_angle", 0.0)
                    status = self.state_manager.get("wind_status", "OFFLINE")
                    status_text = "Активен" if status and status.upper() == "ONLINE" else "Нет связи"
                    color = "green" if status_text == "Активен" else "red"
                    self.hover_status.setText(f"<b>{self.current_hover_zone}</b> <span style='color:{color}'>● {status_text.upper()}</span>")
                    self.hover_currents.setText(f"RPM: {rpm:.1f} об/мин")
                    self.hover_voltages.setText(f"Угол атаки: {angle:.1f}°")
                return
                
            if device_id == "battery":
                if self.state_manager:
                    current = self.state_manager.get_battery_current()
                    voltage = self.state_manager.get_battery_voltage()
                    status = self.state_manager.get_battery_status()
                    status_text = "Заряжается" if status == "CHARGING" else ("Разряжается" if status == "DISCHARGING" else "Не активна")
                    color = "green" if status == "CHARGING" else ("orange" if status == "DISCHARGING" else "gray")
                    self.hover_status.setText(f"<b>{self.current_hover_zone}</b> <span style='color:{color}'>● {status_text}</span>")
                    self.hover_currents.setText(f"I: {current:.2f} A")
                    self.hover_voltages.setText(f"U: {voltage:.2f} V")
                return
                
            if device_id == "load":
                state = "Нет связи"
                if self.state_manager:
                    s = self.state_manager.get("load_state")
                    state = "ВКЛ" if s == "ON" else ("ВЫКЛ" if s == "OFF" else "Нет связи")
                self.hover_status.setText(f"<b>{self.current_hover_zone}</b> <span style='color:green'>● {state}</span>")
                self.hover_currents.setText("")
                self.hover_voltages.setText("Питание через Wi-Fi розетку")
                return
                
            latest = self.db.get_latest_data(device_id)
            if latest:
                vin, vout, iin, iout, temp = latest
                color_obj = self.status_colors.get(self.current_hover_zone, QColor(150,150,150))
                color_name = "green" if color_obj == QColor(0, 200, 0) else ("orange" if color_obj == QColor(255, 165, 0) else "red")
                self.hover_status.setText(f"<b>{self.current_hover_zone}</b> <span style='color:{color_name}'>●</span>")
                self.hover_currents.setText(f"I: {iin:.2f}A / {iout:.2f}A")
                self.hover_voltages.setText(f"U: {vin:.2f}V / {vout:.2f}V<br>Temp: {temp:.1f}°C")
            else:
                self.hover_status.setText(f"<b>{self.current_hover_zone}</b> <span style='color:red'>● Нет связи</span>")
                self.hover_currents.setText("")
                self.hover_voltages.setText("")
            self.hover_tooltip.adjustSize()
        except:
            pass

    def on_param_selected(self, param_name, device_id):
        self.param_selected.emit(param_name, device_id)
        if self.active_popup:
            self.active_popup.close()

    def resizeEvent(self, event):
        super().resizeEvent(event)
