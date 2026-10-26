// The keys menu of the VNC console page: key combinations the browser or the
// operating system would otherwise catch, and modifiers a device lacks.
import KeyTable from './novnc/core/input/keysym.js';

const CTRL = { keysym: KeyTable.XK_Control_L, code: 'ControlLeft' };
const ALT = { keysym: KeyTable.XK_Alt_L, code: 'AltLeft' };
const SUPER = { keysym: KeyTable.XK_Super_L, code: 'MetaLeft' };
const HOLDS = [['holdctrl', CTRL], ['holdalt', ALT], ['holdsuper', SUPER]];

function hold(rfb, id, key, down) {
    const item = document.getElementById(id);
    rfb.sendKey(key.keysym, key.code, down);
    item.setAttribute('aria-pressed', down);
    item.classList.toggle('active', down);
}

// the held modifiers up: before a combination from the menu (which presses
// and releases its own), and before the page stops sending keys
export function releaseHeld(rfb) {
    for (const [id, key] of HOLDS) {
        if (document.getElementById(id).getAttribute('aria-pressed') === 'true') {
            hold(rfb, id, key, false);
        }
    }
}

// press the keys in order, release them in reverse
function sendKeys(rfb, keys) {
    releaseHeld(rfb);
    keys.forEach((key) => rfb.sendKey(key.keysym, key.code, true));
    setTimeout(() => [...keys].reverse().forEach((key) => rfb.sendKey(key.keysym, key.code, false)), 20);
}

export function bindKeyAction(id, handler) {
    const el = document.getElementById(id);
    if (el) {
        el.addEventListener('click', (e) => {
            e.preventDefault();
            handler();
        });
    }
}

export function bindSendKeys(rfb) {
    const send = (...keys) => () => sendKeys(rfb, keys);
    bindKeyAction('ctrlaltdel', () => {
        releaseHeld(rfb);
        rfb.sendCtrlAltDel();
    });
    bindKeyAction('ctrlaltbackspace', send(CTRL, ALT, { keysym: KeyTable.XK_BackSpace, code: 'Backspace' }));
    bindKeyAction('alttab', send(ALT, { keysym: KeyTable.XK_Tab, code: 'Tab' }));
    bindKeyAction('superkey', send(SUPER));
    bindKeyAction('sendesc', send({ keysym: KeyTable.XK_Escape, code: 'Escape' }));
    bindKeyAction('sendtab', send({ keysym: KeyTable.XK_Tab, code: 'Tab' }));
    bindKeyAction('ctrlc', send(CTRL, { keysym: KeyTable.XK_c, code: 'KeyC' }));
    bindKeyAction('ctrlz', send(CTRL, { keysym: KeyTable.XK_z, code: 'KeyZ' }));
    bindKeyAction('ctrld', send(CTRL, { keysym: KeyTable.XK_d, code: 'KeyD' }));
    bindKeyAction('ctrlbackslash', send(CTRL, { keysym: KeyTable.XK_backslash, code: 'Backslash' }));
    for (let i = 1; i <= 12; i++) {
        bindKeyAction('ctrlaltf' + i, send(CTRL, ALT, { keysym: KeyTable['XK_F' + i], code: 'F' + i }));
    }
    // a held modifier stays down until it is chosen again: with the next key
    // typed it makes a combination the menu does not list
    for (const [id, key] of HOLDS) {
        bindKeyAction(id, () => {
            // a view-only page sends no keys: nothing to hold
            if (!rfb.viewOnly) {
                hold(rfb, id, key, document.getElementById(id).getAttribute('aria-pressed') !== 'true');
            }
        });
    }
}

// the Fullscreen item; in full screen the page also takes the keys the
// browser would keep (Alt, Tab, Escape) where the browser lets it
export function bindFullscreen() {
    const item = document.getElementById('fullscreen_button');
    if (!document.fullscreenEnabled) {
        item.hidden = true;
        return;
    }
    bindKeyAction('fullscreen_button', () => {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        } else {
            document.documentElement.requestFullscreen().catch(() => {});
        }
    });
    document.addEventListener('fullscreenchange', () => {
        if (!navigator.keyboard) {
            return;
        }
        if (document.fullscreenElement) {
            navigator.keyboard.lock(['AltLeft', 'AltRight', 'Tab', 'Escape']).catch(() => {});
        } else {
            navigator.keyboard.unlock();
        }
    });
}
