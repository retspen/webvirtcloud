'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.init_logging = init_logging;
exports.get_logging = get_logging;
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

/*
 * Logging/debug routines
 */

var _log_level = 'warn';

var Debug = function (msg) {};
var Info = function (msg) {};
var Warn = function (msg) {};
var Error = function (msg) {};

function init_logging(level) {
    if (typeof level === 'undefined') {
        level = _log_level;
    } else {
        _log_level = level;
    }

    exports.Debug = Debug = exports.Info = Info = exports.Warn = Warn = exports.Error = Error = function (msg) {};
    if (typeof window.console !== "undefined") {
        switch (level) {
            case 'debug':
                exports.Debug = Debug = console.debug.bind(window.console);
            case 'info':
                exports.Info = Info = console.info.bind(window.console);
            case 'warn':
                exports.Warn = Warn = console.warn.bind(window.console);
            case 'error':
                exports.Error = Error = console.error.bind(window.console);
            case 'none':
                break;
            default:
                throw new Error("invalid logging type '" + level + "'");
        }
    }
};
function get_logging() {
    return _log_level;
};
exports.Debug = Debug;
exports.Info = Info;
exports.Warn = Warn;
exports.Error = Error;

// Initialize logging level

init_logging();