'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.isTouchDevice = undefined;
exports.supportsCursorURIs = supportsCursorURIs;
exports.isMac = isMac;
exports.isIE = isIE;
exports.isEdge = isEdge;
exports.isWindows = isWindows;
exports.isIOS = isIOS;

var _logging = require('./logging.js');

var Log = _interopRequireWildcard(_logging);

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

// Touch detection
var isTouchDevice = exports.isTouchDevice = 'ontouchstart' in document.documentElement ||
// requried for Chrome debugger
document.ontouchstart !== undefined ||
// required for MS Surface
navigator.maxTouchPoints > 0 || navigator.msMaxTouchPoints > 0; /*
                                                                 * noVNC: HTML5 VNC client
                                                                 * Copyright (C) 2012 Joel Martin
                                                                 * Licensed under MPL 2.0 (see LICENSE.txt)
                                                                 *
                                                                 * See README.md for usage and integration instructions.
                                                                 */

window.addEventListener('touchstart', function onFirstTouch() {
    exports.isTouchDevice = isTouchDevice = true;
    window.removeEventListener('touchstart', onFirstTouch, false);
}, false);

var _cursor_uris_supported = null;

function supportsCursorURIs() {
    if (_cursor_uris_supported === null) {
        try {
            var target = document.createElement('canvas');
            target.style.cursor = 'url("data:image/x-icon;base64,AAACAAEACAgAAAIAAgA4AQAAFgAAACgAAAAIAAAAEAAAAAEAIAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAD/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////AAAAAAAAAAAAAAAAAAAAAA==") 2 2, default';

            if (target.style.cursor) {
                Log.Info("Data URI scheme cursor supported");
                _cursor_uris_supported = true;
            } else {
                Log.Warn("Data URI scheme cursor not supported");
                _cursor_uris_supported = false;
            }
        } catch (exc) {
            Log.Error("Data URI scheme cursor test exception: " + exc);
            _cursor_uris_supported = false;
        }
    }

    return _cursor_uris_supported;
};

function isMac() {
    return navigator && !!/mac/i.exec(navigator.platform);
}

function isIE() {
    return navigator && !!/trident/i.exec(navigator.userAgent);
}

function isEdge() {
    return navigator && !!/edge/i.exec(navigator.userAgent);
}

function isWindows() {
    return navigator && !!/win/i.exec(navigator.platform);
}

function isIOS() {
    return navigator && (!!/ipad/i.exec(navigator.platform) || !!/iphone/i.exec(navigator.platform) || !!/ipod/i.exec(navigator.platform));
}