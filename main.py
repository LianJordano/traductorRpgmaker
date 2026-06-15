"""RPG Translator Pro – entry point."""
import sys
import os

# Ensure project root is in path when running as a script
sys.path.insert(0, os.path.dirname(__file__))

from gui.styles import theme
theme.apply()

from gui.main_window import MainWindow

def main() -> None:
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
