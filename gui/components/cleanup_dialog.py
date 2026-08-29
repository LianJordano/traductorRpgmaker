"""Modal window to inspect and delete stored translation checkpoints.

The checkpoint folder is what makes a re-extraction come back already
translated. When a game is reinstalled in the same folder that is a surprise,
not a feature, so it needs to be visible and removable per game — not only as
an all-or-nothing wipe.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
import tkinter.messagebox as mb

import customtkinter as ctk

from core import checkpoint, logger
from gui.styles import theme


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class CleanupDialog(ctk.CTkToplevel):
    """List every checkpoint with its size, and delete the ones picked."""

    def __init__(self, master):
        super().__init__(master)
        self.title("Limpiar traducciones ejecutadas")
        self.geometry("720x520")
        self.minsize(560, 400)
        self.configure(fg_color=theme.BG_PRIMARY)
        self._vars: list[tuple[ctk.BooleanVar, dict]] = []

        self._build()
        self._reload()

        # Modal, and centred on the window that opened it.
        self.transient(master)
        self.after(120, self._grab)
        self.update_idletasks()
        try:
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass

    def _grab(self) -> None:
        # grab_set before the window is mapped raises on some window managers.
        try:
            self.grab_set()
        except Exception:
            pass

    # -- Layout ---------------------------------------------------------------

    def _build(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 4))

        ctk.CTkLabel(header, text="Traducciones ejecutadas", font=theme.FONT_SUBTITLE,
                     text_color=theme.TEXT_PRIMARY, anchor="w").pack(anchor="w")
        self._total_lbl = ctk.CTkLabel(header, text="", font=theme.FONT_BODY,
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self._total_lbl.pack(anchor="w")
        ctk.CTkLabel(
            header,
            text=f"Carpeta: {checkpoint.CHECKPOINT_DIR}",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            anchor="w", justify="left", wraplength=660,
        ).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(
            header,
            text="Borrar el punto de control de un juego hace que su proximo analisis "
                 "empiece de cero. No toca los archivos del juego.",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
            anchor="w", justify="left", wraplength=660,
        ).pack(anchor="w", pady=(4, 0))

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.pack(fill="x", padx=14, pady=(8, 2))
        ctk.CTkButton(tools, text="Seleccionar todo", width=130, height=28,
                      font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
                      command=lambda: self._set_all(True)).pack(side="left")
        ctk.CTkButton(tools, text="Ninguno", width=90, height=28,
                      font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
                      command=lambda: self._set_all(False)).pack(side="left", padx=6)
        ctk.CTkButton(tools, text="Abrir carpeta", width=120, height=28,
                      font=theme.FONT_SMALL, fg_color=theme.BG_CARD,
                      command=self._open_folder).pack(side="right")

        self._list = ctk.CTkScrollableFrame(self, fg_color=theme.BG_SECONDARY)
        self._list.pack(fill="both", expand=True, padx=14, pady=8)

        # Filled by _reload when another install's folder still holds data.
        self._others = ctk.CTkFrame(self, fg_color="transparent")
        self._others.pack(fill="x", padx=14)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(actions, text="Cerrar", width=110, height=theme.BTN_H,
                      font=theme.FONT_BODY, fg_color=theme.BG_CARD,
                      command=self.destroy).pack(side="left")
        ctk.CTkButton(actions, text="Borrar TODO", width=140, height=theme.BTN_H,
                      font=theme.FONT_BODY, fg_color=theme.ERROR_COLOR,
                      command=self._delete_all).pack(side="right")
        self._del_btn = ctk.CTkButton(
            actions, text="Borrar seleccionadas", height=theme.BTN_H,
            font=theme.FONT_BODY, fg_color=theme.WARNING, text_color=theme.BG_PRIMARY,
            command=self._delete_selected,
        )
        self._del_btn.pack(side="right", padx=8)

    # -- Data -----------------------------------------------------------------

    def _reload(self) -> None:
        for child in self._list.winfo_children():
            child.destroy()
        self._vars.clear()

        records = checkpoint.entries()
        count, total = checkpoint.usage()
        self._total_lbl.configure(
            text=f"{count} juego(s) guardado(s) - {_fmt_size(total)} en disco "
                 f"- limite automatico {checkpoint.MAX_TOTAL_MB} MB"
        )
        self._reload_others()

        if not records:
            ctk.CTkLabel(self._list, text="La carpeta esta vacia. Nada que limpiar.",
                         font=theme.FONT_BODY, text_color=theme.TEXT_MUTED).pack(pady=24)
            return

        for rec in records:
            row = ctk.CTkFrame(self._list, fg_color=theme.BG_CARD, corner_radius=6)
            row.pack(fill="x", padx=4, pady=3)

            var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(row, variable=var, text="", width=26).pack(
                side="left", padx=(10, 4), pady=8)

            ctk.CTkLabel(row, text=_fmt_size(rec["size"]), font=theme.FONT_BODY,
                         text_color=theme.WARNING, width=80, anchor="e").pack(
                side="right", padx=12)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, pady=6)

            title = ctk.CTkFrame(info, fg_color="transparent")
            title.pack(anchor="w", fill="x")
            ctk.CTkLabel(title, text=rec["name"] or "(sin nombre)", font=theme.FONT_BODY,
                         text_color=theme.TEXT_PRIMARY, anchor="w",
                         justify="left").pack(side="left")
            if rec.get("protected"):
                ctk.CTkLabel(
                    title, text="  reciente - no se borra solo",
                    font=theme.FONT_SMALL, text_color=theme.SUCCESS, anchor="w",
                ).pack(side="left")

            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(rec["mtime"]))
            sub = rec["game_path"] or rec["path"].name
            ctk.CTkLabel(info, text=f"{when}   {sub}", font=theme.FONT_SMALL,
                         text_color=theme.TEXT_MUTED, anchor="w",
                         justify="left").pack(anchor="w", fill="x")

            self._vars.append((var, rec))

    def _reload_others(self) -> None:
        """Surface checkpoint folders belonging to another install of the app.

        Running from source and running the .exe keep separate folders. Cleaning
        only the active one would report 0 MB while the other still holds data.
        """
        for child in self._others.winfo_children():
            child.destroy()

        siblings = checkpoint.sibling_dirs()
        if not siblings:
            return

        ctk.CTkLabel(
            self._others,
            text="Otras carpetas con traducciones guardadas "
                 "(otra instalacion del programa):",
            font=theme.FONT_SMALL, text_color=theme.WARNING, anchor="w",
        ).pack(anchor="w", pady=(2, 4))

        for directory in siblings:
            n, size = checkpoint.dir_usage(directory)
            row = ctk.CTkFrame(self._others, fg_color=theme.BG_SECONDARY, corner_radius=6)
            row.pack(fill="x", pady=2)
            ctk.CTkButton(
                row, text=f"Borrar ({_fmt_size(size)})", width=130, height=28,
                font=theme.FONT_SMALL, fg_color=theme.ERROR_COLOR,
                command=lambda d=directory: self._delete_other(d),
            ).pack(side="right", padx=8, pady=6)
            ctk.CTkLabel(
                row, text=f"{n} juego(s)   {directory}", font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED, anchor="w", justify="left",
            ).pack(side="left", padx=10, fill="x", expand=True)

    def _delete_other(self, directory) -> None:
        n, size = checkpoint.dir_usage(directory)
        if not mb.askyesno(
            "Confirmar",
            f"Se borraran {n} punto(s) de control ({_fmt_size(size)}) de:\n\n{directory}\n\n"
            "Es la carpeta de otra instalacion del programa. Esos juegos volveran a "
            "traducirse desde cero alli.\n\nContinuar?",
            parent=self,
        ):
            return
        freed = checkpoint.clear_dir(directory)
        logger.success(f"{directory} vaciada - {_fmt_size(freed)} liberados.")
        self._reload()

    def _set_all(self, value: bool) -> None:
        for var, _ in self._vars:
            var.set(value)

    def _open_folder(self) -> None:
        path = str(checkpoint.CHECKPOINT_DIR)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            logger.warning(f"No se pudo abrir la carpeta: {exc}")

    # -- Actions --------------------------------------------------------------

    def _delete_selected(self) -> None:
        picked = [rec for var, rec in self._vars if var.get()]
        if not picked:
            mb.showinfo("Nada seleccionado",
                        "Marca al menos un juego de la lista.", parent=self)
            return
        total = sum(r["size"] for r in picked)
        shown = "\n".join("  - " + r["name"] for r in picked[:12])
        if len(picked) > 12:
            shown += f"\n  ... y {len(picked) - 12} mas"
        if not mb.askyesno(
            "Confirmar",
            f"Se borraran {len(picked)} punto(s) de control ({_fmt_size(total)}):\n\n"
            f"{shown}\n\nEsos juegos volveran a traducirse desde cero.\n\nContinuar?",
            parent=self,
        ):
            return
        freed = sum(checkpoint.delete_file(r["path"]) for r in picked)
        logger.success(
            f"{len(picked)} punto(s) de control borrado(s) - {_fmt_size(freed)} liberados."
        )
        self._reload()

    def _delete_all(self) -> None:
        count, total = checkpoint.usage()
        if not count:
            mb.showinfo("Vacio", "No hay nada que borrar.", parent=self)
            return
        if not mb.askyesno(
            "Confirmar",
            f"Se borraran los {count} punto(s) de control ({_fmt_size(total)}).\n\n"
            "Todos los juegos volveran a traducirse desde cero.\n\nContinuar?",
            parent=self,
        ):
            return
        freed = checkpoint.clear()
        logger.success(f"Carpeta vaciada - {_fmt_size(freed)} liberados.")
        self._reload()
