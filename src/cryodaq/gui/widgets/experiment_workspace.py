from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.user_preferences import UserPreferences, suggest_experiment_name
from cryodaq.drivers.base import Reading
from cryodaq.paths import get_data_dir
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    add_form_rows,
    apply_button_style,
    apply_group_box_style,
    apply_panel_frame_style,
    apply_status_label_style,
    build_action_row,
)
from cryodaq.gui.zmq_client import ZmqCommandWorker, send_command


class ExperimentWorkspace(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._templates: list[dict[str, Any]] = []
        self._templates_by_id: dict[str, dict[str, Any]] = {}
        self._active_experiment: dict[str, Any] | None = None
        self._app_mode = "experiment"
        self._timeline_entries: list[str] = []
        self._workers: list[ZmqCommandWorker] = []
        self._post_action: Callable[[], None] | None = None
        self._shell_message: Callable[[str, int], None] | None = None
        self._finalize_guard: Callable[[], tuple[bool, str]] | None = None
        self._preferences = UserPreferences(get_data_dir() / "user_preferences.json")
        self._build_ui()
        self._apply_preferences()

    @property
    def app_mode(self) -> str:
        return self._app_mode

    @property
    def active_experiment(self) -> dict[str, Any] | None:
        return self._active_experiment

    def set_post_action_callback(self, callback: Callable[[], None]) -> None:
        self._post_action = callback

    def set_shell_message_callback(self, callback: Callable[[str, int], None]) -> None:
        self._shell_message = callback

    def set_finalize_guard(self, callback: Callable[[], tuple[bool, str]]) -> None:
        self._finalize_guard = callback

    def focus_create_form(self) -> None:
        self._create_title_edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def focus_finalize_action(self) -> None:
        self._finalize_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def refresh_state(self) -> bool:
        result = send_command({"cmd": "experiment_status"})
        if not result.get("ok"):
            self._workspace_status.show_error(
                str(result.get("error", "Не удалось загрузить состояние эксперимента."))
            )
            self._show_shell_message(self._workspace_status.text())
            return False

        self._templates = list(result.get("templates", []))
        self._templates_by_id = {
            str(template.get("id", "")): template for template in self._templates if template.get("id")
        }
        self._active_experiment = result.get("active_experiment")
        self._app_mode = str(result.get("app_mode", "experiment"))
        self._sync_create_template_choices()
        self._sync_ui_from_state()
        self._reload_timeline()
        return True

    def on_reading(self, reading: Reading) -> None:
        if reading.channel == "analytics/operator_log_entry" and self._active_experiment:
            metadata = dict(reading.metadata or {})
            experiment_id = str(metadata.get("experiment_id", "")).strip()
            active_id = str(self._active_experiment.get("experiment_id", "")).strip()
            if experiment_id and experiment_id == active_id:
                self._reload_timeline()
        elif reading.channel.startswith("analytics/keithley_channel_state/") and self._active_experiment:
            channel_name = reading.channel.rsplit("/", 1)[-1]
            state_name = str(reading.metadata.get("state", "off")).strip() or "off"
            self._prepend_runtime_timeline_entry(
                f"{self._format_now()} • {channel_name}: состояние канала {state_name}"
            )

    @Slot()
    def _on_mode_experiment(self) -> None:
        self._switch_mode("experiment")

    @Slot()
    def _on_mode_debug(self) -> None:
        self._switch_mode("debug")

    @Slot()
    def _on_create_experiment(self) -> None:
        template = self._create_template_combo.currentData() or {}
        title = self._create_title_edit.text().strip()
        operator = self._create_operator_edit.currentText().strip()
        if not title:
            self._workspace_status.show_warning("Укажите название нового эксперимента.")
            return
        if not operator:
            self._workspace_status.show_warning("Укажите оператора эксперимента.")
            return

        # Pre-flight checklist (только в режиме эксперимента)
        from cryodaq.gui.widgets.preflight_dialog import PreFlightDialog
        from PySide6.QtWidgets import QDialog
        preflight = PreFlightDialog(self)
        if preflight.exec() != QDialog.DialogCode.Accepted:
            return

        payload = {
            "cmd": "experiment_create",
            "template_id": str(template.get("id", "custom")),
            "title": title,
            "name": title,
            "operator": operator,
            "sample": self._create_sample_edit.text().strip(),
            "cryostat": self._create_cryostat_edit.currentText().strip(),
            "description": self._create_description_edit.toPlainText().strip(),
            "notes": self._create_notes_edit.toPlainText().strip(),
            "custom_fields": {
                field_id: edit.text().strip()
                for field_id, edit in self._create_custom_edits.items()
                if edit.text().strip()
            },
        }
        self._create_button.setEnabled(False)
        worker = ZmqCommandWorker(payload)
        worker.finished.connect(lambda result, op=operator, pl=payload: self._on_create_result(result, op, pl))
        self._workers.append(worker)
        worker.start()

    def _on_create_result(self, result: dict, operator: str, payload: dict) -> None:
        self._create_button.setEnabled(True)
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok"):
            self._workspace_status.show_error(
                str(result.get("error", "Не удалось создать эксперимент."))
            )
            self._show_shell_message(self._workspace_status.text())
            return

        # Сохранить оператора в QSettings-историю
        if operator:
            from PySide6.QtCore import QSettings
            _s = QSettings("FIAN", "CryoDAQ")
            _known = _s.value("known_operators", [])
            if not isinstance(_known, list):
                _known = []
            if operator not in _known:
                _known.insert(0, operator)
                _known = _known[:20]
                _s.setValue("known_operators", _known)

        # Сохранить данные формы в историю
        self._preferences.save_last_experiment(
            template_id=str(payload.get("template_id", "")),
            operator=operator,
            sample=str(payload.get("sample", "")),
            cryostat=str(payload.get("cryostat", "")),
            description=str(payload.get("description", "")),
            custom_fields=payload.get("custom_fields", {}),
        )

        if self.refresh_state():
            self._workspace_status.show_success("Эксперимент создан, карточка открыта.")
        else:
            self._workspace_status.show_warning(
                "Команда на создание эксперимента выполнена, но состояние интерфейса не удалось обновить."
            )
        self._notify_post_action()

    @Slot()
    def _on_save_card(self) -> None:
        if not self._active_experiment:
            return
        payload = {
            "cmd": "experiment_update",
            "experiment_id": str(self._active_experiment.get("experiment_id", "")),
            "title": self._card_title_edit.text().strip(),
            "sample": self._card_sample_edit.text().strip(),
            "description": self._card_description_edit.toPlainText().strip(),
            "notes": self._card_notes_edit.toPlainText().strip(),
            "custom_fields": {
                field_id: edit.text().strip()
                for field_id, edit in self._card_custom_edits.items()
                if edit.text().strip()
            },
        }
        self._save_button.setEnabled(False)
        worker = ZmqCommandWorker(payload)
        worker.finished.connect(self._on_save_card_result)
        self._workers.append(worker)
        worker.start()

    def _on_save_card_result(self, result: dict) -> None:
        self._save_button.setEnabled(True)
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok"):
            self._save_status.show_error(str(result.get("error", "Не удалось сохранить карточку.")))
            self._show_shell_message(self._save_status.text())
            return
        updated = result.get("experiment")
        if isinstance(updated, dict):
            self._active_experiment = dict(updated)
            template = self._templates_by_id.get(str(self._active_experiment.get("template_id", "custom")), {})
            self._populate_active_card(self._active_experiment)
            self._rebuild_artifacts(self._active_experiment, template)
        self._save_status.show_success("Карточка сохранена. Поля оставлены без очистки.")
        self._notify_post_action()

    @Slot()
    def _on_finalize_experiment(self) -> None:
        self._finalize_or_abort("experiment_finalize", "Завершить текущий эксперимент?")

    @Slot()
    def _on_abort_experiment(self) -> None:
        self._finalize_or_abort("experiment_abort", "Прервать текущий эксперимент?")

    def _finalize_or_abort(self, command: str, question: str) -> None:
        if not self._active_experiment:
            return
        if self._finalize_guard is not None:
            allowed, message = self._finalize_guard()
            if not allowed:
                self._save_status.show_warning(message)
                self._show_shell_message(message)
                return
        answer = QMessageBox.question(self, "Карточка эксперимента", question)
        if answer != QMessageBox.StandardButton.Yes:
            return
        payload = {
            "cmd": command,
            "experiment_id": str(self._active_experiment.get("experiment_id", "")),
            "title": self._card_title_edit.text().strip(),
            "sample": self._card_sample_edit.text().strip(),
            "description": self._card_description_edit.toPlainText().strip(),
            "notes": self._card_notes_edit.toPlainText().strip(),
            "custom_fields": {
                field_id: edit.text().strip()
                for field_id, edit in self._card_custom_edits.items()
                if edit.text().strip()
            },
        }
        self._finalize_button.setEnabled(False)
        self._abort_button.setEnabled(False)
        worker = ZmqCommandWorker(payload)
        worker.finished.connect(lambda result, cmd=command: self._on_finalize_result(result, cmd))
        self._workers.append(worker)
        worker.start()

    def _on_finalize_result(self, result: dict, command: str) -> None:
        self._finalize_button.setEnabled(True)
        self._abort_button.setEnabled(True)
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok"):
            self._save_status.show_error(
                str(result.get("error", "Не удалось закрыть карточку эксперимента."))
            )
            self._show_shell_message(self._save_status.text())
            return
        if command == "experiment_finalize" and result.get("report_generated"):
            action_text = "Эксперимент завершён. Отчёт сформирован."
        elif command == "experiment_finalize":
            action_text = "Эксперимент завершён."
        else:
            action_text = "Эксперимент прерван."
        if self.refresh_state():
            self._workspace_status.show_success(action_text)
        else:
            self._workspace_status.show_warning(
                "Команда выполнена, но состояние интерфейса не удалось обновить."
            )
        self._notify_post_action()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        root.addWidget(
            PanelHeader(
                "Рабочее место оператора",
                "Главная карточка эксперимента, режим приложения и основные действия без перехода к отдельному журналу.",
            )
        )

        mode_frame = QFrame()
        apply_panel_frame_style(mode_frame, background="#11151d", border="#30363d", radius=6)
        mode_layout = QHBoxLayout(mode_frame)
        mode_layout.setContentsMargins(12, 10, 12, 10)
        mode_layout.setSpacing(10)

        self._mode_title = QLabel("Режим")
        self._mode_title.setStyleSheet("color: #8b949e; font-size: 12px;")
        mode_layout.addWidget(self._mode_title)

        self._mode_label = QLabel("ЭКСПЕРИМЕНТ")
        self._mode_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        mode_layout.addWidget(self._mode_label)

        mode_layout.addStretch()

        self._mode_experiment_button = QPushButton("Эксперимент")
        apply_button_style(self._mode_experiment_button, "primary")
        self._mode_experiment_button.clicked.connect(self._on_mode_experiment)
        mode_layout.addWidget(self._mode_experiment_button)

        self._mode_debug_button = QPushButton("Отладка")
        apply_button_style(self._mode_debug_button, "warning")
        self._mode_debug_button.clicked.connect(self._on_mode_debug)
        mode_layout.addWidget(self._mode_debug_button)
        root.addWidget(mode_frame)

        self._mode_notice = QLabel("")
        self._mode_notice.setWordWrap(True)
        root.addWidget(self._mode_notice)

        self._workspace_status = StatusBanner()
        self._workspace_status.clear_message()
        root.addWidget(self._workspace_status)

        # Phase progress bar (visible only when experiment is active)
        self._phase_frame = QFrame()
        apply_panel_frame_style(self._phase_frame, background="#11151d", border="#30363d", radius=6)
        phase_layout = QHBoxLayout(self._phase_frame)
        phase_layout.setContentsMargins(12, 6, 12, 6)
        phase_layout.setSpacing(4)
        self._phase_labels: dict[str, QLabel] = {}
        _phase_names = [
            ("preparation", "Подгот."),
            ("vacuum", "Откачка"),
            ("cooldown", "Захолаж."),
            ("measurement", "Измерен."),
            ("warmup", "Растепл."),
            ("teardown", "Разборка"),
        ]
        for i, (key, label) in enumerate(_phase_names):
            if i > 0:
                arrow = QLabel("→")
                arrow.setStyleSheet("color: #555555; border: none; font-size: 11px;")
                phase_layout.addWidget(arrow)
            lbl = QLabel(f"○ {label}")
            lbl.setStyleSheet("color: #555555; border: none; font-size: 11px;")
            phase_layout.addWidget(lbl)
            self._phase_labels[key] = lbl
        phase_layout.addStretch()
        self._advance_phase_btn = QPushButton("Фаза →")
        apply_button_style(self._advance_phase_btn, "neutral")
        self._advance_phase_btn.clicked.connect(self._on_advance_phase)
        phase_layout.addWidget(self._advance_phase_btn)
        self._phase_frame.setVisible(False)
        root.addWidget(self._phase_frame)

        self._debug_panel = QFrame()
        apply_panel_frame_style(self._debug_panel, background="#1e2430", border="#9e6a03", radius=6)
        debug_layout = QVBoxLayout(self._debug_panel)
        debug_layout.setContentsMargins(12, 10, 12, 10)
        debug_layout.addWidget(QLabel("Режим отладки активен."))
        self._debug_message = QLabel(
            "Карточка эксперимента не открывается. Архивные записи и автоматические отчёты по эксперименту сейчас не формируются."
        )
        self._debug_message.setWordWrap(True)
        self._debug_message.setStyleSheet("color: #c9d1d9;")
        debug_layout.addWidget(self._debug_message)
        root.addWidget(self._debug_panel)

        self._create_box = QGroupBox("Новый эксперимент")
        apply_group_box_style(self._create_box, "#3fb950")
        create_layout = QVBoxLayout(self._create_box)
        create_layout.setSpacing(8)
        create_form = QFormLayout()
        create_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        create_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._create_template_combo = QComboBox()
        self._create_template_combo.currentIndexChanged.connect(self._rebuild_create_custom_fields)
        self._create_title_edit = QLineEdit()
        self._create_operator_edit = QComboBox()
        self._create_operator_edit.setEditable(True)
        self._create_operator_edit.setInsertPolicy(QComboBox.InsertPolicy.InsertAtTop)
        from PySide6.QtCore import QSettings
        _settings = QSettings("FIAN", "CryoDAQ")
        _known_ops = _settings.value("known_operators", [])
        if isinstance(_known_ops, list) and _known_ops:
            self._create_operator_edit.addItems(_known_ops)
        self._create_sample_edit = QLineEdit()
        self._create_cryostat_edit = QComboBox()
        self._create_cryostat_edit.setEditable(True)
        self._create_cryostat_edit.addItems(["Криостат АКЦ ФИАН"])
        self._create_description_edit = QTextEdit()
        self._create_description_edit.setMaximumHeight(70)
        self._create_notes_edit = QTextEdit()
        self._create_notes_edit.setMaximumHeight(70)
        add_form_rows(
            create_form,
            [
                ("Шаблон:", self._create_template_combo),
                ("Название:", self._create_title_edit),
                ("Оператор:", self._create_operator_edit),
                ("Образец:", self._create_sample_edit),
                ("Криостат:", self._create_cryostat_edit),
                ("Описание:", self._create_description_edit),
                ("Заметки:", self._create_notes_edit),
            ],
        )
        create_layout.addLayout(create_form)
        self._create_custom_form = QFormLayout()
        self._create_custom_edits: dict[str, QLineEdit] = {}
        create_layout.addLayout(self._create_custom_form)
        self._create_button = QPushButton("Создать эксперимент")
        apply_button_style(self._create_button, "primary")
        self._create_button.clicked.connect(self._on_create_experiment)
        create_layout.addLayout(build_action_row(self._create_button, add_stretch=True))
        root.addWidget(self._create_box)

        self._active_box = QGroupBox("Текущая карточка эксперимента")
        apply_group_box_style(self._active_box, "#58a6ff")
        active_layout = QVBoxLayout(self._active_box)
        active_layout.setSpacing(8)

        self._card_summary = QLabel("Активный эксперимент не открыт.")
        self._card_summary.setWordWrap(True)
        active_layout.addWidget(self._card_summary)

        self._passport_box = QGroupBox("Паспортные данные")
        apply_group_box_style(self._passport_box, "#58a6ff")
        passport_layout = QFormLayout(self._passport_box)
        passport_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        passport_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._card_experiment_id = QLabel("—")
        self._card_experiment_id.setWordWrap(True)
        self._card_status = QLabel("—")
        self._card_status.setWordWrap(True)
        self._card_operator = QLabel("—")
        self._card_operator.setWordWrap(True)
        self._card_template = QLabel("—")
        self._card_template.setWordWrap(True)
        self._card_started = QLabel("—")
        self._card_started.setWordWrap(True)
        self._card_cryostat = QLabel("—")
        self._card_cryostat.setWordWrap(True)
        add_form_rows(
            passport_layout,
            [
                ("Идентификатор:", self._card_experiment_id),
                ("Статус:", self._card_status),
                ("Оператор:", self._card_operator),
                ("Шаблон:", self._card_template),
                ("Старт:", self._card_started),
                ("Криостат:", self._card_cryostat),
            ],
        )
        active_layout.addWidget(self._passport_box)

        self._card_fields_box = QGroupBox("Поля карточки")
        apply_group_box_style(self._card_fields_box, "#3fb950")
        card_fields_layout = QVBoxLayout(self._card_fields_box)
        card_form = QFormLayout()
        card_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        card_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._card_title_edit = QLineEdit()
        self._card_sample_edit = QLineEdit()
        self._card_description_edit = QTextEdit()
        self._card_description_edit.setMaximumHeight(70)
        self._card_notes_edit = QTextEdit()
        self._card_notes_edit.setMaximumHeight(70)
        add_form_rows(
            card_form,
            [
                ("Название:", self._card_title_edit),
                ("Образец:", self._card_sample_edit),
                ("Описание:", self._card_description_edit),
                ("Заметки:", self._card_notes_edit),
            ],
        )
        card_fields_layout.addLayout(card_form)
        self._card_custom_form = QFormLayout()
        self._card_custom_edits: dict[str, QLineEdit] = {}
        card_fields_layout.addLayout(self._card_custom_form)
        self._save_button = QPushButton("Сохранить карточку")
        apply_button_style(self._save_button, "primary")
        self._save_button.clicked.connect(self._on_save_card)
        self._finalize_button = QPushButton("Завершить эксперимент")
        apply_button_style(self._finalize_button, "warning")
        self._finalize_button.clicked.connect(self._on_finalize_experiment)
        self._abort_button = QPushButton("Прервать эксперимент")
        apply_button_style(self._abort_button, "danger")
        self._abort_button.clicked.connect(self._on_abort_experiment)
        card_fields_layout.addLayout(
            build_action_row(self._save_button, self._finalize_button, self._abort_button, add_stretch=True)
        )
        self._save_status = StatusBanner()
        self._save_status.clear_message()
        card_fields_layout.addWidget(self._save_status)
        active_layout.addWidget(self._card_fields_box)

        details_layout = QHBoxLayout()
        details_layout.setSpacing(8)

        self._timeline_box = QGroupBox("Таймлайн событий и прогонов")
        apply_group_box_style(self._timeline_box, "#f0883e")
        timeline_layout = QVBoxLayout(self._timeline_box)
        self._timeline_list = QListWidget()
        timeline_layout.addWidget(self._timeline_list)
        details_layout.addWidget(self._timeline_box, 1)

        right_column = QVBoxLayout()
        right_column.setSpacing(8)

        self._artifacts_box = QGroupBox("Артефакты и результаты")
        apply_group_box_style(self._artifacts_box, "#bc8cff")
        artifacts_layout = QVBoxLayout(self._artifacts_box)
        self._artifacts_list = QListWidget()
        artifacts_layout.addWidget(self._artifacts_list)
        right_column.addWidget(self._artifacts_box, 1)

        self._report_box = QGroupBox("Готовность отчётов")
        apply_group_box_style(self._report_box, "#58a6ff")
        report_layout = QVBoxLayout(self._report_box)
        self._report_label = QLabel("—")
        self._report_label.setWordWrap(True)
        report_layout.addWidget(self._report_label)
        right_column.addWidget(self._report_box)

        details_layout.addLayout(right_column, 1)
        active_layout.addLayout(details_layout)
        root.addWidget(self._active_box)

        # Push all content to top — empty space goes to bottom
        root.addStretch()

    def _apply_preferences(self) -> None:
        """Подставить последние значения из истории и настроить autocomplete."""
        last = self._preferences.get_last_experiment()

        # Pre-fill fields (только если поле пустое)
        if last.get("operator") and not self._create_operator_edit.currentText():
            self._create_operator_edit.setCurrentText(last["operator"])
        if last.get("sample") and not self._create_sample_edit.text():
            self._create_sample_edit.setText(last["sample"])
        if last.get("cryostat") and not self._create_cryostat_edit.currentText():
            self._create_cryostat_edit.setCurrentText(last["cryostat"])

        # QCompleter для текстовых полей
        def _make_completer(items: list[str]) -> QCompleter:
            c = QCompleter(items, self)
            c.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            return c

        self._create_operator_edit.lineEdit().setCompleter(
            _make_completer(self._preferences.get_history("operator"))
        )
        self._create_sample_edit.setCompleter(
            _make_completer(self._preferences.get_history("sample"))
        )
        self._create_cryostat_edit.lineEdit().setCompleter(
            _make_completer(self._preferences.get_history("cryostat"))
        )

        # Подключить suggest name при смене шаблона
        self._create_template_combo.currentIndexChanged.connect(self._suggest_name)

    def _suggest_name(self) -> None:
        """Предложить имя эксперимента с авто-инкрементом при смене шаблона."""
        if self._create_title_edit.text().strip():
            return  # Не перезаписывать если уже введено
        template = self._create_template_combo.currentData() or {}
        template_id = str(template.get("id", ""))
        template_name = str(template.get("name", template_id))
        if not template_name:
            return
        name_map = {template_id: template_name} if template_id else {}
        suggested = suggest_experiment_name(template_id, [], name_map)
        self._create_title_edit.setText(suggested)

    def _switch_mode(self, mode: str) -> None:
        if mode == self._app_mode:
            return
        answer = QMessageBox.question(
            self,
            "Режим приложения",
            f"Переключить приложение в режим «{'Эксперимент' if mode == 'experiment' else 'Отладка'}»?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = send_command({"cmd": "set_app_mode", "app_mode": mode})
        if not result.get("ok"):
            self._workspace_status.show_error(str(result.get("error", "Не удалось сменить режим.")))
            self._show_shell_message(self._workspace_status.text())
            return
        if self.refresh_state():
            mode_label = "Эксперимент" if mode == "experiment" else "Отладка"
            self._workspace_status.show_success(f"Режим переключён: {mode_label}.")
        else:
            self._workspace_status.show_warning(
                "Команда на смену режима выполнена, но состояние интерфейса не удалось обновить."
            )
        self._notify_post_action()

    def _sync_ui_from_state(self) -> None:
        self._mode_label.setText("ЭКСПЕРИМЕНТ" if self._app_mode == "experiment" else "ОТЛАДКА")
        apply_status_label_style(
            self._mode_label,
            "success" if self._app_mode == "experiment" else "warning",
            bold=True,
        )
        self._mode_notice.setText(
            "В режиме эксперимента доступна одна активная карточка, архивирование и подготовка отчётов."
            if self._app_mode == "experiment"
            else "В режиме отладки карточка эксперимента не ведётся, архив и автоматические отчёты не формируются."
        )
        apply_status_label_style(
            self._mode_notice,
            "muted" if self._app_mode == "experiment" else "warning",
        )
        self._mode_experiment_button.setEnabled(self._app_mode != "experiment")
        self._mode_debug_button.setEnabled(self._app_mode != "debug")

        debug_mode = self._app_mode == "debug"
        has_active = self._active_experiment is not None
        self._debug_panel.setVisible(debug_mode)
        self._create_box.setVisible(self._app_mode == "experiment" and not has_active)
        self._active_box.setVisible(self._app_mode == "experiment" and has_active)
        self._phase_frame.setVisible(self._app_mode == "experiment" and has_active)
        if has_active:
            self._populate_active_card(self._active_experiment)
            self._update_phase_display()
        else:
            self._clear_active_card()

    def _sync_create_template_choices(self) -> None:
        current_id = str(self._create_template_combo.currentData() or "")
        self._create_template_combo.blockSignals(True)
        self._create_template_combo.clear()
        for template in self._templates:
            self._create_template_combo.addItem(str(template.get("name", "")), template)
        self._create_template_combo.blockSignals(False)
        if current_id:
            index = self._create_template_combo.findData(self._templates_by_id.get(current_id))
            if index >= 0:
                self._create_template_combo.setCurrentIndex(index)
        self._rebuild_create_custom_fields()

    def _populate_active_card(self, experiment: dict[str, Any]) -> None:
        template_id = str(experiment.get("template_id", "custom"))
        template = self._templates_by_id.get(template_id, {})
        self._card_summary.setText(
            f"{experiment.get('title', experiment.get('name', ''))}\n"
            f"Открытая карточка ведётся с {self._format_datetime(experiment.get('start_time'))}."
        )
        self._card_experiment_id.setText(str(experiment.get("experiment_id", "")))
        self._card_status.setText(str(experiment.get("status", "")))
        self._card_operator.setText(str(experiment.get("operator", "")))
        self._card_template.setText(str(template.get("name", template_id)))
        self._card_started.setText(self._format_datetime(experiment.get("start_time")))
        self._card_cryostat.setText(str(experiment.get("cryostat", "")) or "—")

        self._card_title_edit.setText(str(experiment.get("title", "")))
        self._card_sample_edit.setText(str(experiment.get("sample", "")))
        self._card_description_edit.setPlainText(str(experiment.get("description", "")))
        self._card_notes_edit.setPlainText(str(experiment.get("notes", "")))
        self._rebuild_active_custom_fields(template, dict(experiment.get("custom_fields") or {}))
        self._rebuild_artifacts(experiment, template)
        self._report_label.setText(self._describe_report_state(experiment))

    def _clear_active_card(self) -> None:
        self._card_summary.setText("Активный эксперимент не открыт.")
        for label in (
            self._card_experiment_id,
            self._card_status,
            self._card_operator,
            self._card_template,
            self._card_started,
            self._card_cryostat,
        ):
            label.setText("—")
        for edit in (self._card_title_edit, self._card_sample_edit):
            edit.clear()
        self._card_description_edit.clear()
        self._card_notes_edit.clear()
        self._clear_form_layout(self._card_custom_form)
        self._card_custom_edits.clear()
        self._timeline_list.clear()
        self._artifacts_list.clear()
        self._report_label.setText("Отчёты будут доступны после появления активной карточки.")
        self._save_status.clear_message()

    def _rebuild_create_custom_fields(self) -> None:
        template = self._create_template_combo.currentData() or {}
        self._clear_form_layout(self._create_custom_form)
        self._create_custom_edits.clear()
        for field in template.get("custom_fields", []):
            field_id = str(field.get("id", "")).strip()
            if not field_id:
                continue
            edit = QLineEdit()
            edit.setPlaceholderText(str(field.get("default", "")))
            self._create_custom_edits[field_id] = edit
            self._create_custom_form.addRow(f"{field.get('label', field_id)}:", edit)

    def _rebuild_active_custom_fields(
        self,
        template: dict[str, Any],
        values: dict[str, Any],
    ) -> None:
        self._clear_form_layout(self._card_custom_form)
        self._card_custom_edits.clear()
        labels = {
            str(field.get("id", "")): str(field.get("label", field.get("id", "")))
            for field in template.get("custom_fields", [])
            if str(field.get("id", "")).strip()
        }
        for field_id in sorted({*labels.keys(), *[str(key) for key in values.keys()]}):
            edit = QLineEdit(str(values.get(field_id, "")))
            self._card_custom_edits[field_id] = edit
            self._card_custom_form.addRow(f"{labels.get(field_id, field_id)}:", edit)

    def _reload_timeline(self) -> None:
        self._timeline_list.clear()
        if not self._active_experiment:
            return
        result = send_command({"cmd": "log_get", "current_experiment": True, "limit": 50})
        if result.get("ok"):
            entries = list(result.get("entries", []))
            self._timeline_entries = [self._format_timeline_entry(entry) for entry in entries]
        for item in self._timeline_entries:
            self._timeline_list.addItem(QListWidgetItem(item))
        if self._timeline_list.count() == 0:
            self._timeline_list.addItem(
                QListWidgetItem("События текущего эксперимента пока не зафиксированы.")
            )

    def _prepend_runtime_timeline_entry(self, text: str) -> None:
        self._timeline_entries.insert(0, text)
        self._timeline_entries = self._timeline_entries[:50]
        self._timeline_list.clear()
        for item in self._timeline_entries:
            self._timeline_list.addItem(QListWidgetItem(item))

    def _rebuild_artifacts(self, experiment: dict[str, Any], template: dict[str, Any]) -> None:
        self._artifacts_list.clear()
        artifact_dir = str(experiment.get("artifact_dir", "")).strip()
        metadata_path = str(experiment.get("metadata_path", "")).strip()
        for text in [
            f"artifact_dir: {artifact_dir}" if artifact_dir else "artifact_dir: будет создан backend",
            f"metadata: {metadata_path}" if metadata_path else "metadata: будет обновляться вместе с карточкой",
            f"sections: {', '.join(experiment.get('sections', []))}" if experiment.get("sections") else "",
            f"template_report_enabled: {'yes' if experiment.get('report_enabled', template.get('report_enabled', True)) else 'no'}",
        ]:
            if text:
                self._artifacts_list.addItem(QListWidgetItem(text))
        if self._artifacts_list.count() == 0:
            self._artifacts_list.addItem(QListWidgetItem("Артефакты и результаты ещё не зафиксированы."))

    def _describe_report_state(self, experiment: dict[str, Any]) -> str:
        if self._app_mode == "debug":
            return "Автоматические отчёты отключены в режиме отладки."
        if not bool(experiment.get("report_enabled", True)):
            return "Для выбранного шаблона автоматический отчёт отключён."
        return (
            "Карточка активна. Автоматический отчёт станет доступен после завершения и архивирования эксперимента."
        )

    def _update_phase_display(self) -> None:
        """Update phase labels from current experiment status (non-blocking)."""
        worker = ZmqCommandWorker({"cmd": "experiment_phase_status"}, parent=self)
        worker.finished.connect(self._on_phase_display_result)
        self._workers.append(worker)
        worker.start()

    @Slot(dict)
    def _on_phase_display_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if not isinstance(result, dict) or not result.get("ok"):
            return
        current = result.get("current_phase")
        completed = set()
        for p in result.get("phases", []):
            if p.get("ended_at") is not None:
                completed.add(p.get("phase"))
        for key, lbl in self._phase_labels.items():
            if key == current:
                lbl.setText(f"● {lbl.text().split(' ', 1)[-1]}")
                lbl.setStyleSheet("color: #2ECC40; font-weight: bold; border: none; font-size: 11px;")
            elif key in completed:
                lbl.setText(f"✓ {lbl.text().split(' ', 1)[-1]}")
                lbl.setStyleSheet("color: #58a6ff; border: none; font-size: 11px;")
            else:
                name = lbl.text().split(" ", 1)[-1]
                lbl.setText(f"○ {name}")
                lbl.setStyleSheet("color: #555555; border: none; font-size: 11px;")

    @Slot()
    def _on_advance_phase(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        phases = ["preparation", "vacuum", "cooldown", "measurement", "warmup", "teardown"]
        labels = ["Подготовка", "Откачка", "Захолаживание", "Измерение", "Растепление", "Разборка"]
        item, ok = QInputDialog.getItem(self, "Следующая фаза", "Выберите фазу:", labels, 0, False)
        if not ok:
            return
        idx = labels.index(item)
        self._advance_phase_btn.setEnabled(False)
        worker = ZmqCommandWorker({"cmd": "experiment_advance_phase", "phase": phases[idx]})
        worker.finished.connect(lambda result, label=item: self._on_advance_phase_result(result, label))
        self._workers.append(worker)
        worker.start()

    def _on_advance_phase_result(self, result: dict, label: str) -> None:
        self._advance_phase_btn.setEnabled(True)
        self._workers = [w for w in self._workers if w.isRunning()]
        if result.get("ok"):
            self._update_phase_display()
            self._workspace_status.show_success(f"Фаза: {label}")
        else:
            self._workspace_status.show_error(str(result.get("error", "Ошибка смены фазы")))

    @staticmethod
    def _clear_form_layout(layout: QFormLayout) -> None:
        while layout.rowCount() > 0:
            layout.removeRow(0)

    @staticmethod
    def _format_datetime(raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return "—"
        try:
            if text.endswith("Z"):
                text = f"{text[:-1]}+00:00"
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text

    @staticmethod
    def _format_timeline_entry(entry: dict[str, Any]) -> str:
        stamp = ExperimentWorkspace._format_datetime(entry.get("timestamp"))
        author = str(entry.get("author", "")).strip() or str(entry.get("source", "")).strip() or "system"
        message = str(entry.get("message", "")).strip()
        return f"{stamp} • {author}: {message}"

    @staticmethod
    def _format_now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _notify_post_action(self) -> None:
        if self._post_action is not None:
            self._post_action()

    def _show_shell_message(self, text: str) -> None:
        if self._shell_message is not None:
            self._shell_message(text, 5000)
