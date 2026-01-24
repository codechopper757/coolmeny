#!/usr/bin/env python3
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple
from prompt_toolkit.layout.dimension import Dimension


from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

CACHE_FILE = Path.home() / ".cache" / "coolmenu.json"
MAX_RESULTS = 10


# -------------------------
# Utilities
# -------------------------

def fuzzy_score(pattern: str, text: str) -> int:
    """Simple fuzzy scoring: higher is better, -1 = no match"""
    pattern = pattern.lower()
    text = text.lower()

    score = 0
    ti = 0

    for pc in pattern:
        found = False
        while ti < len(text):
            if text[ti] == pc:
                found = True
                score += 10
                ti += 1
                break
            ti += 1
        if not found:
            return -1

    score -= len(text) // 4
    return score


def scan_path() -> List[str]:
    seen = set()
    result = []

    for d in os.environ.get("PATH", "").split(":"):
        if not os.path.isdir(d):
            continue
        try:
            for name in os.listdir(d):
                full = os.path.join(d, name)
                if name not in seen and os.access(full, os.X_OK) and os.path.isfile(full):
                    seen.add(name)
                    result.append(name)
        except PermissionError:
            pass

    result.sort()
    return result


def load_items() -> List[str]:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass

    items = scan_path()
    CACHE_FILE.write_text(json.dumps(items))
    return items


# -------------------------
# UI
# -------------------------

class CoolMenu:
    def __init__(self, items: List[str]):
        self.scroll = 0
        self.items = items
        self.query = ""
        self.filtered: List[str] = items[:]
        self.selected = 0

        self.kb = KeyBindings()

        self.input_control = FormattedTextControl(self.render_input)
        self.list_control = FormattedTextControl(self.render_list)

        self.root_container = HSplit([
            Window(height=1, content=FormattedTextControl(self.render_border_top)),
            Window(height=1, content=self.input_control),
            Window(height=1, content=FormattedTextControl(self.render_divider)),
            Window(content=self.list_control, height=Dimension(weight=1)),
            Window(height=1, content=FormattedTextControl(self.render_footer)),
            Window(height=1, content=FormattedTextControl(self.render_border_bottom)),
        ])

        self.layout = Layout(self.root_container)

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            style=self.build_style()
        )


        self.bind_keys()
        self.update_filter()

    # -------------------------
    # Rendering
    # -------------------------

    def width(self):
        return shutil.get_terminal_size((80, 20)).columns

    def render_border_top(self):
        w = self.width()
        return [("class:border", "╭" + "─" * (w - 2) + "╮")]

    def render_border_bottom(self):
        w = self.width()
        return [("class:border", "╰" + "─" * (w - 2) + "╯")]

    def render_divider(self):
        w = self.width()
        return [("class:border", "├" + "─" * (w - 2) + "┤")]

    def render_input(self):
        w = self.width()
        text = f" Search: {self.query}"
        return [("class:input", text.ljust(w - 2))]

    def render_footer(self):
        w = self.width()
        help_text = " ↑↓ / Ctrl-jk  Enter launch  Esc quit  Ctrl-u clear "
        return [("class:footer", help_text.ljust(w - 2))]

    def render_list(self):
        lines = []

        visible = self.visible_rows()
        start = self.scroll
        end = min(start + visible, len(self.filtered))

        for i in range(start, end):
            item = self.filtered[i]
            prefix = "> " if i == self.selected else "  "
            style = "class:selected" if i == self.selected else "class:item"

            lines.append((style, (prefix + item).ljust(self.width() - 2)))
            lines.append(("", "\n"))

        return lines

    def build_style(self):
        return Style.from_dict({
            "border": "fg:#888888",
            "input": "fg:#ffffff",
            "footer": "fg:#aaaaaa",
            "item": "",
            "selected": "reverse",
        })

    # -------------------------
    # Logic
    # -------------------------

    def update_filter(self):
        q = self.query.lower()

        if not q:
            self.filtered = self.items[:]
        else:
            self.filtered = [
                it for it in self.items
                if q in it.lower()
            ]

        self.selected = 0


    def move(self, delta):
        if not self.filtered:
            return

        self.selected = max(0, min(self.selected + delta, len(self.filtered) - 1))

        visible = self.visible_rows()

        if self.selected < self.scroll:
            self.scroll = self.selected
        elif self.selected >= self.scroll + visible:
            self.scroll = self.selected - visible + 1

    def visible_rows(self):
        # total terminal height minus borders/input/footer
        rows = shutil.get_terminal_size((80, 20)).lines
        return max(1, rows - 6)



    def launch_selected(self):
        if not self.filtered:
            return
        cmd = self.filtered[self.selected]
        self.app.exit(result=cmd)

    # -------------------------
    # Keys
    # -------------------------

    def bind_keys(self):
        @self.kb.add("escape")
        @self.kb.add("c-c")
        def _(event):
            event.app.exit(result=None)

        @self.kb.add("enter")
        def _(event):
            self.launch_selected()

        @self.kb.add("up")
        @self.kb.add("c-k")
        def _(event):
            self.move(-1)

        @self.kb.add("down")
        @self.kb.add("c-j")
        def _(event):
            self.move(1)

        @self.kb.add("c-u")
        def _(event):
            self.query = ""
            self.update_filter()

        @self.kb.add("<any>")
        def _(event):
            if event.data.isprintable():
                self.query += event.data
                self.update_filter()
            elif event.data in ("\b", "\x7f"):
                self.query = self.query[:-1]
                self.update_filter()


    def run(self):
        return self.app.run()


# -------------------------
# Main
# -------------------------

def main():
    items = load_items()

    menu = CoolMenu(items)
    result = menu.run()

    if result:
        os.execvp(result, [result])


if __name__ == "__main__":
    main()
