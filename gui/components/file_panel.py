"""Left sidebar: game folder picker, version badge, and found-files list."""
from __future__ import annotations
import os
import tkinter.filedialog as fd
import customtkinter as ctk
from pathlib import Path
from typing import Callable, Optional

from gui.styles import theme
from core import detector


class FilePanel(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_folder_selected: Optional[Callable[[str], None]] = None,
        **kwargs,
    ):
        kwargs.setdefault("fg_color", theme.BG_SECONDARY)
        kwargs.setdefault("width", theme.SIDEBAR_W)
        super().__init__(master, **kwargs)
        self._on_folder_selected = on_folder_selected
        self._game_path: Optional[str] = None
        self._build()

    def _build(self) -> None:
        self.grid_propagate(False)

        # Title
        ctk.CTkLabel(
            self, text="  Carpeta del Juego", font=theme.FONT_SUBTITLE,
            text_color=theme.TEXT_PRIMARY, anchor="w",
        ).pack(fill="x", padx=8, pady=(12, 4))

        # Browse button
        self._path_entry = ctk.CTkEntry(
            self, placeholder_text="Seleccionar carpeta del juego...",
            font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
        )
        self._path_entry.pack(fill="x", padx=8, pady=(0, 4))

        ctk.CTkButton(
            self, text="Explorar...", height=theme.BTN_H,
            font=theme.FONT_BODY, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            command=self._browse,
        ).pack(fill="x", padx=8, pady=(0, 10))

        # Version badge
        ctk.CTkLabel(
            self, text="  Versión Detectada", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=8)

        self._version_lbl = ctk.CTkLabel(
            self, text="—", font=("Segoe UI", 13, "bold"),
            text_color=theme.ACCENT, anchor="w",
        )
        self._version_lbl.pack(fill="x", padx=14, pady=(0, 8))

        # Confidence
        self._conf_lbl = ctk.CTkLabel(
            self, text="", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        self._conf_lbl.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(
            self, text="  Archivos de Datos", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=8)

        self._files_frame = ctk.CTkScrollableFrame(
            self, fg_color=theme.BG_PRIMARY, label_text="",
        )
        self._files_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _browse(self) -> None:
        start = self._game_path or os.path.expanduser("~")
        folder = fd.askdirectory(title="Seleccionar Carpeta del Juego RPG Maker", initialdir=start)
        if folder:
            self._set_path(folder)

    def _set_path(self, path: str) -> None:
        self._game_path = path
        self._path_entry.delete(0, "end")
        self._path_entry.insert(0, path)

        detection = detector.detect(path)
        if detection.supported:
            self._version_lbl.configure(text=detection.display_name, text_color=theme.SUCCESS)
            self._conf_lbl.configure(
                text=f"Confianza: {detection.confidence}%",
                text_color=theme.TEXT_MUTED,
            )
            self._populate_files(detection)
        else:
            self._version_lbl.configure(text="No detectada", text_color=theme.ERROR_COLOR)
            self._conf_lbl.configure(text="", text_color=theme.TEXT_MUTED)
            self._clear_files()

        if self._on_folder_selected:
            self._on_folder_selected(path)

    def _populate_files(self, detection: detector.DetectionResult) -> None:
        self._clear_files()
        data_dir = detection.data_dir
        if not data_dir or not data_dir.is_dir():
            return

        globs = {
            "MV": "*.json", "MZ": "*.json",
            "XP": "*.rxdata", "VX": "*.rvdata",
            "VXAce": "*.rvdata2",
            "RM2000": "*.lmu", "RM2003": "*.lmu",
        }
        pattern = globs.get(detection.version, "*.*")
        files = sorted(data_dir.glob(pattern))[:80]

        for fpath in files:
            row = ctk.CTkFrame(self._files_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                row, text="✓", font=theme.FONT_SMALL,
                text_color=theme.SUCCESS, width=16,
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=fpath.name, font=theme.FONT_SMALL,
                text_color=theme.TEXT_PRIMARY, anchor="w",
            ).pack(side="left", fill="x", expand=True)

        if not files:
            ctk.CTkLabel(
                self._files_frame, text="No se encontraron archivos",
                font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            ).pack()

    def _clear_files(self) -> None:
        for widget in self._files_frame.winfo_children():
            widget.destroy()

    def get_game_path(self) -> Optional[str]:
        return self._game_path

    def set_game_path(self, path: str) -> None:
        self._set_path(path)
