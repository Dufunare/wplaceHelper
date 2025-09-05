# wplace_helper.py
from __future__ import annotations
from typing import List, Tuple, Optional, Set, Dict

import sys
import math
import colorsys
import json
from pathlib import Path

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QTimer, Signal
)
from PySide6.QtGui import (
    QAction, QImage, QPainter, QPen, QBrush, QColor, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QComboBox, QCheckBox, QLineEdit, QMessageBox,
    QGraphicsView, QGraphicsScene, QToolBar, QStatusBar, QMenu, QInputDialog,
    QGraphicsItem,QSlider
)

from PIL import Image
from sklearn.cluster import KMeans
import numpy as np

# -------------------- 工具函数 --------------------

def qimage_from_pil(img: Image.Image) -> QImage:
    if img.mode != "RGBA": img = img.convert("RGBA")
    return QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format_RGBA8888).copy()

def hex_from_qcolor(c: QColor) -> str:
    return "#%02X%02X%02X" % (c.red(), c.green(), c.blue())

def build_even_hsv_palette(n: int) -> List[Tuple[int, int, int]]:
    if n <= 0: return [(0, 0, 0)]
    out = []
    rows = 2 if n > 16 else 1
    per_row = math.ceil(n / rows)
    for r in range(rows):
        v = 0.8 - r * 0.25
        for i in range(per_row):
            h, s = (i / per_row), 0.75
            rgb = colorsys.hsv_to_rgb(h, s, v)
            out.append(tuple(int(255 * x) for x in rgb))
            if len(out) >= n: return out
    return out
    
def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

PRESET_16 = [(0,0,0),(255,255,255),(190,38,51),(224,111,139),(73,60,43),(164,100,34),(235,137,49),(247,226,107),(47,72,78),(68,137,26),(163,206,39),(27,38,50),(0,87,132),(49,162,242),(178,220,239),(58,175,169)]
WPLACE_PALETTE_HEX = ["000000","3c3c3c","787878","d2d2d2","ffffff","600018","ed1c24","ff7f27","f6aa09","f9dd3b","fffabc","0eb968","13e67b","87ff5e","0c816e","10aea6","13e1be","28509e","4093e4","60f7f2","6b50f6","99b1fb","780c99","aa38b9","e09ff9","cb007a","ec1f80","f38da9","684634","95682a","f8b277"]
WPLACE_PALETTE = [hex_to_rgb(h) for h in WPLACE_PALETTE_HEX]

# -------------------- 自定义的覆盖层图形项 --------------------

class OverlayItem(QGraphicsItem):
    def __init__(self, pixel_view: "PixelView", parent: QGraphicsItem | None = None):
        super().__init__(parent)
        self.view = pixel_view

    def boundingRect(self) -> QRectF:
        if self.view.pixel_qimg: return QRectF(0, 0, self.view.pixel_qimg.width(), self.view.pixel_qimg.height())
        return QRectF()

    def paint(self, painter: QPainter, option, widget=None):
        if not self.view.pixel_qimg: return
        painter.setRenderHint(QPainter.Antialiasing, False)
        if self.view.show_grid and self.view.transform().m11() > 4:
            pen = QPen(QColor(0,0,0,40)); pen.setWidth(0); pen.setCosmetic(True); painter.setPen(pen)
            w, h = self.view.pixel_qimg.width(), self.view.pixel_qimg.height()
            view_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
            left, top, right, bottom = max(0, int(view_rect.left())), max(0, int(view_rect.top())), min(w, math.ceil(view_rect.right())), min(h, math.ceil(view_rect.bottom()))
            for x in range(left, right + 1): painter.drawLine(x, top, x, bottom)
            for y in range(top, bottom + 1): painter.drawLine(left, y, right, y)
        if self.view.painted:
            pen = QPen(QColor(220,20,60,230)); pen.setWidthF(3.0); pen.setCosmetic(True); pen.setCapStyle(Qt.RoundCap); painter.setPen(pen)
            margin = 0.2
            for (x, y) in self.view.painted:
                painter.drawLine(QPointF(x + margin, y + margin), QPointF(x + 1 - margin, y + 1 - margin))
                painter.drawLine(QPointF(x + 1 - margin, y + margin), QPointF(x + margin, y + 1 - margin))
        if self.view.hovered_pixel and self.view.hovered_pixel != self.view.selected_pixel:
            x, y = self.view.hovered_pixel
            pen = QPen(QColor(255,0,0,180), 1.5); pen.setCosmetic(True); painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawRect(QRectF(x, y, 1, 1))
        if self.view.selected_pixel:
            x, y = self.view.selected_pixel
            pen = QPen(QColor(255,215,0,255), 2.0); pen.setCosmetic(True); painter.setPen(pen); painter.setBrush(Qt.NoBrush); painter.drawRect(QRectF(x, y, 1, 1))

# -------------------- 像素画视图 --------------------

class PixelView(QGraphicsView):
    colorChanged = Signal(str, int, int); hoverChanged = Signal(str, int, int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing, False); self.setRenderHint(QPainter.SmoothPixmapTransform, False); self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate); self.setMouseTracking(True); self.setTransformationAnchor(QGraphicsView.NoAnchor); self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.scene = QGraphicsScene(self); self.setScene(self.scene)
        self.pixmap_item, self.overlay_item, self.pixel_qimg = None, None, None
        self.output_w, self.output_h = 0, 0
        self.painted: Set[Tuple[int, int]] = set()
        self.selected_pixel, self.hovered_pixel, self.show_grid = None, None, False
        self._press_pos, self._panning, self._pan_timer = None, False, QTimer(self)
        self._pan_timer.setSingleShot(True); self._pan_timer.timeout.connect(self._start_pan_by_timer)

    def set_image(self, qimg: QImage):
        self.pixel_qimg = qimg; self.output_w, self.output_h = qimg.width(), qimg.height()
        pm = QPixmap.fromImage(qimg)
        if self.pixmap_item is None: self.pixmap_item = self.scene.addPixmap(pm)
        else: self.pixmap_item.setPixmap(pm)
        if self.overlay_item is None: self.overlay_item = OverlayItem(self); self.scene.addItem(self.overlay_item)
        else: self.overlay_item.setZValue(1); self.overlay_item.prepareGeometryChange()
        self.scene.setSceneRect(QRectF(0, 0, pm.width(), pm.height())); self.resetTransform(); self.centerOn(self.pixmap_item)
        self.painted.clear(); self.selected_pixel = None; self.hovered_pixel = None; self.overlay_item.update()

    def toggle_grid(self, on: bool): self.show_grid = on; self.overlay_item.update() if self.overlay_item else None
    def fit_to_view(self):
        if self.pixel_qimg: self.fitInView(QRectF(0, 0, self.pixel_qimg.width(), self.pixel_qimg.height()), Qt.KeepAspectRatio)

    def mousePressEvent(self, e):
        if not self.pixel_qimg: return super().mousePressEvent(e)
        if e.button() == Qt.MiddleButton: self._start_pan(e.position()); return
        if e.button() == Qt.LeftButton:
            self._press_pos, self._panning = e.position(), False; self.setCursor(Qt.ArrowCursor); self._pan_timer.start(220)
        elif e.button() == Qt.RightButton and self.hovered_pixel: self.toggle_mark_at(self.hovered_pixel)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.pixel_qimg and not self._panning:
            new_hover = self._map_to_pixel(e.position())
            if new_hover != self.hovered_pixel:
                self.hovered_pixel = new_hover
                if self.overlay_item: self.overlay_item.update()
                self.hoverChanged.emit(self._hex_at(new_hover), new_hover[0], new_hover[1]) if new_hover else self.hoverChanged.emit("", -1, -1)
        if self.pixel_qimg and self._panning and self._press_pos:
            new_pos = e.position(); delta = new_pos - self._press_pos; self._press_pos = new_pos; self._translate(delta)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        is_left_click = e.button() == Qt.LeftButton and not self._panning; self._pan_timer.stop()
        if self._panning: self.setCursor(Qt.ArrowCursor)
        self._panning, self._press_pos = False, None
        if is_left_click:
            pos = self._map_to_pixel(e.position())
            if pos: self.selected_pixel = pos; self.colorChanged.emit(self._hex_at(pos), pos[0], pos[1]); self.overlay_item.update() if self.overlay_item else None
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        if self.pixel_qimg: self._zoom_at(e.position(), 1.25 if e.angleDelta().y() > 0 else 0.8)

    def _start_pan_by_timer(self):
        if self._press_pos: self._start_pan(self._press_pos)
    def _start_pan(self, pos): self._panning, self._press_pos, = True, pos; self.setCursor(Qt.ClosedHandCursor)
    def _translate(self, view_delta: QPointF):
        t = self.transform(); sx, sy = t.m11(), t.m22()
        if sx==0 or sy==0: return
        self.translate(view_delta.x() / sx, view_delta.y() / sy)
    def _zoom_at(self, pos, factor): self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse); self.scale(factor, factor)
    def _map_to_pixel(self, view_pos) -> Optional[Tuple[int, int]]:
        if not self.pixel_qimg: return None
        scene_pos = self.mapToScene(view_pos.toPoint())
        x, y = int(scene_pos.x()), int(scene_pos.y())
        if 0 <= x < self.pixel_qimg.width() and 0 <= y < self.pixel_qimg.height(): return (x, y)
        return None

    def toggle_mark_at(self, pos_xy: Tuple[int, int]):
        if pos_xy in self.painted: self.painted.discard(pos_xy)
        else: self.painted.add(pos_xy)
        if self.overlay_item: self.overlay_item.update()
        
    def _hex_at(self, pos_xy: Tuple[int, int]) -> str:
        return hex_from_qcolor(QColor(self.pixel_qimg.pixel(pos_xy[0], pos_xy[1])))

# -------------------- 主窗口 --------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("wplace 像素创作小助手"); self.resize(1100, 700)
        self.view = PixelView(); self.setCentralWidget(self.view)
        self._build_toolbar(); self._build_statusbar()
        self.src_img: Optional[Image.Image] = None; self.src_img_aspect_ratio = 1.0
        self.palette: List[Tuple[int, int, int]] = WPLACE_PALETTE.copy()
        self.current_project_path = None
        self.view.colorChanged.connect(self._on_color_changed)
        self.view.hoverChanged.connect(self._on_hover_changed)

    def _build_toolbar(self):
        tb = QToolBar("工具"); tb.setMovable(False); self.addToolBar(tb)
        file_menu = self.menuBar().addMenu("文件")
        action_open_image = QAction("打开新图片...", self); action_open_image.triggered.connect(self.open_image); file_menu.addAction(action_open_image)
        file_menu.addSeparator()
        action_load_project = QAction("加载项目...", self); action_load_project.triggered.connect(self.load_project); file_menu.addAction(action_load_project)
        self.action_save_project = QAction("保存项目", self); self.action_save_project.triggered.connect(self.save_project); self.action_save_project.setEnabled(False); file_menu.addAction(self.action_save_project)
        self.action_save_project_as = QAction("项目另存为...", self); self.action_save_project_as.triggered.connect(self.save_project_as); self.action_save_project_as.setEnabled(False); file_menu.addAction(self.action_save_project_as)
        file_menu.addSeparator()
        self.action_export_image = QAction("导出图片...", self); self.action_export_image.triggered.connect(self.export_image); self.action_export_image.setEnabled(False); file_menu.addAction(self.action_export_image)

        tb.addAction(action_open_image); tb.addAction(self.action_export_image); tb.addSeparator()
        tb.addWidget(QLabel("输出宽 W:")); self.spn_w = QSpinBox(); self.spn_w.setRange(1, 4096); self.spn_w.setValue(64); self.spn_w.valueChanged.connect(self._on_width_changed); tb.addWidget(self.spn_w)
        tb.addWidget(QLabel("高 H:")); self.spn_h = QSpinBox(); self.spn_h.setRange(1, 4096); self.spn_h.setValue(64); self.spn_h.setReadOnly(True); tb.addWidget(self.spn_h)
        self.chk_aspect = QCheckBox("锁定宽高比"); self.chk_aspect.setChecked(True); self.chk_aspect.stateChanged.connect(self._on_aspect_lock_changed); tb.addWidget(self.chk_aspect)
        btn_apply = QAction("应用像素化", self); btn_apply.triggered.connect(self.apply_pixelate); tb.addAction(btn_apply); tb.addSeparator()
        tb.addWidget(QLabel("算法:")); self.cmb_alg = QComboBox(); self.cmb_alg.addItems(["邻近采样", "Floyd-Steinberg 抖动"]); tb.addWidget(self.cmb_alg)
        tb.addWidget(QLabel("调色板:")); self.cmb_palette = QComboBox(); self.cmb_palette.addItems(["wplace", "预设16", "预设32", "预设64", "自定义…"]); self.cmb_palette.currentIndexChanged.connect(self.on_palette_changed); tb.addWidget(self.cmb_palette)
        self.chk_grid = QCheckBox("网格"); self.chk_grid.stateChanged.connect(lambda s: self.view.toggle_grid(s == Qt.Checked)); tb.addWidget(self.chk_grid)
        btn_fit = QAction("适配窗口", self); btn_fit.triggered.connect(self.view.fit_to_view); tb.addAction(btn_fit)
        tb.addSeparator()
        tb.addWidget(QLabel("  界面不透明度:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setFixedWidth(120) # 给滑块一个固定宽度
        self.opacity_slider.setRange(30, 100)  # 不透明度范围从 30% 到 100%
        self.opacity_slider.setValue(100)      # 默认是 100% 不透明
        
        # 连接滑块的 valueChanged 信号到我们的新方法
        self.opacity_slider.valueChanged.connect(self.set_window_opacity)
        
        # 将滑块添加到工具栏
        tb.addWidget(self.opacity_slider)       
    def set_window_opacity(self, value):
        """
        根据滑块的值（这是一个整数，例如 30 到 100）来设置窗口的不透明度。
        """
        # 将整数值转换为 0.0 到 1.0 之间的小数
        opacity_level = value / 100.0
        
        # 调用 QMainWindow 自带的 setWindowOpacity 方法
        self.setWindowOpacity(opacity_level)
    def _build_statusbar(self):
        sb = QStatusBar(); self.setStatusBar(sb)
        self.lbl_info = QLabel("未载入图片"); sb.addWidget(self.lbl_info)
        self.lbl_hover_info = QLabel(""); sb.addPermanentWidget(self.lbl_hover_info)

    def _update_ui_state(self, has_pixel_data: bool):
        self.action_save_project.setEnabled(has_pixel_data)
        self.action_save_project_as.setEnabled(has_pixel_data)
        self.action_export_image.setEnabled(has_pixel_data)

    def _on_color_changed(self, hex_str: str, x: int, y: int): self.lbl_info.setText(f"已选中: ({x}, {y}) | 颜色: {hex_str.upper()}")
    def _on_hover_changed(self, hex_str: str, x: int, y: int): self.lbl_hover_info.setText(f"悬停: ({x}, {y}) {hex_str.upper()}" if x >= 0 else "")
    def _on_width_changed(self, new_width: int):
        if self.chk_aspect.isChecked() and self.src_img:
            new_height = int(new_width / self.src_img_aspect_ratio)
            self.spn_h.blockSignals(True); self.spn_h.setValue(max(1, new_height)); self.spn_h.blockSignals(False)
    def _on_aspect_lock_changed(self, state):
        is_locked = (state == Qt.Checked)
        self.spn_h.setReadOnly(is_locked)
        if is_locked: self._on_width_changed(self.spn_w.value())

    def open_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path: return
        try: self.src_img = Image.open(path)
        except Exception as e: QMessageBox.critical(self, "错误", f"无法打开图片：{e}"); return
        self.src_img.filename = path # 保存文件路径
        w, h = self.src_img.size
        if h > 0: self.src_img_aspect_ratio = w / h
        self._on_width_changed(self.spn_w.value())
        self.view.set_image(qimage_from_pil(self.src_img))
        self.lbl_info.setText("已载入图片，请设置参数并点击“应用像素化”")
        self.current_project_path = None; self._update_ui_state(False)

    def on_palette_changed(self, idx: int):
        palettes = {0: WPLACE_PALETTE.copy(), 1: PRESET_16.copy(), 2: build_even_hsv_palette(32), 3: build_even_hsv_palette(64)}
        if idx in palettes: self.palette = palettes[idx]
        elif idx == 4:
            if not self._ask_custom_palette():
                self.cmb_palette.blockSignals(True)
                n = len(self.palette)
                back = {len(WPLACE_PALETTE): 0, 16: 1, 32: 2, 64: 3}.get(n, 0)
                self.cmb_palette.setCurrentIndex(back)
                self.cmb_palette.blockSignals(False)

    def _ask_custom_palette(self) -> bool:
        text, ok = QInputDialog.getText(self, "自定义调色板", "请输入十六进制颜色 (#RRGGBB)，用逗号/空格分隔：")
        if not ok or not text.strip(): return False
        cols = []
        for token in text.replace(',', ' ').split():
            s = token.strip().lstrip('#')
            if len(s) == 6:
                try: cols.append(tuple(int(s[i:i+2], 16) for i in (0, 2, 4)))
                except Exception: pass
        if not cols: QMessageBox.warning(self, "提示", "未解析到有效颜色。"); return False
        self.palette = cols
        return True

    def apply_pixelate(self):
        if not self.src_img: QMessageBox.information(self, "提示", "请先打开一张图片"); return
        W, H, alg, pal = self.spn_w.value(), self.spn_h.value(), self.cmb_alg.currentText(), self.palette
        try: pix = self._pixelate(self.src_img, W, H, alg, pal)
        except Exception as e: QMessageBox.critical(self, "错误", f"像素化失败：{e}"); return
        self.view.set_image(qimage_from_pil(pix))
        self.lbl_info.setText("像素化完成：左键选择，右键标记；滚轮缩放，长按/中键拖动。")
        self._update_ui_state(True)

    def _pixelate(self, img: Image.Image, W: int, H: int, alg_name: str, palette: List[Tuple[int,int,int]]) -> Image.Image:
        pal_img = self._build_palette_image(palette)
        rgb_img = img.convert("RGB")
        dither = Image.Dither.FLOYDSTEINBERG if alg_name == "Floyd-Steinberg 抖动" else Image.Dither.NONE
        quantized_img = rgb_img.quantize(palette=pal_img, dither=dither)
        pixelated_img = quantized_img.resize((W, H), Image.Resampling.NEAREST)
        return pixelated_img.convert("RGBA")

    def _build_palette_image(self, palette: List[Tuple[int,int,int]]) -> Image.Image:
        flat = [c for rgb in palette[:256] for c in rgb]
        if len(flat) < 256 * 3: flat.extend([0] * (256 * 3 - len(flat)))
        pal_img = Image.new('P', (1, 1)); pal_img.putpalette(flat)
        return pal_img

    def save_project(self):
        if self.current_project_path: self._perform_save(self.current_project_path)
        else: self.save_project_as()

    def save_project_as(self):
        if not self.view.pixel_qimg: return
        path, _ = QFileDialog.getSaveFileName(self, "项目另存为", "", "wplace Project (*.wpp)")
        if path: self.current_project_path = path; self._perform_save(path)
            
    def _perform_save(self, path: str):
        if not self.view.pixel_qimg or not self.src_img: QMessageBox.warning(self, "提示", "没有可保存的数据。"); return
        project_data = {
            "version": "1.0",
            "source_image_path": self.src_img.filename,
            "pixelization_settings": {"width": self.spn_w.value(), "height": self.spn_h.value(), "algorithm": self.cmb_alg.currentText(), "palette_name": self.cmb_palette.currentText(), "custom_palette": self.palette if self.cmb_palette.currentText() == "自定义…" else None},
            "marked_pixels": list(self.view.painted)
        }
        try:
            with open(path, 'w', encoding='utf-8') as f: json.dump(project_data, f, indent=2)
            self.lbl_info.setText(f"项目已保存到: {Path(path).name}")
        except Exception as e: QMessageBox.critical(self, "错误", f"保存项目失败: {e}")

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载项目", "", "wplace Project (*.wpp)")
        if not path: return
        try:
            with open(path, 'r', encoding='utf-8') as f: project_data = json.load(f)
            src_path = project_data["source_image_path"]
            if not src_path or not Path(src_path).exists():
                QMessageBox.warning(self, "提示", f"找不到原始图片:\n{src_path}\n请手动选择。"); self.open_image(); return
            self.src_img = Image.open(src_path); self.src_img.filename = src_path
            w, h = self.src_img.size
            if h > 0: self.src_img_aspect_ratio = w / h
            
            settings = project_data["pixelization_settings"]
            self.spn_w.setValue(settings["width"]); self.spn_h.setValue(settings["height"])
            self.cmb_alg.setCurrentText(settings["algorithm"])
            
            palette_name = settings["palette_name"]
            if palette_name == "自定义…":
                self.palette = [tuple(c) for c in settings["custom_palette"]]
                custom_index = self.cmb_palette.findText("自定义…")
                if custom_index != -1: self.cmb_palette.setCurrentIndex(custom_index)
            else:
                preset_index = self.cmb_palette.findText(palette_name)
                if preset_index != -1: self.cmb_palette.setCurrentIndex(preset_index)
            
            self.apply_pixelate()
            
            self.view.painted = set(tuple(p) for p in project_data["marked_pixels"])
            self.view.overlay_item.update()

            self.current_project_path = path; self.lbl_info.setText(f"项目 '{Path(path).stem}' 已加载。")
        except Exception as e: QMessageBox.critical(self, "错误", f"加载项目失败: {e}")

    def export_image(self):
        if self.view.pixel_qimg is None: QMessageBox.information(self, "提示", "没有可导出的结果"); return
        path, _ = QFileDialog.getSaveFileName(self, "导出为图片", "pixelized.png", "PNG (*.png)")
        if not path: return
        include_marks = QMessageBox.question(self, "导出选项", "是否在导出图像中包含标记覆盖？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        qimg = self.view.pixel_qimg
        if include_marks == QMessageBox.StandardButton.Yes:
            img_to_save = QImage(qimg); p = QPainter(img_to_save)
            if self.view.overlay_item: self.view.overlay_item.paint(p, None, None)
            p.end(); img_to_save.save(path)
        else: qimg.save(path)
        QMessageBox.information(self, "完成", f"已导出到：{path}")

# -------------------- 入口 --------------------

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()