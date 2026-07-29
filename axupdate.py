#!/usr/bin/env python3
"""
axupdate.py — Linux GUI Update Manager for axpm / apt
Targets: Debian Testing + KDE Plasma (Wayland) via PyQt6
"""

import os
import re
import shutil
import subprocess
import sys
from typing import Optional

from PyQt6.QtCore import (
    QObject,
    QProcess,
    Qt,
    QThread,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Security level rules
# ---------------------------------------------------------------------------

SECURITY_LEVEL_RULES: list[tuple[list[str], int]] = [
    # Level 5 — critical / security channels
    (["-security", "security.debian.org", "security-updates"], 5),
    # Level 4 — commonly exploited or kernel packages
    (["linux-image", "linux-headers", "linux-libc", "libc6", "libssl", "openssl", "openssh"], 4),
    # Level 3 — core system libraries & daemons
    (["systemd", "dbus", "sudo", "polkit", "udev", "libpam", "libglib", "libgtk", "libqt"], 3),
    # Level 2 — desktop / user-space apps
    (["gnome", "kde", "plasma", "firefox", "chromium", "thunderbird"], 2),
    # Level 1 — everything else (standard updates)
    ([], 1),
]

LEVEL_COLORS = {
    5: QColor("#e74c3c"),   # red
    4: QColor("#e67e22"),   # orange
    3: QColor("#f1c40f"),   # yellow
    2: QColor("#3498db"),   # blue
    1: QColor("#2ecc71"),   # green
}

LEVEL_LABELS = {
    5: "⬛ Critical (5)",
    4: "🔴 High (4)",
    3: "🟡 Medium (3)",
    2: "🔵 Low (2)",
    1: "🟢 Minimal (1)",
}


def security_level(package_name: str, origin: str) -> int:
    """Return a 1–5 security level for a package based on name / origin."""
    combined = f"{package_name} {origin}".lower()
    for keywords, level in SECURITY_LEVEL_RULES[:-1]:  # skip catch-all last entry
        if any(kw.lower() in combined for kw in keywords):
            return level
    return 1


# ---------------------------------------------------------------------------
# Package info dataclass
# ---------------------------------------------------------------------------

class PackageInfo:
    def __init__(
        self,
        name: str,
        current_version: str,
        new_version: str,
        size: str,
        origin: str,
    ):
        self.name = name
        self.current_version = current_version
        self.new_version = new_version
        self.size = size
        self.origin = origin
        self.level = security_level(name, origin)


# ---------------------------------------------------------------------------
# Worker thread: fetch upgradable packages
# ---------------------------------------------------------------------------

class FetchWorker(QObject):
    finished = pyqtSignal(list, str)   # list[PackageInfo], error_message
    status = pyqtSignal(str)

    def run(self):
        self.status.emit("Running apt update…")
        try:
            subprocess.run(
                ["apt-get", "update", "-qq"],
                capture_output=True,
                check=False,
                timeout=120,
            )
        except Exception as exc:
            self.finished.emit([], f"apt update failed: {exc}")
            return

        self.status.emit("Fetching upgradable packages…")
        try:
            result = subprocess.run(
                ["apt", "list", "--upgradable"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except Exception as exc:
            self.finished.emit([], f"apt list failed: {exc}")
            return

        packages: list[PackageInfo] = []
        # Pattern: name/channel version [arch] [upgradable from: old_version]
        pattern = re.compile(
            r"^(?P<name>[^\s/]+)/(?P<origin>[^\s]+)\s+"
            r"(?P<new_ver>\S+)\s+\S+\s+\[upgradable from:\s*(?P<old_ver>[^\]]+)\]",
            re.MULTILINE,
        )
        for m in pattern.finditer(result.stdout):
            packages.append(
                PackageInfo(
                    name=m.group("name"),
                    current_version=m.group("old_ver"),
                    new_version=m.group("new_ver"),
                    size="",        # populated below when possible
                    origin=m.group("origin"),
                )
            )

        # Best-effort: fetch sizes via apt-cache
        if packages:
            try:
                cache = subprocess.run(
                    ["apt-cache", "show"] + [p.name for p in packages],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                size_map: dict[str, str] = {}
                current_pkg: Optional[str] = None
                for line in cache.stdout.splitlines():
                    if line.startswith("Package:"):
                        current_pkg = line.split(":", 1)[1].strip()
                    elif line.startswith("Installed-Size:") and current_pkg:
                        kb = line.split(":", 1)[1].strip()
                        try:
                            size_map[current_pkg] = f"{int(kb) // 1024} MB" if int(kb) >= 1024 else f"{kb} kB"
                        except ValueError:
                            size_map[current_pkg] = f"{kb} kB"
                for p in packages:
                    p.size = size_map.get(p.name, "—")
            except Exception:
                pass  # sizes are optional

        self.finished.emit(packages, "")


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

COL_CHECK   = 0
COL_NAME    = 1
COL_CURRENT = 2
COL_NEW     = 3
COL_SIZE    = 4
COL_LEVEL   = 5
COLUMNS     = ["", "Package", "Current Version", "New Version", "Size", "Security Level"]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("axupdate — OS Update Manager")
        self.setMinimumSize(900, 650)
        self.setWindowIcon(QIcon.fromTheme("system-software-update"))

        self._packages: list[PackageInfo] = []
        self._process: Optional[QProcess] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[FetchWorker] = None

        self._build_ui()
        self._start_fetch()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- header banner ----
        self._banner = QLabel("Checking for updates…")
        self._banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._banner.setFixedHeight(64)
        self._banner.setFont(QFont("Sans Serif", 14, QFont.Weight.Bold))
        self._banner.setStyleSheet(
            "background-color: #7f8c8d; color: white; padding: 8px;"
        )
        layout.addWidget(self._banner)

        # ---- toolbar row ----
        toolbar = QWidget()
        tbar_layout = QHBoxLayout(toolbar)
        tbar_layout.setContentsMargins(12, 6, 12, 6)

        self._status_label = QLabel("Initialising…")
        self._status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        tbar_layout.addWidget(self._status_label)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setIcon(QIcon.fromTheme("view-refresh"))
        self._refresh_btn.clicked.connect(self._start_fetch)
        tbar_layout.addWidget(self._refresh_btn)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.clicked.connect(self._select_all)
        tbar_layout.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("Deselect All")
        self._deselect_all_btn.clicked.connect(self._deselect_all)
        tbar_layout.addWidget(self._deselect_all_btn)

        layout.addWidget(toolbar)

        # ---- splitter: table + terminal ----
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setContentsMargins(12, 0, 12, 0)
        layout.addWidget(splitter, stretch=1)

        # Package table
        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            COL_NAME, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_CURRENT, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_NEW, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_SIZE, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            COL_LEVEL, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setColumnWidth(COL_CHECK, 32)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._table.setAlternatingRowColors(True)
        splitter.addWidget(self._table)

        # Embedded terminal
        terminal_container = QWidget()
        tc_layout = QVBoxLayout(terminal_container)
        tc_layout.setContentsMargins(0, 4, 0, 0)

        term_header = QLabel("Installation Output")
        term_header.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
        term_header.setStyleSheet("color: #888; padding-left: 4px;")
        tc_layout.addWidget(term_header)

        self._terminal = QTextEdit()
        self._terminal.setReadOnly(True)
        self._terminal.setFont(QFont("Monospace", 10))
        self._terminal.setStyleSheet(
            "background-color: #1a1a2e; color: #e0e0e0; border: none;"
        )
        tc_layout.addWidget(self._terminal)

        splitter.addWidget(terminal_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        # ---- Update Now button ----
        btn_bar = QWidget()
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(12, 8, 12, 12)

        self._update_btn = QPushButton("  Update Now  ")
        self._update_btn.setIcon(QIcon.fromTheme("system-software-update"))
        self._update_btn.setFixedHeight(48)
        self._update_btn.setFont(QFont("Sans Serif", 13, QFont.Weight.Bold))
        self._update_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #27ae60; color: white;"
            "  border-radius: 8px; padding: 0 32px;"
            "}"
            "QPushButton:hover { background-color: #2ecc71; }"
            "QPushButton:pressed { background-color: #1e8449; }"
            "QPushButton:disabled { background-color: #aaa; }"
        )
        self._update_btn.setEnabled(False)
        self._update_btn.clicked.connect(self._start_upgrade)
        btn_layout.addStretch()
        btn_layout.addWidget(self._update_btn)
        btn_layout.addStretch()

        layout.addWidget(btn_bar)

    # ------------------------------------------------------------------
    # Background fetch
    # ------------------------------------------------------------------

    def _start_fetch(self):
        if self._thread and self._thread.isRunning():
            return

        self._packages = []
        self._table.setRowCount(0)
        self._update_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._banner.setText("Checking for updates…")
        self._banner.setStyleSheet(
            "background-color: #7f8c8d; color: white; padding: 8px;"
        )

        self._thread = QThread()
        self._worker = FetchWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.status.connect(self._on_status)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_status(self, msg: str):
        self._status_label.setText(msg)

    def _on_fetch_done(self, packages: list[PackageInfo], error: str):
        self._refresh_btn.setEnabled(True)

        if error:
            self._status_label.setText(f"Error: {error}")
            self._banner.setText("⚠ Could not check for updates")
            self._banner.setStyleSheet(
                "background-color: #c0392b; color: white; padding: 8px;"
            )
            return

        self._packages = packages
        self._populate_table(packages)

        count = len(packages)
        if count == 0:
            self._banner.setText("✔  Your system is up to date")
            self._banner.setStyleSheet(
                "background-color: #27ae60; color: white; padding: 8px;"
            )
            self._status_label.setText("No updates available.")
        else:
            self._banner.setText(f"  {count} update{'s' if count != 1 else ''} available")
            # Use orange if any security level ≥ 4, blue otherwise
            max_level = max((p.level for p in packages), default=1)
            color = "#e67e22" if max_level >= 4 else "#2980b9"
            self._banner.setStyleSheet(
                f"background-color: {color}; color: white; padding: 8px;"
            )
            self._status_label.setText(
                f"{count} package{'s' if count != 1 else ''} can be upgraded."
            )
            self._update_btn.setEnabled(True)
            self._send_notification(count)

    def _populate_table(self, packages: list[PackageInfo]):
        self._table.setRowCount(len(packages))
        for row, pkg in enumerate(packages):
            # Checkbox
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Checked)
            chk.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
            )
            self._table.setItem(row, COL_CHECK, chk)

            # Text columns
            for col, text in [
                (COL_NAME, pkg.name),
                (COL_CURRENT, pkg.current_version),
                (COL_NEW, pkg.new_version),
                (COL_SIZE, pkg.size),
            ]:
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self._table.setItem(row, col, item)

            # Security level column
            level_item = QTableWidgetItem(LEVEL_LABELS[pkg.level])
            level_item.setForeground(LEVEL_COLORS[pkg.level])
            level_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self._table.setItem(row, COL_LEVEL, level_item)

    # ------------------------------------------------------------------
    # Select / deselect helpers
    # ------------------------------------------------------------------

    def _select_all(self):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    # ------------------------------------------------------------------
    # Upgrade via QProcess
    # ------------------------------------------------------------------

    def _start_upgrade(self):
        selected = [
            self._packages[row].name
            for row in range(self._table.rowCount())
            if self._table.item(row, COL_CHECK)
            and self._table.item(row, COL_CHECK).checkState() == Qt.CheckState.Checked
        ]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Please select at least one package.")
            return

        self._terminal.clear()
        self._terminal.append("=== axupdate: starting upgrade ===\n")
        self._update_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)

        # Decide command: prefer axpm, fall back to apt-get
        if shutil.which("axpm"):
            cmd = "axpm"
            args = ["full-upgrade", "-y"]
        else:
            cmd = "apt-get"
            args = ["dist-upgrade", "-y"]

        self._terminal.append(f"$ {cmd} {' '.join(args)}\n\n")

        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyRead.connect(self._on_process_output)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        env = self._process.processEnvironment()
        env.insert("DEBIAN_FRONTEND", "noninteractive")
        self._process.setProcessEnvironment(env)

        self._process.start(cmd, args)

    def _on_process_output(self):
        if self._process:
            data = bytes(self._process.readAll()).decode("utf-8", errors="replace")
            self._terminal.insertPlainText(data)
            self._terminal.ensureCursorVisible()

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus):
        self._update_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        if exit_code == 0:
            self._terminal.append("\n=== Upgrade completed successfully ===")
            self._start_fetch()   # refresh package list
        else:
            self._terminal.append(f"\n=== Process exited with code {exit_code} ===")

    def _on_process_error(self, error: QProcess.ProcessError):
        self._terminal.append(f"\n[QProcess error: {error}]")
        self._update_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)

    # ------------------------------------------------------------------
    # System notification
    # ------------------------------------------------------------------

    def _send_notification(self, count: int):
        title = "axupdate"
        body = f"{count} update{'s' if count != 1 else ''} available for axupdate"

        # Try plyer first (optional dep), fall back to notify-send
        try:
            from plyer import notification  # type: ignore
            notification.notify(
                title=title,
                message=body,
                app_name="axupdate",
                app_icon="",
                timeout=8,
            )
            return
        except Exception:
            pass

        if shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    [
                        "notify-send",
                        "--icon=system-software-update",
                        "--urgency=normal",
                        title,
                        body,
                    ]
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Wayland: set native platform so PyQt6 uses the correct backend
    if "WAYLAND_DISPLAY" in os.environ and "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "wayland"

    app = QApplication(sys.argv)
    app.setApplicationName("axupdate")
    app.setApplicationDisplayName("axupdate")
    app.setWindowIcon(QIcon.fromTheme("system-software-update"))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
