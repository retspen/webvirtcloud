// The serial console page: xterm.js on socketiod (Socket.IO behind nginx's
// /socket.io/), driven from the panel's bar: status, keys, reconnect.
import { bindFullscreen, bindKeyAction } from './console_keys.js';

const status = document.getElementById('status');
const connectionButton = document.getElementById('connection_button');

// the page's signed token is the credential, good for two minutes: a new
// connection takes a new page (Reconnect), not an automatic retry
const token = JSON.parse(document.getElementById('serial-token').textContent);
const socket = io({ transports: ['websocket', 'polling'], auth: { token }, reconnection: false });

const term = new Terminal({ cursorBlink: true });
const fitAddon = new FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.open(document.getElementById('terminal'));

function send(input) {
    if (socket.connected) {
        socket.emit('pty_input', { input });
    }
}

function resize() {
    fitAddon.fit();
    if (socket.connected) {
        socket.emit('resize', { cols: term.cols, rows: term.rows });
    }
}

function showStatus(text, color) {
    status.textContent = text;
    status.className = 'badge text-bg-' + color;
    connectionButton.textContent = socket.connected ? connectionButton.dataset.disconnect : connectionButton.dataset.reconnect;
}

let output = false;
let takenBy = null;

// typed and pasted input
term.onData(send);
socket.on('pty_output', (data) => {
    output = true;
    term.write(data.output);
});
socket.on('connect', () => {
    showStatus(status.dataset.connected, 'success');
    resize();
    term.focus();
    // a serial console shows nothing until the VM writes
    setTimeout(() => {
        if (!output && socket.connected) {
            term.write('\x1b[2m' + status.dataset.hint + '\x1b[0m\r\n');
        }
    }, 1500);
});
// a superuser opened this console: the server ends this session next
socket.on('taken_over', (data) => {
    takenBy = data.by;
});
socket.on('disconnect', () => {
    if (takenBy) {
        const text = status.dataset.takenOver.replace('%(name)s', takenBy);
        term.write('\r\n[' + text + ']\r\n');
        showStatus(text, 'danger');
    } else {
        showStatus(status.dataset.disconnected, 'danger');
    }
});
// the server says why: serial console off, an expired link, the console open elsewhere
socket.on('connect_error', (err) => showStatus(err.message, 'danger'));

connectionButton.addEventListener('click', () => {
    if (socket.connected) {
        socket.disconnect();
    } else {
        window.location.reload();
    }
});

const keys = { ctrlc: '\x03', ctrld: '\x04', ctrlz: '\x1a', ctrlbackslash: '\x1c', sendtab: '\t', sendesc: '\x1b' };
for (const [id, input] of Object.entries(keys)) {
    bindKeyAction(id, () => send(input));
}
bindFullscreen();

// back to the terminal after the menu
document.addEventListener('hidden.bs.dropdown', () => term.focus());
new ResizeObserver(resize).observe(document.getElementById('terminal'));
