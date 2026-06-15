"""Color palette and widget style constants for RPG Translator Pro."""
import customtkinter as ctk

# App appearance
APPEARANCE = "dark"
COLOR_THEME = "blue"

# Colors
BG_PRIMARY    = "#1a1a2e"
BG_SECONDARY  = "#16213e"
BG_CARD       = "#0f3460"
ACCENT        = "#4a9eff"
ACCENT_HOVER  = "#2980d9"
SUCCESS       = "#2ecc71"
WARNING       = "#f39c12"
ERROR_COLOR   = "#e74c3c"
TEXT_PRIMARY  = "#ffffff"
TEXT_MUTED    = "#8a9bb5"
BORDER        = "#2d4a6e"

# Font sizes
FONT_TITLE    = ("Segoe UI", 22, "bold")
FONT_SUBTITLE = ("Segoe UI", 14, "bold")
FONT_BODY     = ("Segoe UI", 12)
FONT_SMALL    = ("Segoe UI", 10)
FONT_MONO     = ("Consolas", 11)
FONT_LOGO     = ("Segoe UI", 18, "bold")

# Widget sizing
BTN_H         = 38
SIDEBAR_W     = 280
LOG_H         = 180
PROGRESS_H    = 8

LOG_COLORS = {
    "INFO":    "#a0c4ff",
    "SUCCESS": "#90ee90",
    "WARNING": "#ffd700",
    "ERROR":   "#ff6b6b",
    "DEBUG":   "#888888",
}


def apply() -> None:
    ctk.set_appearance_mode(APPEARANCE)
    ctk.set_default_color_theme(COLOR_THEME)


def log_color(level: str) -> str:
    return LOG_COLORS.get(level.upper(), TEXT_PRIMARY)
