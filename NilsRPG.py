"""Main application module for Nils' RPG.

This script stitches together the Tkinter front end with Google Gemini
services to generate narrative text, images and speech for a dynamic
role‑playing experience.
"""

import glob
import json
import os
import os.path
import pickle
import re
import sys
import threading
import time
import uuid
import asyncio
import tkinter as tk
from pathlib import Path
from io import BytesIO
from tkinter import ttk, messagebox, font as tkfont

import importlib.resources as pkg_resources
from PIL import Image, ImageTk
from google import genai
from google.genai import types, errors
from ttkbootstrap import Style

import numpy as np
try:
    import sounddevice as sd
    HAVE_SD = True
except Exception:  # pragma: no cover - missing sounddevice
    HAVE_SD = False

from models import Attributes, Environment, GameResponse, InventoryItem, PerkSkill
from utils import (
    clean_unicode,
    load_embedded_fonts,
    set_user_env_var,
    get_user_env_var,
    get_response_tokens,
)

IMAGE_GENERATION_ENABLED = False
SOUND_ENABLED = True
DEBUG_TTS = os.environ.get("RPG_DEBUG_TTS") == "1"

# --- Model configuration -------------------------------------------------
# These constants declare which Gemini model powers each content stream.
MODEL = "gemini-2.5-flash"  # Primary text model powering narrative responses.
#AUDIO_MODEL = "gemini-2.5-pro-preview-tts"
AUDIO_MODEL = "gemini-2.5-flash-preview-native-audio-dialog"  # Native audio dialog model for narration.
AUDIO_VOICE = "Algenib"  # Default voice used for narration.
#IMAGE_MODEL = "imagen-4.0-generate-001"  # Baseline image generation model.
#IMAGE_MODEL = "imagen-4.0-ultra-generate-001"  # High quality image model.
IMAGE_MODEL = "imagen-4.0-fast-generate-001"  # Fast default image model.

# --- Model pricing -------------------------------------------------------
# Pricing data is loaded from an external JSON file to allow easy updates
# when Google adjusts model rates.
COST_FILE = Path(__file__).with_name("model_costs.json")
try:
    with COST_FILE.open("r", encoding="utf-8") as f:
        MODEL_COSTS = json.load(f)
except FileNotFoundError:  # pragma: no cover - file should exist in repo
    MODEL_COSTS = {}

# --- Attribute explanations ---
# These explanations supply tooltip text for the GUI and provide players with
# context about what each attribute represents within the game.
ATTRIBUTE_EXPLANATIONS = {
    "Name": "The character's chosen or given name; used for narrative reference and identification.",
    "Background": "A concise summary of upbringing, training, or profession that anchors starting skills and worldview.",
    "Age": "Number of lived or apparent years; shapes physical capability, maturity, and social perception.",
    "Health": "Current state of physical well-being; when it reaches zero the character dies. Death is the end; or not.",
    "Sanity": "Mental stability and resilience; low sanity triggers irrational behaviour, fear, or hallucinations.",
    "Hunger": "Level of nourishment; starvation steadily degrades Stamina, Health and Sanity until food is consumed.",
    "Thirst": "Level of hydration; dehydration progressively impairs Stamina, Health, and Sanity until water is consumed.",
    "Stamina": "Reserve of physical energy for actions such as running or fighting; exhaustion lowers overall Health.",
    "Light": "Current illumination level; deep darkness erodes Sanity, while a steady light can restore it.",
    "Location": "Immediate geographical setting—village, wilderness, or landmark—providing environmental context and local influences.",
    "Daytime": "Current phase of the day (dawn, day, dusk, or night); governs ambient light, activity cycles, and potential encounters.",
    "Temperature": "Perceived ambient heat or cold; extremes burn or freeze the body, harming Health and Stamina.",
    "Humidity": "Moisture in the air; high humidity magnifies heat stress, while low humidity accelerates dehydration.",
    "Wind": "Air movement that modifies Temperature and Humidity effects and can hinder ranged or delicate tasks.",
    "Soundscape": "Ambient sounds from nature or activity; shapes awareness, mood, and stealth dynamics."
}

# Load embedded fonts once on startup to ensure consistent presentation across
# platforms.
load_embedded_fonts()

# --- Parse STYLE & DIFFICULTY sections from world.txt ---
# Reads the optional world configuration file and returns dictionaries of the
# available styles and difficulty modes.
def _parse_world():
    """Return two dicts: {style_title: full_section}, {difficulty_title: full_section}."""
    styles, diffs = {}, {}
    # 1) Try user-provided world.txt next to the executable
    try:
        with open("world.txt", "r", encoding="utf-8") as f:
            raw = f.read()
    except FileNotFoundError:
        # 2) Fallback to embedded world.txt in assets/
        try:
            raw = pkg_resources.read_text("assets", "world.txt")
        except (FileNotFoundError, ModuleNotFoundError):
            return styles, diffs

    # Split on lines beginning with '##'
    parts = re.split(r'(?m)^##\s*', raw)
    for part in parts:
        if not part.strip():
            continue
        header, *body = part.splitlines()
        header = header.strip()        
        m = re.match(r'(STYLE|DIFFICULTY):\s*(.+)', header)
        if not m:
            continue
        kind, title = m.group(1), m.group(2).strip()
        content = "## " + header + "\n" + "\n".join(body).strip() + "\n"        
        if kind == "STYLE":
            styles[title] = content
        else:
            diffs[title] = content
    return styles, diffs

# Load all available styles & difficulties once
_STYLES, _DIFFICULTIES = _parse_world()

# Global prompt prefix from chosen style & difficulty
world_text = ""

# --- Gemini client setup ---
# Defer client creation; we'll (re)create it when starting the game.
client = None
_client_key = None


def _resolve_api_key() -> str:
    """Return the best available Gemini API key.

    This first checks ``os.environ`` then falls back to the user's global
    environment via :func:`get_user_env_var`. If a key is found it is written
    back into ``os.environ`` so downstream code can rely on it.
    """
    key = (
        os.environ.get("GEMINI_API_KEY")
        or get_user_env_var("GEMINI_API_KEY")
        or ""
    ).strip()
    if key:
        os.environ["GEMINI_API_KEY"] = key  # ensure downstream code sees it
    return key


def _ensure_client() -> genai.Client | None:
    """Return a Gemini client for the current environment key.

    This lazily (re)creates the global ``client`` if the key has been set or
    changed since the last call.
    """
    global client, _client_key
    key = _resolve_api_key()
    if not key:
        client = None
        _client_key = None
        return None
    if client is None or key != _client_key:
        client = genai.Client(api_key=key)
        _client_key = key
    return client

# --- Main RPG application ---
class RPGGame:
    """Tkinter-based RPG application powered by Google's Gemini models."""
    def __init__(self, root: tk.Tk):
        """Configure widgets, fonts and initial game state."""
        # unique ID for this character (initialized on first identity choice)
        self.character_id = None

        # record chosen world style & difficulty
        self.style_choice = None
        self.diff_choice  = None        

        # guard flag to prevent double‐submit
        self._is_submitting = False        

        # — Metrics for tokens & images —
        self.last_prompt_tokens = 0
        self.total_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.total_completion_tokens = 0
        # Narration token tracking (text-to-speech)
        self.total_audio_prompt_tokens = 0
        self.total_audio_output_tokens = 0
        self.total_images = 0

        # Track the last image prompt for consistency
        self.previous_image_prompt = None
        self._loading = False

        # Audio streaming state
        self._audio_stream = None
        self._audio_stream_lock = threading.Lock()

        # Narration tracking
        self._debug_t_text_done = None
        self._tts_warmed = False
        self._debug_logged_once = False

        # Directory for saving every generated image
        self.image_save_dir = os.path.join(
            os.getenv("APPDATA", os.path.expanduser("~")),
            "Nils' RPG",
            "generated_images"
        )        

        # Bind ESC to open the modal menu pane
        root.bind('<Escape>', self._handle_global_escape)

        # Auto-save on window close
        root.protocol("WM_DELETE_WINDOW",
                      lambda: (self._save_game(), root.destroy()))        

        # Timing tracking
        self.last_api_duration = 10.0 
        self.last_image_duration = 7.0

        self._image_generation_cancel = threading.Event()
        self._perk_win = None
        self._perk_click_binding = None
        self._item_win = None
        self._item_click_binding = None

        # Override default font aliases: use Cardo for body and Cormorant Garamond for headings
        body_serif   = tkfont.Font(family="Cardo", size=12)
        header_serif = tkfont.Font(family="Cormorant Garamond", size=14)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkFixedFont"):
            tkfont.nametofont(name).configure(
                family=body_serif.cget("family"), size=12
            )
        tkfont.nametofont("TkHeadingFont").configure(
            family=header_serif.cget("family"), size=14
        )

        self.root = root
        root.title("Nils' RPG")
        root.state("zoomed")  

        # --- Dark-mode “medieval” theme setup ---
        style = Style(theme="darkly")
        style.configure(
            ".", background="#1F1F1F", foreground="#F5F0E1",
            font=body_serif
        )
        style.configure(
            "Heading.TLabel",
            font=header_serif, foreground="#F5F0E1"
        )
        style.configure(
            "TLabelframe", background="#1F1F1F",
            bordercolor="#AD863E"
        )
        style.configure(
            "TLabelframe.Label",
            font=header_serif, foreground="#F5F0E1"
        )
        style.configure(
            "RPG.TButton",
            font=header_serif,
            background="#AD863E", foreground="#1F1F1F",
            borderwidth=0
        )
        style.configure(
            "TRadiobutton",
            background="#1F1F1F", font=body_serif,
            foreground="#F5F0E1"
        )
        style.configure("Change.TLabel", foreground="#A0B023")

        root.configure(background="#1F1F1F")

        # -- Progress-bar styles for thinking (blue) vs. image (red) phases --
        style.configure(
            "Thinking.Horizontal.TProgressbar",
            background="#007bff"
        )
        style.configure(
            "Image.Horizontal.TProgressbar",
            background="#dc3545"
        )

        # Initialize game state
        self.turn = 1            # GM’s turn counter
        self.day = 0             # starts at day 0
        self.time = ""           # HH:MM, will be set by GM’s response
        self.style_choice = None
        self.diff_choice  = None        
        self.attributes = {}
        self.environment = {}
        self.inventory = []
        self.perks_skills = []
        self.current_situation = ""
        self.options = []
        self.past_situations = []
        self.past_options = []
        self.past_days       = []
        self.past_times      = []

        # Build UI; defer starting a new game until the menu is used
        self._build_gui()

    def _append_choice_and_blank(self):
        """Insert the last chosen option plus an empty line, before streaming the new situation."""
        self.situation_text.config(state='normal')
        last_choice = self.past_options[-1]
        self.situation_text.insert(tk.END, f"\nChosen Option: {last_choice}\n\n")
        self.situation_text.see(tk.END)
        self.situation_text.config(state='disabled')        

    def _ask_identity(self):
        """Prompt once at startup: 'Who are you?' with custom entry."""
        win = tk.Toplevel(self.root)
        # Make this dialog modal and transient, then raise it
        win.transient(self.root)
        win.grab_set()
        win.lift()
        win.title("Who are you?")

        # Variables & widgets
        identity_var = tk.StringVar()
        custom_entry = ttk.Entry(win)

        def on_submit():
            """Commit the chosen identity and start the game."""
            # 1) grab the choice
            choice = custom_entry.get().strip() or identity_var.get()
            if not choice:
                return

            # 2) record it
            self.identity     = choice
            self.character_id = str(uuid.uuid4())

            # 3) tear down the dialog and start the game
            win.grab_release()
            win.destroy()
            self._start_game()

        submit_btn = ttk.Button(win, text="Submit", command=on_submit, style="RPG.TButton")

        def populate_options(options: list[str]):
            """Fill the dialog with preset identity options."""
            ttk.Label(win, text="Who are you?", anchor="center").pack(
                fill=tk.X,
                padx=20,
                pady=(20, 0)
            )            
            combobox = ttk.Combobox(
                win,
                textvariable=identity_var,
                values=options,
                state="readonly"
            )
            combobox.current(0)
            combobox.pack(fill=tk.X, padx=20, pady=(0,10))
            ttk.Label(
                win,
                text="Or enter your own:",
                font=tkfont.Font(size=12, slant="italic")
            ).pack(padx=20, pady=(10,0))
            custom_entry.pack(fill=tk.X, padx=20, pady=(0,10))
            submit_btn.pack(pady=(0,20))

            # Give focus to the identity dropdown
            combobox.focus_set()            

        default_identities = [
            "Hephaest: An experienced fire sorcerer at the entrance of a dungeon, looking for knowledge and power.",
            "Arin the Swift: A nimble halfling rogue with quick wit.",
            "Lyra Stormcall: A fierce human sorceress channeling storm magic.",
            "Thorin Ironfist: A stalwart dwarven warrior with unbreakable resolve.",
            "Selene Moonshadow: A mysterious elven ranger guided by the stars.",
            "Morgor the Scribe: A scholarly goblin alchemist obsessed with arcane lore."
        ]

        populate_options(default_identities)

        # Center the dialog at 60% of screen width and fixed height 380
        win.update_idletasks()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        final_w = int(screen_w * 0.6)
        final_h = 400
        x = (screen_w - final_w) // 2
        y = (screen_h - final_h) // 2
        win.geometry(f"{final_w}x{final_h}+{x}+{y}")

        # Allow ESC to cancel identity selection: release grab, destroy dialog, reopen menu
        def _on_escape(event=None):
            """Cancel identity selection and return to the menu."""
            win.grab_release()
            win.destroy()
            self._open_menu()
        win.bind("<Escape>", _on_escape)

    def _build_gui(self):
        """Assemble all widgets composing the main game interface."""
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        self.left_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(self.left_pane, weight=1)
        self.right_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(self.right_pane, weight=3)

        # Character stats
        attr_frame = ttk.LabelFrame(self.left_pane, text="Character")
        self.left_pane.add(attr_frame, weight=0)
        self._attr_widgets = {}
        char_stats = [
            "Name", "Background", "Age", "Health", "Sanity", "Hunger", "Thirst", "Stamina"
        ]
        for attr in char_stats:
            # container for each row
            row = ttk.Frame(attr_frame)
            row.pack(anchor="w", fill=tk.X, pady=1)

            # main value label
            main_var = tk.StringVar()
            main_lbl = ttk.Label(row, textvariable=main_var)
            main_lbl.pack(side=tk.LEFT)

            # attach tooltip with the general explanation
            explanation = ATTRIBUTE_EXPLANATIONS.get(attr, "")
            self._create_text_tooltip(main_lbl, explanation)

            # change/diff label (unused initially, but reserved for diffs)
            change_var = tk.StringVar()
            change_lbl = ttk.Label(row, textvariable=change_var)
            change_lbl.pack(side=tk.LEFT, padx=(4, 0))

            # store the four widgets so we can update & diff later
            self._attr_widgets[attr] = (main_var, change_var, main_lbl, change_lbl)

            #add separator
            if attr == "Age":
                ttk.Separator(attr_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
 
        # Environment stats
        env_frame = ttk.LabelFrame(self.left_pane, text="Environment")
        self.left_pane.add(env_frame, weight=0)
        self._env_widgets = {}
        env_stats = ["Location", "Daytime", "Light", "Temperature", "Humidity", "Wind", "Soundscape"]
        for attr in env_stats:
            row = ttk.Frame(env_frame)
            row.pack(anchor="w", fill=tk.X, pady=1)
            main_var   = tk.StringVar()
            main_lbl   = ttk.Label(row, textvariable=main_var)
            main_lbl.pack(side=tk.LEFT)
            explanation = ATTRIBUTE_EXPLANATIONS.get(attr, "")
            self._create_text_tooltip(main_lbl, explanation)
            change_var = tk.StringVar()
            change_lbl = ttk.Label(row, textvariable=change_var)
            change_lbl.pack(side=tk.LEFT, padx=(4,0))
            self._env_widgets[attr] = (main_var, change_var, main_lbl, change_lbl)

        # Inventory (scrollable when needed)
        inv_frame = ttk.LabelFrame(self.left_pane, text="Inventory")
        self.left_pane.add(inv_frame, weight=1)
        bg = self.root.cget("background")
        inv_canvas = tk.Canvas(inv_frame, bg=bg, highlightthickness=0, borderwidth=0)
        inv_vbar = ttk.Scrollbar(inv_frame, orient=tk.VERTICAL, command=inv_canvas.yview)
        inv_canvas.configure(yscrollcommand=inv_vbar.set)
        inv_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        inv_canvas.bind('<Enter>', lambda e: inv_canvas.focus_set())
        inv_canvas.bind('<MouseWheel>', lambda e: inv_canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))        
        inv_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.inv_items_container = ttk.Frame(inv_canvas)
        inv_canvas.create_window((0,0), window=self.inv_items_container, anchor='nw')
        # update scrollregion whenever contents change
        self.inv_items_container.bind(
            "<Configure>",
            lambda e: inv_canvas.configure(scrollregion=inv_canvas.bbox("all"))
        )

        # Perks & Skills (individual rows with tooltips)
        perks_frame = ttk.LabelFrame(self.left_pane, text="Perks & Skills")
        self.left_pane.add(perks_frame, weight=1)
        perks_canvas = tk.Canvas(perks_frame, bg=bg, highlightthickness=0, borderwidth=0)
        perks_vbar = ttk.Scrollbar(perks_frame, orient=tk.VERTICAL, command=perks_canvas.yview)
        perks_canvas.configure(yscrollcommand=perks_vbar.set)
        perks_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=2, pady=2)
        perks_canvas.bind('<Enter>', lambda e: perks_canvas.focus_set())
        perks_canvas.bind('<MouseWheel>', lambda e: perks_canvas.yview_scroll(int(-1*(e.delta/120)), 'units'))
        perks_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.perks_items_container = ttk.Frame(perks_canvas)
        perks_canvas.create_window((0,0), window=self.perks_items_container, anchor='nw')
        self.perks_items_container.bind(
            "<Configure>",
            lambda e: perks_canvas.configure(scrollregion=perks_canvas.bbox("all"))
        )

        # Scene Image + progress widgets — take all extra vertical space
        self.scene_frame = ttk.LabelFrame(self.right_pane, text="Scene")
        self.right_pane.add(self.scene_frame, weight=1)
        # load default scene image from embedded assets
        img_data = pkg_resources.read_binary("assets", "default.png")
        self._orig_scene_img = Image.open(BytesIO(img_data))
        self.scene_photo = ImageTk.PhotoImage(self._orig_scene_img)
        self.scene_label = ttk.Label(self.scene_frame, image=self.scene_photo, anchor="center")
        self.scene_label.pack(fill=tk.BOTH, expand=True)
        self.scene_label.bind("<Button-1>", self._on_scene_click)
        self.scene_frame.pack_propagate(False)

        # progress widgets (initially hidden)
        self.scene_progress_label = ttk.Label(self.scene_frame, text="Generating image...")
        self.scene_progress = ttk.Progressbar(self.scene_frame, mode="determinate")

        self.scene_frame.bind("<Configure>", self._resize_scene_image)

        # Story pane (Text + ttk Scrollbar for consistent look)
        situation_frame = ttk.LabelFrame(self.right_pane, text="Story")
        self.right_pane.add(situation_frame, weight=0)
        # container for text and scrollbar
        sit_container = ttk.Frame(situation_frame)
        sit_container.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        # story text widget
        self.situation_text = tk.Text(
            sit_container,
            height=6,
            wrap=tk.WORD,
            state='disabled',
            background=self.root.cget("background")
        )
        self.situation_text.bind('<Enter>', lambda e: self.situation_text.focus_set())
        self.situation_text.bind('<MouseWheel>', lambda e: self.situation_text.yview_scroll(int(-1*(e.delta/120)), 'units'))
        # vertical scrollbar 
        sit_vbar = ttk.Scrollbar(
            sit_container,
            orient=tk.VERTICAL,
            command=self.situation_text.yview
        )
        self.situation_text.configure(yscrollcommand=sit_vbar.set)
        self.situation_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sit_vbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Options pane (moved to just above the Thinking pane)
        options_frame = ttk.LabelFrame(self.right_pane, text="Your Options")
        self.right_pane.add(options_frame, weight=0)
        self.selected_option = tk.IntVar(value=0)
        self.option_buttons = []
        for i in range(5):
            rb = ttk.Radiobutton(
                options_frame,
                text="",
                variable=self.selected_option,
                value=i+1,
            )
            rb.pack(anchor="w", padx=4)
            self.option_buttons.append(rb)

        ttk.Label(options_frame, text="Or decide yourself:").pack(anchor="w", pady=(6,0))
        self.custom_entry = tk.Text(options_frame, height=2, wrap=tk.WORD)
        self.custom_entry.pack(fill=tk.BOTH, padx=2, pady=(0,4))
        self.custom_entry.bind("<Return>", lambda e: (self._on_submit(), "break"))

        # Thinking pane (text‐API progress)
        progress_frame = ttk.Frame(self.right_pane)
        self.right_pane.add(progress_frame, weight=0)
        self.progress_label = ttk.Label(progress_frame, text="Thinking...")
        self.progress_label.pack(pady=(4,0))
        self.progress = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress.pack(fill=tk.X, padx=2, pady=(0,4))

    def _start_game(self):
        """Begin a new game session after validating the API key."""
        # Resolve the API key, including the registry fallback. If no key is
        # available, return to the main menu so the user can configure one.
        key = _resolve_api_key()
        if not key:
            messagebox.showwarning(
                "Missing API Key",
                "No Developer API key found.\nPlease go to API and add your Gemini Developer API key."
            )
            self._open_menu()
            return

        # (Re)create the genai client now that we definitely have a key
        global client, _client_key
        client = genai.Client(api_key=key)
        _client_key = key

        # Key present—game is officially starting.
        # Immediately show the default placeholder scene (overwriting who.png).
        data = pkg_resources.read_binary("assets", "default.png")
        placeholder = Image.open(BytesIO(data))
        self._finish_image_generation(placeholder)

        # Now begin the first turn
        self._call_api(option_text="", initial=True)

    def _on_submit(self):
        """Handle user submission of a chosen or custom option."""
        self._clear_narration()
        # cancel any in‐flight image generation
        self._image_generation_cancel.set()

        # drop any extra invocations while one is already in progress
        if self._is_submitting:
            return
        self._is_submitting = True

        idx = self.selected_option.get()
        if 1 <= idx <= len(self.options):
            choice = self.options[idx-1]
        else:
            choice = self.custom_entry.get("1.0", tk.END).strip()
        if not choice:
            return

        self.past_situations.append(self.current_situation)
        self.past_options.append(choice)

        # record GM’s day/time for this turn before launching the API call
        self.past_days.append(self.day)
        self.past_times.append(self.time)
        self._call_api(choice)

    def _call_api(self, option_text: str, initial: bool=False):
        """Send the player's choice to Gemini and stream the response."""
        def thread_target():
            """Worker thread that performs the streaming API call."""
            try:
                # Collect the streamed situation text for TTS.
                self._current_situation_streamed = ""
                self._clear_narration()
    
                # advance our local turn counter (initial remains turn 1)
                if not initial:
                    self.turn += 1
    
                # Build prompt
                if not initial:
                    self.root.after(0, self._append_choice_and_blank)                
    
                start_api = time.time()
                prompt = world_text
                if not initial:
                    # Build full history.
                    history = list(zip(
                        self.past_days,
                        self.past_times,
                        self.past_situations,
                        self.past_options,
                    ))
                    if history[:-1]:
                        prompt += "\n## **Player story:**"
                        for d, t, s, o in history[:-1]:
                            prompt += (
                                f"\n[Day {d}, Time {t}]: Situation: {s}"
                                f"\nChosen Option: {o}\n"
                            )                     
    
                    prompt += f"\n## **Current Environment:** {json.dumps(self.environment)}\n"                                        
                    prompt += "\n## **Current player character state:**"
                    prompt += f"\n### Current Attributes: {json.dumps(self.attributes)}\n"
                    prompt += "### Current Perks & Skills: " + json.dumps([p.model_dump() for p in self.perks_skills]) + "\n"
                    prompt += "### Current Inventory: " + json.dumps([i.model_dump() for i in self.inventory]) + "\n"
    
                    prompt+="\n## **Image prompt**: The image prompt describes the unfolding scene from the point of view (POV) of the played character. If reasonable, he can see his hands or parts of his body.\n"
                    
                    last_day, last_time, last_situation, last_option = history[-1]
                    prompt += "\n## **Latest Situation/ Chosen Option:**"
                    prompt += (
                        f"\n[Day {last_day}, Time {last_time}]: Situation: {last_situation}\n"
                        f"**Chosen Option:** {last_option}\n"
                    ) 
    
                    prompt+="\n## **Your Task**:"
                    prompt+="\nYou are the Game Master. Process the latest Chosen Option to advance the story."
                    prompt+="\nDo not allow actions the character is incapable of. If he tries, punish him."
                    prompt+="\nSoundscape: do not list sounds, but summarize all of them with one or two words (maximum)."
                    prompt+="\nAddress the player in the first person only.\n"
    
                else:
                    prompt += (
                        "\n## **Game Start:**\n"
                        f"**Player's self-description:** '{self.identity}'\n"
                        "**Initial time context:** It is day 1 of this adventure. Choose a time (HH:MM)\n"
                        "**First situation:** Place the character in a creative and interesting situation.\n"
                        "**Environment of the character**: Describe the surroundings.\n"
                        "**Initial inventory:** Equip the character with plausible starting items. Take into account essential supplies (for example, food, water, tools or ammunition), a reasonable amount of currency and clothing appropriate for the current temperature and climate conditions.\n"
                        "**Perks & skills:** List relevant abilities\n"
                        "**Attributes & background:**\n"
                        "* If the character does not know their own name, use \"unknown\"; otherwise create one.\n"
                        "* Provide the background in the form of a plausible fantasy class.\n"
                        "**Present choices:** Offer 1-5 valid actions the player character could take next.\n"
                        "**Image prompt:** Craft a detailed, high-quality prompt depicting the player character within this fantasy scenario. Put a special focus on the equipped gear.\n"
                    )
    
                    prompt+="\n## **Your Task**:"
                    prompt+="\nYou are the Game Master. Start this adventure."
                    prompt+="\nUse up to three words to describe the attributes and the environment."
                    prompt+="\nAddress the player in the first person only.\n"
                
    #            prompt += "\n If the player wants to do something ridiculous or stupid, ask whether they are serious once. If already asked last turn and the player insists, follow their wish.\n"
    #            prompt += "Respond exclusively in German."
    
                # Disable inputs
                self.root.after(0, self._set_options_enabled, False)
    
                # Maximum creativity on the very first turn
                temp = 2.0 if initial else 0.6
    
                print("\n================\n"+prompt)
    
                # Streaming API call
                _ensure_client()
                if client is None:
                    raise RuntimeError("No API client available")
                if SOUND_ENABLED and not self._tts_warmed:
                    threading.Thread(
                        target=self._speak_situation,
                        args=("Ready.",),
                        daemon=True,
                    ).start()
                    self._tts_warmed = True
                stream = client.models.generate_content_stream(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=temp,
                        response_mime_type="application/json",
                        response_schema=GameResponse,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0,          # Turns off thinking
                            include_thoughts=False      # Explicitly suppresses any thought fragments
                        )
                    ),
                )
    
                # Buffers
                json_output = ""     # accumulate entire JSON
                buf = ""             # working buffer for string extraction
    
                # State flags
                in_situation = False
                escaping = False
                done_situation = False
    
                key = '"current_situation"'
    
                # — Initialize for streaming token tracking —
                last_usage = None
    
                for chunk in stream:
                    # Capture the most recent cumulative token usage                
                    last_usage = chunk.usage_metadata                
    
                    text = chunk.text or ""
                    text = clean_unicode(chunk.text or "")
                    
                    # 1) Always accumulate the full JSON text
                    json_output += text
    
                    # 2) If we've already finished streaming the field, skip to next chunk
                    if done_situation:
                        continue
    
                    # 3) Otherwise, append to buf and try to extract more of the string
                    buf += text
    
                    # 3a) If we haven't located the opening quote yet, look for the key + opening "
                    if not in_situation:
                        idx = buf.find(key)
                        if idx == -1:
                            # keep only last len(key) chars to match a split key next time
                            buf = buf[-len(key):]
                            continue
    
                        # drop everything through the key
                        buf = buf[idx + len(key):]
                        # find the colon+quote (allowing whitespace)
                        m = re.search(r'\s*:\s*"', buf)
                        if not m:
                            continue
    
                        # drop through the opening quote
                        buf = buf[m.end():]
                        in_situation = True
    
                    # 3b) We're inside the string: scan char by char
                    out_chars = []
                    i = 0
                    while i < len(buf):
                        c = buf[i]
                        if escaping:
                            # previous '\' means this char is literal
                            out_chars.append(c)
                            escaping = False
                        elif c == '\\':
                            # start escape; keep the backslash for later JSON decoding
                            out_chars.append(c)
                            escaping = True
                        elif c == '"':
                            # un-escaped quote → end of string value
                            raw_value = "".join(out_chars)
                            # decode JSON escapes (e.g. \n, \uXXXX)
                            try:
                                decoded = json.loads(f'"{raw_value}"')
                            except json.JSONDecodeError:
                                decoded = raw_value
                            # stream final fragment
                            self.root.after(0, lambda txt=decoded: self._stream_situation(txt))
                            # remove through the closing quote
                            buf = buf[i+1:]
                            done_situation = True
                            break
                        else:
                            out_chars.append(c)
                        i += 1
    
                    # 3c) If we didn't reach the closing quote yet, flush what we have
                    if not done_situation:
                        partial = "".join(out_chars)
                        if partial:
                            self.root.after(0, lambda txt=partial: self._stream_situation(txt))
                        # clear buf so we don't reprocess these chars
                        buf = ""
    
                # 4) After the loop completes, parse the full JSON and speak the narration
                if DEBUG_TTS and self._debug_t_text_done is None and not self._debug_logged_once:
                    self._debug_t_text_done = time.time()
                if SOUND_ENABLED:
                    self.root.after(
                        0,
                        lambda: threading.Thread(
                            target=self._speak_situation,
                            args=(self._current_situation_streamed,),
                            daemon=True,
                        ).start(),
                    )
                gr = GameResponse.model_validate_json(json_output)
                data = gr.model_dump()           # all fields as a dictionary
                cleaned = clean_unicode(data)           # recursively filter all strings
                gr = GameResponse.model_validate(cleaned)  # convert back into GameResponse
            
                print("\n=========================\n")
                print(gr)
    
                # — Update prompt & completion token metrics from streaming —
                if last_usage is not None:
                    self.last_prompt_tokens = last_usage.prompt_token_count
                    self.total_prompt_tokens += self.last_prompt_tokens
                    # The usage metadata object has reported response tokens
                    # under different attribute names across SDK versions.
                    # Use a helper that handles both to stay backwards
                    # compatible.
                    self.last_completion_tokens = get_response_tokens(last_usage)
                    self.total_completion_tokens += self.last_completion_tokens
    
                self.last_api_duration = time.time() - start_api
                #print("DURATION: "+str(self.last_api_duration))
    
                # First, hide the text‐API “Thinking…” progress bar
                self.root.after(0, self._finish_api)
    
                # Store this turn’s image prompt before any UI callback
                self.previous_image_prompt = gr.image_prompt
                # Then schedule image generation if enabled.
                if IMAGE_GENERATION_ENABLED:
                    prompt = self.previous_image_prompt
                    self.root.after(0, lambda p=prompt: self._start_image_generation(p))
                # otherwise: do nothing, leave the last‐shown image in place
    
                # Finally, update the UI state and re‐enable inputs
                self.root.after(0, lambda: self._update_remaining_state(gr))
                self.root.after(0, self._set_options_enabled, True)
    
            except Exception as e:
                self.root.after(0, self._finish_api)
                self.root.after(0, self._set_options_enabled, True)
                # "e" goes out of scope once the except block ends, so capture
                # the error message now and pass it directly to "after" to
                # avoid a NameError in the scheduled callback.
                self.root.after(0, messagebox.showerror, "API Error", str(e))
        # Show thinking progress bar
        self.progress_label.config(text="Thinking…")
        self.progress.config(style="Thinking.Horizontal.TProgressbar")
        self.progress_label.pack(pady=(4,0))
        self.progress.pack(fill=tk.X, padx=2, pady=(0,4))
        steps = max(1, int(self.last_api_duration * 100))
        self.progress.config(maximum=steps, value=0)
        delay_ms = 10
        def tick():
            """Increment the progress bar until the API response arrives."""
            if self.progress["value"] < steps:
                self.progress["value"] += 1
                self.root.after(delay_ms, tick)
        tick()

        threading.Thread(target=thread_target, daemon=True).start()

    def _finish_api(self):
        """Hide progress indicators once the text API call completes."""
        self.progress.pack_forget()
        self.progress_label.pack_forget()

    def _update_remaining_state(self, gr: GameResponse):
        """Refresh UI elements based on the latest `GameResponse`."""
        old_attributes = self.attributes.copy()
        # on very first update, old_attributes is empty → skip all “new/changed” highlighting
        is_initial = not bool(old_attributes)
        self.previous_attributes = old_attributes
        old_inventory  = [(i.name, i.weight, i.equipped) for i in self.inventory]
        # -- Perks & Skills --
        # record old perks as (name, degree) tuples so we can match by name
        old_perks      = [(p.name, p.degree) for p in self.perks_skills]

        # -- Attributes --
        attr_dict = gr.attributes.model_dump()
        for attr, val in attr_dict.items():
            main_var, change_var, main_lbl, change_lbl = self._attr_widgets[attr]
            old_val = old_attributes.get(attr)
            if not is_initial and old_val != val:
                main_var.set(f"{attr}: {old_val} → {val}")
                main_lbl.configure(style="Change.TLabel")
            else:
                main_var.set(f"{attr}: {val}")
                main_lbl.configure(style="TLabel")
            change_var.set("")
            change_lbl.configure(style="TLabel")
            self.attributes[attr] = val

        # -- Environment attributes --
        env_dict = gr.environment.model_dump()
        for attr, val in env_dict.items():
            main_var, change_var, main_lbl, change_lbl = self._env_widgets[attr]
            old_val = getattr(self, 'previous_environment', {}).get(attr)
            if not is_initial and old_val != val:
                main_var.set(f"{attr}: {old_val} → {val}")
                main_lbl.configure(style="Change.TLabel")
            else:
                main_var.set(f"{attr}: {val}")
                main_lbl.configure(style="TLabel")
            change_var.set("")
        self.previous_environment = env_dict
        self.environment = env_dict

        # -- Inventory --
        self.inventory = gr.inventory
        for widget in self.inv_items_container.winfo_children():
            widget.destroy()
        for item in self.inventory:
            row = ttk.Frame(self.inv_items_container)
            row.pack(anchor='w', fill=tk.X, pady=1)

            new_str = f"{'[E]' if item.equipped else '[ ]'} {item.name} ({item.weight:.1f} kg)"
            old = next((oi for oi in old_inventory if oi[0] == item.name), None)

            if not is_initial:
                if old is None:
                    lbl = ttk.Label(row, text=new_str, style="Change.TLabel")
                else:
                    old_str = f"{'[E]' if old[2] else '[ ]'} {old[0]} ({old[1]:.1f} kg)"
                    if old_str != new_str:
                        display = f"{old_str} → {new_str}"
                        lbl = ttk.Label(row, text=display, style="Change.TLabel")
                    else:
                        lbl = ttk.Label(row, text=new_str)
            else:
                lbl = ttk.Label(row, text=new_str)

            lbl.pack(side=tk.LEFT)
            self._create_text_tooltip(lbl, item.description)

        # -- Perks & Skills --
        self.perks_skills = gr.perks_skills
        for widget in self.perks_items_container.winfo_children():
            widget.destroy()
        for p in self.perks_skills:
            row = ttk.Frame(self.perks_items_container)
            row.pack(anchor='w', fill=tk.X, pady=1)
            display_name = f"{p.name} ({p.degree})"
            old = next((op for op in old_perks if op[0] == p.name), None)
            if not is_initial:
                if old is None:
                    # new perk: highlight addition
                    lbl = ttk.Label(row, text=display_name, style="Change.TLabel")
                else:
                    old_display = f"{old[0]} ({old[1]})"
                    if old_display != display_name:
                        # changed degree: show inline diff
                        lbl = ttk.Label(
                            row,
                            text=f"{old_display} → {display_name}",
                            style="Change.TLabel"
                        )
                    else:
                        lbl = ttk.Label(row, text=display_name)
            else:
                # initial load: no highlighting
                lbl = ttk.Label(row, text=display_name)
            lbl.pack(side=tk.LEFT)
            self._create_text_tooltip(lbl, p.description)

        # -- Situation & Options --
        # parse and store the GM-provided time context
        self.day = gr.day
        self.time = gr.time
        self.current_situation = gr.current_situation
        self.root.title(f"Nils' RPG - Turn {self.turn}")

        self.options = gr.options
        for i, rb in enumerate(self.option_buttons):
            if i < len(self.options):
                # valid choice: enable and set text & handler
                rb.config(
                    text=f"{i+1}. {self.options[i]}",
                    state=tk.NORMAL,
                    command=lambda idx=i+1: self._select_option_and_submit(idx)
                )
                # remove any click-block binding from previous state
                rb.unbind("<Button-1>")
            else:
                # no choice: disable, clear text, and block clicks
                rb.config(text="", state=tk.DISABLED)
                rb.bind("<Button-1>", lambda e: "break")

        # bind number‑keys to our guarded handler (ignore custom entry and invalid choices)
        for n in range(1, 6):
            self.root.bind(str(n), lambda e, num=n: self._on_number_key(e, num))  

        # Bind any alphabet key to switch into custom-entry and start typing there
        self.root.bind("<Key>", self._on_alpha_key)

        # clear selection once new options are in place
        self.selected_option.set(0)

        # automatically save game state after UI has been fully updated
        # suppress auto-save during loading
        if not getattr(self, '_loading', False):
            self._save_game()

    def _on_alpha_key(self, event):
        """If an A–Z key is pressed outside the custom box,
        switch focus there, clear it, insert the char, and consume."""
        ch = event.char
        # Only single alphabetic characters
        if len(ch) == 1 and ch.isalpha():
            # If not already editing custom entry
            if self.root.focus_get() != self.custom_entry:
                # clear and focus the custom-entry text widget
                self.custom_entry.delete("1.0", tk.END)
                self.custom_entry.insert("1.0", ch)
                self.custom_entry.focus_set()
                # prevent further handling
                return "break"
       # otherwise let other handlers run

    # --- Read the just-streamed situation out loud (Gemini TTS) ---
    def _stop_audio(self):
        """Stop any currently playing audio stream."""
        with self._audio_stream_lock:
            if self._audio_stream is not None:
                try:
                    self._audio_stream.stop()
                    self._audio_stream.close()
                except Exception:
                    pass
                self._audio_stream = None

    def _clear_narration(self):
        """Stop audio and reset narration debug state."""
        self._stop_audio()
        self._debug_t_text_done = None
        self._debug_logged_once = False

    def _speak_situation(self, text: str):
        """Generate and play a fantasy-style narration of `text` using Gemini Live."""
        if not SOUND_ENABLED or not HAVE_SD:
            return
        self._stop_audio()

        narration = (
            "You are a skilled fantasy narrator. "
            "Read VERBATIM—no additions.\n\n"
            "[SCRIPT START]\n" + text + "\n[SCRIPT END]"
        )

        async def _run():
            t_audio_first_chunk = None
            t_audio_play_start = None
            async with client.aio.live.connect(
                model=AUDIO_MODEL,
                config=types.LiveConnectConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=AUDIO_VOICE
                            )
                        )
                    ),
                ),
            ) as session:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=narration)],
                    )
                )
                with self._audio_stream_lock:
                    sd_stream = sd.OutputStream(
                        samplerate=24000,
                        channels=1,
                        dtype="int16",
                    )
                    sd_stream.start()
                    self._audio_stream = sd_stream
                last_usage = None
                loop = asyncio.get_running_loop()
                async for msg in session.receive():
                    if msg.usage_metadata:
                        # The SDK reports cumulative token counts for the stream
                        # in `usage_metadata` on each message.  Record the last
                        # seen values and apply them after the stream finishes so
                        # tokens are only counted once.
                        last_usage = msg.usage_metadata
                    data = msg.data
                    if data:
                        if t_audio_first_chunk is None:
                            t_audio_first_chunk = time.time()
                            t_audio_play_start = time.time()
                        # Writing to the sound device is a blocking call. If this
                        # runs on the event loop thread, the websockets keepalive
                        # pings cannot be processed which eventually triggers a
                        # timeout ("keepalive ping timeout; no close frame"). Run
                        # the blocking write in a worker thread so the event loop
                        # stays responsive during long narrations.
                        arr = np.frombuffer(data, dtype=np.int16)
                        # Offload the blocking write via the default threadpool so
                        # asyncio can continue replying to websocket pings.
                        await loop.run_in_executor(None, sd_stream.write, arr)
                with self._audio_stream_lock:
                    sd_stream.stop()
                    sd_stream.close()
                    self._audio_stream = None
                if last_usage:
                    self.total_audio_prompt_tokens += (
                        last_usage.prompt_token_count or 0
                    )
                    # The SDK has used different attribute names for response
                    # tokens over time.  Rely on the helper to read whichever
                    # is present.
                    self.total_audio_output_tokens += get_response_tokens(last_usage)
            return t_audio_first_chunk, t_audio_play_start

        try:
            t_audio_first_chunk, t_audio_play_start = asyncio.run(_run())
        except Exception as e:
            # Non-fatal: just log it
            print("TTS error:", e)
            t_audio_first_chunk = t_audio_play_start = None
        finally:
            if (
                DEBUG_TTS
                and t_audio_first_chunk
                and t_audio_play_start
                and self._debug_t_text_done is not None
            ):
                print(
                    f"Model→audio-bytes: {t_audio_first_chunk - self._debug_t_text_done:.3f}s"
                )
                print(
                    f"Bytes→audible: {t_audio_play_start - t_audio_first_chunk:.3f}s"
                )
                self._debug_logged_once = True
            self._debug_t_text_done = None

    def _set_options_enabled(self, enabled: bool):
        """Enable or disable all choice inputs during API calls."""
        # when disabling inputs, keep the submit lock;
        # when re‐enabling, clear it so next turn can submit again
        if enabled:
            self._is_submitting = False
        state = tk.NORMAL if enabled else tk.DISABLED
        for rb in self.option_buttons:
            rb.config(state=state)
        self.custom_entry.config(state=state)     
        if enabled:
            # Start of a new turn → clear and reset the custom-entry widget
            self.custom_entry.delete("1.0", tk.END)
            # Move insertion cursor to the top
            self.custom_entry.mark_set("insert", "1.0")
            # Defocus the text box so number keys select options immediately
            self.root.focus_set()       

    def _resize_scene_image(self, event):
        """Scale the scene artwork to fit the current label size."""
        orig = self._orig_scene_img
        orig_w, orig_h = orig.size
        scale = min(event.width/orig_w, event.height/orig_h)
        new_w, new_h = int(orig_w * scale), int(orig_h * scale)
        img = orig.copy().resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
        self.scene_photo = ImageTk.PhotoImage(img)
        self.scene_label.configure(image=self.scene_photo)

    def _on_perk_select(self, event):
        """Show a borderless description window for the selected perk, closing on any click."""
        sel = event.widget.curselection()
        if not sel:
            return
        idx = sel[0]
        perk = self.perks_skills[idx]
        # Close existing window if present
        if self._perk_win:
            self._perk_win.destroy()
            self._perk_win = None
            # Unbind previous click handler
            if self._perk_click_binding:
                self.root.unbind("<Button-1>", self._perk_click_binding)
                self._perk_click_binding = None
        # Create borderless, always-on-top window
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        # Display the description
        ttk.Label(win,
                  text=perk.description,
                  wraplength=800,    # allow more text per line
                  justify=tk.LEFT).pack(padx=10, pady=5)
        # Size window based on its content
        win.update_idletasks()
        req_w = win.winfo_reqwidth()
        req_h = win.winfo_reqheight()
        x = self.root.winfo_pointerx()
        y = self.root.winfo_pointery()
        win.geometry(f"{req_w}x{req_h}+{x+10}+{y+10}")
        self._perk_win = win
        # Close window on any click elsewhere
        def _close_perk_win(event):
            """Dismiss the perk description window on external clicks."""
            if self._perk_win:
                self._perk_win.destroy()
                self._perk_win = None
            if self._perk_click_binding:
                self.root.unbind("<Button-1>", self._perk_click_binding)
                self._perk_click_binding = None
        # Bind at root to catch any click
        self._perk_click_binding = self.root.bind("<Button-1>", _close_perk_win) 

    def _on_item_select(self, event):
        """Display a temporary window describing the selected item."""
        sel = event.widget.curselection()
        if not sel:
            return
        idx = sel[0]
        item = self.inventory[idx]
        # Close existing description window if present
        if self._item_win:
            self._item_win.destroy()
            self._item_win = None
            if self._item_click_binding:
                self.root.unbind("<Button-1>", self._item_click_binding)
                self._item_click_binding = None
        # Create borderless, always-on-top window
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        # Show the item description with larger layout
        ttk.Label(win,
                  text=item.description,
                  wraplength=500,
                  justify=tk.LEFT).pack(padx=10, pady=5)
        # Size window based on its content
        win.update_idletasks()
        req_w = win.winfo_reqwidth()
        req_h = win.winfo_reqheight()
        x = self.root.winfo_pointerx()
        y = self.root.winfo_pointery()
        win.geometry(f"{req_w}x{req_h}+{x+10}+{y+10}")
        self._item_win = win
        # Close on any click elsewhere
        def _close_item_win(event):
            """Dismiss the item description window on external clicks."""
            if self._item_win:
                self._item_win.destroy()
                self._item_win = None
            if self._item_click_binding:
                self.root.unbind("<Button-1>", self._item_click_binding)
                self._item_click_binding = None
        self._item_click_binding = self.root.bind("<Button-1>", _close_item_win)              

    def _start_image_generation(self, prompt_text: str):
        """Kick off asynchronous image generation for the current scene."""
        # show image generation progress in thinking pane
        steps = max(1, int(self.last_image_duration * 100))
        self.progress_label.config(text="Generating image…")
        self.progress.config(
            style="Image.Horizontal.TProgressbar",
            maximum=steps,
            value=0
        )
        self.progress_label.pack(pady=(4,0))
        self.progress.pack(fill=tk.X, padx=2, pady=(0,4))

        delay_ms = 10
        def tick():
            """Animate the progress bar while waiting for an image."""
            if self.progress["value"] < steps and not self._image_generation_cancel.is_set():
                self.progress["value"] += 1
                self.root.after(delay_ms, tick)
        tick()

        def thread_target():
            """Background worker that requests an image from Gemini."""
            start = time.time()
            response = client.models.generate_images(
                model=IMAGE_MODEL,
                prompt=prompt_text,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    include_rai_reason=True,
                    aspectRatio="16:9",
                    personGeneration="ALLOW_ADULT"
                )
            )
            self.last_image_duration = time.time() - start

            images = getattr(response, 'generated_images', None)
            if not images:
                # display went_missing.png when image is blocked or empty
                data = pkg_resources.read_binary("assets", "went_missing.png")
                placeholder = Image.open(BytesIO(data))
                self.root.after(0, lambda image=placeholder: self._finish_image_generation(image))
                return

            # Only count successful, unfiltered generations
            self.total_images += 1            

            generated = images[0]
            # check for safety‐filter block or missing bytes
            rai_reason = getattr(generated, 'rai_filtered_reason', None)
            if not generated.image.image_bytes or rai_reason:
                # display safety_reasons.png on filter or missing bytes
                data = pkg_resources.read_binary("assets", "safety_reasons.png")
                placeholder = Image.open(BytesIO(data))
                self.root.after(0, lambda image=placeholder: self._finish_image_generation(image))
                return

            # normal case: load and display
            img_bytes = generated.image.image_bytes

            # Save raw image bytes to disk
            os.makedirs(self.image_save_dir, exist_ok=True)
            image_filename = (
                f"{self.character_id}_"
                f"day{self.day}_turn{self.turn}_"
                f"{int(time.time())}.png"
            )
            image_path = os.path.join(self.image_save_dir, image_filename)
            with open(image_path, "wb") as f:
                f.write(img_bytes)

            # Now load into PIL for display
            img = Image.open(BytesIO(img_bytes))
            self.root.after(0, lambda image=img: self._finish_image_generation(image))

        threading.Thread(target=thread_target, daemon=True).start()

    def _finish_image_generation(self, image: Image.Image):
        """Update the scene with a newly generated image."""
        # hide thinking pane progress
        self.progress.pack_forget()
        self.progress_label.pack_forget()

        self._orig_scene_img = image
        w = self.scene_frame.winfo_width()
        h = self.scene_frame.winfo_height()
        fake_event = type("E", (), {"width": w, "height": h})
        self._resize_scene_image(fake_event)

        # — Attach a tooltip showing the last image‐generation prompt —
        # First, remove any existing Enter/Leave bindings to avoid stacking tooltips
        self.scene_label.unbind("<Enter>")
        self.scene_label.unbind("<Leave>")
        # Use the stored prompt (may be empty if no generation yet)
        prompt_text = getattr(self, "previous_image_prompt", "")
        self._create_text_tooltip(self.scene_label, prompt_text, wraplength=800)

    def _select_option_and_submit(self, idx: int):
        """Helper used by numeric shortcuts to choose an option."""
        self.selected_option.set(idx)
        self.root.update_idletasks()
        self._on_submit()

    def _on_number_key(self, event, num):
        """Bind number keys so they select corresponding options."""
        # suppress if typing in custom option box
        if self.root.focus_get() == self.custom_entry:
            return "break"
        # only allow selecting a real option
        if num > len(self.options):
            return "break"
        self.selected_option.set(num)
        self._on_submit()

    def _create_text_tooltip(self, widget, text, wraplength=500):
        """Show a simple tooltip with the given text (e.g. item or perk description)."""
        # allow custom wraplength (px) for wider tooltips
        def on_enter(event):
            """Create and display the tooltip window."""
            tw = tk.Toplevel(self.root)
            tw.overrideredirect(True)
            lbl = ttk.Label(
                tw,
                text=text,
                wraplength=wraplength,
                justify=tk.LEFT,
                relief="solid",
                borderwidth=1,
                padding=(4,2)
            )
            lbl.pack()
            x, y = event.x_root + 10, event.y_root + 10
            tw.wm_geometry(f"+{x}+{y}")
            widget._tooltip = tw

        def on_leave(event):
            """Destroy the tooltip window when the cursor exits."""
            tw = getattr(widget, "_tooltip", None)
            if tw:
                tw.destroy()
                widget._tooltip = None

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)    

    def _stream_situation(self, text: str):
        """Append streamed text to the story pane and buffer for TTS."""
        self.situation_text.config(state='normal')
        self.situation_text.insert(tk.END, text)
        self.situation_text.see(tk.END)
        self.situation_text.config(state='disabled')
        # Also keep a full copy so TTS can read it verbatim once complete.
        self._current_situation_streamed += text

    def _open_menu(self):
        """Display the main menu overlay with available actions."""
        # Do not open a second menu if one is already shown
        if hasattr(self, 'menu_win') and self.menu_win.winfo_exists():
            return
        menu = tk.Toplevel(self.root)
        self.menu_win = menu
        menu.title("Menu")
        menu.transient(self.root)
        menu.grab_set()
        menu.focus_force()        

        # Center the window
        menu.update_idletasks()
        width, height = 600, 580
        x = (self.root.winfo_screenwidth() - width) // 2
        y = (self.root.winfo_screenheight() - height) // 2
        menu.geometry(f"{width}x{height}+{x}+{y}")

        # Define each entry: (label, callback) or (None, None) for a spacer
        entries = [
            ("Close Menu",       menu.destroy),
            (None,               None),  # spacer
            ("New Game",         lambda: self._handle_new_game()),
            ("Load Game",        lambda: self._handle_load_game()),
            ("API",              self._open_API),
            ("Cost & Tokens",    self._show_costs_tokens),
            ("Compress History", getattr(self, "_show_history", lambda: None)),
            ("Exit game",        lambda: (self._save_game(), self.root.destroy())),
        ]

        for text, cmd in entries:
            if text is None:
                # Separator as spacer
                ttk.Separator(menu, orient=tk.HORIZONTAL).pack(
                    fill=tk.X, padx=20, pady=10
                )
            else:
                btn = ttk.Button(menu,
                                 text=text,
                                 style="RPG.TButton",
                                 command=cmd)
                # disable Close Menu until a game is active
                if text == "Close Menu" and self.character_id is None:
                    btn.config(state=tk.DISABLED)
                btn.pack(fill=tk.X, padx=20, pady=5)

    def _show_costs_tokens(self):
        """Display a summary of token usage, image count, and costs in a spreadsheet-like view."""
        win = tk.Toplevel(self.root)

        # — Allow ESC to close this window —
        win.bind("<Escape>", lambda e: win.destroy())
        
        win.title("Cost & Tokens")
        win.transient(self.root)
        win.grab_set()
        # bring window to front
        win.focus_force()

        # Compute costs based on external pricing data
        text_rates  = MODEL_COSTS.get(MODEL, {})
        audio_rates = MODEL_COSTS.get(AUDIO_MODEL, {})
        image_rates = MODEL_COSTS.get(IMAGE_MODEL, {})

        cost_text_prompt = (
            self.total_prompt_tokens * text_rates.get("input_cost_per_token", 0)
        )
        cost_text_completion = (
            self.total_completion_tokens
            * text_rates.get("output_cost_per_token", 0)
        )
        cost_audio_prompt = (
            self.total_audio_prompt_tokens
            * audio_rates.get("input_cost_per_token", 0)
        )
        cost_audio_output = (
            self.total_audio_output_tokens
            * audio_rates.get("output_cost_per_token", 0)
        )
        cost_images = (
            self.total_images * image_rates.get("output_cost_per_image", 0)
        )

        cost_text_tokens = cost_text_prompt + cost_text_completion
        cost_audio_tokens = cost_audio_prompt + cost_audio_output
        cost_prompt = cost_text_prompt + cost_audio_prompt
        cost_completion = cost_text_completion + cost_audio_output
        cost_total = cost_text_tokens + cost_audio_tokens + cost_images

        # Prepare rows: (Metric, Value)
        rows = [
            ("Last-turn prompt tokens",         f"{self.last_prompt_tokens}"),
            ("Last-turn completion tokens",     f"{self.last_completion_tokens}"),
            ("Total prompt tokens",             f"{self.total_prompt_tokens}"),
            ("Total completion tokens",         f"{self.total_completion_tokens}"),
            ("Total narration prompt tokens",   f"{self.total_audio_prompt_tokens}"),
            ("Total narration output tokens",   f"{self.total_audio_output_tokens}"),
            ("Total images generated",          f"{self.total_images}"),
            ("Total text token cost",           f"${cost_text_tokens:,.4f}"),
            ("Total narration token cost",      f"${cost_audio_tokens:,.4f}"),
            ("Total image generation cost",     f"${cost_images:,.2f}"),
            ("Average cost per turn",           f"${cost_total/max(1,self.turn):,.4f}"),
            ("Grand total cost",                f"${cost_total:,.4f}"),
        ]

        # Frame to hold the Treeview
        container = ttk.Frame(win)
        container.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Create a Treeview with two columns
        columns = ("Metric", "Value")
        tree = ttk.Treeview(container, columns=columns, show="headings", height=len(rows))
        tree.heading("Metric", text="Metric")
        tree.heading("Value", text="Value")
        tree.column("Metric", anchor="w", width=500)
        tree.column("Value", anchor="e", width=100)

        # Insert the data
        for metric, value in rows:
            tree.insert("", tk.END, values=(metric, value))
        tree.pack(fill=tk.BOTH, expand=True)

        # Close button
        btn_close = ttk.Button(win, text="Close", command=win.destroy)
        btn_close.pack(pady=(0,12))

        # Resize window to fit content and center on screen
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        win.minsize(w+50, h)

        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _reset_game(self):
        """Completely wipe game state, UI, tokens, images, and restore placeholder."""
        # --- Core state ---
        self.turn = 1
        self.day = 0
        self.time = ""
        self.identity = None
        self.current_situation = ""
        self.options = []
        self.past_situations.clear()
        self.past_options.clear()
        self.past_days.clear()
        self.past_times.clear()

        # --- Clear previous diff buffers (for highlighting) ---
        self.previous_attributes = {}
        self.previous_environment = {}     

        # --- Character & world data ---
        self.attributes.clear()
        self.environment.clear()
        self.inventory.clear()
        self.perks_skills.clear()

        # --- Cancel any in‐flight image generation & close popups ---
        #self._image_generation_cancel.set()
        self._image_generation_cancel = threading.Event()
        if getattr(self, "_perk_win", None):
            self._perk_win.destroy()
            self._perk_win = None
        if getattr(self, "_item_win", None):
            self._item_win.destroy()
            self._item_win = None        

        # --- Hide any progress bars ---
        self.progress.pack_forget()
        self.progress_label.pack_forget()
        self.scene_progress.pack_forget()
        self.scene_progress_label.pack_forget()

        # --- Clear Story pane ---
        self.situation_text.config(state='normal')
        self.situation_text.delete('1.0', tk.END)
        self.situation_text.config(state='disabled')

        # --- Clear Options pane ---
        for rb in self.option_buttons:
            rb.config(text="", state=tk.DISABLED)
            rb.unbind("<Button-1>")
        self.custom_entry.config(state=tk.NORMAL)
        self.custom_entry.delete("1.0", tk.END)

        # --- Clear Inventory display ---
        for widget in self.inv_items_container.winfo_children():
            widget.destroy()

        # --- Clear Perks & Skills display ---
        for widget in self.perks_items_container.winfo_children():
            widget.destroy()

        # --- Clear Character & Environment panes ---
        for main_var, change_var, main_lbl, change_lbl in self._attr_widgets.values():
            main_var.set("")
            change_var.set("")
            main_lbl.configure(style="TLabel")
            change_lbl.configure(style="TLabel")
        for main_var, change_var, main_lbl, change_lbl in self._env_widgets.values():
            main_var.set("")
            change_var.set("")
            main_lbl.configure(style="TLabel")
            change_lbl.configure(style="TLabel")

        # --- Restore placeholder scene image ---
        # load placeholder via importlib.resources from assets package
        data = pkg_resources.read_binary("assets", "who.png")
        placeholder = Image.open(BytesIO(data))
        self._orig_scene_img = placeholder

        # trigger resize into the scene_frame
        w = self.scene_frame.winfo_width()
        h = self.scene_frame.winfo_height()
        fake = type("E", (), {"width": w, "height": h})
        self._resize_scene_image(fake)

        # Reset selection
        self.selected_option.set(0)        

        # --- Reset window title & re-bind number keys ---
        self.root.title("Nils' RPG")
        for n in range(1, 6):
            # re-bind so stale handlers are replaced
            self.root.bind(str(n), lambda e, num=n: self._on_number_key(e, num))

    def run(self):
        """Enter the Tkinter main event loop."""
        self.root.mainloop()

    def _save_game(self):
        """Serialize the current game state to the user's save directory."""
        # if no character has been chosen/loaded yet, skip saving
        if self.character_id is None:
            return        
        data = {
            'identity':             self.identity,
            'style':                self.style_choice,
            'difficulty':           self.diff_choice,            
            'turn':                 self.turn,
            'day':                  self.day,
            'time':                 self.time,
            'current_situation':    self.current_situation,
            'environment':          self.environment,
            'attributes':           self.attributes,
            'inventory':            [i.model_dump() for i in self.inventory],
            'perks_skills':         [p.model_dump() for p in self.perks_skills],
            'options':              self.options,
            'past_situations':      self.past_situations,
            'past_options':         self.past_options,
            'past_days':            self.past_days,
            'past_times':           self.past_times,
            'previous_image_prompt':self.previous_image_prompt,
        }
        # 1. Determine per-user save directory on Windows
        save_dir = os.path.join(
            os.getenv("APPDATA", os.path.expanduser("~")),
            "Nils' RPG"
        )
        os.makedirs(save_dir, exist_ok=True)

        # 2. Single save per character: overwrite <character_id>.dat
        filename = f"{self.character_id}.dat"
        path = os.path.join(save_dir, filename)
        # record the character_id in the save data
        data['character_id'] = self.character_id

        # record current pane sizes (sash positions)
        try:
            pane_sizes = {
                'main_sash':      self.main_pane.sashpos(0),
                'left_sashes':   [
                    self.left_pane.sashpos(i)
                    for i in range(len(self.left_pane.panes()) - 1)
                ],
                'right_sashes':  [
                    self.right_pane.sashpos(i)
                    for i in range(len(self.right_pane.panes()) - 1)
                ],
            }
            data['pane_sizes'] = pane_sizes
        except Exception:
            pass

        # 3. Serialize the current scene image into bytes
        try:
            buf = BytesIO()
            self._orig_scene_img.save(buf, format="PNG")
            data['scene_image_bytes'] = buf.getvalue()
            # 4. Serialize the full story/history text
            data['story_text'] = self.situation_text.get('1.0', tk.END)            

            # 5. Write the pickle and report success
            with open(path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            # 6. On failure, report error
            messagebox.showerror("Save Game", f"Could not save game:\n{e}")

    def _load_game(self):
        """Open a load-game dialog listing all saved games."""
        self._open_load_game_window()

    def _open_load_game_window(self):
        """Modal window showing scrollable list of all save files with thumbnails and metadata."""
        # pause any pending image generation
        self._image_generation_cancel.set()

        save_dir = os.path.join(
            os.getenv("APPDATA", os.path.expanduser("~")),
            "Nils' RPG"
        )
        os.makedirs(save_dir, exist_ok=True)
        files = glob.glob(os.path.join(save_dir, "*.dat"))
        if not files:
            messagebox.showinfo("Load Game", "No save files found.")
            return

        # Sort by most-recent first
        files.sort(key=os.path.getmtime, reverse=True)

        win = tk.Toplevel(self.root)
        self.load_win = win
        win.title("Load Game")
        win.transient(self.root)
        win.grab_set()
        # Bind ESC in load-game window to close it and return to the main menu
        win.bind('<Escape>', lambda e: (win.destroy(), self._open_menu()))

        #Back Button
        back_btn = ttk.Button(
            win,
            text="Back",
            command=lambda: (win.destroy(), self._open_menu()),
            style="RPG.TButton"
        )
        back_btn.pack(padx=20, pady=5)

        # Give focus to the Back button so ESC will always work
        back_btn.focus_set()

        # Scrollable canvas + scrollbar
        canvas = tk.Canvas(win, background=self.root.cget("background"))
        vbar = ttk.Scrollbar(win, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        # Enable mousewheel scrolling when pointer is over the canvas
        canvas.bind(
            '<Enter>',
            lambda e: canvas.bind(
                '<MouseWheel>',
                lambda ev: canvas.yview_scroll(int(-1*(ev.delta/120)), 'units')
            )
        )
        canvas.bind('<Leave>', lambda e: canvas.unbind('<MouseWheel>'))        
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        container = ttk.Frame(canvas)
        canvas.create_window((0,0), window=container, anchor='nw')
        container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        for path in files:
            try:
                with open(path, 'rb') as f:
                    data = pickle.load(f)
            except Exception:
                continue

            # extract metadata
            attrs     = data.get('attributes', {})
            char_name = attrs.get('Name', 'Unknown')
            loc       = data.get('environment', {}).get('Location', 'Unknown')
            turn      = data.get('turn', 0)
            mtime     = time.localtime(os.path.getmtime(path))
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", mtime)

            # build a larger, 16:9 thumbnail
            img_bytes = data.get('scene_image_bytes')
            if img_bytes:
                img = Image.open(BytesIO(img_bytes))
                img.thumbnail((160, 90), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
            else:
                # placeholder thumbnail from embedded assets
                data = pkg_resources.read_binary("assets", "default.png")
                placeholder = Image.open(BytesIO(data))
                placeholder.thumbnail((160, 90), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(placeholder)

            # one row per save
            row = ttk.Frame(container, relief="ridge", padding=5)
            row.pack(fill=tk.X, padx=5, pady=5)
            thumb = ttk.Label(row, image=photo)
            thumb.image = photo
            thumb.pack(side=tk.LEFT)
            # truncate very long location strings
            max_loc_len = 30
            if len(loc) > max_loc_len:
                loc_display = loc[:max_loc_len-3] + "..."
            else:
                loc_display = loc

            info = (
                f"{char_name}\n"
                f"Location: {loc_display}\n"
                f"Turn: {turn}\n"
                f"Saved: {timestamp}"
            )
            lbl = ttk.Label(row, text=info, justify=tk.LEFT)
            lbl.pack(side=tk.LEFT, padx=10)
            # buttons for Load and Delete
            btn_frame = ttk.Frame(row)
            btn_frame.pack(side=tk.RIGHT, padx=(0,10))

            load_btn = ttk.Button(
                btn_frame,
                text="Load",
                command=lambda p=path: self._load_game_from_path(p)
            )
            load_btn.pack(fill=tk.X, pady=(0,2))

            del_btn = ttk.Button(
                btn_frame,
                text="Delete",
                command=lambda p=path, r=row: self._confirm_delete(p, r)
            )
            del_btn.pack(fill=tk.X)

            # click anywhere in this row to load
            def make_cb(p=path):
                """Return a click handler that loads the given save file."""
                return lambda e=None: (win.destroy(), self._load_game_from_path(p))
            for w in (row, thumb, lbl):
                w.bind("<Button-1>", make_cb())

        # size & center
        win.update_idletasks()
        w = 1280
        h = 720
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _load_game_from_path(self, path):
        """Load game state from the user’s chosen save file."""
        try:
            with open(path, 'rb') as f:
                data = pickle.load(f)
        except Exception as e:
            messagebox.showerror("Load Game", f"Could not load save:\n{e}")
            return
        
        # restore saved style & difficulty, and rebuild prompt context
        self.style_choice = data.get('style')
        self.diff_choice  = data.get('difficulty')
        global world_text
        world_text = (
            _STYLES.get(self.style_choice, "") +
            "\n" +
            _DIFFICULTIES.get(self.diff_choice, "")
        )

        # same logic as before, but now parameterized
        # reset UI/state
        self._reset_game()
        # suppress auto-save while we restore everything

        self._loading = True
        self.character_id          = data.get('character_id')
        self.identity              = data.get('identity')
        self.turn                  = data.get('turn', 1)
        self.past_situations       = data.get('past_situations', [])
        self.past_options          = data.get('past_options', [])
        self.past_days             = data.get('past_days', [])
        self.past_times            = data.get('past_times', [])
        self.previous_image_prompt = data.get('previous_image_prompt')

        gr = GameResponse(
            day=data.get('day', 0),
            time=data.get('time', ""),
            current_situation=data.get('current_situation', ""),
            environment=Environment(**data.get('environment', {})),
            inventory=[InventoryItem(**i) for i in data.get('inventory', [])],
            perks_skills=[PerkSkill(**p) for p in data.get('perks_skills', [])],
            attributes=Attributes(**data.get('attributes', {})),
            options=data.get('options', []),
            image_prompt=self.previous_image_prompt or ""
        )
        self._update_remaining_state(gr)
        # done loading, re-enable auto-save
        self._loading = False

        # restore story text
        saved = data.get('story_text')
        self.situation_text.config(state='normal')
        self.situation_text.delete('1.0', tk.END)
        self.situation_text.insert('1.0', saved or gr.current_situation)
        self.situation_text.config(state='disabled')

        # restore exact scene image
        img_bytes = data.get('scene_image_bytes')
        if img_bytes:
            try:
                img = Image.open(BytesIO(img_bytes))
                self._orig_scene_img = img
            except Exception:
                self._orig_scene_img = Image.open("default.png")
            evt = type("E", (), {
                "width":  self.scene_frame.winfo_width(),
                "height": self.scene_frame.winfo_height()
            })
            self._resize_scene_image(evt)

            # — Attach tooltip on load to show the saved image prompt —
            self.scene_label.unbind("<Enter>")
            self.scene_label.unbind("<Leave>")
            tooltip_text = data.get('previous_image_prompt', "") or ""
            self._create_text_tooltip(self.scene_label, tooltip_text)

        # restore pane sizes
        pane_sizes = data.get('pane_sizes', {})
        if pane_sizes:
            try:
                self.main_pane.sashpos(0, pane_sizes['main_sash'])
            except Exception:
                pass
            for idx, pos in enumerate(pane_sizes.get('left_sashes', [])):
                try:
                    self.left_pane.sashpos(idx, pos)
                except Exception:
                    pass
            for idx, pos in enumerate(pane_sizes.get('right_sashes', [])):
                try:
                    self.right_pane.sashpos(idx, pos)
                except Exception:
                    pass            

    def _confirm_delete(self, path, row):
        """Prompt to delete a save file and remove it from the list."""
        if messagebox.askyesno("Delete Save", f"Are you sure?"):
            try:
                os.remove(path)
                row.destroy()
            except Exception as e:
                messagebox.showerror("Delete Save", f"Could not delete save:\n{e}")     

    def _handle_global_escape(self, event=None):
        """Handle ESC presses by closing popups or toggling the menu."""
        # 1. If load-game window is open, close it
        if hasattr(self, 'load_win') and self.load_win.winfo_exists():
            self.load_win.destroy()
        # 2. Else if menu is already open, close it
        elif hasattr(self, 'menu_win') and self.menu_win.winfo_exists():
            self.menu_win.destroy()
            return
        # 3. Otherwise, open the main menu
        else:
            self._open_menu()

    def _open_API(self):
        """Open a modal dialog for API key and model configuration."""
        win = tk.Toplevel(self.root)
        win.title("API Configuration")
        # Make this dialog modal and transient, then raise it
        win.transient(self.root)
        win.grab_set()
        win.lift()
        win.bind("<Escape>", lambda e: win.destroy())

        # Variables
        api_key_var     = tk.StringVar(value=os.environ.get("GEMINI_API_KEY", ""))
        img_var         = tk.BooleanVar(value=IMAGE_GENERATION_ENABLED)
        sound_var       = tk.BooleanVar(value=SOUND_ENABLED)
        text_model_var  = tk.StringVar(value=MODEL)
        image_model_var = tk.StringVar(value=IMAGE_MODEL)
        audio_model_var = tk.StringVar(value=AUDIO_MODEL)
        voice_var       = tk.StringVar(value=AUDIO_VOICE)

        frm = ttk.Frame(win, padding=20)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frm, text="Gemini API Key:").grid(row=0, column=0, sticky="w")
        api_key_entry = ttk.Entry(frm, textvariable=api_key_var, width=60)
        api_key_entry.grid(row=0, column=2, sticky="w")
        # Give focus to the API Key entry rather than forcing the whole window
        api_key_entry.focus_set()

        ttk.Label(frm, text="Automatic Image:  ").grid(row=1, column=0, sticky="w", pady=(10,0))
        ttk.Checkbutton(frm, variable=img_var).grid(row=1, column=2, sticky="w", pady=(10,0))

        ttk.Label(frm, text="Narrate Situation:").grid(row=2, column=0, sticky="w", pady=(10,0))
        ttk.Checkbutton(frm, variable=sound_var).grid(row=2, column=2, sticky="w", pady=(10,0))

        ttk.Label(frm, text="Text Model:").grid(row=3, column=0, sticky="w", pady=(10,0))
        ttk.Entry(frm, textvariable=text_model_var, width=60).grid(row=3, column=2, sticky="w", pady=(10,0))

        ttk.Label(frm, text="Image Model:").grid(row=4, column=0, sticky="w", pady=(10,0))
        ttk.Entry(frm, textvariable=image_model_var, width=60).grid(row=4, column=2, sticky="w", pady=(10,0))

        ttk.Label(frm, text="Sound Model:").grid(row=5, column=0, sticky="w", pady=(10,0))
        ttk.Entry(frm, textvariable=audio_model_var, width=60).grid(row=5, column=2, sticky="w", pady=(10,0))

        ttk.Label(frm, text="Sound Voice:").grid(row=6, column=0, sticky="w", pady=(10,0))
        ttk.Entry(frm, textvariable=voice_var, width=60).grid(row=6, column=2, sticky="w", pady=(10,0))

        btns = ttk.Frame(win, padding=(0,0,20,20))
        btns.pack(fill=tk.X, side=tk.BOTTOM)

        def _save():
            """Persist settings after validating the API key."""
            key = api_key_var.get().strip()

            # 1. Instantiate a temporary client and validate the key before saving
            try:
                test_client = genai.Client(api_key=key)
                test_client.models.list(config={'page_size': 1})
            except Exception as e:
                messagebox.showerror(
                    "Invalid API Key",
                    f"The provided API key is invalid or unauthorized:\n{e}"
                )
                return

            # 2) On success, write into HKCU\Environment, update this process,
            #    and rebind the global client
            set_user_env_var("GEMINI_API_KEY", key)
            os.environ["GEMINI_API_KEY"] = key
            global client, _client_key
            client = test_client
            _client_key = key

            global IMAGE_GENERATION_ENABLED
            IMAGE_GENERATION_ENABLED = img_var.get()

            global SOUND_ENABLED
            SOUND_ENABLED = sound_var.get()

            global MODEL
            MODEL = text_model_var.get().strip()

            global IMAGE_MODEL
            IMAGE_MODEL = image_model_var.get().strip()

            global AUDIO_MODEL
            AUDIO_MODEL = audio_model_var.get().strip()

            global AUDIO_VOICE
            AUDIO_VOICE = voice_var.get().strip()

            win.destroy()

        ttk.Button(btns, text="Save",   command=_save,   style="RPG.TButton")\
            .pack(side=tk.RIGHT, padx=(0,5))

        # — Center the API Configuration window on screen —
        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")
        
    # ——— New methods for API‑key validation on menu actions ———
    def _validate_api_key(self):
        """Check that GEMINI_API_KEY exists and authorizes requests."""
        key = _resolve_api_key()
        if not key:
            messagebox.showwarning(
                "Missing API Key",
                "No Developer API key found.\n"
                "Please configure your Gemini Developer API key before proceeding.",
            )
            return False
        try:
            _ensure_client()
            if client is None:
                raise RuntimeError("No API client available")
            client.models.list(config={'page_size': 1})
        except Exception as e:
            messagebox.showerror(
                "Invalid API Key",
                f"The provided API key is invalid or unauthorized:\n{e}"
            )
            return False
        return True
    def _handle_new_game(self):
        """Callback for New Game: immediately go to identity prompt."""
        self.menu_win.destroy()
        self._reset_game()
        self._ask_style()

    def _handle_load_game(self):
        """Callback for Load Game: immediately open save-slots dialog."""
        self.menu_win.destroy()
        self._load_game()   

    def _on_scene_click(self, event=None):
        """
        When the user clicks the scene image, regenerate it:
        - If we have a previous image prompt, use it.
        - Otherwise, show the default placeholder.
        """
        # Cancel any ongoing image generation
        self._image_generation_cancel.set()
        prompt = getattr(self, 'previous_image_prompt', None)
        if prompt:
            # Clear the cancel flag and start a new generation
            self._image_generation_cancel.clear()
            self._start_image_generation(prompt)
        else:
            # No prompt yet: load the default placeholder image
            data = pkg_resources.read_binary("assets", "default.png")
            placeholder = Image.open(BytesIO(data))
            self._finish_image_generation(placeholder)

    def _ask_style(self):
        """Prompt the player to choose a narrative style."""
        win = tk.Toplevel(self.root)
        win.transient(self.root); win.grab_set(); win.lift()
        win.title("Choose World Style")

        var = tk.StringVar()
        cb = ttk.Combobox(win, textvariable=var,
                          values=list(_STYLES.keys()), state="readonly")
        if _STYLES: cb.current(0)
        cb.pack(padx=20, pady=20)

        btn = ttk.Button(win, text="Next", style="RPG.TButton",
                         command=lambda: self._on_style_selected(win, var.get()))
        btn.pack(pady=10)

        # center and enlarge
        win.update_idletasks()
        w, h = 500, 200
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")        

    def _on_style_selected(self, win, choice):
        """Store the style selection and proceed to difficulty choices."""
        self.style_choice = choice
        win.grab_release(); win.destroy()
        self._ask_difficulty()

    def _ask_difficulty(self):
        """Prompt the player to choose a difficulty level."""
        win = tk.Toplevel(self.root)
        win.transient(self.root); win.grab_set(); win.lift()
        win.title("Choose Difficulty")

        var = tk.StringVar()
        cb = ttk.Combobox(win, textvariable=var,
                          values=list(_DIFFICULTIES.keys()), state="readonly")
        if _DIFFICULTIES: cb.current(0)
        cb.pack(padx=20, pady=20)        

        btn = ttk.Button(win, text="Next", style="RPG.TButton",
                         command=lambda: self._on_difficulty_selected(win, var.get()))
        btn.pack(pady=10)

        # center and enlarge
        win.update_idletasks()
        w, h = 500, 200
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")        

    def _on_difficulty_selected(self, win, choice):
        """Finalize difficulty, rebuild world text and ask for identity."""
        self.diff_choice = choice
        # build the world_text used by _call_api()
        global world_text
        world_text = (
            _STYLES.get(self.style_choice, "") +
            "\n" +
            _DIFFICULTIES.get(self.diff_choice, "")
        )
        win.grab_release(); win.destroy()
        self._ask_identity()
 
if __name__ == "__main__":
    root = tk.Tk()
    game = RPGGame(root)
    game._open_menu()
    game.run()

# pyinstaller --clean --noconfirm --onefile --windowed --add-data "assets;assets" NilsRPG.py

