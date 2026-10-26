// The keys menu of the VNC console pages (lite and full): key combinations
// the browser or the operating system would otherwise catch.
import KeyTable from './novnc/core/input/keysym.js';

const CTRL = { keysym: KeyTable.XK_Control_L, code: 'ControlLeft' };
const ALT = { keysym: KeyTable.XK_Alt_L, code: 'AltLeft' };

// press the keys in order, release them in reverse
function sendKeys(rfb, keys) {
    if (!rfb || (rfb._rfbConnectionState && rfb._rfbConnectionState !== 'connected')) { return; }
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

// getRfb: the page's RFB object, which the full page creates on connect
export function bindSendKeys(getRfb) {
    const send = (...keys) => () => sendKeys(getRfb(), keys);
    const ctrlAltDel = () => {
        const rfb = getRfb();
        if (rfb && typeof rfb.sendCtrlAltDel === 'function') {
            rfb.sendCtrlAltDel();
        }
    };
    bindKeyAction('ctrlaltdel', ctrlAltDel);
    bindKeyAction('sendCtrlAltDelButton', ctrlAltDel);
    bindKeyAction('ctrlaltbackspace', send(CTRL, ALT, { keysym: KeyTable.XK_BackSpace, code: 'Backspace' }));
    bindKeyAction('alttab', send(ALT, { keysym: KeyTable.XK_Tab, code: 'Tab' }));
    bindKeyAction('superkey', send({ keysym: KeyTable.XK_Super_L, code: 'MetaLeft' }));
    bindKeyAction('sendesc', send({ keysym: KeyTable.XK_Escape, code: 'Escape' }));
    bindKeyAction('sendtab', send({ keysym: KeyTable.XK_Tab, code: 'Tab' }));
    bindKeyAction('ctrlc', send(CTRL, { keysym: KeyTable.XK_c, code: 'KeyC' }));
    bindKeyAction('ctrlz', send(CTRL, { keysym: KeyTable.XK_z, code: 'KeyZ' }));
    bindKeyAction('ctrld', send(CTRL, { keysym: KeyTable.XK_d, code: 'KeyD' }));
    bindKeyAction('ctrlbackslash', send(CTRL, { keysym: KeyTable.XK_backslash, code: 'Backslash' }));
    for (let i = 1; i <= 12; i++) {
        bindKeyAction('ctrlaltf' + i, send(CTRL, ALT, { keysym: KeyTable['XK_F' + i], code: 'F' + i }));
    }
}
