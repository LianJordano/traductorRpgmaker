"""Main application window for RPG Translator Pro."""
from __future__ import annotations
import os
import queue
import subprocess
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from core import config, logger
from core import checkpoint
from core.models import ExtractionResult, WorkerMessage
from gui.styles import theme
from gui.components.file_panel import FilePanel
from gui.components.log_panel import LogPanel
from gui.components.progress_panel import ProgressPanel
from gui.components.settings_panel import SettingsPanel


class MainWindow(ctk.CTk):
    TITLE = "RPG Traductor Pro"
    GEOMETRY = "1100x720"
    POLL_MS = 100  # GUI queue poll interval

    def __init__(self) -> None:
        super().__init__()
        self._worker: Optional[object] = None
        self._result: Optional[ExtractionResult] = None
        self._msg_queue: queue.Queue[WorkerMessage] = queue.Queue()
        self._paused = False
        self._worker_start_time: float = 0.0
        self._apply_running = False
        self._apply_ok = True

        self._setup_window()
        self._build_layout()
        self._hook_logger()
        self._start_queue_poll()
        # Drop checkpoints for games that have not been touched in a month, so
        # the resume data does not accumulate forever.
        try:
            checkpoint.prune()
        except Exception:
            pass

        last = config.get("last_game_path", "")
        if last and Path(last).is_dir():
            self.after(200, lambda: self._file_panel.set_game_path(last))

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self) -> None:
        self.title(self.TITLE)
        self.geometry(self.GEOMETRY)
        self.minsize(900, 600)
        self.configure(fg_color=theme.BG_PRIMARY)
        # Without this the window closes but the process does not: the
        # translation pool's threads are not daemons, so the interpreter waits
        # for them at exit while the run carries on with no window to show it.
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

    def _on_close(self) -> None:
        """Stop any running work before letting the window go."""
        worker = self._worker
        running = worker is not None and getattr(worker, "is_alive", lambda: False)()

        if running:
            if not mb.askokcancel(
                "Salir",
                "Hay una tarea en curso.\n\n"
                "Si sales ahora se detendrá. Lo ya traducido se conserva en el "
                "punto de control y podrás continuar más tarde.\n\n¿Cerrar?",
                parent=self,
            ):
                return
            for method in ("resume", "cancel"):
                try:
                    getattr(worker, method)()
                except Exception:
                    pass
            # Give the threads a moment to notice, keeping the window responsive
            # instead of freezing on a hard join.
            import time
            deadline = time.monotonic() + 8.0
            while worker.is_alive() and time.monotonic() < deadline:
                try:
                    self.update()
                except Exception:
                    break
                time.sleep(0.1)

        self.destroy()

    # ── Layout construction ────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        # Top bar
        self._build_topbar()

        # Main content (sidebar + tabs)
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=0, pady=0)

        # Sidebar
        self._file_panel = FilePanel(
            content, on_folder_selected=self._on_folder_selected, width=theme.SIDEBAR_W
        )
        self._file_panel.pack(side="left", fill="y", padx=(8, 4), pady=8)

        # Right area
        right = ctk.CTkFrame(content, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        self._build_tabs(right)

        # Progress
        self._progress = ProgressPanel(right)
        self._progress.pack(fill="x", pady=(4, 0))

        # Log
        self._log_panel = LogPanel(right, height=theme.LOG_H)
        self._log_panel.pack(fill="x", pady=(4, 0))

        # Control buttons
        self._build_controls(right)

    def _build_topbar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=theme.BG_SECONDARY, height=52, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        ctk.CTkLabel(
            bar, text="RPG Traductor Pro",
            font=theme.FONT_LOGO, text_color=theme.ACCENT,
        ).pack(side="left", padx=16, pady=10)

        ctk.CTkLabel(
            bar, text="v1.0.0",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(side="left", pady=10)

        # Right-side buttons in top bar
        ctk.CTkButton(
            bar, text="Acerca de", width=80, height=30,
            font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
            command=self._show_about,
        ).pack(side="right", padx=8, pady=10)

        ctk.CTkButton(
            bar, text="Limpiar traducciones", width=150, height=30,
            font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
            command=self._open_cleanup,
        ).pack(side="right", padx=0, pady=10)

    def _open_cleanup(self) -> None:
        """Show the checkpoint cleaner (also reachable from the settings tab)."""
        from gui.components.cleanup_dialog import CleanupDialog
        CleanupDialog(self)

    def _build_tabs(self, parent) -> None:
        self._tabs = ctk.CTkTabview(
            parent, fg_color=theme.BG_SECONDARY,
            segmented_button_fg_color=theme.BG_CARD,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT_PRIMARY,
        )
        self._tabs.pack(fill="both", expand=True)

        for tab in ("Extraer", "Traducir", "Importar / Exportar", "Resultados"):
            self._tabs.add(tab)

        self._build_tab_extract()
        self._build_tab_translate()
        self._build_tab_import_export()
        self._build_tab_results()
        self._build_tab_settings()  # added as extra tab

    def _build_tab_extract(self) -> None:
        tab = self._tabs.tab("Extraer")

        ctk.CTkLabel(
            tab, text="Extrae los textos del juego a un archivo de traducción",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        opts = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        opts.pack(fill="x", padx=8, pady=8)

        row = ctk.CTkFrame(opts, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(row, text="Formato de exportación:", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=170, anchor="w").pack(side="left")
        self._extract_format = ctk.CTkComboBox(
            row, values=["csv", "json", "excel"], width=140,
            font=theme.FONT_BODY, fg_color=theme.BG_SECONDARY,
            command=lambda v: config.set("export_format", v),
        )
        self._extract_format.set(config.get("export_format", "csv"))
        self._extract_format.pack(side="left", padx=8)

        row2 = ctk.CTkFrame(opts, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(row2, text="Carpeta de salida:", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=170, anchor="w").pack(side="left")
        self._output_entry = ctk.CTkEntry(
            row2, placeholder_text="Igual que la carpeta del juego (predeterminado)",
            font=theme.FONT_SMALL, fg_color=theme.BG_SECONDARY, width=240,
        )
        self._output_entry.pack(side="left", padx=(8, 4))
        saved_out = config.get("output_dir", "")
        if saved_out:
            self._output_entry.insert(0, saved_out)
        ctk.CTkButton(
            row2, text="...", width=36, height=28, fg_color=theme.BG_PRIMARY,
            command=self._pick_output_dir,
        ).pack(side="left")

        ctk.CTkButton(
            tab, text="Iniciar Extracción", height=44,
            font=("Segoe UI", 14, "bold"),
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._start_extraction,
        ).pack(fill="x", padx=8, pady=8)

    def _build_tab_translate(self) -> None:
        tab = self._tabs.tab("Traducir")

        ctk.CTkLabel(
            tab, text="Traduce los textos extraídos usando una API",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        card = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        card.pack(fill="x", padx=8, pady=8)

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(row, text="Traductor:", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=150, anchor="w").pack(side="left")
        self._trans_var = ctk.StringVar(value=config.get("translator", "google"))
        ctk.CTkComboBox(
            row, values=["google", "deepl", "openai"], variable=self._trans_var,
            font=theme.FONT_BODY, fg_color=theme.BG_SECONDARY, width=160,
        ).pack(side="left", padx=8)

        row2 = ctk.CTkFrame(card, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(0, 8))
        ctk.CTkLabel(row2, text="¿Sobreescribir existentes?", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=180, anchor="w").pack(side="left")
        self._overwrite_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(row2, variable=self._overwrite_var, text="").pack(side="left", padx=8)

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            btn_row, text="Iniciar Traducción", height=44,
            font=("Segoe UI", 14, "bold"),
            fg_color=theme.SUCCESS, hover_color="#27ae60",
            command=self._start_translation,
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            btn_row, text="Probar Conexión", height=44,
            font=theme.FONT_BODY, fg_color=theme.BG_CARD,
            command=self._test_translator,
        ).pack(side="left", padx=(4, 0))

    def _build_tab_import_export(self) -> None:
        tab = self._tabs.tab("Importar / Exportar")

        # Export section
        exp_card = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        exp_card.pack(fill="x", padx=8, pady=(12, 4))
        ctk.CTkLabel(exp_card, text="Exportar traducciones", font=theme.FONT_SUBTITLE,
                     text_color=theme.ACCENT, anchor="w").pack(padx=10, pady=(8, 2), anchor="w")
        ctk.CTkLabel(exp_card,
                     text="Exporta la extracción actual a CSV/JSON/Excel para edición externa.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(padx=10, pady=(0, 8), anchor="w")

        exp_btns = ctk.CTkFrame(exp_card, fg_color="transparent")
        exp_btns.pack(fill="x", padx=10, pady=(0, 10))
        for fmt, color in [("CSV", theme.ACCENT), ("JSON", theme.WARNING), ("Excel", "#27ae60")]:
            ctk.CTkButton(
                exp_btns, text=f"Exportar {fmt}", height=36, width=120,
                font=theme.FONT_BODY, fg_color=color,
                command=lambda f=fmt.lower(): self._export(f),
            ).pack(side="left", padx=(0, 6))

        # Import section
        imp_card = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        imp_card.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(imp_card, text="Importar traducciones", font=theme.FONT_SUBTITLE,
                     text_color=theme.ACCENT, anchor="w").pack(padx=10, pady=(8, 2), anchor="w")
        ctk.CTkLabel(imp_card,
                     text="Importa un archivo CSV/JSON/Excel editado manualmente.",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(padx=10, pady=(0, 8), anchor="w")
        ctk.CTkButton(
            imp_card, text="Importar archivo...", height=36,
            font=theme.FONT_BODY, fg_color=theme.BG_SECONDARY,
            command=self._import_file,
        ).pack(padx=10, pady=(0, 10), anchor="w")

        # Reinsert section
        ins_card = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        ins_card.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(ins_card, text="Aplicar al juego", font=theme.FONT_SUBTITLE,
                     text_color=theme.ACCENT, anchor="w").pack(padx=10, pady=(8, 2), anchor="w")
        ctk.CTkLabel(ins_card,
                     text="Escribe las traducciones en los archivos del juego (se crea un backup primero).",
                     font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
                     anchor="w").pack(padx=10, pady=(0, 8), anchor="w")
        ctk.CTkButton(
            ins_card, text="Aplicar Traducciones al Juego", height=40,
            font=("Segoe UI", 13, "bold"), fg_color=theme.ERROR_COLOR,
            command=self._apply_to_game,
        ).pack(padx=10, pady=(0, 10), anchor="w")

        # Backup maintenance
        bk_card = ctk.CTkFrame(tab, fg_color=theme.BG_CARD, corner_radius=8)
        bk_card.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(bk_card, text="Copias de seguridad", font=theme.FONT_SUBTITLE,
                     text_color=theme.ACCENT, anchor="w").pack(padx=10, pady=(8, 2), anchor="w")
        self._backup_info = ctk.CTkLabel(
            bk_card,
            text="Selecciona una carpeta de juego para ver sus backups.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED, anchor="w",
        )
        self._backup_info.pack(padx=10, pady=(0, 8), anchor="w")

        bk_btns = ctk.CTkFrame(bk_card, fg_color="transparent")
        bk_btns.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(
            bk_btns, text="Liberar espacio", height=36, width=150,
            font=theme.FONT_BODY, fg_color=theme.WARNING,
            command=self._clean_backups,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            bk_btns, text="Restaurar juego original", height=36, width=180,
            font=theme.FONT_BODY, fg_color=theme.BG_SECONDARY,
            command=self._restore_backup,
        ).pack(side="left")

    def _refresh_backup_info(self) -> None:
        from core import backup as bk
        path = self._file_panel.get_game_path()
        if not path:
            return
        try:
            from core.detector import detect
            game_dir = detect(path).game_dir
            count, size = bk.usage(game_dir)
        except Exception:
            return
        if not count:
            text = "Todavía no hay backups de este juego."
        else:
            text = (f"{count} backup(s), {size / (1024*1024):.1f} MB. "
                    f"La copia sin traducir se conserva siempre.")
        self._backup_info.configure(text=text)

    def _clean_backups(self) -> None:
        from core import backup as bk
        from core.detector import detect
        path = self._file_panel.get_game_path()
        if not path:
            mb.showwarning("Sin carpeta", "Selecciona primero una carpeta de juego.", parent=self)
            return
        game_dir = detect(path).game_dir
        freed = bk.reclaim_space(game_dir)
        self._refresh_backup_info()
        mb.showinfo(
            "Backups",
            f"Espacio liberado: {freed / (1024*1024):.1f} MB\n\n"
            "Se conserva la copia sin traducir del juego.",
            parent=self,
        )

    def _restore_backup(self) -> None:
        from core import backup as bk
        from core.detector import detect
        path = self._file_panel.get_game_path()
        if not path:
            mb.showwarning("Sin carpeta", "Selecciona primero una carpeta de juego.", parent=self)
            return
        detection = detect(path)
        backups = bk.list_backups(detection.game_dir)
        original = next((b for b in backups if bk.is_original(b)), None)
        if original is None:
            mb.showwarning("Sin backup", "No hay ninguna copia original de este juego.", parent=self)
            return
        if not mb.askyesno(
            "Restaurar",
            f"Se devolverán los archivos del juego al estado sin traducir\n"
            f"({original.name}).\n\n¿Continuar?",
            parent=self,
        ):
            return
        data_dir = detection.data_dir or detection.game_dir
        if bk.restore_backup(original, data_dir):
            mb.showinfo("Restaurado", "El juego ha vuelto a su estado original.", parent=self)
        else:
            mb.showerror("Error", "No se pudo restaurar. Revisa el registro.", parent=self)

    def _build_tab_results(self) -> None:
        tab = self._tabs.tab("Resultados")
        self._results_frame = ctk.CTkScrollableFrame(
            tab, fg_color=theme.BG_PRIMARY, label_text=""
        )
        self._results_frame.pack(fill="both", expand=True, padx=4, pady=4)

        self._result_lbl = ctk.CTkLabel(
            self._results_frame,
            text="Sin resultados aún.\nEjecuta la extracción primero (pestaña Extraer).",
            font=theme.FONT_BODY, text_color=theme.TEXT_MUTED,
        )
        self._result_lbl.pack(pady=30)

    def _build_tab_settings(self) -> None:
        self._tabs.add("Configuración")
        tab = self._tabs.tab("Configuración")
        SettingsPanel(tab).pack(fill="both", expand=True)

    def _build_controls(self, parent) -> None:
        bar = ctk.CTkFrame(parent, fg_color=theme.BG_SECONDARY, height=46, corner_radius=8)
        bar.pack(fill="x", pady=(4, 0))
        bar.pack_propagate(False)

        self._pause_btn = ctk.CTkButton(
            bar, text="Pausar", width=90, height=32,
            font=theme.FONT_BODY, fg_color=theme.WARNING,
            command=self._toggle_pause, state="disabled",
        )
        self._pause_btn.pack(side="left", padx=(8, 4), pady=7)

        self._cancel_btn = ctk.CTkButton(
            bar, text="Cancelar", width=90, height=32,
            font=theme.FONT_BODY, fg_color=theme.ERROR_COLOR,
            command=self._cancel, state="disabled",
        )
        self._cancel_btn.pack(side="left", padx=4, pady=7)

        ctk.CTkButton(
            bar, text="Abrir Carpeta de Salida", width=180, height=32,
            font=theme.FONT_BODY, fg_color=theme.BG_CARD,
            command=self._open_output_folder,
        ).pack(side="right", padx=(4, 8), pady=7)

    # ── Queue polling ──────────────────────────────────────────────────────────

    def _start_queue_poll(self) -> None:
        self._process_queue()

    def _process_queue(self) -> None:
        # Capped per tick: a large game can enqueue thousands of log lines
        # between polls, and draining them all in one pass freezes the window.
        budget = 300
        try:
            while budget > 0:
                budget -= 1
                msg: WorkerMessage = self._msg_queue.get_nowait()
                try:
                    self._handle_msg(msg)
                except Exception as exc:
                    import traceback
                    self._log_panel.append("ERROR", f"Error interno GUI: {exc}")
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.after(self.POLL_MS, self._process_queue)

    def _handle_msg(self, msg: WorkerMessage) -> None:
        if msg.type == "log":
            self._log_panel.append(msg.data.get("level", "INFO"), msg.data.get("msg", ""))

        elif msg.type == "progress":
            self._progress.update_progress(
                msg.data.get("current", 0),
                msg.data.get("total", 1),
                msg.data.get("file", ""),
            )

        elif msg.type == "stats":
            if "apply_ok" in msg.data:
                self._apply_ok = msg.data.get("apply_ok", True)
            version = msg.data.get("version")
            if version:
                self._progress.set_status(f"Detectado: {version}", theme.SUCCESS)
            total = msg.data.get("total")
            if total is not None:
                errors = msg.data.get("errors", 0)
                self._progress.set_extra_stats(Total=total, Errores=errors)

        elif msg.type == "complete":
            result = msg.data.get("result")
            if isinstance(result, ExtractionResult):
                self._result = result
                self._show_result_summary(result)
            import time
            elapsed = time.monotonic() - self._worker_start_time if self._worker_start_time else 0
            self._progress.mark_complete(elapsed)
            self._on_worker_done()
            if self._apply_running:
                self._apply_running = False
                if self._apply_ok:
                    mb.showinfo("Listo", "Traducciones aplicadas a los archivos del juego.", parent=self)
                else:
                    mb.showerror("Error", "La reinserción tuvo errores. Revisa el registro.", parent=self)

        elif msg.type == "error":
            err = msg.data.get("msg", "Error desconocido")
            self._log_panel.append("ERROR", err)
            mb.showerror("Error", err, parent=self)
            self._on_worker_done()

    # ── Logger hook ───────────────────────────────────────────────────────────

    def _hook_logger(self) -> None:
        def cb(entry: dict) -> None:
            msg = WorkerMessage.log(entry["level"], entry["msg"])
            self._msg_queue.put(msg)
        logger.add_callback(cb)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_folder_selected(self, path: str) -> None:
        config.set("last_game_path", path)
        self._log_panel.append("INFO", f"Carpeta del juego: {path}")
        self._refresh_backup_info()

    def _pick_output_dir(self) -> None:
        d = fd.askdirectory(title="Seleccionar Carpeta de Salida")
        if d:
            self._output_entry.delete(0, "end")
            self._output_entry.insert(0, d)
            config.set("output_dir", d)

    def _start_extraction(self) -> None:
        game_path = self._file_panel.get_game_path()
        if not game_path:
            mb.showwarning("Sin carpeta", "Por favor selecciona una carpeta de juego primero.", parent=self)
            return

        out = self._output_entry.get().strip()
        if out:
            config.set("output_dir", out)

        import time
        self._worker_start_time = time.monotonic()
        self._progress.reset()
        self._progress.start_timer()

        from workers.extraction_worker import ExtractionWorker
        self._worker = ExtractionWorker(game_path, self._msg_queue)
        self._worker.start()

        self._progress.set_status("Extrayendo...", theme.ACCENT)
        self._set_busy(True)
        self._tabs.set("Extraer")

    def _start_translation(self) -> None:
        if not self._result:
            mb.showwarning("Sin datos", "Primero debes extraer los textos (pestaña 'Extraer').", parent=self)
            return

        translator_name = self._trans_var.get()
        if self._overwrite_var.get():
            for e in self._result.entries:
                if e.status in ("translated", "error"):
                    e.status = "pending"

        import time
        self._worker_start_time = time.monotonic()
        self._progress.reset()
        self._progress.start_timer()

        from workers.translation_worker import TranslationWorker
        self._worker = TranslationWorker(self._result, self._msg_queue, translator_name)
        self._worker.start()

        self._progress.set_status("Traduciendo...", theme.SUCCESS)
        self._set_busy(True)

    def _test_translator(self) -> None:
        name = self._trans_var.get()
        src = config.get("language_from", "en")
        tgt = config.get("language_to", "es")
        try:
            from translators import google_translator, deepl_translator, openai_translator
            translators = {
                "google": google_translator.GoogleTranslator,
                "deepl": deepl_translator.DeepLTranslator,
                "openai": openai_translator.OpenAITranslator,
            }
            cls = translators.get(name)
            if not cls:
                mb.showerror("Error", f"Traductor desconocido: {name}", parent=self)
                return
            ok, msg = cls(src, tgt).test_connection()
            if ok:
                mb.showinfo("Conexión OK", msg, parent=self)
            else:
                mb.showerror("Conexión fallida", msg, parent=self)
        except Exception as exc:
            mb.showerror("Error", str(exc), parent=self)

    def _export(self, fmt: str) -> None:
        if not self._result:
            mb.showwarning("Sin datos", "Primero debes extraer los textos (pestaña 'Extraer').", parent=self)
            return
        out = self._output_entry.get().strip() or str(
            Path(self._file_panel.get_game_path() or ".") / "_rpgt_output"
        )
        Path(out).mkdir(parents=True, exist_ok=True)

        try:
            if fmt == "csv":
                from exporters.csv_exporter import CsvExporter
                path = CsvExporter().export(self._result, Path(out))
            elif fmt == "json":
                from exporters.json_exporter import JsonExporter
                path = JsonExporter().export(self._result, Path(out))
            else:
                from exporters.excel_exporter import ExcelExporter
                path = ExcelExporter().export(self._result, Path(out))
            mb.showinfo("Exportado", f"Archivo guardado:\n{path}", parent=self)
        except Exception as exc:
            mb.showerror("Error de exportación", str(exc), parent=self)

    def _import_file(self) -> None:
        if not self._result:
            mb.showwarning("Sin datos", "Primero debes extraer los textos (pestaña 'Extraer').", parent=self)
            return
        path = fd.askopenfilename(
            title="Importar archivo de traducción",
            filetypes=[
                ("Todos los soportados", "*.csv *.json *.xlsx"),
                ("CSV", "*.csv"), ("JSON", "*.json"), ("Excel", "*.xlsx"),
            ],
        )
        if not path:
            return
        ext = Path(path).suffix.lower()
        from importers.csv_importer import import_csv, import_json, import_excel
        try:
            if ext == ".csv":
                n = import_csv(Path(path), self._result)
            elif ext == ".json":
                n = import_json(Path(path), self._result)
            elif ext == ".xlsx":
                n = import_excel(Path(path), self._result)
            else:
                mb.showerror("Error", "Formato de archivo no soportado.", parent=self)
                return
            mb.showinfo("Importación OK", f"Se importaron {n} traducciones.", parent=self)
            self._show_result_summary(self._result)
        except Exception as exc:
            mb.showerror("Error de importación", str(exc), parent=self)

    def _apply_to_game(self) -> None:
        if not self._result:
            mb.showwarning("Sin datos", "Primero debes extraer los textos (pestaña 'Extraer').", parent=self)
            return
        translated = sum(1 for e in self._result.entries if e.status == "translated")
        if translated == 0:
            mb.showwarning("Nada que aplicar", "No se encontraron textos traducidos.", parent=self)
            return
        if not mb.askyesno(
            "Aplicar al juego",
            f"Se escribirán {translated} textos traducidos en los archivos del juego.\n"
            "Se creará un backup primero.\n\n¿Continuar?",
            parent=self,
        ):
            return
        game_path = self._file_panel.get_game_path()
        if not game_path:
            return

        # Run backup + reinsertion in a background thread so the GUI doesn't
        # freeze on large games (copying files and reinserting 50k+ texts).
        import time
        self._worker_start_time = time.monotonic()
        self._progress.reset()
        self._progress.start_timer()
        self._progress.set_status("Aplicando al juego...", theme.ACCENT)

        from workers.apply_worker import ApplyWorker
        self._apply_running = True
        self._apply_ok = True
        self._worker = ApplyWorker(game_path, self._result, self._msg_queue)
        self._worker.start()
        self._set_busy(True)

    def _toggle_pause(self) -> None:
        if not self._worker:
            return
        if hasattr(self._worker, "pause") and hasattr(self._worker, "resume"):
            if self._paused:
                self._worker.resume()
                self._pause_btn.configure(text="Pausar")
                self._paused = False
                self._progress.set_status("Ejecutando...", theme.ACCENT)
            else:
                self._worker.pause()
                self._pause_btn.configure(text="Reanudar")
                self._paused = True
                self._progress.set_status("Pausado", theme.WARNING)

    def _cancel(self) -> None:
        if self._worker and hasattr(self._worker, "cancel"):
            self._worker.cancel()
        self._progress.set_status("Cancelando...", theme.WARNING)

    def _on_worker_done(self) -> None:
        self._set_busy(False)
        self._paused = False
        self._pause_btn.configure(text="Pausar")

    def _set_busy(self, busy: bool) -> None:
        state = "normal" if busy else "disabled"
        self._pause_btn.configure(state=state)
        self._cancel_btn.configure(state=state)
        if not busy:
            self._progress.update_progress(
                self._progress._bar.get() and 1 or 0, 1
            )

    def _show_result_summary(self, result: ExtractionResult) -> None:
        for w in self._results_frame.winfo_children():
            w.destroy()

        stats = [
            ("Total de textos", result.total, theme.TEXT_PRIMARY),
            ("Pendientes", result.pending, theme.WARNING),
            ("Traducidos", result.translated, theme.SUCCESS),
            ("Errores", len(result.errors), theme.ERROR_COLOR),
        ]

        ctk.CTkLabel(
            self._results_frame, text="Resumen de Extracción",
            font=theme.FONT_SUBTITLE, text_color=theme.ACCENT,
        ).pack(pady=(10, 8))

        for label, value, color in stats:
            row = ctk.CTkFrame(self._results_frame, fg_color=theme.BG_CARD, corner_radius=6)
            row.pack(fill="x", padx=8, pady=3)
            ctk.CTkLabel(row, text=label, font=theme.FONT_BODY,
                         text_color=theme.TEXT_MUTED, anchor="w").pack(side="left", padx=12, pady=8)
            ctk.CTkLabel(row, text=str(value), font=("Segoe UI", 16, "bold"),
                         text_color=color, anchor="e").pack(side="right", padx=12)

        if result.errors:
            ctk.CTkLabel(
                self._results_frame, text="Errores:", font=theme.FONT_SUBTITLE,
                text_color=theme.ERROR_COLOR, anchor="w",
            ).pack(fill="x", padx=8, pady=(12, 4))
            for err in result.errors[:20]:
                ctk.CTkLabel(
                    self._results_frame, text=f"  • {err}",
                    font=theme.FONT_SMALL, text_color=theme.ERROR_COLOR, anchor="w",
                ).pack(fill="x", padx=8)

        self._tabs.set("Resultados")

    def _open_output_folder(self) -> None:
        game_path = self._file_panel.get_game_path()
        out = self._output_entry.get().strip() if hasattr(self, "_output_entry") else ""
        if not out:
            out = str(Path(game_path or ".") / "_rpgt_output") if game_path else "."
        Path(out).mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(out)
            else:
                subprocess.Popen(["xdg-open", out])
        except Exception:
            pass

    def _show_about(self) -> None:
        mb.showinfo(
            "Acerca de RPG Traductor Pro",
            "RPG Traductor Pro v1.0.0\n\n"
            "Herramienta profesional de traducción para juegos RPG Maker.\n"
            "Compatible con: MV, MZ, VX Ace, VX, XP, 2003, 2000\n\n"
            "Desarrollado con Python + CustomTkinter\n"
            "Gratuito y de código abierto.",
            parent=self,
        )
