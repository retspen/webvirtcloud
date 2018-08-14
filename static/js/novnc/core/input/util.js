"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.getKeycode = getKeycode;
exports.getKey = getKey;
exports.getKeysym = getKeysym;

var _keysym = require("./keysym.js");

var _keysym2 = _interopRequireDefault(_keysym);

var _keysymdef = require("./keysymdef.js");

var _keysymdef2 = _interopRequireDefault(_keysymdef);

var _vkeys = require("./vkeys.js");

var _vkeys2 = _interopRequireDefault(_vkeys);

var _fixedkeys = require("./fixedkeys.js");

var _fixedkeys2 = _interopRequireDefault(_fixedkeys);

var _domkeytable = require("./domkeytable.js");

var _domkeytable2 = _interopRequireDefault(_domkeytable);

var _browser = require("../util/browser.js");

var browser = _interopRequireWildcard(_browser);

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

// Get 'KeyboardEvent.code', handling legacy browsers
function getKeycode(evt) {
    // Are we getting proper key identifiers?
    // (unfortunately Firefox and Chrome are crappy here and gives
    // us an empty string on some platforms, rather than leaving it
    // undefined)
    if (evt.code) {
        // Mozilla isn't fully in sync with the spec yet
        switch (evt.code) {
            case 'OSLeft':
                return 'MetaLeft';
            case 'OSRight':
                return 'MetaRight';
        }

        return evt.code;
    }

    // The de-facto standard is to use Windows Virtual-Key codes
    // in the 'keyCode' field for non-printable characters. However
    // Webkit sets it to the same as charCode in 'keypress' events.
    if (evt.type !== 'keypress' && evt.keyCode in _vkeys2.default) {
        var code = _vkeys2.default[evt.keyCode];

        // macOS has messed up this code for some reason
        if (browser.isMac() && code === 'ContextMenu') {
            code = 'MetaRight';
        }

        // The keyCode doesn't distinguish between left and right
        // for the standard modifiers
        if (evt.location === 2) {
            switch (code) {
                case 'ShiftLeft':
                    return 'ShiftRight';
                case 'ControlLeft':
                    return 'ControlRight';
                case 'AltLeft':
                    return 'AltRight';
            }
        }

        // Nor a bunch of the numpad keys
        if (evt.location === 3) {
            switch (code) {
                case 'Delete':
                    return 'NumpadDecimal';
                case 'Insert':
                    return 'Numpad0';
                case 'End':
                    return 'Numpad1';
                case 'ArrowDown':
                    return 'Numpad2';
                case 'PageDown':
                    return 'Numpad3';
                case 'ArrowLeft':
                    return 'Numpad4';
                case 'ArrowRight':
                    return 'Numpad6';
                case 'Home':
                    return 'Numpad7';
                case 'ArrowUp':
                    return 'Numpad8';
                case 'PageUp':
                    return 'Numpad9';
                case 'Enter':
                    return 'NumpadEnter';
            }
        }

        return code;
    }

    return 'Unidentified';
}

// Get 'KeyboardEvent.key', handling legacy browsers
function getKey(evt) {
    // Are we getting a proper key value?
    if (evt.key !== undefined) {
        // IE and Edge use some ancient version of the spec
        // https://developer.microsoft.com/en-us/microsoft-edge/platform/issues/8860571/
        switch (evt.key) {
            case 'Spacebar':
                return ' ';
            case 'Esc':
                return 'Escape';
            case 'Scroll':
                return 'ScrollLock';
            case 'Win':
                return 'Meta';
            case 'Apps':
                return 'ContextMenu';
            case 'Up':
                return 'ArrowUp';
            case 'Left':
                return 'ArrowLeft';
            case 'Right':
                return 'ArrowRight';
            case 'Down':
                return 'ArrowDown';
            case 'Del':
                return 'Delete';
            case 'Divide':
                return '/';
            case 'Multiply':
                return '*';
            case 'Subtract':
                return '-';
            case 'Add':
                return '+';
            case 'Decimal':
                return evt.char;
        }

        // Mozilla isn't fully in sync with the spec yet
        switch (evt.key) {
            case 'OS':
                return 'Meta';
        }

        // iOS leaks some OS names
        switch (evt.key) {
            case 'UIKeyInputUpArrow':
                return 'ArrowUp';
            case 'UIKeyInputDownArrow':
                return 'ArrowDown';
            case 'UIKeyInputLeftArrow':
                return 'ArrowLeft';
            case 'UIKeyInputRightArrow':
                return 'ArrowRight';
            case 'UIKeyInputEscape':
                return 'Escape';
        }

        // IE and Edge have broken handling of AltGraph so we cannot
        // trust them for printable characters
        if (evt.key.length !== 1 || !browser.isIE() && !browser.isEdge()) {
            return evt.key;
        }
    }

    // Try to deduce it based on the physical key
    var code = getKeycode(evt);
    if (code in _fixedkeys2.default) {
        return _fixedkeys2.default[code];
    }

    // If that failed, then see if we have a printable character
    if (evt.charCode) {
        return String.fromCharCode(evt.charCode);
    }

    // At this point we have nothing left to go on
    return 'Unidentified';
}

// Get the most reliable keysym value we can get from a key event
function getKeysym(evt) {
    var key = getKey(evt);

    if (key === 'Unidentified') {
        return null;
    }

    // First look up special keys
    if (key in _domkeytable2.default) {
        var location = evt.location;

        // Safari screws up location for the right cmd key
        if (key === 'Meta' && location === 0) {
            location = 2;
        }

        if (location === undefined || location > 3) {
            location = 0;
        }

        return _domkeytable2.default[key][location];
    }

    // Now we need to look at the Unicode symbol instead

    var codepoint;

    // Special key? (FIXME: Should have been caught earlier)
    if (key.length !== 1) {
        return null;
    }

    codepoint = key.charCodeAt();
    if (codepoint) {
        return _keysymdef2.default.lookup(codepoint);
    }

    return null;
}