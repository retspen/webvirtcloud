// The VNC console page: noVNC's RFB in the page's screen, driven from the
// panel's bar: status, keys, clipboard, view, touch keyboard, reconnect.
import RFB from './novnc/core/rfb.js';
import Keyboard from './novnc/core/input/keyboard.js';
import KeyTable from './novnc/core/input/keysym.js';
import keysyms from './novnc/core/input/keysymdef.js';
import { isTouchDevice } from './novnc/core/util/browser.js';
import { bindFullscreen, bindKeyAction, bindSendKeys, releaseHeld } from './console_keys.js';

const config = JSON.parse(document.getElementById('vnc-config').textContent);
const status = document.getElementById('status');
const connectionButton = document.getElementById('connection_button');

// novncd behind the panel's own address (nginx's /novncd/), never a host from
// the link; the page's token is its credential
const scheme = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
const url = scheme + window.location.host + '/novncd/?token=' + encodeURIComponent(config.token);
const rfb = new RFB(document.getElementById('screen'), url,
    { credentials: config.password ? { password: config.password } : {} });

// ---- status and reconnect

let connected = false;
let closed = false;
let refusal = null;

function showStatus(text, color) {
    status.textContent = text;
    status.className = 'badge text-bg-' + color;
}

rfb.addEventListener('connect', () => {
    connected = true;
    showStatus(status.dataset.connected, 'success');
    rfb.focus();
});
// the server's own words (untranslated) on hover
rfb.addEventListener('securityfailure', (e) => {
    refusal = status.dataset.refused;
    status.title = (e.detail.reason || '').replace(/\0/g, '');
});
rfb.addEventListener('disconnect', (e) => {
    closed = true;
    if (refusal) {
        showStatus(refusal, 'danger');
    } else if (!connected) {
        showStatus(status.dataset.failed, 'danger');
    } else {
        showStatus(e.detail.clean ? status.dataset.disconnected : status.dataset.lost, 'danger');
    }
    connectionButton.textContent = connectionButton.dataset.reconnect;
    credentialsDialog.hide();
});
// the token is good for one connection soon after the page loads: a new
// connection takes a new page
connectionButton.addEventListener('click', () => {
    if (closed) {
        window.location.reload();
    } else {
        rfb.disconnect();
    }
});

// ---- the VNC password, when the server asks for it

const credentialsDialog = new bootstrap.Modal('#credentials_dialog');
const username = document.getElementById('credentials_username');
const password = document.getElementById('credentials_password');

rfb.addEventListener('credentialsrequired', (e) => {
    document.getElementById('credentials_username_field').hidden = !e.detail.types.includes('username');
    credentialsDialog.show();
});
document.getElementById('credentials_dialog').addEventListener('shown.bs.modal', () => {
    // closed while it was opening: a dialog still opening ignores hide()
    if (closed) {
        credentialsDialog.hide();
        return;
    }
    (username.offsetParent ? username : password).focus();
});
document.getElementById('credentials_form').addEventListener('submit', (e) => {
    e.preventDefault();
    const credentials = { password: password.value };
    if (username.offsetParent) {
        credentials.username = username.value;
    }
    password.value = '';
    credentialsDialog.hide();
    rfb.sendCredentials(credentials);
});
bindKeyAction('credentials_cancel', () => {
    credentialsDialog.hide();
    rfb.disconnect();
});

// ---- keys, clipboard and typed text

bindSendKeys(rfb);
bindFullscreen();

// the characters a US keyboard types with Shift: the VM gets keys, and its
// key for "A" is the key for "a"
const SHIFTED = /[A-Z~!@#$%^&*()_+{}|:"<>?]/;

const typedKeys = {
    '\n': [KeyTable.XK_Return, 'Enter'],
    '\b': [KeyTable.XK_BackSpace, 'Backspace'],
    '\t': [KeyTable.XK_Tab, 'Tab'],
};

async function typeCharacter(character) {
    // a typist's pace: firmware drops keys that come faster
    await new Promise((resolve) => setTimeout(resolve, 25));
    const [keysym, code] = typedKeys[character] || [keysyms.lookup(character.codePointAt(0)), null];
    if (SHIFTED.test(character)) {
        rfb.sendKey(KeyTable.XK_Shift_L, 'ShiftLeft', true);
        rfb.sendKey(keysym, code);
        rfb.sendKey(KeyTable.XK_Shift_L, 'ShiftLeft', false);
    } else {
        rfb.sendKey(keysym, code);
    }
}

// key by key, after what is still being typed: works where no clipboard does
// (firmware, installers, login prompts); "\b" is a Backspace
let typing = Promise.resolve();
function typeText(text) {
    for (const character of text.replace(/\r\n?/g, '\n')) {
        typing = typing.then(() => typeCharacter(character));
    }
}

const clipboardText = document.getElementById('clipboard_text');
const clipboardDialog = bootstrap.Modal.getOrCreateInstance('#clipboard_dialog');
rfb.addEventListener('clipboard', (e) => {
    clipboardText.value = e.detail.text;
});
bindKeyAction('clipboard_send', () => {
    rfb.clipboardPasteFrom(clipboardText.value);
    clipboardDialog.hide();
});
bindKeyAction('clipboard_type', () => {
    clipboardDialog.hide();
    typeText(clipboardText.value);
});

const bell = document.getElementById('bell');
rfb.addEventListener('bell', () => bell.play().catch(() => {}));

// back to the VM's screen after a menu or a dialog
document.addEventListener('hidden.bs.dropdown', () => rfb.focus());
document.addEventListener('hidden.bs.modal', () => rfb.focus());

// ---- the View menu

const resize = document.getElementById('view_resize');
const clip = document.getElementById('view_clip');
const drag = document.getElementById('view_drag');
const viewOnly = document.getElementById('view_only');
const dot = document.getElementById('view_dot');
const quality = document.getElementById('view_quality');
const compression = document.getElementById('view_compression');

function applyView() {
    rfb.scaleViewport = resize.value === 'scale';
    rfb.resizeSession = resize.value === 'remote';
    // a screen fitted to the window has nothing to clip, an unclipped one nothing to drag
    clip.disabled = rfb.scaleViewport;
    rfb.clipViewport = clip.checked && !rfb.scaleViewport;
    drag.disabled = !rfb.clipViewport;
    rfb.dragViewport = drag.checked && rfb.clipViewport;
    if (viewOnly.checked) {
        releaseHeld(rfb);  // while it still sends keys
    }
    rfb.viewOnly = viewOnly.checked;
    rfb.showDotCursor = dot.checked;
    rfb.qualityLevel = Number(quality.value);
    rfb.compressionLevel = Number(compression.value);
}

// a touch screen cannot scroll a screen larger than the window: it starts fitted
resize.value = isTouchDevice && config.resize === 'off' ? 'scale' : config.resize;
clip.checked = config.clip;
viewOnly.checked = config.viewOnly;
applyView();
document.getElementById('view_menu').addEventListener('change', applyView);

// ---- the on-screen keyboard of a touch device

if (isTouchDevice) {
    const keyboardInput = document.getElementById('keyboard_input');
    document.getElementById('keyboard_button').hidden = false;
    bindKeyAction('keyboard_button', () => keyboardInput.focus());
    keyboardInput.addEventListener('focus', () => { rfb.focusOnClick = false; });
    keyboardInput.addEventListener('blur', () => { rfb.focusOnClick = true; });

    // the keys it reports as key events
    const keyboard = new Keyboard(keyboardInput);
    keyboard.onkeyevent = (keysym, code, down) => rfb.sendKey(keysym, code, down);
    keyboard.grab();

    // the text it reports only as input (Android): what changed since the
    // last input, as Backspaces and characters; the field always holds text
    // for a Backspace to delete
    let lastText = '';
    const resetInput = () => { keyboardInput.value = lastText = '_'.repeat(100); };
    resetInput();
    keyboardInput.addEventListener('input', () => {
        const text = keyboardInput.value;
        let same = 0;
        while (same < Math.min(text.length, lastText.length) && text[same] === lastText[same]) {
            same++;
        }
        typeText('\b'.repeat(lastText.length - same) + text.slice(same));
        if (text.length === 0 || text.length > 200) {
            resetInput();
        } else {
            lastText = text;
        }
    });
}
