"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.init_logging = init_logging;
exports.getQueryVar = getQueryVar;
exports.getHashVar = getHashVar;
exports.getConfigVar = getConfigVar;
exports.createCookie = createCookie;
exports.readCookie = readCookie;
exports.eraseCookie = eraseCookie;
exports.initSettings = initSettings;
exports.writeSetting = writeSetting;
exports.readSetting = readSetting;
exports.eraseSetting = eraseSetting;
exports.injectParamIfMissing = injectParamIfMissing;
exports.fetchJSON = fetchJSON;

var _logging = require("../core/util/logging.js");

// init log level reading the logging HTTP param
function init_logging(level) {
    "use strict";

    if (typeof level !== "undefined") {
        (0, _logging.init_logging)(level);
    } else {
        var param = document.location.href.match(/logging=([A-Za-z0-9\._\-]*)/);
        (0, _logging.init_logging)(param || undefined);
    }
} /*
   * noVNC: HTML5 VNC client
   * Copyright (C) 2012 Joel Martin
   * Copyright (C) 2013 NTT corp.
   * Licensed under MPL 2.0 (see LICENSE.txt)
   *
   * See README.md for usage and integration instructions.
   */

;

// Read a query string variable
function getQueryVar(name, defVal) {
    "use strict";

    var re = new RegExp('.*[?&]' + name + '=([^&#]*)'),
        match = document.location.href.match(re);
    if (typeof defVal === 'undefined') {
        defVal = null;
    }
    if (match) {
        return decodeURIComponent(match[1]);
    } else {
        return defVal;
    }
};

// Read a hash fragment variable
function getHashVar(name, defVal) {
    "use strict";

    var re = new RegExp('.*[&#]' + name + '=([^&]*)'),
        match = document.location.hash.match(re);
    if (typeof defVal === 'undefined') {
        defVal = null;
    }
    if (match) {
        return decodeURIComponent(match[1]);
    } else {
        return defVal;
    }
};

// Read a variable from the fragment or the query string
// Fragment takes precedence
function getConfigVar(name, defVal) {
    "use strict";

    var val = getHashVar(name);
    if (val === null) {
        val = getQueryVar(name, defVal);
    }
    return val;
};

/*
 * Cookie handling. Dervied from: http://www.quirksmode.org/js/cookies.html
 */

// No days means only for this browser session
function createCookie(name, value, days) {
    "use strict";

    var date, expires;
    if (days) {
        date = new Date();
        date.setTime(date.getTime() + days * 24 * 60 * 60 * 1000);
        expires = "; expires=" + date.toGMTString();
    } else {
        expires = "";
    }

    var secure;
    if (document.location.protocol === "https:") {
        secure = "; secure";
    } else {
        secure = "";
    }
    document.cookie = name + "=" + value + expires + "; path=/" + secure;
};

function readCookie(name, defaultValue) {
    "use strict";

    var nameEQ = name + "=",
        ca = document.cookie.split(';');

    for (var i = 0; i < ca.length; i += 1) {
        var c = ca[i];
        while (c.charAt(0) === ' ') {
            c = c.substring(1, c.length);
        }
        if (c.indexOf(nameEQ) === 0) {
            return c.substring(nameEQ.length, c.length);
        }
    }
    return typeof defaultValue !== 'undefined' ? defaultValue : null;
};

function eraseCookie(name) {
    "use strict";

    createCookie(name, "", -1);
};

/*
 * Setting handling.
 */

var settings = {};

function initSettings(callback /*, ...callbackArgs */) {
    "use strict";

    var callbackArgs = Array.prototype.slice.call(arguments, 1);
    if (window.chrome && window.chrome.storage) {
        window.chrome.storage.sync.get(function (cfg) {
            settings = cfg;
            if (callback) {
                callback.apply(this, callbackArgs);
            }
        });
    } else {
        // No-op
        if (callback) {
            callback.apply(this, callbackArgs);
        }
    }
};

// No days means only for this browser session
function writeSetting(name, value) {
    "use strict";

    if (window.chrome && window.chrome.storage) {
        if (settings[name] !== value) {
            settings[name] = value;
            window.chrome.storage.sync.set(settings);
        }
    } else {
        localStorage.setItem(name, value);
    }
};

function readSetting(name, defaultValue) {
    "use strict";

    var value;
    if (window.chrome && window.chrome.storage) {
        value = settings[name];
    } else {
        value = localStorage.getItem(name);
    }
    if (typeof value === "undefined") {
        value = null;
    }
    if (value === null && typeof defaultValue !== "undefined") {
        return defaultValue;
    } else {
        return value;
    }
};

function eraseSetting(name) {
    "use strict";

    if (window.chrome && window.chrome.storage) {
        window.chrome.storage.sync.remove(name);
        delete settings[name];
    } else {
        localStorage.removeItem(name);
    }
};

function injectParamIfMissing(path, param, value) {
    // force pretend that we're dealing with a relative path
    // (assume that we wanted an extra if we pass one in)
    path = "/" + path;

    var elem = document.createElement('a');
    elem.href = path;

    var param_eq = encodeURIComponent(param) + "=";
    var query;
    if (elem.search) {
        query = elem.search.slice(1).split('&');
    } else {
        query = [];
    }

    if (!query.some(function (v) {
        return v.startsWith(param_eq);
    })) {
        query.push(param_eq + encodeURIComponent(value));
        elem.search = "?" + query.join("&");
    }

    // some browsers (e.g. IE11) may occasionally omit the leading slash
    // in the elem.pathname string. Handle that case gracefully.
    if (elem.pathname.charAt(0) == "/") {
        return elem.pathname.slice(1) + elem.search + elem.hash;
    } else {
        return elem.pathname + elem.search + elem.hash;
    }
};

// sadly, we can't use the Fetch API until we decide to drop
// IE11 support or polyfill promises and fetch in IE11.
// resolve will receive an object on success, while reject
// will receive either an event or an error on failure.
function fetchJSON(path, resolve, reject) {
    // NB: IE11 doesn't support JSON as a responseType
    var req = new XMLHttpRequest();
    req.open('GET', path);

    req.onload = function () {
        if (req.status === 200) {
            try {
                var resObj = JSON.parse(req.responseText);
            } catch (err) {
                reject(err);
                return;
            }
            resolve(resObj);
        } else {
            reject(new Error("XHR got non-200 status while trying to load '" + path + "': " + req.status));
        }
    };

    req.onerror = function (evt) {
        reject(new Error("XHR encountered an error while trying to load '" + path + "': " + evt.message));
    };

    req.ontimeout = function (evt) {
        reject(new Error("XHR timed out while trying to load '" + path + "'"));
    };

    req.send();
}