import importlib
import os
import tempfile
import tkinter as tk
import unittest

from services.narrative import build_prompt
from state import GameState
from storage.saves import load_state, save_state


class ServiceTests(unittest.TestCase):
    def test_build_prompt(self) -> None:
        state = GameState(day=1, time="dawn", inventory=["sword"])
        initial = build_prompt(state, initial=True)
        self.assertIn("day 1", initial)
        follow = build_prompt(state)
        self.assertIn("Inventory", follow)

    def test_json_round_trip(self) -> None:
        state = GameState(day=2, time="noon", inventory=["torch"], history=["start"])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "save.json")
            save_state(path, state)
            loaded = load_state(path)
        self.assertEqual(state, loaded)

    def test_import_does_not_start_tk(self) -> None:
        if tk._default_root is not None:
            tk._default_root.destroy()
            tk._default_root = None
        importlib.invalidate_caches()
        mod = importlib.import_module("NilsRPG")
        importlib.reload(mod)
        self.assertIsNone(tk._default_root)
