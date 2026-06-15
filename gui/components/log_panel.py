"""Scrollable log panel with color-coded levels."""
from __future__ import annotations
import customtkinter as ctk
from gui.styles import theme


class LogPanel(ctk.CTkFrame):
    MAX_LINES = 2000

    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", theme.BG_SECONDARY)
        super().__init__(master, **kwargs)
        self._build()

    def _build(self) -> None:
        header = ctk.CTkLabel(
            self, text="  Registro de Actividad", font=theme.FONT_SUBTITLE,
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        header.pack(fill="x", padx=8, pady=(6, 2))

        self._text = ctk.CTkTextbox(
            self,
            font=theme.FONT_MONO,
            fg_color=theme.BG_PRIMARY,
            text_color=theme.TEXT_PRIMARY,
            wrap="word",
            state="disabled",
        )
        self._text.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Tag colors for log levels
        self._text._textbox.tag_configure("INFO",    foreground=theme.LOG_COLORS["INFO"])
        self._text._textbox.tag_configure("SUCCESS", foreground=theme.LOG_COLORS["SUCCESS"])
        self._text._textbox.tag_configure("WARNING", foreground=theme.LOG_COLORS["WARNING"])
        self._text._textbox.tag_configure("ERROR",   foreground=theme.LOG_COLORS["ERROR"])
        self._text._textbox.tag_configure("DEBUG",   foreground=theme.LOG_COLORS["DEBUG"])

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=6, pady=(0, 4))
        ctk.CTkButton(
            btn_frame, text="Limpiar", width=90, height=26,
            font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
            command=self.clear,
        ).pack(side="right")

    def append(self, level: str, msg: str) -> None:
        """Append a log line. Thread-safe via after()."""
        self._text._textbox.configure(state="normal")
        tag = level.upper()
        prefix = f"[{tag}] "
        self._text._textbox.insert("end", prefix + msg + "\n", tag)

        # Trim if too long
        lines = int(self._text._textbox.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self._text._textbox.delete("1.0", f"{lines - self.MAX_LINES}.0")

        self._text._textbox.configure(state="disabled")
        self._text._textbox.see("end")

    def clear(self) -> None:
        self._text._textbox.configure(state="normal")
        self._text._textbox.delete("1.0", "end")
        self._text._textbox.configure(state="disabled")
