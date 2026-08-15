"""Settings tab: translator selector, language pair, API keys, export format."""
from __future__ import annotations
import customtkinter as ctk
from gui.styles import theme
from core import config

TRANSLATORS = ["google", "deepl", "openai", "manual"]
LANGUAGES = {
    "Japanese (ja)": "ja",
    "English (en)": "en",
    "Spanish (es)": "es",
    "French (fr)": "fr",
    "German (de)": "de",
    "Portuguese (pt)": "pt",
    "Korean (ko)": "ko",
    "Chinese Simplified (zh)": "zh",
    "Russian (ru)": "ru",
}
EXPORT_FORMATS = ["csv", "json", "excel"]


class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("fg_color", theme.BG_PRIMARY)
        super().__init__(master, **kwargs)
        self._build()
        self._load()

    def _section(self, title: str) -> None:
        ctk.CTkLabel(
            self, text=title, font=theme.FONT_SUBTITLE,
            text_color=theme.ACCENT, anchor="w",
        ).pack(fill="x", padx=6, pady=(16, 4))

    def _row(self, label: str, widget_builder) -> ctk.CTkBaseClass:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(
            frame, text=label, font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY, width=180, anchor="w",
        ).pack(side="left")
        w = widget_builder(frame)
        w.pack(side="right", fill="x", expand=True)
        return w

    def _build(self) -> None:
        # --- Translation ---
        self._section("Traducción")

        self._translator_var = ctk.StringVar(value="google")
        self._translator_cb = self._row(
            "Motor de traducción",
            lambda f: ctk.CTkComboBox(
                f, values=TRANSLATORS, variable=self._translator_var,
                font=theme.FONT_BODY, fg_color=theme.BG_CARD,
                command=self._on_translator_change,
            ),
        )

        lang_keys = list(LANGUAGES.keys())
        self._src_var = ctk.StringVar()
        self._src_cb = self._row(
            "Idioma de origen",
            lambda f: ctk.CTkComboBox(
                f, values=lang_keys, variable=self._src_var, font=theme.FONT_BODY,
                fg_color=theme.BG_CARD,
            ),
        )

        self._tgt_var = ctk.StringVar()
        self._tgt_cb = self._row(
            "Idioma de destino",
            lambda f: ctk.CTkComboBox(
                f, values=lang_keys, variable=self._tgt_var, font=theme.FONT_BODY,
                fg_color=theme.BG_CARD,
            ),
        )

        # --- API Keys ---
        self._section("Claves API")

        self._openai_key = self._row(
            "Clave API OpenAI",
            lambda f: ctk.CTkEntry(f, show="*", font=theme.FONT_BODY,
                                   fg_color=theme.BG_CARD,
                                   placeholder_text="sk-..."),
        )
        self._deepl_key = self._row(
            "Clave API DeepL",
            lambda f: ctk.CTkEntry(f, show="*", font=theme.FONT_BODY,
                                   fg_color=theme.BG_CARD,
                                   placeholder_text="xxx:fx"),
        )
        self._openai_model_var = ctk.StringVar(value="gpt-4o-mini")
        self._row(
            "Modelo OpenAI",
            lambda f: ctk.CTkComboBox(
                f, values=["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
                variable=self._openai_model_var, font=theme.FONT_BODY,
                fg_color=theme.BG_CARD,
            ),
        )

        # --- Text layout ---
        self._section("Texto en el juego")

        self._wrap_var = ctk.BooleanVar(value=True)
        wrap_frame = ctk.CTkFrame(self, fg_color="transparent")
        wrap_frame.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(wrap_frame, text="Ajustar líneas al cuadro de mensaje",
                     font=theme.FONT_BODY, text_color=theme.TEXT_PRIMARY,
                     width=250, anchor="w").pack(side="left")
        ctk.CTkSwitch(wrap_frame, variable=self._wrap_var, text="",
                      onvalue=True, offvalue=False).pack(side="right")

        self._lines_var = ctk.IntVar(value=4)
        self._row(
            "Líneas por mensaje",
            lambda f: ctk.CTkSlider(f, from_=1, to=8, variable=self._lines_var,
                                    number_of_steps=7),
        )

        self._notes_var = ctk.BooleanVar(value=False)
        notes_frame = ctk.CTkFrame(self, fg_color="transparent")
        notes_frame.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(notes_frame, text="Traducir notas (rompe plugins)",
                     font=theme.FONT_BODY, text_color=theme.TEXT_PRIMARY,
                     width=250, anchor="w").pack(side="left")
        ctk.CTkSwitch(notes_frame, variable=self._notes_var, text="",
                      onvalue=True, offvalue=False).pack(side="right")

        # --- Export ---
        self._section("Exportación")

        self._export_var = ctk.StringVar(value="csv")
        self._row(
            "Formato de exportación",
            lambda f: ctk.CTkComboBox(
                f, values=EXPORT_FORMATS, variable=self._export_var,
                font=theme.FONT_BODY, fg_color=theme.BG_CARD,
            ),
        )

        # --- Safety ---
        self._section("Seguridad y Rendimiento")

        self._backup_var = ctk.BooleanVar(value=True)
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(frame, text="Backup automático al modificar", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=200, anchor="w").pack(side="left")
        ctk.CTkSwitch(frame, variable=self._backup_var, text="", onvalue=True,
                      offvalue=False).pack(side="right")

        self._checkpoint_var = ctk.BooleanVar(value=True)
        frame2 = ctk.CTkFrame(self, fg_color="transparent")
        frame2.pack(fill="x", padx=6, pady=3)
        ctk.CTkLabel(frame2, text="Guardar puntos de control", font=theme.FONT_BODY,
                     text_color=theme.TEXT_PRIMARY, width=200, anchor="w").pack(side="left")
        ctk.CTkSwitch(frame2, variable=self._checkpoint_var, text="", onvalue=True,
                      offvalue=False).pack(side="right")

        self._delay_var = ctk.IntVar(value=200)
        self._row(
            "Retraso entre solicitudes (ms)",
            lambda f: ctk.CTkSlider(f, from_=0, to=2000, variable=self._delay_var,
                                    number_of_steps=20),
        )

        self._workers_var = ctk.IntVar(value=8)
        self._row(
            "Hilos en paralelo (traducción)",
            lambda f: ctk.CTkSlider(f, from_=1, to=32, variable=self._workers_var,
                                    number_of_steps=31),
        )

        # Save button
        ctk.CTkButton(
            self, text="Guardar Configuración", height=theme.BTN_H,
            font=theme.FONT_BODY, fg_color=theme.SUCCESS,
            command=self.save,
        ).pack(fill="x", padx=6, pady=16)

    def _on_translator_change(self, _=None) -> None:
        pass

    def _load(self) -> None:
        self._translator_var.set(config.get("translator", "google"))
        src = config.get("language_from", "en")
        tgt = config.get("language_to", "es")
        self._src_var.set(self._lang_label(src))
        self._tgt_var.set(self._lang_label(tgt))
        self._openai_key.delete(0, "end")
        self._openai_key.insert(0, config.get("openai_api_key", ""))
        self._deepl_key.delete(0, "end")
        self._deepl_key.insert(0, config.get("deepl_api_key", ""))
        self._openai_model_var.set(config.get("openai_model", "gpt-4o-mini"))
        self._export_var.set(config.get("export_format", "csv"))
        self._backup_var.set(config.get("backup_enabled", True))
        self._checkpoint_var.set(config.get("checkpoint_enabled", True))
        self._delay_var.set(config.get("delay_ms", 200))
        self._workers_var.set(config.get("max_workers", 8))
        self._wrap_var.set(config.get("wrap_text", True))
        self._lines_var.set(config.get("max_message_lines", 4))
        self._notes_var.set(config.get("translate_notes", False))

    def _lang_label(self, code: str) -> str:
        for label, c in LANGUAGES.items():
            if c == code:
                return label
        return "English (en)"

    def save(self) -> None:
        src_label = self._src_var.get()
        tgt_label = self._tgt_var.get()
        config.update({
            "translator": self._translator_var.get(),
            "language_from": LANGUAGES.get(src_label, "en"),
            "language_to": LANGUAGES.get(tgt_label, "es"),
            "openai_api_key": self._openai_key.get(),
            "deepl_api_key": self._deepl_key.get(),
            "openai_model": self._openai_model_var.get(),
            "export_format": self._export_var.get(),
            "backup_enabled": self._backup_var.get(),
            "checkpoint_enabled": self._checkpoint_var.get(),
            "delay_ms": self._delay_var.get(),
            "max_workers": self._workers_var.get(),
            "wrap_text": self._wrap_var.get(),
            "max_message_lines": self._lines_var.get(),
            "translate_notes": self._notes_var.get(),
        })
        from core import logger
        logger.success("Configuración guardada.")
