#!/usr/bin/env python3
"""Write console/layouts/<id>.json, a keyboard layout the VNC console's
"Type it" can type with, from the system's XKB data (xkeyboard-config),
as libxkbcommon computes it.

    python3 dev/console_layout.py tr "Turkish Q"
    python3 dev/console_layout.py tr "Turkish F" --variant f
    python3 dev/console_layout.py us "English (US)" --model pc104

The model is the keyboard's: pc105 (the default) has a key left of Z
(IntlBackslash) that US keyboards (pc104) lack.

Each key the layout writes with gets the characters it types plainly, with
Shift, with AltGr and with Shift+AltGr (null: none, or the same as without
AltGr). Dead keys are left out and listed.
"""

import argparse
import ctypes
import ctypes.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANCODES = ROOT / "static/js/novnc/core/input/xtscancodes.js"
LAYOUTS = ROOT / "console/layouts"

KEY_DOWN = 1
SHIFT = "ShiftLeft"
ALTGR = "AltRight"
MODIFIERS = [[], [SHIFT], [ALTGR], [ALTGR, SHIFT]]  # pressed in this order, as the console page does
# the writing keys a keyboard model lacks (XKB defines them all the same);
# other models, such as jp106 and abnt2, have them
MISSING_KEYS = {"pc104": {"IntlBackslash", "IntlRo", "IntlYen"}, "pc105": {"IntlRo", "IntlYen"}}


class RuleNames(ctypes.Structure):
    _fields_ = [(name, ctypes.c_char_p) for name in ("rules", "model", "layout", "variant", "options")]


def load_xkbcommon():
    xkb = ctypes.CDLL(ctypes.util.find_library("xkbcommon") or "libxkbcommon.so.0")
    for name, restype, argtypes in (
        ("xkb_context_new", ctypes.c_void_p, [ctypes.c_int]),
        ("xkb_keymap_new_from_names", ctypes.c_void_p, [ctypes.c_void_p, ctypes.POINTER(RuleNames), ctypes.c_int]),
        ("xkb_state_new", ctypes.c_void_p, [ctypes.c_void_p]),
        ("xkb_state_unref", None, [ctypes.c_void_p]),
        ("xkb_state_update_key", ctypes.c_int, [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]),
        ("xkb_state_key_get_utf32", ctypes.c_uint32, [ctypes.c_void_p, ctypes.c_uint32]),
        ("xkb_state_key_get_one_sym", ctypes.c_uint32, [ctypes.c_void_p, ctypes.c_uint32]),
        ("xkb_keysym_get_name", ctypes.c_int, [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_size_t]),
    ):
        function = getattr(xkb, name)
        function.restype, function.argtypes = restype, argtypes
    return xkb


def linux_keycodes():
    """{DOM code: Linux keycode}, from noVNC's table (QEMU's keycodemapdb)."""
    pattern = re.compile(r'^  "(\w+)": 0x\w+, /\* html:\w+ \(\w+\) -> linux:(\d+) ', re.M)
    return {code: int(linux) for code, linux in pattern.findall(SCANCODES.read_text())}


def writing_keys(codes, model):
    """The keys of the model's keyboard that write characters: not the keypad,
    not Space (typed on its own)."""
    missing = MISSING_KEYS.get(model, set()) | {"Space"}
    return {code: linux for code, linux in codes.items() if not code.startswith("Numpad") and code not in missing}


def press(xkb, keymap, keycodes, keys):
    """What the last of the keys gives with the others held: (character or None, keysym)."""
    state = xkb.xkb_state_new(keymap)
    for key in keys[:-1]:
        xkb.xkb_state_update_key(state, keycodes[key], KEY_DOWN)
    utf32 = xkb.xkb_state_key_get_utf32(state, keycodes[keys[-1]])
    keysym = xkb.xkb_state_key_get_one_sym(state, keycodes[keys[-1]])
    xkb.xkb_state_unref(state)
    return (chr(utf32) if utf32 >= 0x20 and utf32 != 0x7F else None), keysym


def keysym_name(xkb, keysym):
    name = ctypes.create_string_buffer(64)
    xkb.xkb_keysym_get_name(keysym, name, len(name))
    return name.value.decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("layout", help='XKB layout, e.g. "tr", "de", "fr"')
    parser.add_argument("name", help='the name the console shows, e.g. "Turkish Q"')
    parser.add_argument("--variant", default="", help='XKB variant, e.g. "f" for Turkish F')
    parser.add_argument("--model", default="pc105", help="XKB keyboard model: pc105, or pc104 for US keyboards")
    args = parser.parse_args()

    xkb = load_xkbcommon()
    names = RuleNames(b"evdev", args.model.encode(), args.layout.encode(), args.variant.encode(), b"")
    keymap = xkb.xkb_keymap_new_from_names(xkb.xkb_context_new(0), ctypes.byref(names), 0)
    if not keymap:
        parser.error(f"XKB has no layout {args.layout!r} with variant {args.variant!r}")
    # XKB keycodes are Linux keycodes + 8
    keycodes = {code: linux + 8 for code, linux in linux_keycodes().items()}

    keys, dead = {}, []
    for code in sorted(writing_keys(keycodes, args.model), key=keycodes.get):
        characters = []
        for slot, modifiers in enumerate(MODIFIERS):
            character, keysym = press(xkb, keymap, keycodes, [*modifiers, code])
            if keysym_name(xkb, keysym).startswith("dead_"):
                dead.append(f"{'+'.join([*modifiers, code])}: {keysym_name(xkb, keysym)}")
            # AltGr that changes nothing is no AltGr (the US layout has none)
            if slot >= 2 and character == characters[slot - 2]:
                character = None
            characters.append(character)
        if any(characters):
            keys[code] = characters

    layout_id = args.layout + (f"-{args.variant}" if args.variant else "")
    lines = ",\n".join(f"        {json.dumps(code)}: {json.dumps(chars, ensure_ascii=False)}" for code, chars in keys.items())
    source = json.dumps({"xkb_layout": args.layout, "xkb_variant": args.variant, "xkb_model": args.model})
    path = LAYOUTS / f"{layout_id}.json"
    path.write_text(f'{{\n    "name": {json.dumps(args.name, ensure_ascii=False)},\n    "source": {source},\n'
                    f'    "keys": {{\n{lines}\n    }}\n}}\n')
    print(f"wrote {path.relative_to(ROOT)}: {len(keys)} keys")
    if dead:
        print("dead keys, left out:\n  " + "\n  ".join(dead))


if __name__ == "__main__":
    main()
