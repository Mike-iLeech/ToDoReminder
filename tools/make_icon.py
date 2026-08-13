import struct
import sys

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

OUT = r"H:\Разработка Приложений\ToDoReminder_Version4\resources\icon.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]

app = QApplication(sys.argv)

pngs = []
for s in SIZES:
    pix = QPixmap(s, s)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#3B82F6"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, s, s, s * 0.06, s * 0.06)
    p.setPen(QColor("#FFFFFF"))
    p.drawLine(QPoint(int(s * 0.22), int(s * 0.52)), QPoint(int(s * 0.42), int(s * 0.72)))
    p.drawLine(QPoint(int(s * 0.42), int(s * 0.72)), QPoint(int(s * 0.78), int(s * 0.30)))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    pngs.append((s, bytes(buf.data())))

entries = []
offset = 6 + 16 * len(pngs)
with open(OUT, "wb") as f:
    f.write(struct.pack("<HHH", 0, 1, len(pngs)))
    for s, blob in pngs:
        dim = 0 if s >= 256 else s
        f.write(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset))
        offset += len(blob)
    for _, blob in pngs:
        f.write(blob)

print("ICON OK", OUT)