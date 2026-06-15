"""Progress bar + ETA + stats row shown at the bottom of the main window."""
from __future__ import annotations
import time
import customtkinter as ctk
from gui.styles import theme


class ProgressPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", theme.BG_SECONDARY)
        super().__init__(master, **kwargs)
        self._start_time: float = 0.0
        self._last_current: int = 0
        self._last_total: int = 0
        self._build()
        self.reset()

    def _build(self) -> None:
        # ── Row 1: status label + percentage ──────────────────────────────────
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", padx=10, pady=(6, 1))

        self._status_lbl = ctk.CTkLabel(
            row1, text="Listo", font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY, anchor="w",
        )
        self._status_lbl.pack(side="left")

        self._eta_lbl = ctk.CTkLabel(
            row1, text="", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="center",
        )
        self._eta_lbl.pack(side="left", padx=12)

        self._pct_lbl = ctk.CTkLabel(
            row1, text="0%", font=("Segoe UI", 13, "bold"),
            text_color=theme.ACCENT, anchor="e",
        )
        self._pct_lbl.pack(side="right")

        # ── Progress bar ──────────────────────────────────────────────────────
        self._bar = ctk.CTkProgressBar(
            self,
            height=theme.PROGRESS_H,
            progress_color=theme.ACCENT,
            fg_color=theme.BG_CARD,
        )
        self._bar.pack(fill="x", padx=10, pady=2)

        # ── Row 2: counters + current file ────────────────────────────────────
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=10, pady=(1, 6))

        self._stats_lbl = ctk.CTkLabel(
            row2, text="", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="w",
        )
        self._stats_lbl.pack(side="left")

        self._file_lbl = ctk.CTkLabel(
            row2, text="", font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED, anchor="e",
        )
        self._file_lbl.pack(side="right")

    # ── Public API ────────────────────────────────────────────────────────────

    def start_timer(self) -> None:
        self._start_time = time.monotonic()
        self._last_current = 0

    def update_progress(self, current: int, total: int, file: str = "") -> None:
        if total <= 0:
            return
        pct = min(current / total, 1.0)
        self._bar.set(pct)
        self._pct_lbl.configure(text=f"{pct * 100:.0f}%")
        self._last_current = current
        self._last_total = total

        if file:
            # Truncate long file names in the middle
            display = file if len(file) <= 30 else f"{file[:14]}…{file[-14:]}"
            self._file_lbl.configure(text=f"  {display}")

        self._stats_lbl.configure(text=f"{current:,} / {total:,} textos")
        self._update_eta(current, total)

    def _update_eta(self, current: int, total: int) -> None:
        if current <= 0 or not self._start_time:
            self._eta_lbl.configure(text="")
            return
        elapsed = time.monotonic() - self._start_time
        rate = current / elapsed  # items per second
        remaining = total - current
        if rate > 0 and remaining > 0:
            eta_sec = remaining / rate
            self._eta_lbl.configure(
                text=f"Restante: {_fmt_time(eta_sec)}  •  {rate:.1f}/s"
            )
        else:
            self._eta_lbl.configure(text="")

    def set_status(self, text: str, color: str = "") -> None:
        self._status_lbl.configure(
            text=text, text_color=color or theme.TEXT_PRIMARY
        )

    def set_stats_text(self, text: str) -> None:
        self._stats_lbl.configure(text=text)

    def set_extra_stats(self, **kwargs) -> None:
        parts = [f"{k}: {v:,}" if isinstance(v, int) else f"{k}: {v}"
                 for k, v in kwargs.items()]
        self._stats_lbl.configure(text="   ".join(parts))

    def reset(self) -> None:
        self._bar.set(0)
        self._bar.configure(mode="determinate")
        self._pct_lbl.configure(text="0%")
        self._status_lbl.configure(text="Listo", text_color=theme.TEXT_PRIMARY)
        self._stats_lbl.configure(text="")
        self._file_lbl.configure(text="")
        self._eta_lbl.configure(text="")
        self._start_time = 0.0

    def set_indeterminate(self, running: bool) -> None:
        if running:
            self._bar.configure(mode="indeterminate")
            self._bar.start()
        else:
            self._bar.stop()
            self._bar.configure(mode="determinate")
            self._bar.set(0)

    def mark_complete(self, elapsed: float = 0.0) -> None:
        self._bar.set(1.0)
        self._pct_lbl.configure(text="100%")
        if elapsed > 0:
            self._eta_lbl.configure(
                text=f"Completado en {_fmt_time(elapsed)}", text_color=theme.SUCCESS
            )
        else:
            self._eta_lbl.configure(text="Completado", text_color=theme.SUCCESS)


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    elif s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    else:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m:02d}m"
