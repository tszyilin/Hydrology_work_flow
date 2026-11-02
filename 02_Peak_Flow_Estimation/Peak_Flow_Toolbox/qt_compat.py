"""Qt import shim: use QGIS's bundled PyQt5 when running inside QGIS, and
plain PyQt5 when running standalone. Mirrors the pattern from the sibling
Drain Design Toolbox so dialog/plot code is identical in both environments.
"""

try:
    from qgis.PyQt.QtCore import Qt, QObject, QThread, QTimer, QUrl, pyqtSignal
    from qgis.PyQt import uic
    from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QIcon
    from qgis.PyQt.QtWidgets import (
        QAbstractItemView,
        QAction,
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDockWidget,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError:
    from PyQt5.QtCore import Qt, QObject, QThread, QTimer, QUrl, pyqtSignal
    from PyQt5 import uic
    from PyQt5.QtGui import QColor, QDesktopServices, QFont, QIcon
    from PyQt5.QtWidgets import (
        QAbstractItemView,
        QAction,
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDockWidget,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
