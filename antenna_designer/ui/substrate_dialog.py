"""
Modal dialog for managing the user substrate library.

Built-in substrates are shown read-only (you can read εr/tan δ but not
edit). User substrates are fully editable. Changes persist to
~/.antenna_designer/substrates.json on Save.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QFormLayout, QMessageBox,
    QDialogButtonBox, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from calculators.physics import (
    BUILTIN_SUBSTRATES, is_builtin_substrate, load_user_substrates,
    save_user_substrates, reload_user_substrates,
)


def _format_thicknesses(thick_mm: list) -> str:
    return ", ".join(f"{t:g}" for t in thick_mm)


def _parse_thicknesses(text: str) -> list[float]:
    """Parse a comma/space separated list of mm values. Raises ValueError."""
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("Provide at least one thickness in mm.")
    out = []
    for p in parts:
        v = float(p)
        if v <= 0:
            raise ValueError(f"Thickness must be positive: {p}")
        out.append(v)
    return out


class SubstrateEditorDialog(QDialog):
    """List + form editor for the user substrate library.

    Closes with `accepted` if the user persisted at least one change,
    so the caller can refresh the substrate combo. `rejected` means no
    changes were saved.
    """

    def __init__(self, parent=None, current_name: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manage substrates")
        self.resize(640, 460)

        # In-memory copy of the user library — only written to disk on Save.
        self._user = load_user_substrates()
        self._dirty = False
        self._current_key: str | None = None

        root = QHBoxLayout(self)

        # ---- Left: list of substrates --------------------------------------
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Substrates</b>"))
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._on_select)
        left.addWidget(self.list, 1)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("+ New")
        self.btn_add.clicked.connect(self._on_add)
        self.btn_dup = QPushButton("Duplicate")
        self.btn_dup.setToolTip(
            "Copy the selected substrate (built-in or user) into the user "
            "library so you can edit the values.")
        self.btn_dup.clicked.connect(self._on_duplicate)
        self.btn_del = QPushButton("Delete")
        self.btn_del.clicked.connect(self._on_delete)
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_dup)
        btn_row.addWidget(self.btn_del)
        left.addLayout(btn_row)
        root.addLayout(left, 1)

        # ---- Right: editor form --------------------------------------------
        right = QVBoxLayout()
        right.addWidget(QLabel("<b>Editor</b>"))

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: #ffa040; font-style: italic;")
        right.addWidget(self.lbl_status)

        form = QFormLayout()
        self.in_name  = QLineEdit()
        self.in_er    = QLineEdit()
        self.in_tand  = QLineEdit()
        self.in_thick = QLineEdit()
        self.in_thick.setPlaceholderText("0.254, 0.508, 0.787, 1.524")
        self.in_thick.setToolTip("Comma-separated standard panel "
                                  "thicknesses in mm. The first value is "
                                  "the default when this substrate is "
                                  "selected.")
        form.addRow("Name:",          self.in_name)
        form.addRow("εr:",            self.in_er)
        form.addRow("tan δ:",         self.in_tand)
        form.addRow("Thicknesses (mm):", self.in_thick)
        right.addLayout(form)

        self.btn_apply = QPushButton("Save changes")
        self.btn_apply.clicked.connect(self._on_apply)
        right.addWidget(self.btn_apply)
        right.addStretch(1)

        # Close / OK
        self.box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        self.box.rejected.connect(self.reject)
        right.addWidget(self.box)
        root.addLayout(right, 1)

        self._refresh_list(select_name=current_name)

    # ---- list management ---------------------------------------------------

    def _refresh_list(self, select_name: str | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        # Built-ins first (lock icon prefix)
        for name in sorted(BUILTIN_SUBSTRATES.keys()):
            it = QListWidgetItem(f"🔒  {name}")
            it.setData(Qt.ItemDataRole.UserRole, ("builtin", name))
            self.list.addItem(it)
        if self._user:
            sep = QListWidgetItem("— User substrates —")
            sep.setFlags(Qt.ItemFlag.NoItemFlags)
            f = QFont(); f.setItalic(True); sep.setFont(f)
            self.list.addItem(sep)
            for name in sorted(self._user.keys()):
                it = QListWidgetItem(name)
                it.setData(Qt.ItemDataRole.UserRole, ("user", name))
                self.list.addItem(it)
        self.list.blockSignals(False)

        if select_name:
            for i in range(self.list.count()):
                tag = self.list.item(i).data(Qt.ItemDataRole.UserRole)
                if tag and tag[1] == select_name:
                    self.list.setCurrentRow(i)
                    return
        if self.list.count():
            # Skip separator items
            for i in range(self.list.count()):
                if self.list.item(i).flags() & Qt.ItemFlag.ItemIsSelectable:
                    self.list.setCurrentRow(i)
                    return

    def _selected_tag(self) -> tuple[str, str] | None:
        it = self.list.currentItem()
        if not it:
            return None
        return it.data(Qt.ItemDataRole.UserRole)

    def _on_select(self):
        tag = self._selected_tag()
        if not tag:
            self._set_form_enabled(False)
            self.lbl_status.setText("")
            return
        kind, name = tag
        src = BUILTIN_SUBSTRATES if kind == "builtin" else self._user
        if name not in src:
            return
        s = src[name]
        self._current_key = name
        self.in_name.setText(name)
        self.in_er.setText(f"{s['er']:g}")
        self.in_tand.setText(f"{s['tan_d']:g}")
        self.in_thick.setText(_format_thicknesses(s["thick_mm"]))
        editable = (kind == "user")
        self._set_form_enabled(editable)
        self.lbl_status.setText(
            "" if editable
            else "Built-in (read-only). Use Duplicate to create an editable copy.")

    def _set_form_enabled(self, on: bool):
        for w in (self.in_name, self.in_er, self.in_tand, self.in_thick,
                  self.btn_apply):
            w.setEnabled(on)
        # Delete is also only enabled for user entries
        tag = self._selected_tag()
        self.btn_del.setEnabled(bool(tag) and tag[0] == "user")
        self.btn_dup.setEnabled(bool(tag))

    # ---- mutations ---------------------------------------------------------

    def _on_add(self):
        # Generate a unique placeholder name
        base = "New substrate"
        name = base
        i = 1
        while name in BUILTIN_SUBSTRATES or name in self._user:
            i += 1
            name = f"{base} {i}"
        self._user[name] = {"er": 3.0, "tan_d": 0.001,
                            "thick_mm": [0.508, 1.524]}
        self._dirty = True
        self._refresh_list(select_name=name)

    def _on_duplicate(self):
        tag = self._selected_tag()
        if not tag:
            return
        kind, name = tag
        src = BUILTIN_SUBSTRATES if kind == "builtin" else self._user
        if name not in src:
            return
        s = src[name]
        new_name = f"{name} (copy)"
        i = 2
        while new_name in BUILTIN_SUBSTRATES or new_name in self._user:
            i += 1
            new_name = f"{name} (copy {i})"
        self._user[new_name] = {"er":     float(s["er"]),
                                "tan_d":  float(s["tan_d"]),
                                "thick_mm": list(s["thick_mm"])}
        self._dirty = True
        self._refresh_list(select_name=new_name)

    def _on_delete(self):
        tag = self._selected_tag()
        if not tag or tag[0] != "user":
            return
        name = tag[1]
        if QMessageBox.question(
                self, "Delete substrate",
                f"Delete '{name}' from the user library? This cannot be "
                "undone (built-in defaults will remain unchanged).",
                ) != QMessageBox.StandardButton.Yes:
            return
        self._user.pop(name, None)
        self._dirty = True
        self._refresh_list()

    def _on_apply(self):
        tag = self._selected_tag()
        if not tag or tag[0] != "user":
            return
        old_name = tag[1]
        new_name = self.in_name.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Invalid name",
                                "Substrate name cannot be empty.")
            return
        if new_name in BUILTIN_SUBSTRATES:
            QMessageBox.warning(self, "Name clash",
                                f"'{new_name}' is reserved by a built-in.")
            return
        if new_name != old_name and new_name in self._user:
            QMessageBox.warning(self, "Name clash",
                                f"'{new_name}' already exists.")
            return
        try:
            er    = float(self.in_er.text())
            tan_d = float(self.in_tand.text())
            thick = _parse_thicknesses(self.in_thick.text())
        except ValueError as e:
            QMessageBox.warning(self, "Invalid value", str(e))
            return
        if er <= 0:
            QMessageBox.warning(self, "Invalid εr",
                                "εr must be positive.")
            return
        if tan_d < 0:
            QMessageBox.warning(self, "Invalid tan δ",
                                "tan δ cannot be negative.")
            return

        # Rename if needed, then write the new payload
        if new_name != old_name:
            self._user.pop(old_name, None)
        self._user[new_name] = {"er": er, "tan_d": tan_d,
                                "thick_mm": thick}
        self._dirty = True
        try:
            save_user_substrates(self._user)
            reload_user_substrates()
            self.lbl_status.setText("Saved.")
            self._refresh_list(select_name=new_name)
        except OSError as e:
            QMessageBox.critical(self, "Save failed",
                                 f"Could not write substrates.json: {e}")

    # ---- close handling ----------------------------------------------------

    def closeEvent(self, evt):
        # Persist anything still dirty on close (e.g. user added/deleted
        # but did not click Save on the form).
        if self._dirty:
            try:
                save_user_substrates(self._user)
                reload_user_substrates()
            except OSError:
                pass
        super().closeEvent(evt)
