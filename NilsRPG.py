from __future__ import annotations

"""Thin Tk based UI for the Nils RPG demo."""

import tkinter as tk
from pathlib import Path

from config import AppConfig, load_config, save_config
from services.narrative import build_prompt, finalize_to_model
from services.audio import Narrator
from services.images import PictureService
from storage.saves import load_state, save_state
from state import GameState


class RPGGame:
    """Main application window.  Handles widgets and delegates logic."""

    def __init__(self, root: tk.Tk, config: AppConfig | None = None) -> None:
        self.root = root
        self.config = config or AppConfig()
        self.state = GameState()

        self.narrator = Narrator()
        self.images = PictureService()

        self.text = tk.Text(root, height=20, width=60)
        self.text.pack()
        self.entry = tk.Entry(root)
        self.entry.pack(fill=tk.X)
        self.entry.bind("<Return>", self.on_command)

    # UI callbacks ---------------------------------------------------------
    def on_command(self, event: tk.Event | None = None) -> None:
        command = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if not command:
            return

        prompt = build_prompt(self.state, False) + "\n" + command
        self.text.insert(tk.END, f"> {command}\n{prompt}\n")

    # Persistence ---------------------------------------------------------
    def save(self, path: str | Path) -> None:
        save_state(path, self.state)

    def load(self, path: str | Path) -> None:
        self.state = load_state(path)


def main() -> None:
    root = tk.Tk()
    app = RPGGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
