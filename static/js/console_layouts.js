// The keys that type a character on the VM's keyboard layout: the VM gets
// keys, not characters, and its own layout makes characters of them. The
// layouts are console/layouts/*.json, put in the page by the view.

// the modifiers of a layout key's four characters, pressed in this order:
// AltGr before Shift, as the right Alt pressed after Shift is Alt on the
// Linux console
const MODIFIERS = [[], ['ShiftLeft'], ['AltRight'], ['AltRight', 'ShiftLeft']];

const layouts = JSON.parse(document.getElementById('keyboard-layouts').textContent);

// layout id: {character: [key code, modifier codes]}; of the keys that type
// a character, the first with the fewest modifiers
const keys = {};
for (const [id, layout] of Object.entries(layouts)) {
    keys[id] = {};
    MODIFIERS.forEach((modifiers, slot) => {
        for (const [code, characters] of Object.entries(layout.keys)) {
            const character = characters[slot];
            if (character !== null && !(character in keys[id])) {
                keys[id][character] = [code, modifiers];
            }
        }
    });
}

export function layoutKeys(layout, character) {
    return keys[layout][character];
}
