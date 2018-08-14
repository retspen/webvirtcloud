(function(){function r(e,n,t){function o(i,f){if(!n[i]){if(!e[i]){var c="function"==typeof require&&require;if(!f&&c)return c(i,!0);if(u)return u(i,!0);var a=new Error("Cannot find module '"+i+"'");throw a.code="MODULE_NOT_FOUND",a}var p=n[i]={exports:{}};e[i][0].call(p.exports,function(r){var n=e[i][1][r];return o(n||r)},p,p.exports,r,e,n,t)}return n[i].exports}for(var u="function"==typeof require&&require,i=0;i<t.length;i++)o(t[i]);return o}return r})()({1:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.Localizer = Localizer;
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

/*
 * Localization Utilities
 */

function Localizer() {
    // Currently configured language
    this.language = 'en';

    // Current dictionary of translations
    this.dictionary = undefined;
}

Localizer.prototype = {
    // Configure suitable language based on user preferences
    setup: function (supportedLanguages) {
        var userLanguages;

        this.language = 'en'; // Default: US English

        /*
         * Navigator.languages only available in Chrome (32+) and FireFox (32+)
         * Fall back to navigator.language for other browsers
         */
        if (typeof window.navigator.languages == 'object') {
            userLanguages = window.navigator.languages;
        } else {
            userLanguages = [navigator.language || navigator.userLanguage];
        }

        for (var i = 0; i < userLanguages.length; i++) {
            var userLang = userLanguages[i];
            userLang = userLang.toLowerCase();
            userLang = userLang.replace("_", "-");
            userLang = userLang.split("-");

            // Built-in default?
            if (userLang[0] === 'en' && (userLang[1] === undefined || userLang[1] === 'us')) {
                return;
            }

            // First pass: perfect match
            for (var j = 0; j < supportedLanguages.length; j++) {
                var supLang = supportedLanguages[j];
                supLang = supLang.toLowerCase();
                supLang = supLang.replace("_", "-");
                supLang = supLang.split("-");

                if (userLang[0] !== supLang[0]) continue;
                if (userLang[1] !== supLang[1]) continue;

                this.language = supportedLanguages[j];
                return;
            }

            // Second pass: fallback
            for (var j = 0; j < supportedLanguages.length; j++) {
                supLang = supportedLanguages[j];
                supLang = supLang.toLowerCase();
                supLang = supLang.replace("_", "-");
                supLang = supLang.split("-");

                if (userLang[0] !== supLang[0]) continue;
                if (supLang[1] !== undefined) continue;

                this.language = supportedLanguages[j];
                return;
            }
        }
    },

    // Retrieve localised text
    get: function (id) {
        if (typeof this.dictionary !== 'undefined' && this.dictionary[id]) {
            return this.dictionary[id];
        } else {
            return id;
        }
    },

    // Traverses the DOM and translates relevant fields
    // See https://html.spec.whatwg.org/multipage/dom.html#attr-translate
    translateDOM: function () {
        var self = this;
        function process(elem, enabled) {
            function isAnyOf(searchElement, items) {
                return items.indexOf(searchElement) !== -1;
            }

            function translateAttribute(elem, attr) {
                var str = elem.getAttribute(attr);
                str = self.get(str);
                elem.setAttribute(attr, str);
            }

            function translateTextNode(node) {
                var str = node.data.trim();
                str = self.get(str);
                node.data = str;
            }

            if (elem.hasAttribute("translate")) {
                if (isAnyOf(elem.getAttribute("translate"), ["", "yes"])) {
                    enabled = true;
                } else if (isAnyOf(elem.getAttribute("translate"), ["no"])) {
                    enabled = false;
                }
            }

            if (enabled) {
                if (elem.hasAttribute("abbr") && elem.tagName === "TH") {
                    translateAttribute(elem, "abbr");
                }
                if (elem.hasAttribute("alt") && isAnyOf(elem.tagName, ["AREA", "IMG", "INPUT"])) {
                    translateAttribute(elem, "alt");
                }
                if (elem.hasAttribute("download") && isAnyOf(elem.tagName, ["A", "AREA"])) {
                    translateAttribute(elem, "download");
                }
                if (elem.hasAttribute("label") && isAnyOf(elem.tagName, ["MENUITEM", "MENU", "OPTGROUP", "OPTION", "TRACK"])) {
                    translateAttribute(elem, "label");
                }
                // FIXME: Should update "lang"
                if (elem.hasAttribute("placeholder") && isAnyOf(elem.tagName, ["INPUT", "TEXTAREA"])) {
                    translateAttribute(elem, "placeholder");
                }
                if (elem.hasAttribute("title")) {
                    translateAttribute(elem, "title");
                }
                if (elem.hasAttribute("value") && elem.tagName === "INPUT" && isAnyOf(elem.getAttribute("type"), ["reset", "button", "submit"])) {
                    translateAttribute(elem, "value");
                }
            }

            for (var i = 0; i < elem.childNodes.length; i++) {
                var node = elem.childNodes[i];
                if (node.nodeType === node.ELEMENT_NODE) {
                    process(node, enabled);
                } else if (node.nodeType === node.TEXT_NODE && enabled) {
                    translateTextNode(node);
                }
            }
        }

        process(document.body, true);
    }
};

var l10n = exports.l10n = new Localizer();
exports.default = l10n.get.bind(l10n);
},{}],2:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});

var _logging = require('../core/util/logging.js');

var Log = _interopRequireWildcard(_logging);

var _localization = require('./localization.js');

var _localization2 = _interopRequireDefault(_localization);

var _browser = require('../core/util/browser.js');

var _events = require('../core/util/events.js');

var _keysym = require('../core/input/keysym.js');

var _keysym2 = _interopRequireDefault(_keysym);

var _keysymdef = require('../core/input/keysymdef.js');

var _keysymdef2 = _interopRequireDefault(_keysymdef);

var _keyboard = require('../core/input/keyboard.js');

var _keyboard2 = _interopRequireDefault(_keyboard);

var _rfb = require('../core/rfb.js');

var _rfb2 = _interopRequireDefault(_rfb);

var _display = require('../core/display.js');

var _display2 = _interopRequireDefault(_display);

var _webutil = require('./webutil.js');

var WebUtil = _interopRequireWildcard(_webutil);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Copyright (C) 2016 Samuel Mannehed for Cendio AB
 * Copyright (C) 2016 Pierre Ossman for Cendio AB
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

var UI = {

    connected: false,
    desktopName: "",

    statusTimeout: null,
    hideKeyboardTimeout: null,
    idleControlbarTimeout: null,
    closeControlbarTimeout: null,

    controlbarGrabbed: false,
    controlbarDrag: false,
    controlbarMouseDownClientY: 0,
    controlbarMouseDownOffsetY: 0,

    isSafari: false,
    lastKeyboardinput: null,
    defaultKeyboardinputLen: 100,

    inhibit_reconnect: true,
    reconnect_callback: null,
    reconnect_password: null,

    prime: function (callback) {
        if (document.readyState === "interactive" || document.readyState === "complete") {
            UI.load(callback);
        } else {
            document.addEventListener('DOMContentLoaded', UI.load.bind(UI, callback));
        }
    },

    // Setup rfb object, load settings from browser storage, then call
    // UI.init to setup the UI/menus
    load: function (callback) {
        WebUtil.initSettings(UI.start, callback);
    },

    // Render default UI and initialize settings menu
    start: function (callback) {

        // Setup global variables first
        UI.isSafari = navigator.userAgent.indexOf('Safari') !== -1 && navigator.userAgent.indexOf('Chrome') === -1;

        UI.initSettings();

        // Translate the DOM
        _localization.l10n.translateDOM();

        // Adapt the interface for touch screen devices
        if (_browser.isTouchDevice) {
            document.documentElement.classList.add("noVNC_touch");
            // Remove the address bar
            setTimeout(function () {
                window.scrollTo(0, 1);
            }, 100);
        }

        // Restore control bar position
        if (WebUtil.readSetting('controlbar_pos') === 'right') {
            UI.toggleControlbarSide();
        }

        UI.initFullscreen();

        // Setup event handlers
        UI.addControlbarHandlers();
        UI.addTouchSpecificHandlers();
        UI.addExtraKeysHandlers();
        UI.addMachineHandlers();
        UI.addConnectionControlHandlers();
        UI.addClipboardHandlers();
        UI.addSettingsHandlers();
        document.getElementById("noVNC_status").addEventListener('click', UI.hideStatus);

        // Bootstrap fallback input handler
        UI.keyboardinputReset();

        UI.openControlbar();

        UI.updateVisualState('init');

        document.documentElement.classList.remove("noVNC_loading");

        // *ali*
        //var autoconnect = WebUtil.getConfigVar('autoconnect', false);
        var autoconnect = UI.getSetting('autoconnect');
        if (autoconnect === 'true' || autoconnect == '1') {
            autoconnect = true;
            UI.connect();
        } else {
            autoconnect = false;
            // Show the connect panel on first load unless autoconnecting
            UI.openConnectPanel();
        }

        if (typeof callback === "function") {
            callback(UI.rfb);
        }
    },

    initFullscreen: function () {
        // Only show the button if fullscreen is properly supported
        // * Safari doesn't support alphanumerical input while in fullscreen
        if (!UI.isSafari && (document.documentElement.requestFullscreen || document.documentElement.mozRequestFullScreen || document.documentElement.webkitRequestFullscreen || document.body.msRequestFullscreen)) {
            document.getElementById('noVNC_fullscreen_button').classList.remove("noVNC_hidden");
            UI.addFullscreenHandlers();
        }
    },

    initSettings: function () {
        var i;

        // Logging selection dropdown
        var llevels = ['error', 'warn', 'info', 'debug'];
        for (i = 0; i < llevels.length; i += 1) {
            UI.addOption(document.getElementById('noVNC_setting_logging'), llevels[i], llevels[i]);
        }

        // Settings with immediate effects
        UI.initSetting('logging', 'warn');
        UI.updateLogging();

        // if port == 80 (or 443) then it won't be present and should be
        // set manually
        var port = window.location.port;
        if (!port) {
            if (window.location.protocol.substring(0, 5) == 'https') {
                port = 443;
            } else if (window.location.protocol.substring(0, 4) == 'http') {
                port = 80;
            }
        }

        /* Populate the controls if defaults are provided in the URL */
        UI.initSetting('host', window.location.hostname);
        UI.initSetting('port', port);
        UI.initSetting('encrypt', window.location.protocol === "https:");
        UI.initSetting('view_clip', false);
        UI.initSetting('resize', 'off');
        UI.initSetting('shared', true);
        UI.initSetting('view_only', false);
        UI.initSetting('path', 'websockify');
        UI.initSetting('repeaterID', '');
        UI.initSetting('reconnect', false);
        UI.initSetting('reconnect_delay', 5000);

        UI.setupSettingLabels();
    },
    // Adds a link to the label elements on the corresponding input elements
    setupSettingLabels: function () {
        var labels = document.getElementsByTagName('LABEL');
        for (var i = 0; i < labels.length; i++) {
            var htmlFor = labels[i].htmlFor;
            if (htmlFor != '') {
                var elem = document.getElementById(htmlFor);
                if (elem) elem.label = labels[i];
            } else {
                // If 'for' isn't set, use the first input element child
                var children = labels[i].children;
                for (var j = 0; j < children.length; j++) {
                    if (children[j].form !== undefined) {
                        children[j].label = labels[i];
                        break;
                    }
                }
            }
        }
    },

    /* ------^-------
    *     /INIT
    * ==============
    * EVENT HANDLERS
    * ------v------*/

    addControlbarHandlers: function () {
        document.getElementById("noVNC_control_bar").addEventListener('mousemove', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('mouseup', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('mousedown', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('keydown', UI.activateControlbar);

        document.getElementById("noVNC_control_bar").addEventListener('mousedown', UI.keepControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('keydown', UI.keepControlbar);

        document.getElementById("noVNC_view_drag_button").addEventListener('click', UI.toggleViewDrag);

        document.getElementById("noVNC_control_bar_handle").addEventListener('mousedown', UI.controlbarHandleMouseDown);
        document.getElementById("noVNC_control_bar_handle").addEventListener('mouseup', UI.controlbarHandleMouseUp);
        document.getElementById("noVNC_control_bar_handle").addEventListener('mousemove', UI.dragControlbarHandle);
        // resize events aren't available for elements
        window.addEventListener('resize', UI.updateControlbarHandle);

        var exps = document.getElementsByClassName("noVNC_expander");
        for (var i = 0; i < exps.length; i++) {
            exps[i].addEventListener('click', UI.toggleExpander);
        }
    },

    addTouchSpecificHandlers: function () {
        document.getElementById("noVNC_mouse_button0").addEventListener('click', function () {
            UI.setMouseButton(1);
        });
        document.getElementById("noVNC_mouse_button1").addEventListener('click', function () {
            UI.setMouseButton(2);
        });
        document.getElementById("noVNC_mouse_button2").addEventListener('click', function () {
            UI.setMouseButton(4);
        });
        document.getElementById("noVNC_mouse_button4").addEventListener('click', function () {
            UI.setMouseButton(0);
        });
        document.getElementById("noVNC_keyboard_button").addEventListener('click', UI.toggleVirtualKeyboard);

        UI.touchKeyboard = new _keyboard2.default(document.getElementById('noVNC_keyboardinput'));
        UI.touchKeyboard.onkeyevent = UI.keyEvent;
        UI.touchKeyboard.grab();
        document.getElementById("noVNC_keyboardinput").addEventListener('input', UI.keyInput);
        document.getElementById("noVNC_keyboardinput").addEventListener('focus', UI.onfocusVirtualKeyboard);
        document.getElementById("noVNC_keyboardinput").addEventListener('blur', UI.onblurVirtualKeyboard);
        document.getElementById("noVNC_keyboardinput").addEventListener('submit', function () {
            return false;
        });

        document.documentElement.addEventListener('mousedown', UI.keepVirtualKeyboard, true);

        document.getElementById("noVNC_control_bar").addEventListener('touchstart', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('touchmove', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('touchend', UI.activateControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('input', UI.activateControlbar);

        document.getElementById("noVNC_control_bar").addEventListener('touchstart', UI.keepControlbar);
        document.getElementById("noVNC_control_bar").addEventListener('input', UI.keepControlbar);

        document.getElementById("noVNC_control_bar_handle").addEventListener('touchstart', UI.controlbarHandleMouseDown);
        document.getElementById("noVNC_control_bar_handle").addEventListener('touchend', UI.controlbarHandleMouseUp);
        document.getElementById("noVNC_control_bar_handle").addEventListener('touchmove', UI.dragControlbarHandle);
    },

    addExtraKeysHandlers: function () {
        document.getElementById("noVNC_toggle_extra_keys_button").addEventListener('click', UI.toggleExtraKeys);
        document.getElementById("noVNC_toggle_ctrl_button").addEventListener('click', UI.toggleCtrl);
        document.getElementById("noVNC_toggle_alt_button").addEventListener('click', UI.toggleAlt);
        document.getElementById("noVNC_send_tab_button").addEventListener('click', UI.sendTab);
        document.getElementById("noVNC_send_esc_button").addEventListener('click', UI.sendEsc);
        document.getElementById("noVNC_send_ctrl_alt_del_button").addEventListener('click', UI.sendCtrlAltDel);
    },

    addMachineHandlers: function () {
        document.getElementById("noVNC_shutdown_button").addEventListener('click', function () {
            UI.rfb.machineShutdown();
        });
        document.getElementById("noVNC_reboot_button").addEventListener('click', function () {
            UI.rfb.machineReboot();
        });
        document.getElementById("noVNC_reset_button").addEventListener('click', function () {
            UI.rfb.machineReset();
        });
        document.getElementById("noVNC_power_button").addEventListener('click', UI.togglePowerPanel);
    },

    addConnectionControlHandlers: function () {
        document.getElementById("noVNC_disconnect_button").addEventListener('click', UI.disconnect);
        document.getElementById("noVNC_connect_button").addEventListener('click', UI.connect);
        document.getElementById("noVNC_cancel_reconnect_button").addEventListener('click', UI.cancelReconnect);

        document.getElementById("noVNC_password_button").addEventListener('click', UI.setPassword);
    },

    addClipboardHandlers: function () {
        document.getElementById("noVNC_clipboard_button").addEventListener('click', UI.toggleClipboardPanel);
        document.getElementById("noVNC_clipboard_text").addEventListener('change', UI.clipboardSend);
        document.getElementById("noVNC_clipboard_clear_button").addEventListener('click', UI.clipboardClear);
    },

    // Add a call to save settings when the element changes,
    // unless the optional parameter changeFunc is used instead.
    addSettingChangeHandler: function (name, changeFunc) {
        var settingElem = document.getElementById("noVNC_setting_" + name);
        if (changeFunc === undefined) {
            changeFunc = function () {
                UI.saveSetting(name);
            };
        }
        settingElem.addEventListener('change', changeFunc);
    },

    addSettingsHandlers: function () {
        document.getElementById("noVNC_settings_button").addEventListener('click', UI.toggleSettingsPanel);

        UI.addSettingChangeHandler('encrypt');
        UI.addSettingChangeHandler('resize');
        UI.addSettingChangeHandler('resize', UI.enableDisableViewClip);
        UI.addSettingChangeHandler('resize', UI.applyResizeMode);
        UI.addSettingChangeHandler('view_clip');
        UI.addSettingChangeHandler('view_clip', UI.updateViewClip);
        UI.addSettingChangeHandler('shared');
        UI.addSettingChangeHandler('view_only');
        UI.addSettingChangeHandler('view_only', UI.updateViewOnly);
        UI.addSettingChangeHandler('host');
        UI.addSettingChangeHandler('port');
        UI.addSettingChangeHandler('path');
        UI.addSettingChangeHandler('repeaterID');
        UI.addSettingChangeHandler('logging');
        UI.addSettingChangeHandler('logging', UI.updateLogging);
        UI.addSettingChangeHandler('reconnect');
        UI.addSettingChangeHandler('reconnect_delay');
    },

    addFullscreenHandlers: function () {
        document.getElementById("noVNC_fullscreen_button").addEventListener('click', UI.toggleFullscreen);
        document.getElementById("fullscreen_button").addEventListener('click', UI.toggleFullscreen);

        window.addEventListener('fullscreenchange', UI.updateFullscreenButton);
        window.addEventListener('mozfullscreenchange', UI.updateFullscreenButton);
        window.addEventListener('webkitfullscreenchange', UI.updateFullscreenButton);
        window.addEventListener('msfullscreenchange', UI.updateFullscreenButton);
    },

    /* ------^-------
     * /EVENT HANDLERS
     * ==============
     *     VISUAL
     * ------v------*/

    // Disable/enable controls depending on connection state
    updateVisualState: function (state) {

        document.documentElement.classList.remove("noVNC_connecting");
        document.documentElement.classList.remove("noVNC_connected");
        document.documentElement.classList.remove("noVNC_disconnecting");
        document.documentElement.classList.remove("noVNC_reconnecting");

        let transition_elem = document.getElementById("noVNC_transition_text");
        switch (state) {
            case 'init':
                break;
            case 'connecting':
                transition_elem.textContent = (0, _localization2.default)("Connecting...");
                document.documentElement.classList.add("noVNC_connecting");
                break;
            case 'connected':
                document.documentElement.classList.add("noVNC_connected");
                break;
            case 'disconnecting':
                transition_elem.textContent = (0, _localization2.default)("Disconnecting...");
                document.documentElement.classList.add("noVNC_disconnecting");
                break;
            case 'disconnected':
                break;
            case 'reconnecting':
                transition_elem.textContent = (0, _localization2.default)("Reconnecting...");
                document.documentElement.classList.add("noVNC_reconnecting");
                break;
            default:
                Log.Error("Invalid visual state: " + state);
                UI.showStatus((0, _localization2.default)("Internal error"), 'error');
                return;
        }

        UI.enableDisableViewClip();

        if (UI.connected) {
            UI.disableSetting('encrypt');
            UI.disableSetting('shared');
            UI.disableSetting('host');
            UI.disableSetting('port');
            UI.disableSetting('path');
            UI.disableSetting('repeaterID');
            UI.setMouseButton(1);

            // Hide the controlbar after 2 seconds
            UI.closeControlbarTimeout = setTimeout(UI.closeControlbar, 2000);
        } else {
            UI.enableSetting('encrypt');
            UI.enableSetting('shared');
            UI.enableSetting('host');
            UI.enableSetting('port');
            UI.enableSetting('path');
            UI.enableSetting('repeaterID');
            UI.updatePowerButton();
            UI.keepControlbar();
        }

        // State change disables viewport dragging.
        // It is enabled (toggled) by direct click on the button
        UI.setViewDrag(false);

        // State change also closes the password dialog
        document.getElementById('noVNC_password_dlg').classList.remove('noVNC_open');
    },

    showStatus: function (text, status_type, time) {
        var statusElem = document.getElementById('noVNC_status');

        clearTimeout(UI.statusTimeout);

        if (typeof status_type === 'undefined') {
            status_type = 'normal';
        }

        // Don't overwrite more severe visible statuses and never
        // errors. Only shows the first error.
        let visible_status_type = 'none';
        if (statusElem.classList.contains("noVNC_open")) {
            if (statusElem.classList.contains("noVNC_status_error")) {
                visible_status_type = 'error';
            } else if (statusElem.classList.contains("noVNC_status_warn")) {
                visible_status_type = 'warn';
            } else {
                visible_status_type = 'normal';
            }
        }
        if (visible_status_type === 'error' || visible_status_type === 'warn' && status_type === 'normal') {
            return;
        }

        switch (status_type) {
            case 'error':
                statusElem.classList.remove("noVNC_status_warn");
                statusElem.classList.remove("noVNC_status_normal");
                statusElem.classList.add("noVNC_status_error");
                break;
            case 'warning':
            case 'warn':
                statusElem.classList.remove("noVNC_status_error");
                statusElem.classList.remove("noVNC_status_normal");
                statusElem.classList.add("noVNC_status_warn");
                break;
            case 'normal':
            case 'info':
            default:
                statusElem.classList.remove("noVNC_status_error");
                statusElem.classList.remove("noVNC_status_warn");
                statusElem.classList.add("noVNC_status_normal");
                break;
        }

        statusElem.textContent = text;
        statusElem.classList.add("noVNC_open");

        // If no time was specified, show the status for 1.5 seconds
        if (typeof time === 'undefined') {
            time = 1500;
        }

        // Error messages do not timeout
        if (status_type !== 'error') {
            UI.statusTimeout = window.setTimeout(UI.hideStatus, time);
        }
    },

    hideStatus: function () {
        clearTimeout(UI.statusTimeout);
        document.getElementById('noVNC_status').classList.remove("noVNC_open");
    },

    activateControlbar: function (event) {
        clearTimeout(UI.idleControlbarTimeout);
        // We manipulate the anchor instead of the actual control
        // bar in order to avoid creating new a stacking group
        document.getElementById('noVNC_control_bar_anchor').classList.remove("noVNC_idle");
        UI.idleControlbarTimeout = window.setTimeout(UI.idleControlbar, 2000);
    },

    idleControlbar: function () {
        document.getElementById('noVNC_control_bar_anchor').classList.add("noVNC_idle");
    },

    keepControlbar: function () {
        clearTimeout(UI.closeControlbarTimeout);
    },

    openControlbar: function () {
        document.getElementById('noVNC_control_bar').classList.add("noVNC_open");
    },

    closeControlbar: function () {
        UI.closeAllPanels();
        document.getElementById('noVNC_control_bar').classList.remove("noVNC_open");
    },

    toggleControlbar: function () {
        if (document.getElementById('noVNC_control_bar').classList.contains("noVNC_open")) {
            UI.closeControlbar();
        } else {
            UI.openControlbar();
        }
    },

    toggleControlbarSide: function () {
        // Temporarily disable animation to avoid weird movement
        var bar = document.getElementById('noVNC_control_bar');
        bar.style.transitionDuration = '0s';
        bar.addEventListener('transitionend', function () {
            this.style.transitionDuration = "";
        });

        var anchor = document.getElementById('noVNC_control_bar_anchor');
        if (anchor.classList.contains("noVNC_right")) {
            WebUtil.writeSetting('controlbar_pos', 'left');
            anchor.classList.remove("noVNC_right");
        } else {
            WebUtil.writeSetting('controlbar_pos', 'right');
            anchor.classList.add("noVNC_right");
        }

        // Consider this a movement of the handle
        UI.controlbarDrag = true;
    },

    showControlbarHint: function (show) {
        var hint = document.getElementById('noVNC_control_bar_hint');
        if (show) {
            hint.classList.add("noVNC_active");
        } else {
            hint.classList.remove("noVNC_active");
        }
    },

    dragControlbarHandle: function (e) {
        if (!UI.controlbarGrabbed) return;

        var ptr = (0, _events.getPointerEvent)(e);

        var anchor = document.getElementById('noVNC_control_bar_anchor');
        if (ptr.clientX < window.innerWidth * 0.1) {
            if (anchor.classList.contains("noVNC_right")) {
                UI.toggleControlbarSide();
            }
        } else if (ptr.clientX > window.innerWidth * 0.9) {
            if (!anchor.classList.contains("noVNC_right")) {
                UI.toggleControlbarSide();
            }
        }

        if (!UI.controlbarDrag) {
            // The goal is to trigger on a certain physical width, the
            // devicePixelRatio brings us a bit closer but is not optimal.
            var dragThreshold = 10 * (window.devicePixelRatio || 1);
            var dragDistance = Math.abs(ptr.clientY - UI.controlbarMouseDownClientY);

            if (dragDistance < dragThreshold) return;

            UI.controlbarDrag = true;
        }

        var eventY = ptr.clientY - UI.controlbarMouseDownOffsetY;

        UI.moveControlbarHandle(eventY);

        e.preventDefault();
        e.stopPropagation();
        UI.keepControlbar();
        UI.activateControlbar();
    },

    // Move the handle but don't allow any position outside the bounds
    moveControlbarHandle: function (viewportRelativeY) {
        var handle = document.getElementById("noVNC_control_bar_handle");
        var handleHeight = handle.getBoundingClientRect().height;
        var controlbarBounds = document.getElementById("noVNC_control_bar").getBoundingClientRect();
        var margin = 10;

        // These heights need to be non-zero for the below logic to work
        if (handleHeight === 0 || controlbarBounds.height === 0) {
            return;
        }

        var newY = viewportRelativeY;

        // Check if the coordinates are outside the control bar
        if (newY < controlbarBounds.top + margin) {
            // Force coordinates to be below the top of the control bar
            newY = controlbarBounds.top + margin;
        } else if (newY > controlbarBounds.top + controlbarBounds.height - handleHeight - margin) {
            // Force coordinates to be above the bottom of the control bar
            newY = controlbarBounds.top + controlbarBounds.height - handleHeight - margin;
        }

        // Corner case: control bar too small for stable position
        if (controlbarBounds.height < handleHeight + margin * 2) {
            newY = controlbarBounds.top + (controlbarBounds.height - handleHeight) / 2;
        }

        // The transform needs coordinates that are relative to the parent
        var parentRelativeY = newY - controlbarBounds.top;
        handle.style.transform = "translateY(" + parentRelativeY + "px)";
    },

    updateControlbarHandle: function () {
        // Since the control bar is fixed on the viewport and not the page,
        // the move function expects coordinates relative the the viewport.
        var handle = document.getElementById("noVNC_control_bar_handle");
        var handleBounds = handle.getBoundingClientRect();
        UI.moveControlbarHandle(handleBounds.top);
    },

    controlbarHandleMouseUp: function (e) {
        if (e.type == "mouseup" && e.button != 0) return;

        // mouseup and mousedown on the same place toggles the controlbar
        if (UI.controlbarGrabbed && !UI.controlbarDrag) {
            UI.toggleControlbar();
            e.preventDefault();
            e.stopPropagation();
            UI.keepControlbar();
            UI.activateControlbar();
        }
        UI.controlbarGrabbed = false;
        UI.showControlbarHint(false);
    },

    controlbarHandleMouseDown: function (e) {
        if (e.type == "mousedown" && e.button != 0) return;

        var ptr = (0, _events.getPointerEvent)(e);

        var handle = document.getElementById("noVNC_control_bar_handle");
        var bounds = handle.getBoundingClientRect();

        // Touch events have implicit capture
        if (e.type === "mousedown") {
            (0, _events.setCapture)(handle);
        }

        UI.controlbarGrabbed = true;
        UI.controlbarDrag = false;

        UI.showControlbarHint(true);

        UI.controlbarMouseDownClientY = ptr.clientY;
        UI.controlbarMouseDownOffsetY = ptr.clientY - bounds.top;
        e.preventDefault();
        e.stopPropagation();
        UI.keepControlbar();
        UI.activateControlbar();
    },

    toggleExpander: function (e) {
        if (this.classList.contains("noVNC_open")) {
            this.classList.remove("noVNC_open");
        } else {
            this.classList.add("noVNC_open");
        }
    },

    /* ------^-------
     *    /VISUAL
     * ==============
     *    SETTINGS
     * ------v------*/

    // Initial page load read/initialization of settings
    initSetting: function (name, defVal) {
        // Check Query string followed by cookie
        var val = WebUtil.getConfigVar(name);
        if (val === null) {
            val = WebUtil.readSetting(name, defVal);
        }
        UI.updateSetting(name, val);
        return val;
    },

    // Update cookie and form control setting. If value is not set, then
    // updates from control to current cookie setting.
    updateSetting: function (name, value) {

        // Save the cookie for this session
        if (typeof value !== 'undefined') {
            WebUtil.writeSetting(name, value);
        }

        // Update the settings control
        value = UI.getSetting(name);

        var ctrl = document.getElementById('noVNC_setting_' + name);
        if (ctrl.type === 'checkbox') {
            ctrl.checked = value;
        } else if (typeof ctrl.options !== 'undefined') {
            for (var i = 0; i < ctrl.options.length; i += 1) {
                if (ctrl.options[i].value === value) {
                    ctrl.selectedIndex = i;
                    break;
                }
            }
        } else {
            /*Weird IE9 error leads to 'null' appearring
            in textboxes instead of ''.*/
            if (value === null) {
                value = "";
            }
            ctrl.value = value;
        }
    },

    // Save control setting to cookie
    saveSetting: function (name) {
        var val,
            ctrl = document.getElementById('noVNC_setting_' + name);
        if (ctrl.type === 'checkbox') {
            val = ctrl.checked;
        } else if (typeof ctrl.options !== 'undefined') {
            val = ctrl.options[ctrl.selectedIndex].value;
        } else {
            val = ctrl.value;
        }
        WebUtil.writeSetting(name, val);
        //Log.Debug("Setting saved '" + name + "=" + val + "'");
        return val;
    },

    // Read form control compatible setting from cookie
    getSetting: function (name) {
        var ctrl = document.getElementById('noVNC_setting_' + name);
        var val = WebUtil.readSetting(name);
        if (typeof val !== 'undefined' && val !== null && ctrl.type === 'checkbox') {
            if (val.toString().toLowerCase() in { '0': 1, 'no': 1, 'false': 1 }) {
                val = false;
            } else {
                val = true;
            }
        } else if (ctrl.value !== 'undefined' && ctrl.value !== null) {
            val = ctrl.value;
        }
        return val;
    },

    // These helpers compensate for the lack of parent-selectors and
    // previous-sibling-selectors in CSS which are needed when we want to
    // disable the labels that belong to disabled input elements.
    disableSetting: function (name) {
        var ctrl = document.getElementById('noVNC_setting_' + name);
        ctrl.disabled = true;
        ctrl.label.classList.add('noVNC_disabled');
    },

    enableSetting: function (name) {
        var ctrl = document.getElementById('noVNC_setting_' + name);
        ctrl.disabled = false;
        ctrl.label.classList.remove('noVNC_disabled');
    },

    /* ------^-------
     *   /SETTINGS
     * ==============
     *    PANELS
     * ------v------*/

    closeAllPanels: function () {
        UI.closeSettingsPanel();
        UI.closePowerPanel();
        UI.closeClipboardPanel();
        UI.closeExtraKeys();
    },

    /* ------^-------
     *   /PANELS
     * ==============
     * SETTINGS (panel)
     * ------v------*/

    openSettingsPanel: function () {
        UI.closeAllPanels();
        UI.openControlbar();

        // Refresh UI elements from saved cookies
        UI.updateSetting('encrypt');
        UI.updateSetting('view_clip');
        UI.updateSetting('resize');
        UI.updateSetting('shared');
        UI.updateSetting('view_only');
        UI.updateSetting('path');
        UI.updateSetting('repeaterID');
        UI.updateSetting('logging');
        UI.updateSetting('reconnect');
        UI.updateSetting('reconnect_delay');

        document.getElementById('noVNC_settings').classList.add("noVNC_open");
        document.getElementById('noVNC_settings_button').classList.add("noVNC_selected");
    },

    closeSettingsPanel: function () {
        document.getElementById('noVNC_settings').classList.remove("noVNC_open");
        document.getElementById('noVNC_settings_button').classList.remove("noVNC_selected");
    },

    toggleSettingsPanel: function () {
        if (document.getElementById('noVNC_settings').classList.contains("noVNC_open")) {
            UI.closeSettingsPanel();
        } else {
            UI.openSettingsPanel();
        }
    },

    /* ------^-------
     *   /SETTINGS
     * ==============
     *     POWER
     * ------v------*/

    openPowerPanel: function () {
        UI.closeAllPanels();
        UI.openControlbar();

        document.getElementById('noVNC_power').classList.add("noVNC_open");
        document.getElementById('noVNC_power_button').classList.add("noVNC_selected");
    },

    closePowerPanel: function () {
        document.getElementById('noVNC_power').classList.remove("noVNC_open");
        document.getElementById('noVNC_power_button').classList.remove("noVNC_selected");
    },

    togglePowerPanel: function () {
        if (document.getElementById('noVNC_power').classList.contains("noVNC_open")) {
            UI.closePowerPanel();
        } else {
            UI.openPowerPanel();
        }
    },

    // Disable/enable power button
    updatePowerButton: function () {
        if (UI.connected && UI.rfb.capabilities.power && !UI.rfb.viewOnly) {
            document.getElementById('noVNC_power_button').classList.remove("noVNC_hidden");
        } else {
            document.getElementById('noVNC_power_button').classList.add("noVNC_hidden");
            // Close power panel if open
            UI.closePowerPanel();
        }
    },

    /* ------^-------
     *    /POWER
     * ==============
     *   CLIPBOARD
     * ------v------*/

    openClipboardPanel: function () {
        UI.closeAllPanels();
        UI.openControlbar();

        document.getElementById('noVNC_clipboard').classList.add("noVNC_open");
        document.getElementById('noVNC_clipboard_button').classList.add("noVNC_selected");
    },

    closeClipboardPanel: function () {
        document.getElementById('noVNC_clipboard').classList.remove("noVNC_open");
        document.getElementById('noVNC_clipboard_button').classList.remove("noVNC_selected");
    },

    toggleClipboardPanel: function () {
        if (document.getElementById('noVNC_clipboard').classList.contains("noVNC_open")) {
            UI.closeClipboardPanel();
        } else {
            UI.openClipboardPanel();
        }
    },

    clipboardReceive: function (e) {
        Log.Debug(">> UI.clipboardReceive: " + e.detail.text.substr(0, 40) + "...");
        document.getElementById('noVNC_clipboard_text').value = e.detail.text;
        Log.Debug("<< UI.clipboardReceive");
    },

    clipboardClear: function () {
        document.getElementById('noVNC_clipboard_text').value = "";
        UI.rfb.clipboardPasteFrom("");
    },

    clipboardSend: function () {
        var text = document.getElementById('noVNC_clipboard_text').value;
        Log.Debug(">> UI.clipboardSend: " + text.substr(0, 40) + "...");
        UI.rfb.clipboardPasteFrom(text);
        Log.Debug("<< UI.clipboardSend");
    },

    /* ------^-------
     *  /CLIPBOARD
     * ==============
     *  CONNECTION
     * ------v------*/

    openConnectPanel: function () {
        document.getElementById('noVNC_connect_dlg').classList.add("noVNC_open");
    },

    closeConnectPanel: function () {
        document.getElementById('noVNC_connect_dlg').classList.remove("noVNC_open");
    },

    connect: function (event, password) {

        // Ignore when rfb already exists
        if (typeof UI.rfb !== 'undefined') {
            return;
        }

        var host = UI.getSetting('host');
        var port = UI.getSetting('port');
        var path = UI.getSetting('path');

        if (typeof password === 'undefined') {
            password = WebUtil.getConfigVar('password');
            UI.reconnect_password = password;
        }

        if (password === null) {
            password = undefined;
        }

        UI.hideStatus();

        if (!host) {
            Log.Error("Can't connect when host is: " + host);
            UI.showStatus((0, _localization2.default)("Must set host"), 'error');
            return;
        }

        UI.closeAllPanels();
        UI.closeConnectPanel();

        UI.updateVisualState('connecting');

        var url;

        url = UI.getSetting('encrypt') ? 'wss' : 'ws';

        url += '://' + host;
        if (port) {
            url += ':' + port;
        }
        url += '/' + path;

        UI.rfb = new _rfb2.default(document.getElementById('noVNC_container'), url, { shared: UI.getSetting('shared'),
            repeaterID: UI.getSetting('repeaterID'),
            credentials: { password: password } });
        UI.rfb.addEventListener("connect", UI.connectFinished);
        UI.rfb.addEventListener("disconnect", UI.disconnectFinished);
        UI.rfb.addEventListener("credentialsrequired", UI.credentials);
        UI.rfb.addEventListener("securityfailure", UI.securityFailed);
        UI.rfb.addEventListener("capabilities", function () {
            UI.updatePowerButton();
        });
        UI.rfb.addEventListener("clipboard", UI.clipboardReceive);
        UI.rfb.addEventListener("bell", UI.bell);
        UI.rfb.addEventListener("desktopname", UI.updateDesktopName);
        UI.rfb.clipViewport = UI.getSetting('view_clip');
        UI.rfb.scaleViewport = UI.getSetting('resize') === 'scale';
        UI.rfb.resizeSession = UI.getSetting('resize') === 'remote';

        UI.updateViewOnly(); // requires UI.rfb
    },

    disconnect: function () {
        UI.closeAllPanels();
        UI.rfb.disconnect();

        UI.connected = false;

        // Disable automatic reconnecting
        UI.inhibit_reconnect = true;

        UI.updateVisualState('disconnecting');

        // Don't display the connection settings until we're actually disconnected
    },

    reconnect: function () {
        UI.reconnect_callback = null;

        // if reconnect has been disabled in the meantime, do nothing.
        if (UI.inhibit_reconnect) {
            return;
        }

        UI.connect(null, UI.reconnect_password);
    },

    cancelReconnect: function () {
        if (UI.reconnect_callback !== null) {
            clearTimeout(UI.reconnect_callback);
            UI.reconnect_callback = null;
        }

        UI.updateVisualState('disconnected');

        UI.openControlbar();
        UI.openConnectPanel();
    },

    connectFinished: function (e) {
        UI.connected = true;
        UI.inhibit_reconnect = false;

        let msg;
        if (UI.getSetting('encrypt')) {
            msg = (0, _localization2.default)("Connected (encrypted) to ") + UI.desktopName;
        } else {
            msg = (0, _localization2.default)("Connected (unencrypted) to ") + UI.desktopName;
        }
        UI.showStatus(msg);
        UI.updateVisualState('connected');

        // Do this last because it can only be used on rendered elements
        UI.rfb.focus();
    },

    disconnectFinished: function (e) {
        let wasConnected = UI.connected;

        // This variable is ideally set when disconnection starts, but
        // when the disconnection isn't clean or if it is initiated by
        // the server, we need to do it here as well since
        // UI.disconnect() won't be used in those cases.
        UI.connected = false;

        UI.rfb = undefined;

        if (!e.detail.clean) {
            UI.updateVisualState('disconnected');
            if (wasConnected) {
                UI.showStatus((0, _localization2.default)("Something went wrong, connection is closed"), 'error');
            } else {
                UI.showStatus((0, _localization2.default)("Failed to connect to server"), 'error');
            }
        } else if (UI.getSetting('reconnect', false) === true && !UI.inhibit_reconnect) {
            UI.updateVisualState('reconnecting');

            var delay = parseInt(UI.getSetting('reconnect_delay'));
            UI.reconnect_callback = setTimeout(UI.reconnect, delay);
            return;
        } else {
            UI.updateVisualState('disconnected');
            UI.showStatus((0, _localization2.default)("Disconnected"), 'normal');
        }

        UI.openControlbar();
        UI.openConnectPanel();
    },

    securityFailed: function (e) {
        let msg = "";
        // On security failures we might get a string with a reason
        // directly from the server. Note that we can't control if
        // this string is translated or not.
        if ('reason' in e.detail) {
            msg = (0, _localization2.default)("New connection has been rejected with reason: ") + e.detail.reason;
        } else {
            msg = (0, _localization2.default)("New connection has been rejected");
        }
        UI.showStatus(msg, 'error');
    },

    /* ------^-------
     *  /CONNECTION
     * ==============
     *   PASSWORD
     * ------v------*/

    credentials: function (e) {
        // FIXME: handle more types
        document.getElementById('noVNC_password_dlg').classList.add('noVNC_open');

        setTimeout(function () {
            document.getElementById('noVNC_password_input').focus();
        }, 100);

        Log.Warn("Server asked for a password");
        UI.showStatus((0, _localization2.default)("Password is required"), "warning");
    },

    setPassword: function (e) {
        // Prevent actually submitting the form
        e.preventDefault();

        var inputElem = document.getElementById('noVNC_password_input');
        var password = inputElem.value;
        // Clear the input after reading the password
        inputElem.value = "";
        UI.rfb.sendCredentials({ password: password });
        UI.reconnect_password = password;
        document.getElementById('noVNC_password_dlg').classList.remove('noVNC_open');
    },

    /* ------^-------
     *  /PASSWORD
     * ==============
     *   FULLSCREEN
     * ------v------*/

    fullscreen: function () {
        UI.toggleFullscreen();
    },

    toggleFullscreen: function () {
        if (document.fullscreenElement || // alternative standard method
        document.mozFullScreenElement || // currently working methods
        document.webkitFullscreenElement || document.msFullscreenElement) {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.mozCancelFullScreen) {
                document.mozCancelFullScreen();
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) {
                document.msExitFullscreen();
            }
        } else {
            if (document.documentElement.requestFullscreen) {
                document.documentElement.requestFullscreen();
            } else if (document.documentElement.mozRequestFullScreen) {
                document.documentElement.mozRequestFullScreen();
            } else if (document.documentElement.webkitRequestFullscreen) {
                document.documentElement.webkitRequestFullscreen(Element.ALLOW_KEYBOARD_INPUT);
            } else if (document.body.msRequestFullscreen) {
                document.body.msRequestFullscreen();
            }
        }
        UI.enableDisableViewClip();
        UI.updateFullscreenButton();
    },

    updateFullscreenButton: function () {
        if (document.fullscreenElement || // alternative standard method
        document.mozFullScreenElement || // currently working methods
        document.webkitFullscreenElement || document.msFullscreenElement) {
            document.getElementById('noVNC_fullscreen_button').classList.add("noVNC_selected");
        } else {
            document.getElementById('noVNC_fullscreen_button').classList.remove("noVNC_selected");
        }
    },

    /* ------^-------
     *  /FULLSCREEN
     * ==============
     *     RESIZE
     * ------v------*/

    // Apply remote resizing or local scaling
    applyResizeMode: function () {
        if (!UI.rfb) return;

        UI.rfb.scaleViewport = UI.getSetting('resize') === 'scale';
        UI.rfb.resizeSession = UI.getSetting('resize') === 'remote';
    },

    /* ------^-------
     *    /RESIZE
     * ==============
     * VIEW CLIPPING
     * ------v------*/

    // Update parameters that depend on the viewport clip setting
    updateViewClip: function () {
        if (!UI.rfb) return;

        var cur_clip = UI.rfb.clipViewport;
        var new_clip = UI.getSetting('view_clip');

        if (_browser.isTouchDevice) {
            // Touch devices usually have shit scrollbars
            new_clip = true;
        }

        if (cur_clip !== new_clip) {
            UI.rfb.clipViewport = new_clip;
        }

        // Changing the viewport may change the state of
        // the dragging button
        UI.updateViewDrag();
    },

    // Handle special cases where viewport clipping is forced on/off or locked
    enableDisableViewClip: function () {
        var resizeSetting = UI.getSetting('resize');
        // Disable clipping if we are scaling, connected or on touch
        if (resizeSetting === 'scale' || _browser.isTouchDevice) {
            UI.disableSetting('view_clip');
        } else {
            UI.enableSetting('view_clip');
        }
    },

    /* ------^-------
     * /VIEW CLIPPING
     * ==============
     *    VIEWDRAG
     * ------v------*/

    toggleViewDrag: function () {
        if (!UI.rfb) return;

        var drag = UI.rfb.dragViewport;
        UI.setViewDrag(!drag);
    },

    // Set the view drag mode which moves the viewport on mouse drags
    setViewDrag: function (drag) {
        if (!UI.rfb) return;

        UI.rfb.dragViewport = drag;

        UI.updateViewDrag();
    },

    updateViewDrag: function () {
        if (!UI.connected) return;

        var viewDragButton = document.getElementById('noVNC_view_drag_button');

        if (!UI.rfb.clipViewport && UI.rfb.dragViewport) {
            // We are no longer clipping the viewport. Make sure
            // viewport drag isn't active when it can't be used.
            UI.rfb.dragViewport = false;
        }

        if (UI.rfb.dragViewport) {
            viewDragButton.classList.add("noVNC_selected");
        } else {
            viewDragButton.classList.remove("noVNC_selected");
        }

        // Different behaviour for touch vs non-touch
        // The button is disabled instead of hidden on touch devices
        if (_browser.isTouchDevice) {
            viewDragButton.classList.remove("noVNC_hidden");

            if (UI.rfb.clipViewport) {
                viewDragButton.disabled = false;
            } else {
                viewDragButton.disabled = true;
            }
        } else {
            viewDragButton.disabled = false;

            if (UI.rfb.clipViewport) {
                viewDragButton.classList.remove("noVNC_hidden");
            } else {
                viewDragButton.classList.add("noVNC_hidden");
            }
        }
    },

    /* ------^-------
     *   /VIEWDRAG
     * ==============
     *    KEYBOARD
     * ------v------*/

    showVirtualKeyboard: function () {
        if (!_browser.isTouchDevice) return;

        var input = document.getElementById('noVNC_keyboardinput');

        if (document.activeElement == input) return;

        input.focus();

        try {
            var l = input.value.length;
            // Move the caret to the end
            input.setSelectionRange(l, l);
        } catch (err) {} // setSelectionRange is undefined in Google Chrome
    },

    hideVirtualKeyboard: function () {
        if (!_browser.isTouchDevice) return;

        var input = document.getElementById('noVNC_keyboardinput');

        if (document.activeElement != input) return;

        input.blur();
    },

    toggleVirtualKeyboard: function () {
        if (document.getElementById('noVNC_keyboard_button').classList.contains("noVNC_selected")) {
            UI.hideVirtualKeyboard();
        } else {
            UI.showVirtualKeyboard();
        }
    },

    onfocusVirtualKeyboard: function (event) {
        document.getElementById('noVNC_keyboard_button').classList.add("noVNC_selected");
        if (UI.rfb) {
            UI.rfb.focusOnClick = false;
        }
    },

    onblurVirtualKeyboard: function (event) {
        document.getElementById('noVNC_keyboard_button').classList.remove("noVNC_selected");
        if (UI.rfb) {
            UI.rfb.focusOnClick = true;
        }
    },

    keepVirtualKeyboard: function (event) {
        var input = document.getElementById('noVNC_keyboardinput');

        // Only prevent focus change if the virtual keyboard is active
        if (document.activeElement != input) {
            return;
        }

        // Only allow focus to move to other elements that need
        // focus to function properly
        if (event.target.form !== undefined) {
            switch (event.target.type) {
                case 'text':
                case 'email':
                case 'search':
                case 'password':
                case 'tel':
                case 'url':
                case 'textarea':
                case 'select-one':
                case 'select-multiple':
                    return;
            }
        }

        event.preventDefault();
    },

    keyboardinputReset: function () {
        var kbi = document.getElementById('noVNC_keyboardinput');
        kbi.value = new Array(UI.defaultKeyboardinputLen).join("_");
        UI.lastKeyboardinput = kbi.value;
    },

    keyEvent: function (keysym, code, down) {
        if (!UI.rfb) return;

        UI.rfb.sendKey(keysym, code, down);
    },

    // When normal keyboard events are left uncought, use the input events from
    // the keyboardinput element instead and generate the corresponding key events.
    // This code is required since some browsers on Android are inconsistent in
    // sending keyCodes in the normal keyboard events when using on screen keyboards.
    keyInput: function (event) {

        if (!UI.rfb) return;

        var newValue = event.target.value;

        if (!UI.lastKeyboardinput) {
            UI.keyboardinputReset();
        }
        var oldValue = UI.lastKeyboardinput;

        var newLen;
        try {
            // Try to check caret position since whitespace at the end
            // will not be considered by value.length in some browsers
            newLen = Math.max(event.target.selectionStart, newValue.length);
        } catch (err) {
            // selectionStart is undefined in Google Chrome
            newLen = newValue.length;
        }
        var oldLen = oldValue.length;

        var backspaces;
        var inputs = newLen - oldLen;
        if (inputs < 0) {
            backspaces = -inputs;
        } else {
            backspaces = 0;
        }

        // Compare the old string with the new to account for
        // text-corrections or other input that modify existing text
        var i;
        for (i = 0; i < Math.min(oldLen, newLen); i++) {
            if (newValue.charAt(i) != oldValue.charAt(i)) {
                inputs = newLen - i;
                backspaces = oldLen - i;
                break;
            }
        }

        // Send the key events
        for (i = 0; i < backspaces; i++) {
            UI.rfb.sendKey(_keysym2.default.XK_BackSpace, "Backspace");
        }
        for (i = newLen - inputs; i < newLen; i++) {
            UI.rfb.sendKey(_keysymdef2.default.lookup(newValue.charCodeAt(i)));
        }

        // Control the text content length in the keyboardinput element
        if (newLen > 2 * UI.defaultKeyboardinputLen) {
            UI.keyboardinputReset();
        } else if (newLen < 1) {
            // There always have to be some text in the keyboardinput
            // element with which backspace can interact.
            UI.keyboardinputReset();
            // This sometimes causes the keyboard to disappear for a second
            // but it is required for the android keyboard to recognize that
            // text has been added to the field
            event.target.blur();
            // This has to be ran outside of the input handler in order to work
            setTimeout(event.target.focus.bind(event.target), 0);
        } else {
            UI.lastKeyboardinput = newValue;
        }
    },

    /* ------^-------
     *   /KEYBOARD
     * ==============
     *   EXTRA KEYS
     * ------v------*/

    openExtraKeys: function () {
        UI.closeAllPanels();
        UI.openControlbar();

        document.getElementById('noVNC_modifiers').classList.add("noVNC_open");
        document.getElementById('noVNC_toggle_extra_keys_button').classList.add("noVNC_selected");
    },

    closeExtraKeys: function () {
        document.getElementById('noVNC_modifiers').classList.remove("noVNC_open");
        document.getElementById('noVNC_toggle_extra_keys_button').classList.remove("noVNC_selected");
    },

    toggleExtraKeys: function () {
        if (document.getElementById('noVNC_modifiers').classList.contains("noVNC_open")) {
            UI.closeExtraKeys();
        } else {
            UI.openExtraKeys();
        }
    },

    sendEsc: function () {
        UI.rfb.sendKey(_keysym2.default.XK_Escape, "Escape");
    },

    sendTab: function () {
        UI.rfb.sendKey(_keysym2.default.XK_Tab);
    },

    toggleCtrl: function () {
        var btn = document.getElementById('noVNC_toggle_ctrl_button');
        if (btn.classList.contains("noVNC_selected")) {
            UI.rfb.sendKey(_keysym2.default.XK_Control_L, "ControlLeft", false);
            btn.classList.remove("noVNC_selected");
        } else {
            UI.rfb.sendKey(_keysym2.default.XK_Control_L, "ControlLeft", true);
            btn.classList.add("noVNC_selected");
        }
    },

    toggleAlt: function () {
        var btn = document.getElementById('noVNC_toggle_alt_button');
        if (btn.classList.contains("noVNC_selected")) {
            UI.rfb.sendKey(_keysym2.default.XK_Alt_L, "AltLeft", false);
            btn.classList.remove("noVNC_selected");
        } else {
            UI.rfb.sendKey(_keysym2.default.XK_Alt_L, "AltLeft", true);
            btn.classList.add("noVNC_selected");
        }
    },

    sendCtrlAltDel: function () {
        UI.rfb.sendCtrlAltDel();
    },

    /* ------^-------
     *   /EXTRA KEYS
     * ==============
     *     MISC
     * ------v------*/

    setMouseButton: function (num) {
        var view_only = UI.rfb.viewOnly;
        if (UI.rfb && !view_only) {
            UI.rfb.touchButton = num;
        }

        var blist = [0, 1, 2, 4];
        for (var b = 0; b < blist.length; b++) {
            var button = document.getElementById('noVNC_mouse_button' + blist[b]);
            if (blist[b] === num && !view_only) {
                button.classList.remove("noVNC_hidden");
            } else {
                button.classList.add("noVNC_hidden");
            }
        }
    },

    updateViewOnly: function () {
        if (!UI.rfb) return;
        UI.rfb.viewOnly = UI.getSetting('view_only');

        // Hide input related buttons in view only mode
        if (UI.rfb.viewOnly) {
            document.getElementById('noVNC_keyboard_button').classList.add('noVNC_hidden');
            document.getElementById('noVNC_toggle_extra_keys_button').classList.add('noVNC_hidden');
        } else {
            document.getElementById('noVNC_keyboard_button').classList.remove('noVNC_hidden');
            document.getElementById('noVNC_toggle_extra_keys_button').classList.remove('noVNC_hidden');
        }
        UI.setMouseButton(1); //has it's own logic for hiding/showing
    },

    updateLogging: function () {
        WebUtil.init_logging(UI.getSetting('logging'));
    },

    updateDesktopName: function (e) {
        UI.desktopName = e.detail.name;
        // Display the desktop name in the document title
        document.title = e.detail.name + " - noVNC";
    },

    bell: function (e) {
        if (WebUtil.getConfigVar('bell', 'on') === 'on') {
            var promise = document.getElementById('noVNC_bell').play();
            // The standards disagree on the return value here
            if (promise) {
                promise.catch(function (e) {
                    if (e.name === "NotAllowedError") {
                        // Ignore when the browser doesn't let us play audio.
                        // It is common that the browsers require audio to be
                        // initiated from a user action.
                    } else {
                        Log.Error("Unable to play bell: " + e);
                    }
                });
            }
        }
    },

    //Helper to add options to dropdown.
    addOption: function (selectbox, text, value) {
        var optn = document.createElement("OPTION");
        optn.text = text;
        optn.value = value;
        selectbox.options.add(optn);
    }

    /* ------^-------
     *    /MISC
     * ==============
     */
};

// Set up translations
var LINGUAS = ["de", "el", "es", "nl", "pl", "sv", "tr", "zh"];
_localization.l10n.setup(LINGUAS);
if (_localization.l10n.language !== "en" && _localization.l10n.dictionary === undefined) {
    WebUtil.fetchJSON('../static/js/novnc/app/locale/' + _localization.l10n.language + '.json', function (translations) {
        _localization.l10n.dictionary = translations;

        // wait for translations to load before loading the UI
        UI.prime();
    }, function (err) {
        Log.Error("Failed to load translations: " + err);
        UI.prime();
    });
} else {
    UI.prime();
}

exports.default = UI;
},{"../core/display.js":6,"../core/input/keyboard.js":11,"../core/input/keysym.js":12,"../core/input/keysymdef.js":13,"../core/rfb.js":18,"../core/util/browser.js":19,"../core/util/events.js":20,"../core/util/logging.js":22,"./localization.js":1,"./webutil.js":3}],3:[function(require,module,exports){
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
},{"../core/util/logging.js":22}],4:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});

var _logging = require('./util/logging.js');

var Log = _interopRequireWildcard(_logging);

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

exports.default = {
    /* Convert data (an array of integers) to a Base64 string. */
    toBase64Table: 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/='.split(''),
    base64Pad: '=',

    encode: function (data) {
        "use strict";

        var result = '';
        var toBase64Table = this.toBase64Table;
        var length = data.length;
        var lengthpad = length % 3;
        // Convert every three bytes to 4 ascii characters.

        for (var i = 0; i < length - 2; i += 3) {
            result += toBase64Table[data[i] >> 2];
            result += toBase64Table[((data[i] & 0x03) << 4) + (data[i + 1] >> 4)];
            result += toBase64Table[((data[i + 1] & 0x0f) << 2) + (data[i + 2] >> 6)];
            result += toBase64Table[data[i + 2] & 0x3f];
        }

        // Convert the remaining 1 or 2 bytes, pad out to 4 characters.
        var j = 0;
        if (lengthpad === 2) {
            j = length - lengthpad;
            result += toBase64Table[data[j] >> 2];
            result += toBase64Table[((data[j] & 0x03) << 4) + (data[j + 1] >> 4)];
            result += toBase64Table[(data[j + 1] & 0x0f) << 2];
            result += toBase64Table[64];
        } else if (lengthpad === 1) {
            j = length - lengthpad;
            result += toBase64Table[data[j] >> 2];
            result += toBase64Table[(data[j] & 0x03) << 4];
            result += toBase64Table[64];
            result += toBase64Table[64];
        }

        return result;
    },

    /* Convert Base64 data to a string */
    toBinaryTable: [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, 62, -1, -1, -1, 63, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, -1, -1, -1, 0, -1, -1, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, -1, -1, -1, -1, -1, -1, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, -1, -1, -1, -1, -1],

    decode: function (data, offset) {
        "use strict";

        offset = typeof offset !== 'undefined' ? offset : 0;
        var toBinaryTable = this.toBinaryTable;
        var base64Pad = this.base64Pad;
        var result, result_length;
        var leftbits = 0; // number of bits decoded, but yet to be appended
        var leftdata = 0; // bits decoded, but yet to be appended
        var data_length = data.indexOf('=') - offset;

        if (data_length < 0) {
            data_length = data.length - offset;
        }

        /* Every four characters is 3 resulting numbers */
        result_length = (data_length >> 2) * 3 + Math.floor(data_length % 4 / 1.5);
        result = new Array(result_length);

        // Convert one by one.
        for (var idx = 0, i = offset; i < data.length; i++) {
            var c = toBinaryTable[data.charCodeAt(i) & 0x7f];
            var padding = data.charAt(i) === base64Pad;
            // Skip illegal characters and whitespace
            if (c === -1) {
                Log.Error("Illegal character code " + data.charCodeAt(i) + " at position " + i);
                continue;
            }

            // Collect data into leftdata, update bitcount
            leftdata = leftdata << 6 | c;
            leftbits += 6;

            // If we have 8 or more bits, append 8 bits to the result
            if (leftbits >= 8) {
                leftbits -= 8;
                // Append if not padding.
                if (!padding) {
                    result[idx++] = leftdata >> leftbits & 0xff;
                }
                leftdata &= (1 << leftbits) - 1;
            }
        }

        // If there are any bits left, the base64 string was corrupted
        if (leftbits) {
            err = new Error('Corrupted base64 string');
            err.name = 'Base64-Error';
            throw err;
        }

        return result;
    }
}; /* End of Base64 namespace */
/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// From: http://hg.mozilla.org/mozilla-central/raw-file/ec10630b1a54/js/src/devtools/jint/sunspider/string-base64.js
},{"./util/logging.js":22}],5:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = DES;
/*
 * Ported from Flashlight VNC ActionScript implementation:
 *     http://www.wizhelp.com/flashlight-vnc/
 *
 * Full attribution follows:
 *
 * -------------------------------------------------------------------------
 *
 * This DES class has been extracted from package Acme.Crypto for use in VNC.
 * The unnecessary odd parity code has been removed.
 *
 * These changes are:
 *  Copyright (C) 1999 AT&T Laboratories Cambridge.  All Rights Reserved.
 *
 * This software is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
 *

 * DesCipher - the DES encryption method
 *
 * The meat of this code is by Dave Zimmerman <dzimm@widget.com>, and is:
 *
 * Copyright (c) 1996 Widget Workshop, Inc. All Rights Reserved.
 *
 * Permission to use, copy, modify, and distribute this software
 * and its documentation for NON-COMMERCIAL or COMMERCIAL purposes and
 * without fee is hereby granted, provided that this copyright notice is kept
 * intact.
 *
 * WIDGET WORKSHOP MAKES NO REPRESENTATIONS OR WARRANTIES ABOUT THE SUITABILITY
 * OF THE SOFTWARE, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
 * TO THE IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
 * PARTICULAR PURPOSE, OR NON-INFRINGEMENT. WIDGET WORKSHOP SHALL NOT BE LIABLE
 * FOR ANY DAMAGES SUFFERED BY LICENSEE AS A RESULT OF USING, MODIFYING OR
 * DISTRIBUTING THIS SOFTWARE OR ITS DERIVATIVES.
 *
 * THIS SOFTWARE IS NOT DESIGNED OR INTENDED FOR USE OR RESALE AS ON-LINE
 * CONTROL EQUIPMENT IN HAZARDOUS ENVIRONMENTS REQUIRING FAIL-SAFE
 * PERFORMANCE, SUCH AS IN THE OPERATION OF NUCLEAR FACILITIES, AIRCRAFT
 * NAVIGATION OR COMMUNICATION SYSTEMS, AIR TRAFFIC CONTROL, DIRECT LIFE
 * SUPPORT MACHINES, OR WEAPONS SYSTEMS, IN WHICH THE FAILURE OF THE
 * SOFTWARE COULD LEAD DIRECTLY TO DEATH, PERSONAL INJURY, OR SEVERE
 * PHYSICAL OR ENVIRONMENTAL DAMAGE ("HIGH RISK ACTIVITIES").  WIDGET WORKSHOP
 * SPECIFICALLY DISCLAIMS ANY EXPRESS OR IMPLIED WARRANTY OF FITNESS FOR
 * HIGH RISK ACTIVITIES.
 *
 *
 * The rest is:
 *
 * Copyright (C) 1996 by Jef Poskanzer <jef@acme.com>.  All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * Visit the ACME Labs Java page for up-to-date versions of this and other
 * fine Java utilities: http://www.acme.com/java/
 */

function DES(passwd) {
    "use strict";

    // Tables, permutations, S-boxes, etc.

    var PC2 = [13, 16, 10, 23, 0, 4, 2, 27, 14, 5, 20, 9, 22, 18, 11, 3, 25, 7, 15, 6, 26, 19, 12, 1, 40, 51, 30, 36, 46, 54, 29, 39, 50, 44, 32, 47, 43, 48, 38, 55, 33, 52, 45, 41, 49, 35, 28, 31],
        totrot = [1, 2, 4, 6, 8, 10, 12, 14, 15, 17, 19, 21, 23, 25, 27, 28],
        z = 0x0,
        a,
        b,
        c,
        d,
        e,
        f,
        SP1,
        SP2,
        SP3,
        SP4,
        SP5,
        SP6,
        SP7,
        SP8,
        keys = [];

    a = 1 << 16;b = 1 << 24;c = a | b;d = 1 << 2;e = 1 << 10;f = d | e;
    SP1 = [c | e, z | z, a | z, c | f, c | d, a | f, z | d, a | z, z | e, c | e, c | f, z | e, b | f, c | d, b | z, z | d, z | f, b | e, b | e, a | e, a | e, c | z, c | z, b | f, a | d, b | d, b | d, a | d, z | z, z | f, a | f, b | z, a | z, c | f, z | d, c | z, c | e, b | z, b | z, z | e, c | d, a | z, a | e, b | d, z | e, z | d, b | f, a | f, c | f, a | d, c | z, b | f, b | d, z | f, a | f, c | e, z | f, b | e, b | e, z | z, a | d, a | e, z | z, c | d];
    a = 1 << 20;b = 1 << 31;c = a | b;d = 1 << 5;e = 1 << 15;f = d | e;
    SP2 = [c | f, b | e, z | e, a | f, a | z, z | d, c | d, b | f, b | d, c | f, c | e, b | z, b | e, a | z, z | d, c | d, a | e, a | d, b | f, z | z, b | z, z | e, a | f, c | z, a | d, b | d, z | z, a | e, z | f, c | e, c | z, z | f, z | z, a | f, c | d, a | z, b | f, c | z, c | e, z | e, c | z, b | e, z | d, c | f, a | f, z | d, z | e, b | z, z | f, c | e, a | z, b | d, a | d, b | f, b | d, a | d, a | e, z | z, b | e, z | f, b | z, c | d, c | f, a | e];
    a = 1 << 17;b = 1 << 27;c = a | b;d = 1 << 3;e = 1 << 9;f = d | e;
    SP3 = [z | f, c | e, z | z, c | d, b | e, z | z, a | f, b | e, a | d, b | d, b | d, a | z, c | f, a | d, c | z, z | f, b | z, z | d, c | e, z | e, a | e, c | z, c | d, a | f, b | f, a | e, a | z, b | f, z | d, c | f, z | e, b | z, c | e, b | z, a | d, z | f, a | z, c | e, b | e, z | z, z | e, a | d, c | f, b | e, b | d, z | e, z | z, c | d, b | f, a | z, b | z, c | f, z | d, a | f, a | e, b | d, c | z, b | f, z | f, c | z, a | f, z | d, c | d, a | e];
    a = 1 << 13;b = 1 << 23;c = a | b;d = 1 << 0;e = 1 << 7;f = d | e;
    SP4 = [c | d, a | f, a | f, z | e, c | e, b | f, b | d, a | d, z | z, c | z, c | z, c | f, z | f, z | z, b | e, b | d, z | d, a | z, b | z, c | d, z | e, b | z, a | d, a | e, b | f, z | d, a | e, b | e, a | z, c | e, c | f, z | f, b | e, b | d, c | z, c | f, z | f, z | z, z | z, c | z, a | e, b | e, b | f, z | d, c | d, a | f, a | f, z | e, c | f, z | f, z | d, a | z, b | d, a | d, c | e, b | f, a | d, a | e, b | z, c | d, z | e, b | z, a | z, c | e];
    a = 1 << 25;b = 1 << 30;c = a | b;d = 1 << 8;e = 1 << 19;f = d | e;
    SP5 = [z | d, a | f, a | e, c | d, z | e, z | d, b | z, a | e, b | f, z | e, a | d, b | f, c | d, c | e, z | f, b | z, a | z, b | e, b | e, z | z, b | d, c | f, c | f, a | d, c | e, b | d, z | z, c | z, a | f, a | z, c | z, z | f, z | e, c | d, z | d, a | z, b | z, a | e, c | d, b | f, a | d, b | z, c | e, a | f, b | f, z | d, a | z, c | e, c | f, z | f, c | z, c | f, a | e, z | z, b | e, c | z, z | f, a | d, b | d, z | e, z | z, b | e, a | f, b | d];
    a = 1 << 22;b = 1 << 29;c = a | b;d = 1 << 4;e = 1 << 14;f = d | e;
    SP6 = [b | d, c | z, z | e, c | f, c | z, z | d, c | f, a | z, b | e, a | f, a | z, b | d, a | d, b | e, b | z, z | f, z | z, a | d, b | f, z | e, a | e, b | f, z | d, c | d, c | d, z | z, a | f, c | e, z | f, a | e, c | e, b | z, b | e, z | d, c | d, a | e, c | f, a | z, z | f, b | d, a | z, b | e, b | z, z | f, b | d, c | f, a | e, c | z, a | f, c | e, z | z, c | d, z | d, z | e, c | z, a | f, z | e, a | d, b | f, z | z, c | e, b | z, a | d, b | f];
    a = 1 << 21;b = 1 << 26;c = a | b;d = 1 << 1;e = 1 << 11;f = d | e;
    SP7 = [a | z, c | d, b | f, z | z, z | e, b | f, a | f, c | e, c | f, a | z, z | z, b | d, z | d, b | z, c | d, z | f, b | e, a | f, a | d, b | e, b | d, c | z, c | e, a | d, c | z, z | e, z | f, c | f, a | e, z | d, b | z, a | e, b | z, a | e, a | z, b | f, b | f, c | d, c | d, z | d, a | d, b | z, b | e, a | z, c | e, z | f, a | f, c | e, z | f, b | d, c | f, c | z, a | e, z | z, z | d, c | f, z | z, a | f, c | z, z | e, b | d, b | e, z | e, a | d];
    a = 1 << 18;b = 1 << 28;c = a | b;d = 1 << 6;e = 1 << 12;f = d | e;
    SP8 = [b | f, z | e, a | z, c | f, b | z, b | f, z | d, b | z, a | d, c | z, c | f, a | e, c | e, a | f, z | e, z | d, c | z, b | d, b | e, z | f, a | e, a | d, c | d, c | e, z | f, z | z, z | z, c | d, b | d, b | e, a | f, a | z, a | f, a | z, c | e, z | e, z | d, c | d, z | e, a | f, b | e, z | d, b | d, c | z, c | d, b | z, a | z, b | f, z | z, c | f, a | d, b | d, c | z, b | e, b | f, z | z, c | f, a | e, a | e, z | f, z | f, a | d, b | z, c | e];

    // Set the key.
    function setKeys(keyBlock) {
        var i,
            j,
            l,
            m,
            n,
            o,
            pc1m = [],
            pcr = [],
            kn = [],
            raw0,
            raw1,
            rawi,
            KnLi;

        for (j = 0, l = 56; j < 56; ++j, l -= 8) {
            l += l < -5 ? 65 : l < -3 ? 31 : l < -1 ? 63 : l === 27 ? 35 : 0; // PC1
            m = l & 0x7;
            pc1m[j] = (keyBlock[l >>> 3] & 1 << m) !== 0 ? 1 : 0;
        }

        for (i = 0; i < 16; ++i) {
            m = i << 1;
            n = m + 1;
            kn[m] = kn[n] = 0;
            for (o = 28; o < 59; o += 28) {
                for (j = o - 28; j < o; ++j) {
                    l = j + totrot[i];
                    if (l < o) {
                        pcr[j] = pc1m[l];
                    } else {
                        pcr[j] = pc1m[l - 28];
                    }
                }
            }
            for (j = 0; j < 24; ++j) {
                if (pcr[PC2[j]] !== 0) {
                    kn[m] |= 1 << 23 - j;
                }
                if (pcr[PC2[j + 24]] !== 0) {
                    kn[n] |= 1 << 23 - j;
                }
            }
        }

        // cookey
        for (i = 0, rawi = 0, KnLi = 0; i < 16; ++i) {
            raw0 = kn[rawi++];
            raw1 = kn[rawi++];
            keys[KnLi] = (raw0 & 0x00fc0000) << 6;
            keys[KnLi] |= (raw0 & 0x00000fc0) << 10;
            keys[KnLi] |= (raw1 & 0x00fc0000) >>> 10;
            keys[KnLi] |= (raw1 & 0x00000fc0) >>> 6;
            ++KnLi;
            keys[KnLi] = (raw0 & 0x0003f000) << 12;
            keys[KnLi] |= (raw0 & 0x0000003f) << 16;
            keys[KnLi] |= (raw1 & 0x0003f000) >>> 4;
            keys[KnLi] |= raw1 & 0x0000003f;
            ++KnLi;
        }
    }

    // Encrypt 8 bytes of text
    function enc8(text) {
        var i = 0,
            b = text.slice(),
            fval,
            keysi = 0,
            l,
            r,
            x; // left, right, accumulator

        // Squash 8 bytes to 2 ints
        l = b[i++] << 24 | b[i++] << 16 | b[i++] << 8 | b[i++];
        r = b[i++] << 24 | b[i++] << 16 | b[i++] << 8 | b[i++];

        x = (l >>> 4 ^ r) & 0x0f0f0f0f;
        r ^= x;
        l ^= x << 4;
        x = (l >>> 16 ^ r) & 0x0000ffff;
        r ^= x;
        l ^= x << 16;
        x = (r >>> 2 ^ l) & 0x33333333;
        l ^= x;
        r ^= x << 2;
        x = (r >>> 8 ^ l) & 0x00ff00ff;
        l ^= x;
        r ^= x << 8;
        r = r << 1 | r >>> 31 & 1;
        x = (l ^ r) & 0xaaaaaaaa;
        l ^= x;
        r ^= x;
        l = l << 1 | l >>> 31 & 1;

        for (i = 0; i < 8; ++i) {
            x = r << 28 | r >>> 4;
            x ^= keys[keysi++];
            fval = SP7[x & 0x3f];
            fval |= SP5[x >>> 8 & 0x3f];
            fval |= SP3[x >>> 16 & 0x3f];
            fval |= SP1[x >>> 24 & 0x3f];
            x = r ^ keys[keysi++];
            fval |= SP8[x & 0x3f];
            fval |= SP6[x >>> 8 & 0x3f];
            fval |= SP4[x >>> 16 & 0x3f];
            fval |= SP2[x >>> 24 & 0x3f];
            l ^= fval;
            x = l << 28 | l >>> 4;
            x ^= keys[keysi++];
            fval = SP7[x & 0x3f];
            fval |= SP5[x >>> 8 & 0x3f];
            fval |= SP3[x >>> 16 & 0x3f];
            fval |= SP1[x >>> 24 & 0x3f];
            x = l ^ keys[keysi++];
            fval |= SP8[x & 0x0000003f];
            fval |= SP6[x >>> 8 & 0x3f];
            fval |= SP4[x >>> 16 & 0x3f];
            fval |= SP2[x >>> 24 & 0x3f];
            r ^= fval;
        }

        r = r << 31 | r >>> 1;
        x = (l ^ r) & 0xaaaaaaaa;
        l ^= x;
        r ^= x;
        l = l << 31 | l >>> 1;
        x = (l >>> 8 ^ r) & 0x00ff00ff;
        r ^= x;
        l ^= x << 8;
        x = (l >>> 2 ^ r) & 0x33333333;
        r ^= x;
        l ^= x << 2;
        x = (r >>> 16 ^ l) & 0x0000ffff;
        l ^= x;
        r ^= x << 16;
        x = (r >>> 4 ^ l) & 0x0f0f0f0f;
        l ^= x;
        r ^= x << 4;

        // Spread ints to bytes
        x = [r, l];
        for (i = 0; i < 8; i++) {
            b[i] = (x[i >>> 2] >>> 8 * (3 - i % 4)) % 256;
            if (b[i] < 0) {
                b[i] += 256;
            } // unsigned
        }
        return b;
    }

    // Encrypt 16 bytes of text using passwd as key
    function encrypt(t) {
        return enc8(t.slice(0, 8)).concat(enc8(t.slice(8, 16)));
    }

    setKeys(passwd); // Setup keys
    return { 'encrypt': encrypt }; // Public interface
}; // function DES
},{}],6:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = Display;

var _logging = require("./util/logging.js");

var Log = _interopRequireWildcard(_logging);

var _base = require("./base64.js");

var _base2 = _interopRequireDefault(_base);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Copyright (C) 2015 Samuel Mannehed for Cendio AB
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

function Display(target) {
    this._drawCtx = null;
    this._c_forceCanvas = false;

    this._renderQ = []; // queue drawing actions for in-oder rendering
    this._flushing = false;

    // the full frame buffer (logical canvas) size
    this._fb_width = 0;
    this._fb_height = 0;

    this._prevDrawStyle = "";
    this._tile = null;
    this._tile16x16 = null;
    this._tile_x = 0;
    this._tile_y = 0;

    Log.Debug(">> Display.constructor");

    // The visible canvas
    this._target = target;

    if (!this._target) {
        throw new Error("Target must be set");
    }

    if (typeof this._target === 'string') {
        throw new Error('target must be a DOM element');
    }

    if (!this._target.getContext) {
        throw new Error("no getContext method");
    }

    this._targetCtx = this._target.getContext('2d');

    // the visible canvas viewport (i.e. what actually gets seen)
    this._viewportLoc = { 'x': 0, 'y': 0, 'w': this._target.width, 'h': this._target.height };

    // The hidden canvas, where we do the actual rendering
    this._backbuffer = document.createElement('canvas');
    this._drawCtx = this._backbuffer.getContext('2d');

    this._damageBounds = { left: 0, top: 0,
        right: this._backbuffer.width,
        bottom: this._backbuffer.height };

    Log.Debug("User Agent: " + navigator.userAgent);

    this.clear();

    // Check canvas features
    if (!('createImageData' in this._drawCtx)) {
        throw new Error("Canvas does not support createImageData");
    }

    this._tile16x16 = this._drawCtx.createImageData(16, 16);
    Log.Debug("<< Display.constructor");
};

var SUPPORTS_IMAGEDATA_CONSTRUCTOR = false;
try {
    new ImageData(new Uint8ClampedArray(4), 1, 1);
    SUPPORTS_IMAGEDATA_CONSTRUCTOR = true;
} catch (ex) {
    // ignore failure
}

Display.prototype = {
    // ===== PROPERTIES =====

    _scale: 1.0,
    get scale() {
        return this._scale;
    },
    set scale(scale) {
        this._rescale(scale);
    },

    _clipViewport: false,
    get clipViewport() {
        return this._clipViewport;
    },
    set clipViewport(viewport) {
        this._clipViewport = viewport;
        // May need to readjust the viewport dimensions
        var vp = this._viewportLoc;
        this.viewportChangeSize(vp.w, vp.h);
        this.viewportChangePos(0, 0);
    },

    get width() {
        return this._fb_width;
    },
    get height() {
        return this._fb_height;
    },

    logo: null,

    // ===== EVENT HANDLERS =====

    onflush: function () {}, // A flush request has finished

    // ===== PUBLIC METHODS =====

    viewportChangePos: function (deltaX, deltaY) {
        var vp = this._viewportLoc;
        deltaX = Math.floor(deltaX);
        deltaY = Math.floor(deltaY);

        if (!this._clipViewport) {
            deltaX = -vp.w; // clamped later of out of bounds
            deltaY = -vp.h;
        }

        var vx2 = vp.x + vp.w - 1;
        var vy2 = vp.y + vp.h - 1;

        // Position change

        if (deltaX < 0 && vp.x + deltaX < 0) {
            deltaX = -vp.x;
        }
        if (vx2 + deltaX >= this._fb_width) {
            deltaX -= vx2 + deltaX - this._fb_width + 1;
        }

        if (vp.y + deltaY < 0) {
            deltaY = -vp.y;
        }
        if (vy2 + deltaY >= this._fb_height) {
            deltaY -= vy2 + deltaY - this._fb_height + 1;
        }

        if (deltaX === 0 && deltaY === 0) {
            return;
        }
        Log.Debug("viewportChange deltaX: " + deltaX + ", deltaY: " + deltaY);

        vp.x += deltaX;
        vp.y += deltaY;

        this._damage(vp.x, vp.y, vp.w, vp.h);

        this.flip();
    },

    viewportChangeSize: function (width, height) {

        if (!this._clipViewport || typeof width === "undefined" || typeof height === "undefined") {

            Log.Debug("Setting viewport to full display region");
            width = this._fb_width;
            height = this._fb_height;
        }

        if (width > this._fb_width) {
            width = this._fb_width;
        }
        if (height > this._fb_height) {
            height = this._fb_height;
        }

        var vp = this._viewportLoc;
        if (vp.w !== width || vp.h !== height) {
            vp.w = width;
            vp.h = height;

            var canvas = this._target;
            canvas.width = width;
            canvas.height = height;

            // The position might need to be updated if we've grown
            this.viewportChangePos(0, 0);

            this._damage(vp.x, vp.y, vp.w, vp.h);
            this.flip();

            // Update the visible size of the target canvas
            this._rescale(this._scale);
        }
    },

    absX: function (x) {
        return x / this._scale + this._viewportLoc.x;
    },

    absY: function (y) {
        return y / this._scale + this._viewportLoc.y;
    },

    resize: function (width, height) {
        this._prevDrawStyle = "";

        this._fb_width = width;
        this._fb_height = height;

        var canvas = this._backbuffer;
        if (canvas.width !== width || canvas.height !== height) {

            // We have to save the canvas data since changing the size will clear it
            var saveImg = null;
            if (canvas.width > 0 && canvas.height > 0) {
                saveImg = this._drawCtx.getImageData(0, 0, canvas.width, canvas.height);
            }

            if (canvas.width !== width) {
                canvas.width = width;
            }
            if (canvas.height !== height) {
                canvas.height = height;
            }

            if (saveImg) {
                this._drawCtx.putImageData(saveImg, 0, 0);
            }
        }

        // Readjust the viewport as it may be incorrectly sized
        // and positioned
        var vp = this._viewportLoc;
        this.viewportChangeSize(vp.w, vp.h);
        this.viewportChangePos(0, 0);
    },

    // Track what parts of the visible canvas that need updating
    _damage: function (x, y, w, h) {
        if (x < this._damageBounds.left) {
            this._damageBounds.left = x;
        }
        if (y < this._damageBounds.top) {
            this._damageBounds.top = y;
        }
        if (x + w > this._damageBounds.right) {
            this._damageBounds.right = x + w;
        }
        if (y + h > this._damageBounds.bottom) {
            this._damageBounds.bottom = y + h;
        }
    },

    // Update the visible canvas with the contents of the
    // rendering canvas
    flip: function (from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            this._renderQ_push({
                'type': 'flip'
            });
        } else {
            var x, y, vx, vy, w, h;

            x = this._damageBounds.left;
            y = this._damageBounds.top;
            w = this._damageBounds.right - x;
            h = this._damageBounds.bottom - y;

            vx = x - this._viewportLoc.x;
            vy = y - this._viewportLoc.y;

            if (vx < 0) {
                w += vx;
                x -= vx;
                vx = 0;
            }
            if (vy < 0) {
                h += vy;
                y -= vy;
                vy = 0;
            }

            if (vx + w > this._viewportLoc.w) {
                w = this._viewportLoc.w - vx;
            }
            if (vy + h > this._viewportLoc.h) {
                h = this._viewportLoc.h - vy;
            }

            if (w > 0 && h > 0) {
                // FIXME: We may need to disable image smoothing here
                //        as well (see copyImage()), but we haven't
                //        noticed any problem yet.
                this._targetCtx.drawImage(this._backbuffer, x, y, w, h, vx, vy, w, h);
            }

            this._damageBounds.left = this._damageBounds.top = 65535;
            this._damageBounds.right = this._damageBounds.bottom = 0;
        }
    },

    clear: function () {
        if (this._logo) {
            this.resize(this._logo.width, this._logo.height);
            this.imageRect(0, 0, this._logo.type, this._logo.data);
        } else {
            this.resize(240, 20);
            this._drawCtx.clearRect(0, 0, this._fb_width, this._fb_height);
        }
        this.flip();
    },

    pending: function () {
        return this._renderQ.length > 0;
    },

    flush: function () {
        if (this._renderQ.length === 0) {
            this.onflush();
        } else {
            this._flushing = true;
        }
    },

    fillRect: function (x, y, width, height, color, from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            this._renderQ_push({
                'type': 'fill',
                'x': x,
                'y': y,
                'width': width,
                'height': height,
                'color': color
            });
        } else {
            this._setFillColor(color);
            this._drawCtx.fillRect(x, y, width, height);
            this._damage(x, y, width, height);
        }
    },

    copyImage: function (old_x, old_y, new_x, new_y, w, h, from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            this._renderQ_push({
                'type': 'copy',
                'old_x': old_x,
                'old_y': old_y,
                'x': new_x,
                'y': new_y,
                'width': w,
                'height': h
            });
        } else {
            // Due to this bug among others [1] we need to disable the image-smoothing to
            // avoid getting a blur effect when copying data.
            //
            // 1. https://bugzilla.mozilla.org/show_bug.cgi?id=1194719
            //
            // We need to set these every time since all properties are reset
            // when the the size is changed
            this._drawCtx.mozImageSmoothingEnabled = false;
            this._drawCtx.webkitImageSmoothingEnabled = false;
            this._drawCtx.msImageSmoothingEnabled = false;
            this._drawCtx.imageSmoothingEnabled = false;

            this._drawCtx.drawImage(this._backbuffer, old_x, old_y, w, h, new_x, new_y, w, h);
            this._damage(new_x, new_y, w, h);
        }
    },

    imageRect: function (x, y, mime, arr) {
        var img = new Image();
        img.src = "data: " + mime + ";base64," + _base2.default.encode(arr);
        this._renderQ_push({
            'type': 'img',
            'img': img,
            'x': x,
            'y': y
        });
    },

    // start updating a tile
    startTile: function (x, y, width, height, color) {
        this._tile_x = x;
        this._tile_y = y;
        if (width === 16 && height === 16) {
            this._tile = this._tile16x16;
        } else {
            this._tile = this._drawCtx.createImageData(width, height);
        }

        var red = color[2];
        var green = color[1];
        var blue = color[0];

        var data = this._tile.data;
        for (var i = 0; i < width * height * 4; i += 4) {
            data[i] = red;
            data[i + 1] = green;
            data[i + 2] = blue;
            data[i + 3] = 255;
        }
    },

    // update sub-rectangle of the current tile
    subTile: function (x, y, w, h, color) {
        var red = color[2];
        var green = color[1];
        var blue = color[0];
        var xend = x + w;
        var yend = y + h;

        var data = this._tile.data;
        var width = this._tile.width;
        for (var j = y; j < yend; j++) {
            for (var i = x; i < xend; i++) {
                var p = (i + j * width) * 4;
                data[p] = red;
                data[p + 1] = green;
                data[p + 2] = blue;
                data[p + 3] = 255;
            }
        }
    },

    // draw the current tile to the screen
    finishTile: function () {
        this._drawCtx.putImageData(this._tile, this._tile_x, this._tile_y);
        this._damage(this._tile_x, this._tile_y, this._tile.width, this._tile.height);
    },

    blitImage: function (x, y, width, height, arr, offset, from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            // NB(directxman12): it's technically more performant here to use preallocated arrays,
            // but it's a lot of extra work for not a lot of payoff -- if we're using the render queue,
            // this probably isn't getting called *nearly* as much
            var new_arr = new Uint8Array(width * height * 4);
            new_arr.set(new Uint8Array(arr.buffer, 0, new_arr.length));
            this._renderQ_push({
                'type': 'blit',
                'data': new_arr,
                'x': x,
                'y': y,
                'width': width,
                'height': height
            });
        } else {
            this._bgrxImageData(x, y, width, height, arr, offset);
        }
    },

    blitRgbImage: function (x, y, width, height, arr, offset, from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            // NB(directxman12): it's technically more performant here to use preallocated arrays,
            // but it's a lot of extra work for not a lot of payoff -- if we're using the render queue,
            // this probably isn't getting called *nearly* as much
            var new_arr = new Uint8Array(width * height * 3);
            new_arr.set(new Uint8Array(arr.buffer, 0, new_arr.length));
            this._renderQ_push({
                'type': 'blitRgb',
                'data': new_arr,
                'x': x,
                'y': y,
                'width': width,
                'height': height
            });
        } else {
            this._rgbImageData(x, y, width, height, arr, offset);
        }
    },

    blitRgbxImage: function (x, y, width, height, arr, offset, from_queue) {
        if (this._renderQ.length !== 0 && !from_queue) {
            // NB(directxman12): it's technically more performant here to use preallocated arrays,
            // but it's a lot of extra work for not a lot of payoff -- if we're using the render queue,
            // this probably isn't getting called *nearly* as much
            var new_arr = new Uint8Array(width * height * 4);
            new_arr.set(new Uint8Array(arr.buffer, 0, new_arr.length));
            this._renderQ_push({
                'type': 'blitRgbx',
                'data': new_arr,
                'x': x,
                'y': y,
                'width': width,
                'height': height
            });
        } else {
            this._rgbxImageData(x, y, width, height, arr, offset);
        }
    },

    drawImage: function (img, x, y) {
        this._drawCtx.drawImage(img, x, y);
        this._damage(x, y, img.width, img.height);
    },

    changeCursor: function (pixels, mask, hotx, hoty, w, h) {
        Display.changeCursor(this._target, pixels, mask, hotx, hoty, w, h);
    },

    defaultCursor: function () {
        this._target.style.cursor = "default";
    },

    disableLocalCursor: function () {
        this._target.style.cursor = "none";
    },

    autoscale: function (containerWidth, containerHeight) {
        var vp = this._viewportLoc;
        var targetAspectRatio = containerWidth / containerHeight;
        var fbAspectRatio = vp.w / vp.h;

        var scaleRatio;
        if (fbAspectRatio >= targetAspectRatio) {
            scaleRatio = containerWidth / vp.w;
        } else {
            scaleRatio = containerHeight / vp.h;
        }

        this._rescale(scaleRatio);
    },

    // ===== PRIVATE METHODS =====

    _rescale: function (factor) {
        this._scale = factor;
        var vp = this._viewportLoc;

        // NB(directxman12): If you set the width directly, or set the
        //                   style width to a number, the canvas is cleared.
        //                   However, if you set the style width to a string
        //                   ('NNNpx'), the canvas is scaled without clearing.
        var width = Math.round(factor * vp.w) + 'px';
        var height = Math.round(factor * vp.h) + 'px';

        if (this._target.style.width !== width || this._target.style.height !== height) {
            this._target.style.width = width;
            this._target.style.height = height;
        }
    },

    _setFillColor: function (color) {
        var newStyle = 'rgb(' + color[2] + ',' + color[1] + ',' + color[0] + ')';
        if (newStyle !== this._prevDrawStyle) {
            this._drawCtx.fillStyle = newStyle;
            this._prevDrawStyle = newStyle;
        }
    },

    _rgbImageData: function (x, y, width, height, arr, offset) {
        var img = this._drawCtx.createImageData(width, height);
        var data = img.data;
        for (var i = 0, j = offset; i < width * height * 4; i += 4, j += 3) {
            data[i] = arr[j];
            data[i + 1] = arr[j + 1];
            data[i + 2] = arr[j + 2];
            data[i + 3] = 255; // Alpha
        }
        this._drawCtx.putImageData(img, x, y);
        this._damage(x, y, img.width, img.height);
    },

    _bgrxImageData: function (x, y, width, height, arr, offset) {
        var img = this._drawCtx.createImageData(width, height);
        var data = img.data;
        for (var i = 0, j = offset; i < width * height * 4; i += 4, j += 4) {
            data[i] = arr[j + 2];
            data[i + 1] = arr[j + 1];
            data[i + 2] = arr[j];
            data[i + 3] = 255; // Alpha
        }
        this._drawCtx.putImageData(img, x, y);
        this._damage(x, y, img.width, img.height);
    },

    _rgbxImageData: function (x, y, width, height, arr, offset) {
        // NB(directxman12): arr must be an Type Array view
        var img;
        if (SUPPORTS_IMAGEDATA_CONSTRUCTOR) {
            img = new ImageData(new Uint8ClampedArray(arr.buffer, arr.byteOffset, width * height * 4), width, height);
        } else {
            img = this._drawCtx.createImageData(width, height);
            img.data.set(new Uint8ClampedArray(arr.buffer, arr.byteOffset, width * height * 4));
        }
        this._drawCtx.putImageData(img, x, y);
        this._damage(x, y, img.width, img.height);
    },

    _renderQ_push: function (action) {
        this._renderQ.push(action);
        if (this._renderQ.length === 1) {
            // If this can be rendered immediately it will be, otherwise
            // the scanner will wait for the relevant event
            this._scan_renderQ();
        }
    },

    _resume_renderQ: function () {
        // "this" is the object that is ready, not the
        // display object
        this.removeEventListener('load', this._noVNC_display._resume_renderQ);
        this._noVNC_display._scan_renderQ();
    },

    _scan_renderQ: function () {
        var ready = true;
        while (ready && this._renderQ.length > 0) {
            var a = this._renderQ[0];
            switch (a.type) {
                case 'flip':
                    this.flip(true);
                    break;
                case 'copy':
                    this.copyImage(a.old_x, a.old_y, a.x, a.y, a.width, a.height, true);
                    break;
                case 'fill':
                    this.fillRect(a.x, a.y, a.width, a.height, a.color, true);
                    break;
                case 'blit':
                    this.blitImage(a.x, a.y, a.width, a.height, a.data, 0, true);
                    break;
                case 'blitRgb':
                    this.blitRgbImage(a.x, a.y, a.width, a.height, a.data, 0, true);
                    break;
                case 'blitRgbx':
                    this.blitRgbxImage(a.x, a.y, a.width, a.height, a.data, 0, true);
                    break;
                case 'img':
                    if (a.img.complete) {
                        this.drawImage(a.img, a.x, a.y);
                    } else {
                        a.img._noVNC_display = this;
                        a.img.addEventListener('load', this._resume_renderQ);
                        // We need to wait for this image to 'load'
                        // to keep things in-order
                        ready = false;
                    }
                    break;
            }

            if (ready) {
                this._renderQ.shift();
            }
        }

        if (this._renderQ.length === 0 && this._flushing) {
            this._flushing = false;
            this.onflush();
        }
    }
};

// Class Methods
Display.changeCursor = function (target, pixels, mask, hotx, hoty, w, h) {
    if (w === 0 || h === 0) {
        target.style.cursor = 'none';
        return;
    }

    var cur = [];
    var y, x;
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            var idx = y * Math.ceil(w / 8) + Math.floor(x / 8);
            var alpha = mask[idx] << x % 8 & 0x80 ? 255 : 0;
            idx = (w * y + x) * 4;
            cur.push(pixels[idx + 2]); // red
            cur.push(pixels[idx + 1]); // green
            cur.push(pixels[idx]); // blue
            cur.push(alpha); // alpha
        }
    }

    var canvas = document.createElement('canvas');
    var ctx = canvas.getContext('2d');

    canvas.width = w;
    canvas.height = h;

    var img;
    if (SUPPORTS_IMAGEDATA_CONSTRUCTOR) {
        img = new ImageData(new Uint8ClampedArray(cur), w, h);
    } else {
        img = ctx.createImageData(w, h);
        img.data.set(new Uint8ClampedArray(cur));
    }
    ctx.clearRect(0, 0, w, h);
    ctx.putImageData(img, 0, 0);

    var url = canvas.toDataURL();
    target.style.cursor = 'url(' + url + ')' + hotx + ' ' + hoty + ', default';
};
},{"./base64.js":4,"./util/logging.js":22}],7:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.encodingName = encodingName;
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2017 Pierre Ossman for Cendio AB
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

var encodings = exports.encodings = {
    encodingRaw: 0,
    encodingCopyRect: 1,
    encodingRRE: 2,
    encodingHextile: 5,
    encodingTight: 7,

    pseudoEncodingQualityLevel9: -23,
    pseudoEncodingQualityLevel0: -32,
    pseudoEncodingDesktopSize: -223,
    pseudoEncodingLastRect: -224,
    pseudoEncodingCursor: -239,
    pseudoEncodingQEMUExtendedKeyEvent: -258,
    pseudoEncodingTightPNG: -260,
    pseudoEncodingExtendedDesktopSize: -308,
    pseudoEncodingXvp: -309,
    pseudoEncodingFence: -312,
    pseudoEncodingContinuousUpdates: -313,
    pseudoEncodingCompressLevel9: -247,
    pseudoEncodingCompressLevel0: -256
};

function encodingName(num) {
    switch (num) {
        case encodings.encodingRaw:
            return "Raw";
        case encodings.encodingCopyRect:
            return "CopyRect";
        case encodings.encodingRRE:
            return "RRE";
        case encodings.encodingHextile:
            return "Hextile";
        case encodings.encodingTight:
            return "Tight";
        default:
            return "[unknown encoding " + num + "]";
    }
}
},{}],8:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = Inflate;

var _inflate = require("../vendor/pako/lib/zlib/inflate.js");

var _zstream = require("../vendor/pako/lib/zlib/zstream.js");

var _zstream2 = _interopRequireDefault(_zstream);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

Inflate.prototype = {
    inflate: function (data, flush, expected) {
        this.strm.input = data;
        this.strm.avail_in = this.strm.input.length;
        this.strm.next_in = 0;
        this.strm.next_out = 0;

        // resize our output buffer if it's too small
        // (we could just use multiple chunks, but that would cause an extra
        // allocation each time to flatten the chunks)
        if (expected > this.chunkSize) {
            this.chunkSize = expected;
            this.strm.output = new Uint8Array(this.chunkSize);
        }

        this.strm.avail_out = this.chunkSize;

        (0, _inflate.inflate)(this.strm, flush);

        return new Uint8Array(this.strm.output.buffer, 0, this.strm.next_out);
    },

    reset: function () {
        (0, _inflate.inflateReset)(this.strm);
    }
};

function Inflate() {
    this.strm = new _zstream2.default();
    this.chunkSize = 1024 * 10 * 10;
    this.strm.output = new Uint8Array(this.chunkSize);
    this.windowBits = 5;

    (0, _inflate.inflateInit)(this.strm, this.windowBits);
};
},{"../vendor/pako/lib/zlib/inflate.js":30,"../vendor/pako/lib/zlib/zstream.js":32}],9:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});

var _keysym = require("./keysym.js");

var _keysym2 = _interopRequireDefault(_keysym);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

/*
 * Mapping between HTML key values and VNC/X11 keysyms for "special"
 * keys that cannot be handled via their Unicode codepoint.
 *
 * See https://www.w3.org/TR/uievents-key/ for possible values.
 */

var DOMKeyTable = {}; /*
                       * noVNC: HTML5 VNC client
                       * Copyright (C) 2017 Pierre Ossman for Cendio AB
                       * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
                       */

function addStandard(key, standard) {
    if (standard === undefined) throw "Undefined keysym for key \"" + key + "\"";
    if (key in DOMKeyTable) throw "Duplicate entry for key \"" + key + "\"";
    DOMKeyTable[key] = [standard, standard, standard, standard];
}

function addLeftRight(key, left, right) {
    if (left === undefined) throw "Undefined keysym for key \"" + key + "\"";
    if (right === undefined) throw "Undefined keysym for key \"" + key + "\"";
    if (key in DOMKeyTable) throw "Duplicate entry for key \"" + key + "\"";
    DOMKeyTable[key] = [left, left, right, left];
}

function addNumpad(key, standard, numpad) {
    if (standard === undefined) throw "Undefined keysym for key \"" + key + "\"";
    if (numpad === undefined) throw "Undefined keysym for key \"" + key + "\"";
    if (key in DOMKeyTable) throw "Duplicate entry for key \"" + key + "\"";
    DOMKeyTable[key] = [standard, standard, standard, numpad];
}

// 2.2. Modifier Keys

addLeftRight("Alt", _keysym2.default.XK_Alt_L, _keysym2.default.XK_Alt_R);
addStandard("AltGraph", _keysym2.default.XK_ISO_Level3_Shift);
addStandard("CapsLock", _keysym2.default.XK_Caps_Lock);
addLeftRight("Control", _keysym2.default.XK_Control_L, _keysym2.default.XK_Control_R);
// - Fn
// - FnLock
addLeftRight("Hyper", _keysym2.default.XK_Super_L, _keysym2.default.XK_Super_R);
addLeftRight("Meta", _keysym2.default.XK_Super_L, _keysym2.default.XK_Super_R);
addStandard("NumLock", _keysym2.default.XK_Num_Lock);
addStandard("ScrollLock", _keysym2.default.XK_Scroll_Lock);
addLeftRight("Shift", _keysym2.default.XK_Shift_L, _keysym2.default.XK_Shift_R);
addLeftRight("Super", _keysym2.default.XK_Super_L, _keysym2.default.XK_Super_R);
// - Symbol
// - SymbolLock

// 2.3. Whitespace Keys

addNumpad("Enter", _keysym2.default.XK_Return, _keysym2.default.XK_KP_Enter);
addStandard("Tab", _keysym2.default.XK_Tab);
addNumpad(" ", _keysym2.default.XK_space, _keysym2.default.XK_KP_Space);

// 2.4. Navigation Keys

addNumpad("ArrowDown", _keysym2.default.XK_Down, _keysym2.default.XK_KP_Down);
addNumpad("ArrowUp", _keysym2.default.XK_Up, _keysym2.default.XK_KP_Up);
addNumpad("ArrowLeft", _keysym2.default.XK_Left, _keysym2.default.XK_KP_Left);
addNumpad("ArrowRight", _keysym2.default.XK_Right, _keysym2.default.XK_KP_Right);
addNumpad("End", _keysym2.default.XK_End, _keysym2.default.XK_KP_End);
addNumpad("Home", _keysym2.default.XK_Home, _keysym2.default.XK_KP_Home);
addNumpad("PageDown", _keysym2.default.XK_Next, _keysym2.default.XK_KP_Next);
addNumpad("PageUp", _keysym2.default.XK_Prior, _keysym2.default.XK_KP_Prior);

// 2.5. Editing Keys

addStandard("Backspace", _keysym2.default.XK_BackSpace);
addStandard("Clear", _keysym2.default.XK_Clear);
addStandard("Copy", _keysym2.default.XF86XK_Copy);
// - CrSel
addStandard("Cut", _keysym2.default.XF86XK_Cut);
addNumpad("Delete", _keysym2.default.XK_Delete, _keysym2.default.XK_KP_Delete);
// - EraseEof
// - ExSel
addNumpad("Insert", _keysym2.default.XK_Insert, _keysym2.default.XK_KP_Insert);
addStandard("Paste", _keysym2.default.XF86XK_Paste);
addStandard("Redo", _keysym2.default.XK_Redo);
addStandard("Undo", _keysym2.default.XK_Undo);

// 2.6. UI Keys

// - Accept
// - Again (could just be XK_Redo)
// - Attn
addStandard("Cancel", _keysym2.default.XK_Cancel);
addStandard("ContextMenu", _keysym2.default.XK_Menu);
addStandard("Escape", _keysym2.default.XK_Escape);
addStandard("Execute", _keysym2.default.XK_Execute);
addStandard("Find", _keysym2.default.XK_Find);
addStandard("Help", _keysym2.default.XK_Help);
addStandard("Pause", _keysym2.default.XK_Pause);
// - Play
// - Props
addStandard("Select", _keysym2.default.XK_Select);
addStandard("ZoomIn", _keysym2.default.XF86XK_ZoomIn);
addStandard("ZoomOut", _keysym2.default.XF86XK_ZoomOut);

// 2.7. Device Keys

addStandard("BrightnessDown", _keysym2.default.XF86XK_MonBrightnessDown);
addStandard("BrightnessUp", _keysym2.default.XF86XK_MonBrightnessUp);
addStandard("Eject", _keysym2.default.XF86XK_Eject);
addStandard("LogOff", _keysym2.default.XF86XK_LogOff);
addStandard("Power", _keysym2.default.XF86XK_PowerOff);
addStandard("PowerOff", _keysym2.default.XF86XK_PowerDown);
addStandard("PrintScreen", _keysym2.default.XK_Print);
addStandard("Hibernate", _keysym2.default.XF86XK_Hibernate);
addStandard("Standby", _keysym2.default.XF86XK_Standby);
addStandard("WakeUp", _keysym2.default.XF86XK_WakeUp);

// 2.8. IME and Composition Keys

addStandard("AllCandidates", _keysym2.default.XK_MultipleCandidate);
addStandard("Alphanumeric", _keysym2.default.XK_Eisu_Shift); // could also be _Eisu_Toggle
addStandard("CodeInput", _keysym2.default.XK_Codeinput);
addStandard("Compose", _keysym2.default.XK_Multi_key);
addStandard("Convert", _keysym2.default.XK_Henkan);
// - Dead
// - FinalMode
addStandard("GroupFirst", _keysym2.default.XK_ISO_First_Group);
addStandard("GroupLast", _keysym2.default.XK_ISO_Last_Group);
addStandard("GroupNext", _keysym2.default.XK_ISO_Next_Group);
addStandard("GroupPrevious", _keysym2.default.XK_ISO_Prev_Group);
// - ModeChange (XK_Mode_switch is often used for AltGr)
// - NextCandidate
addStandard("NonConvert", _keysym2.default.XK_Muhenkan);
addStandard("PreviousCandidate", _keysym2.default.XK_PreviousCandidate);
// - Process
addStandard("SingleCandidate", _keysym2.default.XK_SingleCandidate);
addStandard("HangulMode", _keysym2.default.XK_Hangul);
addStandard("HanjaMode", _keysym2.default.XK_Hangul_Hanja);
addStandard("JunjuaMode", _keysym2.default.XK_Hangul_Jeonja);
addStandard("Eisu", _keysym2.default.XK_Eisu_toggle);
addStandard("Hankaku", _keysym2.default.XK_Hankaku);
addStandard("Hiragana", _keysym2.default.XK_Hiragana);
addStandard("HiraganaKatakana", _keysym2.default.XK_Hiragana_Katakana);
addStandard("KanaMode", _keysym2.default.XK_Kana_Shift); // could also be _Kana_Lock
addStandard("KanjiMode", _keysym2.default.XK_Kanji);
addStandard("Katakana", _keysym2.default.XK_Katakana);
addStandard("Romaji", _keysym2.default.XK_Romaji);
addStandard("Zenkaku", _keysym2.default.XK_Zenkaku);
addStandard("ZenkakuHanaku", _keysym2.default.XK_Zenkaku_Hankaku);

// 2.9. General-Purpose Function Keys

addStandard("F1", _keysym2.default.XK_F1);
addStandard("F2", _keysym2.default.XK_F2);
addStandard("F3", _keysym2.default.XK_F3);
addStandard("F4", _keysym2.default.XK_F4);
addStandard("F5", _keysym2.default.XK_F5);
addStandard("F6", _keysym2.default.XK_F6);
addStandard("F7", _keysym2.default.XK_F7);
addStandard("F8", _keysym2.default.XK_F8);
addStandard("F9", _keysym2.default.XK_F9);
addStandard("F10", _keysym2.default.XK_F10);
addStandard("F11", _keysym2.default.XK_F11);
addStandard("F12", _keysym2.default.XK_F12);
addStandard("F13", _keysym2.default.XK_F13);
addStandard("F14", _keysym2.default.XK_F14);
addStandard("F15", _keysym2.default.XK_F15);
addStandard("F16", _keysym2.default.XK_F16);
addStandard("F17", _keysym2.default.XK_F17);
addStandard("F18", _keysym2.default.XK_F18);
addStandard("F19", _keysym2.default.XK_F19);
addStandard("F20", _keysym2.default.XK_F20);
addStandard("F21", _keysym2.default.XK_F21);
addStandard("F22", _keysym2.default.XK_F22);
addStandard("F23", _keysym2.default.XK_F23);
addStandard("F24", _keysym2.default.XK_F24);
addStandard("F25", _keysym2.default.XK_F25);
addStandard("F26", _keysym2.default.XK_F26);
addStandard("F27", _keysym2.default.XK_F27);
addStandard("F28", _keysym2.default.XK_F28);
addStandard("F29", _keysym2.default.XK_F29);
addStandard("F30", _keysym2.default.XK_F30);
addStandard("F31", _keysym2.default.XK_F31);
addStandard("F32", _keysym2.default.XK_F32);
addStandard("F33", _keysym2.default.XK_F33);
addStandard("F34", _keysym2.default.XK_F34);
addStandard("F35", _keysym2.default.XK_F35);
// - Soft1...

// 2.10. Multimedia Keys

// - ChannelDown
// - ChannelUp
addStandard("Close", _keysym2.default.XF86XK_Close);
addStandard("MailForward", _keysym2.default.XF86XK_MailForward);
addStandard("MailReply", _keysym2.default.XF86XK_Reply);
addStandard("MainSend", _keysym2.default.XF86XK_Send);
addStandard("MediaFastForward", _keysym2.default.XF86XK_AudioForward);
addStandard("MediaPause", _keysym2.default.XF86XK_AudioPause);
addStandard("MediaPlay", _keysym2.default.XF86XK_AudioPlay);
addStandard("MediaRecord", _keysym2.default.XF86XK_AudioRecord);
addStandard("MediaRewind", _keysym2.default.XF86XK_AudioRewind);
addStandard("MediaStop", _keysym2.default.XF86XK_AudioStop);
addStandard("MediaTrackNext", _keysym2.default.XF86XK_AudioNext);
addStandard("MediaTrackPrevious", _keysym2.default.XF86XK_AudioPrev);
addStandard("New", _keysym2.default.XF86XK_New);
addStandard("Open", _keysym2.default.XF86XK_Open);
addStandard("Print", _keysym2.default.XK_Print);
addStandard("Save", _keysym2.default.XF86XK_Save);
addStandard("SpellCheck", _keysym2.default.XF86XK_Spell);

// 2.11. Multimedia Numpad Keys

// - Key11
// - Key12

// 2.12. Audio Keys

// - AudioBalanceLeft
// - AudioBalanceRight
// - AudioBassDown
// - AudioBassBoostDown
// - AudioBassBoostToggle
// - AudioBassBoostUp
// - AudioBassUp
// - AudioFaderFront
// - AudioFaderRear
// - AudioSurroundModeNext
// - AudioTrebleDown
// - AudioTrebleUp
addStandard("AudioVolumeDown", _keysym2.default.XF86XK_AudioLowerVolume);
addStandard("AudioVolumeUp", _keysym2.default.XF86XK_AudioRaiseVolume);
addStandard("AudioVolumeMute", _keysym2.default.XF86XK_AudioMute);
// - MicrophoneToggle
// - MicrophoneVolumeDown
// - MicrophoneVolumeUp
addStandard("MicrophoneVolumeMute", _keysym2.default.XF86XK_AudioMicMute);

// 2.13. Speech Keys

// - SpeechCorrectionList
// - SpeechInputToggle

// 2.14. Application Keys

addStandard("LaunchCalculator", _keysym2.default.XF86XK_Calculator);
addStandard("LaunchCalendar", _keysym2.default.XF86XK_Calendar);
addStandard("LaunchMail", _keysym2.default.XF86XK_Mail);
addStandard("LaunchMediaPlayer", _keysym2.default.XF86XK_AudioMedia);
addStandard("LaunchMusicPlayer", _keysym2.default.XF86XK_Music);
addStandard("LaunchMyComputer", _keysym2.default.XF86XK_MyComputer);
addStandard("LaunchPhone", _keysym2.default.XF86XK_Phone);
addStandard("LaunchScreenSaver", _keysym2.default.XF86XK_ScreenSaver);
addStandard("LaunchSpreadsheet", _keysym2.default.XF86XK_Excel);
addStandard("LaunchWebBrowser", _keysym2.default.XF86XK_WWW);
addStandard("LaunchWebCam", _keysym2.default.XF86XK_WebCam);
addStandard("LaunchWordProcessor", _keysym2.default.XF86XK_Word);

// 2.15. Browser Keys

addStandard("BrowserBack", _keysym2.default.XF86XK_Back);
addStandard("BrowserFavorites", _keysym2.default.XF86XK_Favorites);
addStandard("BrowserForward", _keysym2.default.XF86XK_Forward);
addStandard("BrowserHome", _keysym2.default.XF86XK_HomePage);
addStandard("BrowserRefresh", _keysym2.default.XF86XK_Refresh);
addStandard("BrowserSearch", _keysym2.default.XF86XK_Search);
addStandard("BrowserStop", _keysym2.default.XF86XK_Stop);

// 2.16. Mobile Phone Keys

// - A whole bunch...

// 2.17. TV Keys

// - A whole bunch...

// 2.18. Media Controller Keys

// - A whole bunch...
addStandard("Dimmer", _keysym2.default.XF86XK_BrightnessAdjust);
addStandard("MediaAudioTrack", _keysym2.default.XF86XK_AudioCycleTrack);
addStandard("RandomToggle", _keysym2.default.XF86XK_AudioRandomPlay);
addStandard("SplitScreenToggle", _keysym2.default.XF86XK_SplitScreen);
addStandard("Subtitle", _keysym2.default.XF86XK_Subtitle);
addStandard("VideoModeNext", _keysym2.default.XF86XK_Next_VMode);

// Extra: Numpad

addNumpad("=", _keysym2.default.XK_equal, _keysym2.default.XK_KP_Equal);
addNumpad("+", _keysym2.default.XK_plus, _keysym2.default.XK_KP_Add);
addNumpad("-", _keysym2.default.XK_minus, _keysym2.default.XK_KP_Subtract);
addNumpad("*", _keysym2.default.XK_asterisk, _keysym2.default.XK_KP_Multiply);
addNumpad("/", _keysym2.default.XK_slash, _keysym2.default.XK_KP_Divide);
addNumpad(".", _keysym2.default.XK_period, _keysym2.default.XK_KP_Decimal);
addNumpad(",", _keysym2.default.XK_comma, _keysym2.default.XK_KP_Separator);
addNumpad("0", _keysym2.default.XK_0, _keysym2.default.XK_KP_0);
addNumpad("1", _keysym2.default.XK_1, _keysym2.default.XK_KP_1);
addNumpad("2", _keysym2.default.XK_2, _keysym2.default.XK_KP_2);
addNumpad("3", _keysym2.default.XK_3, _keysym2.default.XK_KP_3);
addNumpad("4", _keysym2.default.XK_4, _keysym2.default.XK_KP_4);
addNumpad("5", _keysym2.default.XK_5, _keysym2.default.XK_KP_5);
addNumpad("6", _keysym2.default.XK_6, _keysym2.default.XK_KP_6);
addNumpad("7", _keysym2.default.XK_7, _keysym2.default.XK_KP_7);
addNumpad("8", _keysym2.default.XK_8, _keysym2.default.XK_KP_8);
addNumpad("9", _keysym2.default.XK_9, _keysym2.default.XK_KP_9);

exports.default = DOMKeyTable;
},{"./keysym.js":12}],10:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2017 Pierre Ossman for Cendio AB
 * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
 */

/*
 * Fallback mapping between HTML key codes (physical keys) and
 * HTML key values. This only works for keys that don't vary
 * between layouts. We also omit those who manage fine by mapping the
 * Unicode representation.
 *
 * See https://www.w3.org/TR/uievents-code/ for possible codes.
 * See https://www.w3.org/TR/uievents-key/ for possible values.
 */

exports.default = {

    // 3.1.1.1. Writing System Keys

    'Backspace': 'Backspace',

    // 3.1.1.2. Functional Keys

    'AltLeft': 'Alt',
    'AltRight': 'Alt', // This could also be 'AltGraph'
    'CapsLock': 'CapsLock',
    'ContextMenu': 'ContextMenu',
    'ControlLeft': 'Control',
    'ControlRight': 'Control',
    'Enter': 'Enter',
    'MetaLeft': 'Meta',
    'MetaRight': 'Meta',
    'ShiftLeft': 'Shift',
    'ShiftRight': 'Shift',
    'Tab': 'Tab',
    // FIXME: Japanese/Korean keys

    // 3.1.2. Control Pad Section

    'Delete': 'Delete',
    'End': 'End',
    'Help': 'Help',
    'Home': 'Home',
    'Insert': 'Insert',
    'PageDown': 'PageDown',
    'PageUp': 'PageUp',

    // 3.1.3. Arrow Pad Section

    'ArrowDown': 'ArrowDown',
    'ArrowLeft': 'ArrowLeft',
    'ArrowRight': 'ArrowRight',
    'ArrowUp': 'ArrowUp',

    // 3.1.4. Numpad Section

    'NumLock': 'NumLock',
    'NumpadBackspace': 'Backspace',
    'NumpadClear': 'Clear',

    // 3.1.5. Function Section

    'Escape': 'Escape',
    'F1': 'F1',
    'F2': 'F2',
    'F3': 'F3',
    'F4': 'F4',
    'F5': 'F5',
    'F6': 'F6',
    'F7': 'F7',
    'F8': 'F8',
    'F9': 'F9',
    'F10': 'F10',
    'F11': 'F11',
    'F12': 'F12',
    'F13': 'F13',
    'F14': 'F14',
    'F15': 'F15',
    'F16': 'F16',
    'F17': 'F17',
    'F18': 'F18',
    'F19': 'F19',
    'F20': 'F20',
    'F21': 'F21',
    'F22': 'F22',
    'F23': 'F23',
    'F24': 'F24',
    'F25': 'F25',
    'F26': 'F26',
    'F27': 'F27',
    'F28': 'F28',
    'F29': 'F29',
    'F30': 'F30',
    'F31': 'F31',
    'F32': 'F32',
    'F33': 'F33',
    'F34': 'F34',
    'F35': 'F35',
    'PrintScreen': 'PrintScreen',
    'ScrollLock': 'ScrollLock',
    'Pause': 'Pause',

    // 3.1.6. Media Keys

    'BrowserBack': 'BrowserBack',
    'BrowserFavorites': 'BrowserFavorites',
    'BrowserForward': 'BrowserForward',
    'BrowserHome': 'BrowserHome',
    'BrowserRefresh': 'BrowserRefresh',
    'BrowserSearch': 'BrowserSearch',
    'BrowserStop': 'BrowserStop',
    'Eject': 'Eject',
    'LaunchApp1': 'LaunchMyComputer',
    'LaunchApp2': 'LaunchCalendar',
    'LaunchMail': 'LaunchMail',
    'MediaPlayPause': 'MediaPlay',
    'MediaStop': 'MediaStop',
    'MediaTrackNext': 'MediaTrackNext',
    'MediaTrackPrevious': 'MediaTrackPrevious',
    'Power': 'Power',
    'Sleep': 'Sleep',
    'AudioVolumeDown': 'AudioVolumeDown',
    'AudioVolumeMute': 'AudioVolumeMute',
    'AudioVolumeUp': 'AudioVolumeUp',
    'WakeUp': 'WakeUp'
};
},{}],11:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = Keyboard;

var _logging = require('../util/logging.js');

var Log = _interopRequireWildcard(_logging);

var _events = require('../util/events.js');

var _util = require('./util.js');

var KeyboardUtil = _interopRequireWildcard(_util);

var _keysym = require('./keysym.js');

var _keysym2 = _interopRequireDefault(_keysym);

var _browser = require('../util/browser.js');

var browser = _interopRequireWildcard(_browser);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

//
// Keyboard event handler
//

function Keyboard(target) {
    this._target = target || null;

    this._keyDownList = {}; // List of depressed keys
    // (even if they are happy)
    this._pendingKey = null; // Key waiting for keypress

    // keep these here so we can refer to them later
    this._eventHandlers = {
        'keyup': this._handleKeyUp.bind(this),
        'keydown': this._handleKeyDown.bind(this),
        'keypress': this._handleKeyPress.bind(this),
        'blur': this._allKeysUp.bind(this)
    };
} /*
   * noVNC: HTML5 VNC client
   * Copyright (C) 2012 Joel Martin
   * Copyright (C) 2013 Samuel Mannehed for Cendio AB
   * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
   */

;

Keyboard.prototype = {
    // ===== EVENT HANDLERS =====

    onkeyevent: function () {}, // Handler for key press/release

    // ===== PRIVATE METHODS =====

    _sendKeyEvent: function (keysym, code, down) {
        Log.Debug("onkeyevent " + (down ? "down" : "up") + ", keysym: " + keysym, ", code: " + code);

        // Windows sends CtrlLeft+AltRight when you press
        // AltGraph, which tends to confuse the hell out of
        // remote systems. Fake a release of these keys until
        // there is a way to detect AltGraph properly.
        var fakeAltGraph = false;
        if (down && browser.isWindows()) {
            if (code !== 'ControlLeft' && code !== 'AltRight' && 'ControlLeft' in this._keyDownList && 'AltRight' in this._keyDownList) {
                fakeAltGraph = true;
                this.onkeyevent(this._keyDownList['AltRight'], 'AltRight', false);
                this.onkeyevent(this._keyDownList['ControlLeft'], 'ControlLeft', false);
            }
        }

        this.onkeyevent(keysym, code, down);

        if (fakeAltGraph) {
            this.onkeyevent(this._keyDownList['ControlLeft'], 'ControlLeft', true);
            this.onkeyevent(this._keyDownList['AltRight'], 'AltRight', true);
        }
    },

    _getKeyCode: function (e) {
        var code = KeyboardUtil.getKeycode(e);
        if (code !== 'Unidentified') {
            return code;
        }

        // Unstable, but we don't have anything else to go on
        // (don't use it for 'keypress' events thought since
        // WebKit sets it to the same as charCode)
        if (e.keyCode && e.type !== 'keypress') {
            // 229 is used for composition events
            if (e.keyCode !== 229) {
                return 'Platform' + e.keyCode;
            }
        }

        // A precursor to the final DOM3 standard. Unfortunately it
        // is not layout independent, so it is as bad as using keyCode
        if (e.keyIdentifier) {
            // Non-character key?
            if (e.keyIdentifier.substr(0, 2) !== 'U+') {
                return e.keyIdentifier;
            }

            var codepoint = parseInt(e.keyIdentifier.substr(2), 16);
            var char = String.fromCharCode(codepoint);
            // Some implementations fail to uppercase the symbols
            char = char.toUpperCase();

            return 'Platform' + char.charCodeAt();
        }

        return 'Unidentified';
    },

    _handleKeyDown: function (e) {
        var code = this._getKeyCode(e);
        var keysym = KeyboardUtil.getKeysym(e);

        // We cannot handle keys we cannot track, but we also need
        // to deal with virtual keyboards which omit key info
        // (iOS omits tracking info on keyup events, which forces us to
        // special treat that platform here)
        if (code === 'Unidentified' || browser.isIOS()) {
            if (keysym) {
                // If it's a virtual keyboard then it should be
                // sufficient to just send press and release right
                // after each other
                this._sendKeyEvent(keysym, code, true);
                this._sendKeyEvent(keysym, code, false);
            }

            (0, _events.stopEvent)(e);
            return;
        }

        // Alt behaves more like AltGraph on macOS, so shuffle the
        // keys around a bit to make things more sane for the remote
        // server. This method is used by RealVNC and TigerVNC (and
        // possibly others).
        if (browser.isMac()) {
            switch (keysym) {
                case _keysym2.default.XK_Super_L:
                    keysym = _keysym2.default.XK_Alt_L;
                    break;
                case _keysym2.default.XK_Super_R:
                    keysym = _keysym2.default.XK_Super_L;
                    break;
                case _keysym2.default.XK_Alt_L:
                    keysym = _keysym2.default.XK_Mode_switch;
                    break;
                case _keysym2.default.XK_Alt_R:
                    keysym = _keysym2.default.XK_ISO_Level3_Shift;
                    break;
            }
        }

        // Is this key already pressed? If so, then we must use the
        // same keysym or we'll confuse the server
        if (code in this._keyDownList) {
            keysym = this._keyDownList[code];
        }

        // macOS doesn't send proper key events for modifiers, only
        // state change events. That gets extra confusing for CapsLock
        // which toggles on each press, but not on release. So pretend
        // it was a quick press and release of the button.
        if (browser.isMac() && code === 'CapsLock') {
            this._sendKeyEvent(_keysym2.default.XK_Caps_Lock, 'CapsLock', true);
            this._sendKeyEvent(_keysym2.default.XK_Caps_Lock, 'CapsLock', false);
            (0, _events.stopEvent)(e);
            return;
        }

        // If this is a legacy browser then we'll need to wait for
        // a keypress event as well
        // (IE and Edge has a broken KeyboardEvent.key, so we can't
        // just check for the presence of that field)
        if (!keysym && (!e.key || browser.isIE() || browser.isEdge())) {
            this._pendingKey = code;
            // However we might not get a keypress event if the key
            // is non-printable, which needs some special fallback
            // handling
            setTimeout(this._handleKeyPressTimeout.bind(this), 10, e);
            return;
        }

        this._pendingKey = null;
        (0, _events.stopEvent)(e);

        this._keyDownList[code] = keysym;

        this._sendKeyEvent(keysym, code, true);
    },

    // Legacy event for browsers without code/key
    _handleKeyPress: function (e) {
        (0, _events.stopEvent)(e);

        // Are we expecting a keypress?
        if (this._pendingKey === null) {
            return;
        }

        var code = this._getKeyCode(e);
        var keysym = KeyboardUtil.getKeysym(e);

        // The key we were waiting for?
        if (code !== 'Unidentified' && code != this._pendingKey) {
            return;
        }

        code = this._pendingKey;
        this._pendingKey = null;

        if (!keysym) {
            Log.Info('keypress with no keysym:', e);
            return;
        }

        this._keyDownList[code] = keysym;

        this._sendKeyEvent(keysym, code, true);
    },
    _handleKeyPressTimeout: function (e) {
        // Did someone manage to sort out the key already?
        if (this._pendingKey === null) {
            return;
        }

        var code, keysym;

        code = this._pendingKey;
        this._pendingKey = null;

        // We have no way of knowing the proper keysym with the
        // information given, but the following are true for most
        // layouts
        if (e.keyCode >= 0x30 && e.keyCode <= 0x39) {
            // Digit
            keysym = e.keyCode;
        } else if (e.keyCode >= 0x41 && e.keyCode <= 0x5a) {
            // Character (A-Z)
            var char = String.fromCharCode(e.keyCode);
            // A feeble attempt at the correct case
            if (e.shiftKey) char = char.toUpperCase();else char = char.toLowerCase();
            keysym = char.charCodeAt();
        } else {
            // Unknown, give up
            keysym = 0;
        }

        this._keyDownList[code] = keysym;

        this._sendKeyEvent(keysym, code, true);
    },

    _handleKeyUp: function (e) {
        (0, _events.stopEvent)(e);

        var code = this._getKeyCode(e);

        // See comment in _handleKeyDown()
        if (browser.isMac() && code === 'CapsLock') {
            this._sendKeyEvent(_keysym2.default.XK_Caps_Lock, 'CapsLock', true);
            this._sendKeyEvent(_keysym2.default.XK_Caps_Lock, 'CapsLock', false);
            return;
        }

        // Do we really think this key is down?
        if (!(code in this._keyDownList)) {
            return;
        }

        this._sendKeyEvent(this._keyDownList[code], code, false);

        delete this._keyDownList[code];
    },

    _allKeysUp: function () {
        Log.Debug(">> Keyboard.allKeysUp");
        for (var code in this._keyDownList) {
            this._sendKeyEvent(this._keyDownList[code], code, false);
        };
        this._keyDownList = {};
        Log.Debug("<< Keyboard.allKeysUp");
    },

    // ===== PUBLIC METHODS =====

    grab: function () {
        //Log.Debug(">> Keyboard.grab");
        var c = this._target;

        c.addEventListener('keydown', this._eventHandlers.keydown);
        c.addEventListener('keyup', this._eventHandlers.keyup);
        c.addEventListener('keypress', this._eventHandlers.keypress);

        // Release (key up) if window loses focus
        window.addEventListener('blur', this._eventHandlers.blur);

        //Log.Debug("<< Keyboard.grab");
    },

    ungrab: function () {
        //Log.Debug(">> Keyboard.ungrab");
        var c = this._target;

        c.removeEventListener('keydown', this._eventHandlers.keydown);
        c.removeEventListener('keyup', this._eventHandlers.keyup);
        c.removeEventListener('keypress', this._eventHandlers.keypress);
        window.removeEventListener('blur', this._eventHandlers.blur);

        // Release (key up) all keys that are in a down state
        this._allKeysUp();

        //Log.Debug(">> Keyboard.ungrab");
    }
};
},{"../util/browser.js":19,"../util/events.js":20,"../util/logging.js":22,"./keysym.js":12,"./util.js":15}],12:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = {
  XK_VoidSymbol: 0xffffff, /* Void symbol */

  XK_BackSpace: 0xff08, /* Back space, back char */
  XK_Tab: 0xff09,
  XK_Linefeed: 0xff0a, /* Linefeed, LF */
  XK_Clear: 0xff0b,
  XK_Return: 0xff0d, /* Return, enter */
  XK_Pause: 0xff13, /* Pause, hold */
  XK_Scroll_Lock: 0xff14,
  XK_Sys_Req: 0xff15,
  XK_Escape: 0xff1b,
  XK_Delete: 0xffff, /* Delete, rubout */

  /* International & multi-key character composition */

  XK_Multi_key: 0xff20, /* Multi-key character compose */
  XK_Codeinput: 0xff37,
  XK_SingleCandidate: 0xff3c,
  XK_MultipleCandidate: 0xff3d,
  XK_PreviousCandidate: 0xff3e,

  /* Japanese keyboard support */

  XK_Kanji: 0xff21, /* Kanji, Kanji convert */
  XK_Muhenkan: 0xff22, /* Cancel Conversion */
  XK_Henkan_Mode: 0xff23, /* Start/Stop Conversion */
  XK_Henkan: 0xff23, /* Alias for Henkan_Mode */
  XK_Romaji: 0xff24, /* to Romaji */
  XK_Hiragana: 0xff25, /* to Hiragana */
  XK_Katakana: 0xff26, /* to Katakana */
  XK_Hiragana_Katakana: 0xff27, /* Hiragana/Katakana toggle */
  XK_Zenkaku: 0xff28, /* to Zenkaku */
  XK_Hankaku: 0xff29, /* to Hankaku */
  XK_Zenkaku_Hankaku: 0xff2a, /* Zenkaku/Hankaku toggle */
  XK_Touroku: 0xff2b, /* Add to Dictionary */
  XK_Massyo: 0xff2c, /* Delete from Dictionary */
  XK_Kana_Lock: 0xff2d, /* Kana Lock */
  XK_Kana_Shift: 0xff2e, /* Kana Shift */
  XK_Eisu_Shift: 0xff2f, /* Alphanumeric Shift */
  XK_Eisu_toggle: 0xff30, /* Alphanumeric toggle */
  XK_Kanji_Bangou: 0xff37, /* Codeinput */
  XK_Zen_Koho: 0xff3d, /* Multiple/All Candidate(s) */
  XK_Mae_Koho: 0xff3e, /* Previous Candidate */

  /* Cursor control & motion */

  XK_Home: 0xff50,
  XK_Left: 0xff51, /* Move left, left arrow */
  XK_Up: 0xff52, /* Move up, up arrow */
  XK_Right: 0xff53, /* Move right, right arrow */
  XK_Down: 0xff54, /* Move down, down arrow */
  XK_Prior: 0xff55, /* Prior, previous */
  XK_Page_Up: 0xff55,
  XK_Next: 0xff56, /* Next */
  XK_Page_Down: 0xff56,
  XK_End: 0xff57, /* EOL */
  XK_Begin: 0xff58, /* BOL */

  /* Misc functions */

  XK_Select: 0xff60, /* Select, mark */
  XK_Print: 0xff61,
  XK_Execute: 0xff62, /* Execute, run, do */
  XK_Insert: 0xff63, /* Insert, insert here */
  XK_Undo: 0xff65,
  XK_Redo: 0xff66, /* Redo, again */
  XK_Menu: 0xff67,
  XK_Find: 0xff68, /* Find, search */
  XK_Cancel: 0xff69, /* Cancel, stop, abort, exit */
  XK_Help: 0xff6a, /* Help */
  XK_Break: 0xff6b,
  XK_Mode_switch: 0xff7e, /* Character set switch */
  XK_script_switch: 0xff7e, /* Alias for mode_switch */
  XK_Num_Lock: 0xff7f,

  /* Keypad functions, keypad numbers cleverly chosen to map to ASCII */

  XK_KP_Space: 0xff80, /* Space */
  XK_KP_Tab: 0xff89,
  XK_KP_Enter: 0xff8d, /* Enter */
  XK_KP_F1: 0xff91, /* PF1, KP_A, ... */
  XK_KP_F2: 0xff92,
  XK_KP_F3: 0xff93,
  XK_KP_F4: 0xff94,
  XK_KP_Home: 0xff95,
  XK_KP_Left: 0xff96,
  XK_KP_Up: 0xff97,
  XK_KP_Right: 0xff98,
  XK_KP_Down: 0xff99,
  XK_KP_Prior: 0xff9a,
  XK_KP_Page_Up: 0xff9a,
  XK_KP_Next: 0xff9b,
  XK_KP_Page_Down: 0xff9b,
  XK_KP_End: 0xff9c,
  XK_KP_Begin: 0xff9d,
  XK_KP_Insert: 0xff9e,
  XK_KP_Delete: 0xff9f,
  XK_KP_Equal: 0xffbd, /* Equals */
  XK_KP_Multiply: 0xffaa,
  XK_KP_Add: 0xffab,
  XK_KP_Separator: 0xffac, /* Separator, often comma */
  XK_KP_Subtract: 0xffad,
  XK_KP_Decimal: 0xffae,
  XK_KP_Divide: 0xffaf,

  XK_KP_0: 0xffb0,
  XK_KP_1: 0xffb1,
  XK_KP_2: 0xffb2,
  XK_KP_3: 0xffb3,
  XK_KP_4: 0xffb4,
  XK_KP_5: 0xffb5,
  XK_KP_6: 0xffb6,
  XK_KP_7: 0xffb7,
  XK_KP_8: 0xffb8,
  XK_KP_9: 0xffb9,

  /*
   * Auxiliary functions; note the duplicate definitions for left and right
   * function keys;  Sun keyboards and a few other manufacturers have such
   * function key groups on the left and/or right sides of the keyboard.
   * We've not found a keyboard with more than 35 function keys total.
   */

  XK_F1: 0xffbe,
  XK_F2: 0xffbf,
  XK_F3: 0xffc0,
  XK_F4: 0xffc1,
  XK_F5: 0xffc2,
  XK_F6: 0xffc3,
  XK_F7: 0xffc4,
  XK_F8: 0xffc5,
  XK_F9: 0xffc6,
  XK_F10: 0xffc7,
  XK_F11: 0xffc8,
  XK_L1: 0xffc8,
  XK_F12: 0xffc9,
  XK_L2: 0xffc9,
  XK_F13: 0xffca,
  XK_L3: 0xffca,
  XK_F14: 0xffcb,
  XK_L4: 0xffcb,
  XK_F15: 0xffcc,
  XK_L5: 0xffcc,
  XK_F16: 0xffcd,
  XK_L6: 0xffcd,
  XK_F17: 0xffce,
  XK_L7: 0xffce,
  XK_F18: 0xffcf,
  XK_L8: 0xffcf,
  XK_F19: 0xffd0,
  XK_L9: 0xffd0,
  XK_F20: 0xffd1,
  XK_L10: 0xffd1,
  XK_F21: 0xffd2,
  XK_R1: 0xffd2,
  XK_F22: 0xffd3,
  XK_R2: 0xffd3,
  XK_F23: 0xffd4,
  XK_R3: 0xffd4,
  XK_F24: 0xffd5,
  XK_R4: 0xffd5,
  XK_F25: 0xffd6,
  XK_R5: 0xffd6,
  XK_F26: 0xffd7,
  XK_R6: 0xffd7,
  XK_F27: 0xffd8,
  XK_R7: 0xffd8,
  XK_F28: 0xffd9,
  XK_R8: 0xffd9,
  XK_F29: 0xffda,
  XK_R9: 0xffda,
  XK_F30: 0xffdb,
  XK_R10: 0xffdb,
  XK_F31: 0xffdc,
  XK_R11: 0xffdc,
  XK_F32: 0xffdd,
  XK_R12: 0xffdd,
  XK_F33: 0xffde,
  XK_R13: 0xffde,
  XK_F34: 0xffdf,
  XK_R14: 0xffdf,
  XK_F35: 0xffe0,
  XK_R15: 0xffe0,

  /* Modifiers */

  XK_Shift_L: 0xffe1, /* Left shift */
  XK_Shift_R: 0xffe2, /* Right shift */
  XK_Control_L: 0xffe3, /* Left control */
  XK_Control_R: 0xffe4, /* Right control */
  XK_Caps_Lock: 0xffe5, /* Caps lock */
  XK_Shift_Lock: 0xffe6, /* Shift lock */

  XK_Meta_L: 0xffe7, /* Left meta */
  XK_Meta_R: 0xffe8, /* Right meta */
  XK_Alt_L: 0xffe9, /* Left alt */
  XK_Alt_R: 0xffea, /* Right alt */
  XK_Super_L: 0xffeb, /* Left super */
  XK_Super_R: 0xffec, /* Right super */
  XK_Hyper_L: 0xffed, /* Left hyper */
  XK_Hyper_R: 0xffee, /* Right hyper */

  /*
   * Keyboard (XKB) Extension function and modifier keys
   * (from Appendix C of "The X Keyboard Extension: Protocol Specification")
   * Byte 3 = 0xfe
   */

  XK_ISO_Level3_Shift: 0xfe03, /* AltGr */
  XK_ISO_Next_Group: 0xfe08,
  XK_ISO_Prev_Group: 0xfe0a,
  XK_ISO_First_Group: 0xfe0c,
  XK_ISO_Last_Group: 0xfe0e,

  /*
   * Latin 1
   * (ISO/IEC 8859-1: Unicode U+0020..U+00FF)
   * Byte 3: 0
   */

  XK_space: 0x0020, /* U+0020 SPACE */
  XK_exclam: 0x0021, /* U+0021 EXCLAMATION MARK */
  XK_quotedbl: 0x0022, /* U+0022 QUOTATION MARK */
  XK_numbersign: 0x0023, /* U+0023 NUMBER SIGN */
  XK_dollar: 0x0024, /* U+0024 DOLLAR SIGN */
  XK_percent: 0x0025, /* U+0025 PERCENT SIGN */
  XK_ampersand: 0x0026, /* U+0026 AMPERSAND */
  XK_apostrophe: 0x0027, /* U+0027 APOSTROPHE */
  XK_quoteright: 0x0027, /* deprecated */
  XK_parenleft: 0x0028, /* U+0028 LEFT PARENTHESIS */
  XK_parenright: 0x0029, /* U+0029 RIGHT PARENTHESIS */
  XK_asterisk: 0x002a, /* U+002A ASTERISK */
  XK_plus: 0x002b, /* U+002B PLUS SIGN */
  XK_comma: 0x002c, /* U+002C COMMA */
  XK_minus: 0x002d, /* U+002D HYPHEN-MINUS */
  XK_period: 0x002e, /* U+002E FULL STOP */
  XK_slash: 0x002f, /* U+002F SOLIDUS */
  XK_0: 0x0030, /* U+0030 DIGIT ZERO */
  XK_1: 0x0031, /* U+0031 DIGIT ONE */
  XK_2: 0x0032, /* U+0032 DIGIT TWO */
  XK_3: 0x0033, /* U+0033 DIGIT THREE */
  XK_4: 0x0034, /* U+0034 DIGIT FOUR */
  XK_5: 0x0035, /* U+0035 DIGIT FIVE */
  XK_6: 0x0036, /* U+0036 DIGIT SIX */
  XK_7: 0x0037, /* U+0037 DIGIT SEVEN */
  XK_8: 0x0038, /* U+0038 DIGIT EIGHT */
  XK_9: 0x0039, /* U+0039 DIGIT NINE */
  XK_colon: 0x003a, /* U+003A COLON */
  XK_semicolon: 0x003b, /* U+003B SEMICOLON */
  XK_less: 0x003c, /* U+003C LESS-THAN SIGN */
  XK_equal: 0x003d, /* U+003D EQUALS SIGN */
  XK_greater: 0x003e, /* U+003E GREATER-THAN SIGN */
  XK_question: 0x003f, /* U+003F QUESTION MARK */
  XK_at: 0x0040, /* U+0040 COMMERCIAL AT */
  XK_A: 0x0041, /* U+0041 LATIN CAPITAL LETTER A */
  XK_B: 0x0042, /* U+0042 LATIN CAPITAL LETTER B */
  XK_C: 0x0043, /* U+0043 LATIN CAPITAL LETTER C */
  XK_D: 0x0044, /* U+0044 LATIN CAPITAL LETTER D */
  XK_E: 0x0045, /* U+0045 LATIN CAPITAL LETTER E */
  XK_F: 0x0046, /* U+0046 LATIN CAPITAL LETTER F */
  XK_G: 0x0047, /* U+0047 LATIN CAPITAL LETTER G */
  XK_H: 0x0048, /* U+0048 LATIN CAPITAL LETTER H */
  XK_I: 0x0049, /* U+0049 LATIN CAPITAL LETTER I */
  XK_J: 0x004a, /* U+004A LATIN CAPITAL LETTER J */
  XK_K: 0x004b, /* U+004B LATIN CAPITAL LETTER K */
  XK_L: 0x004c, /* U+004C LATIN CAPITAL LETTER L */
  XK_M: 0x004d, /* U+004D LATIN CAPITAL LETTER M */
  XK_N: 0x004e, /* U+004E LATIN CAPITAL LETTER N */
  XK_O: 0x004f, /* U+004F LATIN CAPITAL LETTER O */
  XK_P: 0x0050, /* U+0050 LATIN CAPITAL LETTER P */
  XK_Q: 0x0051, /* U+0051 LATIN CAPITAL LETTER Q */
  XK_R: 0x0052, /* U+0052 LATIN CAPITAL LETTER R */
  XK_S: 0x0053, /* U+0053 LATIN CAPITAL LETTER S */
  XK_T: 0x0054, /* U+0054 LATIN CAPITAL LETTER T */
  XK_U: 0x0055, /* U+0055 LATIN CAPITAL LETTER U */
  XK_V: 0x0056, /* U+0056 LATIN CAPITAL LETTER V */
  XK_W: 0x0057, /* U+0057 LATIN CAPITAL LETTER W */
  XK_X: 0x0058, /* U+0058 LATIN CAPITAL LETTER X */
  XK_Y: 0x0059, /* U+0059 LATIN CAPITAL LETTER Y */
  XK_Z: 0x005a, /* U+005A LATIN CAPITAL LETTER Z */
  XK_bracketleft: 0x005b, /* U+005B LEFT SQUARE BRACKET */
  XK_backslash: 0x005c, /* U+005C REVERSE SOLIDUS */
  XK_bracketright: 0x005d, /* U+005D RIGHT SQUARE BRACKET */
  XK_asciicircum: 0x005e, /* U+005E CIRCUMFLEX ACCENT */
  XK_underscore: 0x005f, /* U+005F LOW LINE */
  XK_grave: 0x0060, /* U+0060 GRAVE ACCENT */
  XK_quoteleft: 0x0060, /* deprecated */
  XK_a: 0x0061, /* U+0061 LATIN SMALL LETTER A */
  XK_b: 0x0062, /* U+0062 LATIN SMALL LETTER B */
  XK_c: 0x0063, /* U+0063 LATIN SMALL LETTER C */
  XK_d: 0x0064, /* U+0064 LATIN SMALL LETTER D */
  XK_e: 0x0065, /* U+0065 LATIN SMALL LETTER E */
  XK_f: 0x0066, /* U+0066 LATIN SMALL LETTER F */
  XK_g: 0x0067, /* U+0067 LATIN SMALL LETTER G */
  XK_h: 0x0068, /* U+0068 LATIN SMALL LETTER H */
  XK_i: 0x0069, /* U+0069 LATIN SMALL LETTER I */
  XK_j: 0x006a, /* U+006A LATIN SMALL LETTER J */
  XK_k: 0x006b, /* U+006B LATIN SMALL LETTER K */
  XK_l: 0x006c, /* U+006C LATIN SMALL LETTER L */
  XK_m: 0x006d, /* U+006D LATIN SMALL LETTER M */
  XK_n: 0x006e, /* U+006E LATIN SMALL LETTER N */
  XK_o: 0x006f, /* U+006F LATIN SMALL LETTER O */
  XK_p: 0x0070, /* U+0070 LATIN SMALL LETTER P */
  XK_q: 0x0071, /* U+0071 LATIN SMALL LETTER Q */
  XK_r: 0x0072, /* U+0072 LATIN SMALL LETTER R */
  XK_s: 0x0073, /* U+0073 LATIN SMALL LETTER S */
  XK_t: 0x0074, /* U+0074 LATIN SMALL LETTER T */
  XK_u: 0x0075, /* U+0075 LATIN SMALL LETTER U */
  XK_v: 0x0076, /* U+0076 LATIN SMALL LETTER V */
  XK_w: 0x0077, /* U+0077 LATIN SMALL LETTER W */
  XK_x: 0x0078, /* U+0078 LATIN SMALL LETTER X */
  XK_y: 0x0079, /* U+0079 LATIN SMALL LETTER Y */
  XK_z: 0x007a, /* U+007A LATIN SMALL LETTER Z */
  XK_braceleft: 0x007b, /* U+007B LEFT CURLY BRACKET */
  XK_bar: 0x007c, /* U+007C VERTICAL LINE */
  XK_braceright: 0x007d, /* U+007D RIGHT CURLY BRACKET */
  XK_asciitilde: 0x007e, /* U+007E TILDE */

  XK_nobreakspace: 0x00a0, /* U+00A0 NO-BREAK SPACE */
  XK_exclamdown: 0x00a1, /* U+00A1 INVERTED EXCLAMATION MARK */
  XK_cent: 0x00a2, /* U+00A2 CENT SIGN */
  XK_sterling: 0x00a3, /* U+00A3 POUND SIGN */
  XK_currency: 0x00a4, /* U+00A4 CURRENCY SIGN */
  XK_yen: 0x00a5, /* U+00A5 YEN SIGN */
  XK_brokenbar: 0x00a6, /* U+00A6 BROKEN BAR */
  XK_section: 0x00a7, /* U+00A7 SECTION SIGN */
  XK_diaeresis: 0x00a8, /* U+00A8 DIAERESIS */
  XK_copyright: 0x00a9, /* U+00A9 COPYRIGHT SIGN */
  XK_ordfeminine: 0x00aa, /* U+00AA FEMININE ORDINAL INDICATOR */
  XK_guillemotleft: 0x00ab, /* U+00AB LEFT-POINTING DOUBLE ANGLE QUOTATION MARK */
  XK_notsign: 0x00ac, /* U+00AC NOT SIGN */
  XK_hyphen: 0x00ad, /* U+00AD SOFT HYPHEN */
  XK_registered: 0x00ae, /* U+00AE REGISTERED SIGN */
  XK_macron: 0x00af, /* U+00AF MACRON */
  XK_degree: 0x00b0, /* U+00B0 DEGREE SIGN */
  XK_plusminus: 0x00b1, /* U+00B1 PLUS-MINUS SIGN */
  XK_twosuperior: 0x00b2, /* U+00B2 SUPERSCRIPT TWO */
  XK_threesuperior: 0x00b3, /* U+00B3 SUPERSCRIPT THREE */
  XK_acute: 0x00b4, /* U+00B4 ACUTE ACCENT */
  XK_mu: 0x00b5, /* U+00B5 MICRO SIGN */
  XK_paragraph: 0x00b6, /* U+00B6 PILCROW SIGN */
  XK_periodcentered: 0x00b7, /* U+00B7 MIDDLE DOT */
  XK_cedilla: 0x00b8, /* U+00B8 CEDILLA */
  XK_onesuperior: 0x00b9, /* U+00B9 SUPERSCRIPT ONE */
  XK_masculine: 0x00ba, /* U+00BA MASCULINE ORDINAL INDICATOR */
  XK_guillemotright: 0x00bb, /* U+00BB RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK */
  XK_onequarter: 0x00bc, /* U+00BC VULGAR FRACTION ONE QUARTER */
  XK_onehalf: 0x00bd, /* U+00BD VULGAR FRACTION ONE HALF */
  XK_threequarters: 0x00be, /* U+00BE VULGAR FRACTION THREE QUARTERS */
  XK_questiondown: 0x00bf, /* U+00BF INVERTED QUESTION MARK */
  XK_Agrave: 0x00c0, /* U+00C0 LATIN CAPITAL LETTER A WITH GRAVE */
  XK_Aacute: 0x00c1, /* U+00C1 LATIN CAPITAL LETTER A WITH ACUTE */
  XK_Acircumflex: 0x00c2, /* U+00C2 LATIN CAPITAL LETTER A WITH CIRCUMFLEX */
  XK_Atilde: 0x00c3, /* U+00C3 LATIN CAPITAL LETTER A WITH TILDE */
  XK_Adiaeresis: 0x00c4, /* U+00C4 LATIN CAPITAL LETTER A WITH DIAERESIS */
  XK_Aring: 0x00c5, /* U+00C5 LATIN CAPITAL LETTER A WITH RING ABOVE */
  XK_AE: 0x00c6, /* U+00C6 LATIN CAPITAL LETTER AE */
  XK_Ccedilla: 0x00c7, /* U+00C7 LATIN CAPITAL LETTER C WITH CEDILLA */
  XK_Egrave: 0x00c8, /* U+00C8 LATIN CAPITAL LETTER E WITH GRAVE */
  XK_Eacute: 0x00c9, /* U+00C9 LATIN CAPITAL LETTER E WITH ACUTE */
  XK_Ecircumflex: 0x00ca, /* U+00CA LATIN CAPITAL LETTER E WITH CIRCUMFLEX */
  XK_Ediaeresis: 0x00cb, /* U+00CB LATIN CAPITAL LETTER E WITH DIAERESIS */
  XK_Igrave: 0x00cc, /* U+00CC LATIN CAPITAL LETTER I WITH GRAVE */
  XK_Iacute: 0x00cd, /* U+00CD LATIN CAPITAL LETTER I WITH ACUTE */
  XK_Icircumflex: 0x00ce, /* U+00CE LATIN CAPITAL LETTER I WITH CIRCUMFLEX */
  XK_Idiaeresis: 0x00cf, /* U+00CF LATIN CAPITAL LETTER I WITH DIAERESIS */
  XK_ETH: 0x00d0, /* U+00D0 LATIN CAPITAL LETTER ETH */
  XK_Eth: 0x00d0, /* deprecated */
  XK_Ntilde: 0x00d1, /* U+00D1 LATIN CAPITAL LETTER N WITH TILDE */
  XK_Ograve: 0x00d2, /* U+00D2 LATIN CAPITAL LETTER O WITH GRAVE */
  XK_Oacute: 0x00d3, /* U+00D3 LATIN CAPITAL LETTER O WITH ACUTE */
  XK_Ocircumflex: 0x00d4, /* U+00D4 LATIN CAPITAL LETTER O WITH CIRCUMFLEX */
  XK_Otilde: 0x00d5, /* U+00D5 LATIN CAPITAL LETTER O WITH TILDE */
  XK_Odiaeresis: 0x00d6, /* U+00D6 LATIN CAPITAL LETTER O WITH DIAERESIS */
  XK_multiply: 0x00d7, /* U+00D7 MULTIPLICATION SIGN */
  XK_Oslash: 0x00d8, /* U+00D8 LATIN CAPITAL LETTER O WITH STROKE */
  XK_Ooblique: 0x00d8, /* U+00D8 LATIN CAPITAL LETTER O WITH STROKE */
  XK_Ugrave: 0x00d9, /* U+00D9 LATIN CAPITAL LETTER U WITH GRAVE */
  XK_Uacute: 0x00da, /* U+00DA LATIN CAPITAL LETTER U WITH ACUTE */
  XK_Ucircumflex: 0x00db, /* U+00DB LATIN CAPITAL LETTER U WITH CIRCUMFLEX */
  XK_Udiaeresis: 0x00dc, /* U+00DC LATIN CAPITAL LETTER U WITH DIAERESIS */
  XK_Yacute: 0x00dd, /* U+00DD LATIN CAPITAL LETTER Y WITH ACUTE */
  XK_THORN: 0x00de, /* U+00DE LATIN CAPITAL LETTER THORN */
  XK_Thorn: 0x00de, /* deprecated */
  XK_ssharp: 0x00df, /* U+00DF LATIN SMALL LETTER SHARP S */
  XK_agrave: 0x00e0, /* U+00E0 LATIN SMALL LETTER A WITH GRAVE */
  XK_aacute: 0x00e1, /* U+00E1 LATIN SMALL LETTER A WITH ACUTE */
  XK_acircumflex: 0x00e2, /* U+00E2 LATIN SMALL LETTER A WITH CIRCUMFLEX */
  XK_atilde: 0x00e3, /* U+00E3 LATIN SMALL LETTER A WITH TILDE */
  XK_adiaeresis: 0x00e4, /* U+00E4 LATIN SMALL LETTER A WITH DIAERESIS */
  XK_aring: 0x00e5, /* U+00E5 LATIN SMALL LETTER A WITH RING ABOVE */
  XK_ae: 0x00e6, /* U+00E6 LATIN SMALL LETTER AE */
  XK_ccedilla: 0x00e7, /* U+00E7 LATIN SMALL LETTER C WITH CEDILLA */
  XK_egrave: 0x00e8, /* U+00E8 LATIN SMALL LETTER E WITH GRAVE */
  XK_eacute: 0x00e9, /* U+00E9 LATIN SMALL LETTER E WITH ACUTE */
  XK_ecircumflex: 0x00ea, /* U+00EA LATIN SMALL LETTER E WITH CIRCUMFLEX */
  XK_ediaeresis: 0x00eb, /* U+00EB LATIN SMALL LETTER E WITH DIAERESIS */
  XK_igrave: 0x00ec, /* U+00EC LATIN SMALL LETTER I WITH GRAVE */
  XK_iacute: 0x00ed, /* U+00ED LATIN SMALL LETTER I WITH ACUTE */
  XK_icircumflex: 0x00ee, /* U+00EE LATIN SMALL LETTER I WITH CIRCUMFLEX */
  XK_idiaeresis: 0x00ef, /* U+00EF LATIN SMALL LETTER I WITH DIAERESIS */
  XK_eth: 0x00f0, /* U+00F0 LATIN SMALL LETTER ETH */
  XK_ntilde: 0x00f1, /* U+00F1 LATIN SMALL LETTER N WITH TILDE */
  XK_ograve: 0x00f2, /* U+00F2 LATIN SMALL LETTER O WITH GRAVE */
  XK_oacute: 0x00f3, /* U+00F3 LATIN SMALL LETTER O WITH ACUTE */
  XK_ocircumflex: 0x00f4, /* U+00F4 LATIN SMALL LETTER O WITH CIRCUMFLEX */
  XK_otilde: 0x00f5, /* U+00F5 LATIN SMALL LETTER O WITH TILDE */
  XK_odiaeresis: 0x00f6, /* U+00F6 LATIN SMALL LETTER O WITH DIAERESIS */
  XK_division: 0x00f7, /* U+00F7 DIVISION SIGN */
  XK_oslash: 0x00f8, /* U+00F8 LATIN SMALL LETTER O WITH STROKE */
  XK_ooblique: 0x00f8, /* U+00F8 LATIN SMALL LETTER O WITH STROKE */
  XK_ugrave: 0x00f9, /* U+00F9 LATIN SMALL LETTER U WITH GRAVE */
  XK_uacute: 0x00fa, /* U+00FA LATIN SMALL LETTER U WITH ACUTE */
  XK_ucircumflex: 0x00fb, /* U+00FB LATIN SMALL LETTER U WITH CIRCUMFLEX */
  XK_udiaeresis: 0x00fc, /* U+00FC LATIN SMALL LETTER U WITH DIAERESIS */
  XK_yacute: 0x00fd, /* U+00FD LATIN SMALL LETTER Y WITH ACUTE */
  XK_thorn: 0x00fe, /* U+00FE LATIN SMALL LETTER THORN */
  XK_ydiaeresis: 0x00ff, /* U+00FF LATIN SMALL LETTER Y WITH DIAERESIS */

  /*
   * Korean
   * Byte 3 = 0x0e
   */

  XK_Hangul: 0xff31, /* Hangul start/stop(toggle) */
  XK_Hangul_Hanja: 0xff34, /* Start Hangul->Hanja Conversion */
  XK_Hangul_Jeonja: 0xff38, /* Jeonja mode */

  /*
   * XFree86 vendor specific keysyms.
   *
   * The XFree86 keysym range is 0x10080001 - 0x1008FFFF.
   */

  XF86XK_ModeLock: 0x1008FF01,
  XF86XK_MonBrightnessUp: 0x1008FF02,
  XF86XK_MonBrightnessDown: 0x1008FF03,
  XF86XK_KbdLightOnOff: 0x1008FF04,
  XF86XK_KbdBrightnessUp: 0x1008FF05,
  XF86XK_KbdBrightnessDown: 0x1008FF06,
  XF86XK_Standby: 0x1008FF10,
  XF86XK_AudioLowerVolume: 0x1008FF11,
  XF86XK_AudioMute: 0x1008FF12,
  XF86XK_AudioRaiseVolume: 0x1008FF13,
  XF86XK_AudioPlay: 0x1008FF14,
  XF86XK_AudioStop: 0x1008FF15,
  XF86XK_AudioPrev: 0x1008FF16,
  XF86XK_AudioNext: 0x1008FF17,
  XF86XK_HomePage: 0x1008FF18,
  XF86XK_Mail: 0x1008FF19,
  XF86XK_Start: 0x1008FF1A,
  XF86XK_Search: 0x1008FF1B,
  XF86XK_AudioRecord: 0x1008FF1C,
  XF86XK_Calculator: 0x1008FF1D,
  XF86XK_Memo: 0x1008FF1E,
  XF86XK_ToDoList: 0x1008FF1F,
  XF86XK_Calendar: 0x1008FF20,
  XF86XK_PowerDown: 0x1008FF21,
  XF86XK_ContrastAdjust: 0x1008FF22,
  XF86XK_RockerUp: 0x1008FF23,
  XF86XK_RockerDown: 0x1008FF24,
  XF86XK_RockerEnter: 0x1008FF25,
  XF86XK_Back: 0x1008FF26,
  XF86XK_Forward: 0x1008FF27,
  XF86XK_Stop: 0x1008FF28,
  XF86XK_Refresh: 0x1008FF29,
  XF86XK_PowerOff: 0x1008FF2A,
  XF86XK_WakeUp: 0x1008FF2B,
  XF86XK_Eject: 0x1008FF2C,
  XF86XK_ScreenSaver: 0x1008FF2D,
  XF86XK_WWW: 0x1008FF2E,
  XF86XK_Sleep: 0x1008FF2F,
  XF86XK_Favorites: 0x1008FF30,
  XF86XK_AudioPause: 0x1008FF31,
  XF86XK_AudioMedia: 0x1008FF32,
  XF86XK_MyComputer: 0x1008FF33,
  XF86XK_VendorHome: 0x1008FF34,
  XF86XK_LightBulb: 0x1008FF35,
  XF86XK_Shop: 0x1008FF36,
  XF86XK_History: 0x1008FF37,
  XF86XK_OpenURL: 0x1008FF38,
  XF86XK_AddFavorite: 0x1008FF39,
  XF86XK_HotLinks: 0x1008FF3A,
  XF86XK_BrightnessAdjust: 0x1008FF3B,
  XF86XK_Finance: 0x1008FF3C,
  XF86XK_Community: 0x1008FF3D,
  XF86XK_AudioRewind: 0x1008FF3E,
  XF86XK_BackForward: 0x1008FF3F,
  XF86XK_Launch0: 0x1008FF40,
  XF86XK_Launch1: 0x1008FF41,
  XF86XK_Launch2: 0x1008FF42,
  XF86XK_Launch3: 0x1008FF43,
  XF86XK_Launch4: 0x1008FF44,
  XF86XK_Launch5: 0x1008FF45,
  XF86XK_Launch6: 0x1008FF46,
  XF86XK_Launch7: 0x1008FF47,
  XF86XK_Launch8: 0x1008FF48,
  XF86XK_Launch9: 0x1008FF49,
  XF86XK_LaunchA: 0x1008FF4A,
  XF86XK_LaunchB: 0x1008FF4B,
  XF86XK_LaunchC: 0x1008FF4C,
  XF86XK_LaunchD: 0x1008FF4D,
  XF86XK_LaunchE: 0x1008FF4E,
  XF86XK_LaunchF: 0x1008FF4F,
  XF86XK_ApplicationLeft: 0x1008FF50,
  XF86XK_ApplicationRight: 0x1008FF51,
  XF86XK_Book: 0x1008FF52,
  XF86XK_CD: 0x1008FF53,
  XF86XK_Calculater: 0x1008FF54,
  XF86XK_Clear: 0x1008FF55,
  XF86XK_Close: 0x1008FF56,
  XF86XK_Copy: 0x1008FF57,
  XF86XK_Cut: 0x1008FF58,
  XF86XK_Display: 0x1008FF59,
  XF86XK_DOS: 0x1008FF5A,
  XF86XK_Documents: 0x1008FF5B,
  XF86XK_Excel: 0x1008FF5C,
  XF86XK_Explorer: 0x1008FF5D,
  XF86XK_Game: 0x1008FF5E,
  XF86XK_Go: 0x1008FF5F,
  XF86XK_iTouch: 0x1008FF60,
  XF86XK_LogOff: 0x1008FF61,
  XF86XK_Market: 0x1008FF62,
  XF86XK_Meeting: 0x1008FF63,
  XF86XK_MenuKB: 0x1008FF65,
  XF86XK_MenuPB: 0x1008FF66,
  XF86XK_MySites: 0x1008FF67,
  XF86XK_New: 0x1008FF68,
  XF86XK_News: 0x1008FF69,
  XF86XK_OfficeHome: 0x1008FF6A,
  XF86XK_Open: 0x1008FF6B,
  XF86XK_Option: 0x1008FF6C,
  XF86XK_Paste: 0x1008FF6D,
  XF86XK_Phone: 0x1008FF6E,
  XF86XK_Q: 0x1008FF70,
  XF86XK_Reply: 0x1008FF72,
  XF86XK_Reload: 0x1008FF73,
  XF86XK_RotateWindows: 0x1008FF74,
  XF86XK_RotationPB: 0x1008FF75,
  XF86XK_RotationKB: 0x1008FF76,
  XF86XK_Save: 0x1008FF77,
  XF86XK_ScrollUp: 0x1008FF78,
  XF86XK_ScrollDown: 0x1008FF79,
  XF86XK_ScrollClick: 0x1008FF7A,
  XF86XK_Send: 0x1008FF7B,
  XF86XK_Spell: 0x1008FF7C,
  XF86XK_SplitScreen: 0x1008FF7D,
  XF86XK_Support: 0x1008FF7E,
  XF86XK_TaskPane: 0x1008FF7F,
  XF86XK_Terminal: 0x1008FF80,
  XF86XK_Tools: 0x1008FF81,
  XF86XK_Travel: 0x1008FF82,
  XF86XK_UserPB: 0x1008FF84,
  XF86XK_User1KB: 0x1008FF85,
  XF86XK_User2KB: 0x1008FF86,
  XF86XK_Video: 0x1008FF87,
  XF86XK_WheelButton: 0x1008FF88,
  XF86XK_Word: 0x1008FF89,
  XF86XK_Xfer: 0x1008FF8A,
  XF86XK_ZoomIn: 0x1008FF8B,
  XF86XK_ZoomOut: 0x1008FF8C,
  XF86XK_Away: 0x1008FF8D,
  XF86XK_Messenger: 0x1008FF8E,
  XF86XK_WebCam: 0x1008FF8F,
  XF86XK_MailForward: 0x1008FF90,
  XF86XK_Pictures: 0x1008FF91,
  XF86XK_Music: 0x1008FF92,
  XF86XK_Battery: 0x1008FF93,
  XF86XK_Bluetooth: 0x1008FF94,
  XF86XK_WLAN: 0x1008FF95,
  XF86XK_UWB: 0x1008FF96,
  XF86XK_AudioForward: 0x1008FF97,
  XF86XK_AudioRepeat: 0x1008FF98,
  XF86XK_AudioRandomPlay: 0x1008FF99,
  XF86XK_Subtitle: 0x1008FF9A,
  XF86XK_AudioCycleTrack: 0x1008FF9B,
  XF86XK_CycleAngle: 0x1008FF9C,
  XF86XK_FrameBack: 0x1008FF9D,
  XF86XK_FrameForward: 0x1008FF9E,
  XF86XK_Time: 0x1008FF9F,
  XF86XK_Select: 0x1008FFA0,
  XF86XK_View: 0x1008FFA1,
  XF86XK_TopMenu: 0x1008FFA2,
  XF86XK_Red: 0x1008FFA3,
  XF86XK_Green: 0x1008FFA4,
  XF86XK_Yellow: 0x1008FFA5,
  XF86XK_Blue: 0x1008FFA6,
  XF86XK_Suspend: 0x1008FFA7,
  XF86XK_Hibernate: 0x1008FFA8,
  XF86XK_TouchpadToggle: 0x1008FFA9,
  XF86XK_TouchpadOn: 0x1008FFB0,
  XF86XK_TouchpadOff: 0x1008FFB1,
  XF86XK_AudioMicMute: 0x1008FFB2,
  XF86XK_Switch_VT_1: 0x1008FE01,
  XF86XK_Switch_VT_2: 0x1008FE02,
  XF86XK_Switch_VT_3: 0x1008FE03,
  XF86XK_Switch_VT_4: 0x1008FE04,
  XF86XK_Switch_VT_5: 0x1008FE05,
  XF86XK_Switch_VT_6: 0x1008FE06,
  XF86XK_Switch_VT_7: 0x1008FE07,
  XF86XK_Switch_VT_8: 0x1008FE08,
  XF86XK_Switch_VT_9: 0x1008FE09,
  XF86XK_Switch_VT_10: 0x1008FE0A,
  XF86XK_Switch_VT_11: 0x1008FE0B,
  XF86XK_Switch_VT_12: 0x1008FE0C,
  XF86XK_Ungrab: 0x1008FE20,
  XF86XK_ClearGrab: 0x1008FE21,
  XF86XK_Next_VMode: 0x1008FE22,
  XF86XK_Prev_VMode: 0x1008FE23,
  XF86XK_LogWindowTree: 0x1008FE24,
  XF86XK_LogGrabInfo: 0x1008FE25
};
},{}],13:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
/*
 * Mapping from Unicode codepoints to X11/RFB keysyms
 *
 * This file was automatically generated from keysymdef.h
 * DO NOT EDIT!
 */

/* Functions at the bottom */

var codepoints = {
    0x0100: 0x03c0, // XK_Amacron
    0x0101: 0x03e0, // XK_amacron
    0x0102: 0x01c3, // XK_Abreve
    0x0103: 0x01e3, // XK_abreve
    0x0104: 0x01a1, // XK_Aogonek
    0x0105: 0x01b1, // XK_aogonek
    0x0106: 0x01c6, // XK_Cacute
    0x0107: 0x01e6, // XK_cacute
    0x0108: 0x02c6, // XK_Ccircumflex
    0x0109: 0x02e6, // XK_ccircumflex
    0x010a: 0x02c5, // XK_Cabovedot
    0x010b: 0x02e5, // XK_cabovedot
    0x010c: 0x01c8, // XK_Ccaron
    0x010d: 0x01e8, // XK_ccaron
    0x010e: 0x01cf, // XK_Dcaron
    0x010f: 0x01ef, // XK_dcaron
    0x0110: 0x01d0, // XK_Dstroke
    0x0111: 0x01f0, // XK_dstroke
    0x0112: 0x03aa, // XK_Emacron
    0x0113: 0x03ba, // XK_emacron
    0x0116: 0x03cc, // XK_Eabovedot
    0x0117: 0x03ec, // XK_eabovedot
    0x0118: 0x01ca, // XK_Eogonek
    0x0119: 0x01ea, // XK_eogonek
    0x011a: 0x01cc, // XK_Ecaron
    0x011b: 0x01ec, // XK_ecaron
    0x011c: 0x02d8, // XK_Gcircumflex
    0x011d: 0x02f8, // XK_gcircumflex
    0x011e: 0x02ab, // XK_Gbreve
    0x011f: 0x02bb, // XK_gbreve
    0x0120: 0x02d5, // XK_Gabovedot
    0x0121: 0x02f5, // XK_gabovedot
    0x0122: 0x03ab, // XK_Gcedilla
    0x0123: 0x03bb, // XK_gcedilla
    0x0124: 0x02a6, // XK_Hcircumflex
    0x0125: 0x02b6, // XK_hcircumflex
    0x0126: 0x02a1, // XK_Hstroke
    0x0127: 0x02b1, // XK_hstroke
    0x0128: 0x03a5, // XK_Itilde
    0x0129: 0x03b5, // XK_itilde
    0x012a: 0x03cf, // XK_Imacron
    0x012b: 0x03ef, // XK_imacron
    0x012e: 0x03c7, // XK_Iogonek
    0x012f: 0x03e7, // XK_iogonek
    0x0130: 0x02a9, // XK_Iabovedot
    0x0131: 0x02b9, // XK_idotless
    0x0134: 0x02ac, // XK_Jcircumflex
    0x0135: 0x02bc, // XK_jcircumflex
    0x0136: 0x03d3, // XK_Kcedilla
    0x0137: 0x03f3, // XK_kcedilla
    0x0138: 0x03a2, // XK_kra
    0x0139: 0x01c5, // XK_Lacute
    0x013a: 0x01e5, // XK_lacute
    0x013b: 0x03a6, // XK_Lcedilla
    0x013c: 0x03b6, // XK_lcedilla
    0x013d: 0x01a5, // XK_Lcaron
    0x013e: 0x01b5, // XK_lcaron
    0x0141: 0x01a3, // XK_Lstroke
    0x0142: 0x01b3, // XK_lstroke
    0x0143: 0x01d1, // XK_Nacute
    0x0144: 0x01f1, // XK_nacute
    0x0145: 0x03d1, // XK_Ncedilla
    0x0146: 0x03f1, // XK_ncedilla
    0x0147: 0x01d2, // XK_Ncaron
    0x0148: 0x01f2, // XK_ncaron
    0x014a: 0x03bd, // XK_ENG
    0x014b: 0x03bf, // XK_eng
    0x014c: 0x03d2, // XK_Omacron
    0x014d: 0x03f2, // XK_omacron
    0x0150: 0x01d5, // XK_Odoubleacute
    0x0151: 0x01f5, // XK_odoubleacute
    0x0152: 0x13bc, // XK_OE
    0x0153: 0x13bd, // XK_oe
    0x0154: 0x01c0, // XK_Racute
    0x0155: 0x01e0, // XK_racute
    0x0156: 0x03a3, // XK_Rcedilla
    0x0157: 0x03b3, // XK_rcedilla
    0x0158: 0x01d8, // XK_Rcaron
    0x0159: 0x01f8, // XK_rcaron
    0x015a: 0x01a6, // XK_Sacute
    0x015b: 0x01b6, // XK_sacute
    0x015c: 0x02de, // XK_Scircumflex
    0x015d: 0x02fe, // XK_scircumflex
    0x015e: 0x01aa, // XK_Scedilla
    0x015f: 0x01ba, // XK_scedilla
    0x0160: 0x01a9, // XK_Scaron
    0x0161: 0x01b9, // XK_scaron
    0x0162: 0x01de, // XK_Tcedilla
    0x0163: 0x01fe, // XK_tcedilla
    0x0164: 0x01ab, // XK_Tcaron
    0x0165: 0x01bb, // XK_tcaron
    0x0166: 0x03ac, // XK_Tslash
    0x0167: 0x03bc, // XK_tslash
    0x0168: 0x03dd, // XK_Utilde
    0x0169: 0x03fd, // XK_utilde
    0x016a: 0x03de, // XK_Umacron
    0x016b: 0x03fe, // XK_umacron
    0x016c: 0x02dd, // XK_Ubreve
    0x016d: 0x02fd, // XK_ubreve
    0x016e: 0x01d9, // XK_Uring
    0x016f: 0x01f9, // XK_uring
    0x0170: 0x01db, // XK_Udoubleacute
    0x0171: 0x01fb, // XK_udoubleacute
    0x0172: 0x03d9, // XK_Uogonek
    0x0173: 0x03f9, // XK_uogonek
    0x0178: 0x13be, // XK_Ydiaeresis
    0x0179: 0x01ac, // XK_Zacute
    0x017a: 0x01bc, // XK_zacute
    0x017b: 0x01af, // XK_Zabovedot
    0x017c: 0x01bf, // XK_zabovedot
    0x017d: 0x01ae, // XK_Zcaron
    0x017e: 0x01be, // XK_zcaron
    0x0192: 0x08f6, // XK_function
    0x01d2: 0x10001d1, // XK_Ocaron
    0x02c7: 0x01b7, // XK_caron
    0x02d8: 0x01a2, // XK_breve
    0x02d9: 0x01ff, // XK_abovedot
    0x02db: 0x01b2, // XK_ogonek
    0x02dd: 0x01bd, // XK_doubleacute
    0x0385: 0x07ae, // XK_Greek_accentdieresis
    0x0386: 0x07a1, // XK_Greek_ALPHAaccent
    0x0388: 0x07a2, // XK_Greek_EPSILONaccent
    0x0389: 0x07a3, // XK_Greek_ETAaccent
    0x038a: 0x07a4, // XK_Greek_IOTAaccent
    0x038c: 0x07a7, // XK_Greek_OMICRONaccent
    0x038e: 0x07a8, // XK_Greek_UPSILONaccent
    0x038f: 0x07ab, // XK_Greek_OMEGAaccent
    0x0390: 0x07b6, // XK_Greek_iotaaccentdieresis
    0x0391: 0x07c1, // XK_Greek_ALPHA
    0x0392: 0x07c2, // XK_Greek_BETA
    0x0393: 0x07c3, // XK_Greek_GAMMA
    0x0394: 0x07c4, // XK_Greek_DELTA
    0x0395: 0x07c5, // XK_Greek_EPSILON
    0x0396: 0x07c6, // XK_Greek_ZETA
    0x0397: 0x07c7, // XK_Greek_ETA
    0x0398: 0x07c8, // XK_Greek_THETA
    0x0399: 0x07c9, // XK_Greek_IOTA
    0x039a: 0x07ca, // XK_Greek_KAPPA
    0x039b: 0x07cb, // XK_Greek_LAMDA
    0x039c: 0x07cc, // XK_Greek_MU
    0x039d: 0x07cd, // XK_Greek_NU
    0x039e: 0x07ce, // XK_Greek_XI
    0x039f: 0x07cf, // XK_Greek_OMICRON
    0x03a0: 0x07d0, // XK_Greek_PI
    0x03a1: 0x07d1, // XK_Greek_RHO
    0x03a3: 0x07d2, // XK_Greek_SIGMA
    0x03a4: 0x07d4, // XK_Greek_TAU
    0x03a5: 0x07d5, // XK_Greek_UPSILON
    0x03a6: 0x07d6, // XK_Greek_PHI
    0x03a7: 0x07d7, // XK_Greek_CHI
    0x03a8: 0x07d8, // XK_Greek_PSI
    0x03a9: 0x07d9, // XK_Greek_OMEGA
    0x03aa: 0x07a5, // XK_Greek_IOTAdieresis
    0x03ab: 0x07a9, // XK_Greek_UPSILONdieresis
    0x03ac: 0x07b1, // XK_Greek_alphaaccent
    0x03ad: 0x07b2, // XK_Greek_epsilonaccent
    0x03ae: 0x07b3, // XK_Greek_etaaccent
    0x03af: 0x07b4, // XK_Greek_iotaaccent
    0x03b0: 0x07ba, // XK_Greek_upsilonaccentdieresis
    0x03b1: 0x07e1, // XK_Greek_alpha
    0x03b2: 0x07e2, // XK_Greek_beta
    0x03b3: 0x07e3, // XK_Greek_gamma
    0x03b4: 0x07e4, // XK_Greek_delta
    0x03b5: 0x07e5, // XK_Greek_epsilon
    0x03b6: 0x07e6, // XK_Greek_zeta
    0x03b7: 0x07e7, // XK_Greek_eta
    0x03b8: 0x07e8, // XK_Greek_theta
    0x03b9: 0x07e9, // XK_Greek_iota
    0x03ba: 0x07ea, // XK_Greek_kappa
    0x03bb: 0x07eb, // XK_Greek_lamda
    0x03bc: 0x07ec, // XK_Greek_mu
    0x03bd: 0x07ed, // XK_Greek_nu
    0x03be: 0x07ee, // XK_Greek_xi
    0x03bf: 0x07ef, // XK_Greek_omicron
    0x03c0: 0x07f0, // XK_Greek_pi
    0x03c1: 0x07f1, // XK_Greek_rho
    0x03c2: 0x07f3, // XK_Greek_finalsmallsigma
    0x03c3: 0x07f2, // XK_Greek_sigma
    0x03c4: 0x07f4, // XK_Greek_tau
    0x03c5: 0x07f5, // XK_Greek_upsilon
    0x03c6: 0x07f6, // XK_Greek_phi
    0x03c7: 0x07f7, // XK_Greek_chi
    0x03c8: 0x07f8, // XK_Greek_psi
    0x03c9: 0x07f9, // XK_Greek_omega
    0x03ca: 0x07b5, // XK_Greek_iotadieresis
    0x03cb: 0x07b9, // XK_Greek_upsilondieresis
    0x03cc: 0x07b7, // XK_Greek_omicronaccent
    0x03cd: 0x07b8, // XK_Greek_upsilonaccent
    0x03ce: 0x07bb, // XK_Greek_omegaaccent
    0x0401: 0x06b3, // XK_Cyrillic_IO
    0x0402: 0x06b1, // XK_Serbian_DJE
    0x0403: 0x06b2, // XK_Macedonia_GJE
    0x0404: 0x06b4, // XK_Ukrainian_IE
    0x0405: 0x06b5, // XK_Macedonia_DSE
    0x0406: 0x06b6, // XK_Ukrainian_I
    0x0407: 0x06b7, // XK_Ukrainian_YI
    0x0408: 0x06b8, // XK_Cyrillic_JE
    0x0409: 0x06b9, // XK_Cyrillic_LJE
    0x040a: 0x06ba, // XK_Cyrillic_NJE
    0x040b: 0x06bb, // XK_Serbian_TSHE
    0x040c: 0x06bc, // XK_Macedonia_KJE
    0x040e: 0x06be, // XK_Byelorussian_SHORTU
    0x040f: 0x06bf, // XK_Cyrillic_DZHE
    0x0410: 0x06e1, // XK_Cyrillic_A
    0x0411: 0x06e2, // XK_Cyrillic_BE
    0x0412: 0x06f7, // XK_Cyrillic_VE
    0x0413: 0x06e7, // XK_Cyrillic_GHE
    0x0414: 0x06e4, // XK_Cyrillic_DE
    0x0415: 0x06e5, // XK_Cyrillic_IE
    0x0416: 0x06f6, // XK_Cyrillic_ZHE
    0x0417: 0x06fa, // XK_Cyrillic_ZE
    0x0418: 0x06e9, // XK_Cyrillic_I
    0x0419: 0x06ea, // XK_Cyrillic_SHORTI
    0x041a: 0x06eb, // XK_Cyrillic_KA
    0x041b: 0x06ec, // XK_Cyrillic_EL
    0x041c: 0x06ed, // XK_Cyrillic_EM
    0x041d: 0x06ee, // XK_Cyrillic_EN
    0x041e: 0x06ef, // XK_Cyrillic_O
    0x041f: 0x06f0, // XK_Cyrillic_PE
    0x0420: 0x06f2, // XK_Cyrillic_ER
    0x0421: 0x06f3, // XK_Cyrillic_ES
    0x0422: 0x06f4, // XK_Cyrillic_TE
    0x0423: 0x06f5, // XK_Cyrillic_U
    0x0424: 0x06e6, // XK_Cyrillic_EF
    0x0425: 0x06e8, // XK_Cyrillic_HA
    0x0426: 0x06e3, // XK_Cyrillic_TSE
    0x0427: 0x06fe, // XK_Cyrillic_CHE
    0x0428: 0x06fb, // XK_Cyrillic_SHA
    0x0429: 0x06fd, // XK_Cyrillic_SHCHA
    0x042a: 0x06ff, // XK_Cyrillic_HARDSIGN
    0x042b: 0x06f9, // XK_Cyrillic_YERU
    0x042c: 0x06f8, // XK_Cyrillic_SOFTSIGN
    0x042d: 0x06fc, // XK_Cyrillic_E
    0x042e: 0x06e0, // XK_Cyrillic_YU
    0x042f: 0x06f1, // XK_Cyrillic_YA
    0x0430: 0x06c1, // XK_Cyrillic_a
    0x0431: 0x06c2, // XK_Cyrillic_be
    0x0432: 0x06d7, // XK_Cyrillic_ve
    0x0433: 0x06c7, // XK_Cyrillic_ghe
    0x0434: 0x06c4, // XK_Cyrillic_de
    0x0435: 0x06c5, // XK_Cyrillic_ie
    0x0436: 0x06d6, // XK_Cyrillic_zhe
    0x0437: 0x06da, // XK_Cyrillic_ze
    0x0438: 0x06c9, // XK_Cyrillic_i
    0x0439: 0x06ca, // XK_Cyrillic_shorti
    0x043a: 0x06cb, // XK_Cyrillic_ka
    0x043b: 0x06cc, // XK_Cyrillic_el
    0x043c: 0x06cd, // XK_Cyrillic_em
    0x043d: 0x06ce, // XK_Cyrillic_en
    0x043e: 0x06cf, // XK_Cyrillic_o
    0x043f: 0x06d0, // XK_Cyrillic_pe
    0x0440: 0x06d2, // XK_Cyrillic_er
    0x0441: 0x06d3, // XK_Cyrillic_es
    0x0442: 0x06d4, // XK_Cyrillic_te
    0x0443: 0x06d5, // XK_Cyrillic_u
    0x0444: 0x06c6, // XK_Cyrillic_ef
    0x0445: 0x06c8, // XK_Cyrillic_ha
    0x0446: 0x06c3, // XK_Cyrillic_tse
    0x0447: 0x06de, // XK_Cyrillic_che
    0x0448: 0x06db, // XK_Cyrillic_sha
    0x0449: 0x06dd, // XK_Cyrillic_shcha
    0x044a: 0x06df, // XK_Cyrillic_hardsign
    0x044b: 0x06d9, // XK_Cyrillic_yeru
    0x044c: 0x06d8, // XK_Cyrillic_softsign
    0x044d: 0x06dc, // XK_Cyrillic_e
    0x044e: 0x06c0, // XK_Cyrillic_yu
    0x044f: 0x06d1, // XK_Cyrillic_ya
    0x0451: 0x06a3, // XK_Cyrillic_io
    0x0452: 0x06a1, // XK_Serbian_dje
    0x0453: 0x06a2, // XK_Macedonia_gje
    0x0454: 0x06a4, // XK_Ukrainian_ie
    0x0455: 0x06a5, // XK_Macedonia_dse
    0x0456: 0x06a6, // XK_Ukrainian_i
    0x0457: 0x06a7, // XK_Ukrainian_yi
    0x0458: 0x06a8, // XK_Cyrillic_je
    0x0459: 0x06a9, // XK_Cyrillic_lje
    0x045a: 0x06aa, // XK_Cyrillic_nje
    0x045b: 0x06ab, // XK_Serbian_tshe
    0x045c: 0x06ac, // XK_Macedonia_kje
    0x045e: 0x06ae, // XK_Byelorussian_shortu
    0x045f: 0x06af, // XK_Cyrillic_dzhe
    0x0490: 0x06bd, // XK_Ukrainian_GHE_WITH_UPTURN
    0x0491: 0x06ad, // XK_Ukrainian_ghe_with_upturn
    0x05d0: 0x0ce0, // XK_hebrew_aleph
    0x05d1: 0x0ce1, // XK_hebrew_bet
    0x05d2: 0x0ce2, // XK_hebrew_gimel
    0x05d3: 0x0ce3, // XK_hebrew_dalet
    0x05d4: 0x0ce4, // XK_hebrew_he
    0x05d5: 0x0ce5, // XK_hebrew_waw
    0x05d6: 0x0ce6, // XK_hebrew_zain
    0x05d7: 0x0ce7, // XK_hebrew_chet
    0x05d8: 0x0ce8, // XK_hebrew_tet
    0x05d9: 0x0ce9, // XK_hebrew_yod
    0x05da: 0x0cea, // XK_hebrew_finalkaph
    0x05db: 0x0ceb, // XK_hebrew_kaph
    0x05dc: 0x0cec, // XK_hebrew_lamed
    0x05dd: 0x0ced, // XK_hebrew_finalmem
    0x05de: 0x0cee, // XK_hebrew_mem
    0x05df: 0x0cef, // XK_hebrew_finalnun
    0x05e0: 0x0cf0, // XK_hebrew_nun
    0x05e1: 0x0cf1, // XK_hebrew_samech
    0x05e2: 0x0cf2, // XK_hebrew_ayin
    0x05e3: 0x0cf3, // XK_hebrew_finalpe
    0x05e4: 0x0cf4, // XK_hebrew_pe
    0x05e5: 0x0cf5, // XK_hebrew_finalzade
    0x05e6: 0x0cf6, // XK_hebrew_zade
    0x05e7: 0x0cf7, // XK_hebrew_qoph
    0x05e8: 0x0cf8, // XK_hebrew_resh
    0x05e9: 0x0cf9, // XK_hebrew_shin
    0x05ea: 0x0cfa, // XK_hebrew_taw
    0x060c: 0x05ac, // XK_Arabic_comma
    0x061b: 0x05bb, // XK_Arabic_semicolon
    0x061f: 0x05bf, // XK_Arabic_question_mark
    0x0621: 0x05c1, // XK_Arabic_hamza
    0x0622: 0x05c2, // XK_Arabic_maddaonalef
    0x0623: 0x05c3, // XK_Arabic_hamzaonalef
    0x0624: 0x05c4, // XK_Arabic_hamzaonwaw
    0x0625: 0x05c5, // XK_Arabic_hamzaunderalef
    0x0626: 0x05c6, // XK_Arabic_hamzaonyeh
    0x0627: 0x05c7, // XK_Arabic_alef
    0x0628: 0x05c8, // XK_Arabic_beh
    0x0629: 0x05c9, // XK_Arabic_tehmarbuta
    0x062a: 0x05ca, // XK_Arabic_teh
    0x062b: 0x05cb, // XK_Arabic_theh
    0x062c: 0x05cc, // XK_Arabic_jeem
    0x062d: 0x05cd, // XK_Arabic_hah
    0x062e: 0x05ce, // XK_Arabic_khah
    0x062f: 0x05cf, // XK_Arabic_dal
    0x0630: 0x05d0, // XK_Arabic_thal
    0x0631: 0x05d1, // XK_Arabic_ra
    0x0632: 0x05d2, // XK_Arabic_zain
    0x0633: 0x05d3, // XK_Arabic_seen
    0x0634: 0x05d4, // XK_Arabic_sheen
    0x0635: 0x05d5, // XK_Arabic_sad
    0x0636: 0x05d6, // XK_Arabic_dad
    0x0637: 0x05d7, // XK_Arabic_tah
    0x0638: 0x05d8, // XK_Arabic_zah
    0x0639: 0x05d9, // XK_Arabic_ain
    0x063a: 0x05da, // XK_Arabic_ghain
    0x0640: 0x05e0, // XK_Arabic_tatweel
    0x0641: 0x05e1, // XK_Arabic_feh
    0x0642: 0x05e2, // XK_Arabic_qaf
    0x0643: 0x05e3, // XK_Arabic_kaf
    0x0644: 0x05e4, // XK_Arabic_lam
    0x0645: 0x05e5, // XK_Arabic_meem
    0x0646: 0x05e6, // XK_Arabic_noon
    0x0647: 0x05e7, // XK_Arabic_ha
    0x0648: 0x05e8, // XK_Arabic_waw
    0x0649: 0x05e9, // XK_Arabic_alefmaksura
    0x064a: 0x05ea, // XK_Arabic_yeh
    0x064b: 0x05eb, // XK_Arabic_fathatan
    0x064c: 0x05ec, // XK_Arabic_dammatan
    0x064d: 0x05ed, // XK_Arabic_kasratan
    0x064e: 0x05ee, // XK_Arabic_fatha
    0x064f: 0x05ef, // XK_Arabic_damma
    0x0650: 0x05f0, // XK_Arabic_kasra
    0x0651: 0x05f1, // XK_Arabic_shadda
    0x0652: 0x05f2, // XK_Arabic_sukun
    0x0e01: 0x0da1, // XK_Thai_kokai
    0x0e02: 0x0da2, // XK_Thai_khokhai
    0x0e03: 0x0da3, // XK_Thai_khokhuat
    0x0e04: 0x0da4, // XK_Thai_khokhwai
    0x0e05: 0x0da5, // XK_Thai_khokhon
    0x0e06: 0x0da6, // XK_Thai_khorakhang
    0x0e07: 0x0da7, // XK_Thai_ngongu
    0x0e08: 0x0da8, // XK_Thai_chochan
    0x0e09: 0x0da9, // XK_Thai_choching
    0x0e0a: 0x0daa, // XK_Thai_chochang
    0x0e0b: 0x0dab, // XK_Thai_soso
    0x0e0c: 0x0dac, // XK_Thai_chochoe
    0x0e0d: 0x0dad, // XK_Thai_yoying
    0x0e0e: 0x0dae, // XK_Thai_dochada
    0x0e0f: 0x0daf, // XK_Thai_topatak
    0x0e10: 0x0db0, // XK_Thai_thothan
    0x0e11: 0x0db1, // XK_Thai_thonangmontho
    0x0e12: 0x0db2, // XK_Thai_thophuthao
    0x0e13: 0x0db3, // XK_Thai_nonen
    0x0e14: 0x0db4, // XK_Thai_dodek
    0x0e15: 0x0db5, // XK_Thai_totao
    0x0e16: 0x0db6, // XK_Thai_thothung
    0x0e17: 0x0db7, // XK_Thai_thothahan
    0x0e18: 0x0db8, // XK_Thai_thothong
    0x0e19: 0x0db9, // XK_Thai_nonu
    0x0e1a: 0x0dba, // XK_Thai_bobaimai
    0x0e1b: 0x0dbb, // XK_Thai_popla
    0x0e1c: 0x0dbc, // XK_Thai_phophung
    0x0e1d: 0x0dbd, // XK_Thai_fofa
    0x0e1e: 0x0dbe, // XK_Thai_phophan
    0x0e1f: 0x0dbf, // XK_Thai_fofan
    0x0e20: 0x0dc0, // XK_Thai_phosamphao
    0x0e21: 0x0dc1, // XK_Thai_moma
    0x0e22: 0x0dc2, // XK_Thai_yoyak
    0x0e23: 0x0dc3, // XK_Thai_rorua
    0x0e24: 0x0dc4, // XK_Thai_ru
    0x0e25: 0x0dc5, // XK_Thai_loling
    0x0e26: 0x0dc6, // XK_Thai_lu
    0x0e27: 0x0dc7, // XK_Thai_wowaen
    0x0e28: 0x0dc8, // XK_Thai_sosala
    0x0e29: 0x0dc9, // XK_Thai_sorusi
    0x0e2a: 0x0dca, // XK_Thai_sosua
    0x0e2b: 0x0dcb, // XK_Thai_hohip
    0x0e2c: 0x0dcc, // XK_Thai_lochula
    0x0e2d: 0x0dcd, // XK_Thai_oang
    0x0e2e: 0x0dce, // XK_Thai_honokhuk
    0x0e2f: 0x0dcf, // XK_Thai_paiyannoi
    0x0e30: 0x0dd0, // XK_Thai_saraa
    0x0e31: 0x0dd1, // XK_Thai_maihanakat
    0x0e32: 0x0dd2, // XK_Thai_saraaa
    0x0e33: 0x0dd3, // XK_Thai_saraam
    0x0e34: 0x0dd4, // XK_Thai_sarai
    0x0e35: 0x0dd5, // XK_Thai_saraii
    0x0e36: 0x0dd6, // XK_Thai_saraue
    0x0e37: 0x0dd7, // XK_Thai_sarauee
    0x0e38: 0x0dd8, // XK_Thai_sarau
    0x0e39: 0x0dd9, // XK_Thai_sarauu
    0x0e3a: 0x0dda, // XK_Thai_phinthu
    0x0e3f: 0x0ddf, // XK_Thai_baht
    0x0e40: 0x0de0, // XK_Thai_sarae
    0x0e41: 0x0de1, // XK_Thai_saraae
    0x0e42: 0x0de2, // XK_Thai_sarao
    0x0e43: 0x0de3, // XK_Thai_saraaimaimuan
    0x0e44: 0x0de4, // XK_Thai_saraaimaimalai
    0x0e45: 0x0de5, // XK_Thai_lakkhangyao
    0x0e46: 0x0de6, // XK_Thai_maiyamok
    0x0e47: 0x0de7, // XK_Thai_maitaikhu
    0x0e48: 0x0de8, // XK_Thai_maiek
    0x0e49: 0x0de9, // XK_Thai_maitho
    0x0e4a: 0x0dea, // XK_Thai_maitri
    0x0e4b: 0x0deb, // XK_Thai_maichattawa
    0x0e4c: 0x0dec, // XK_Thai_thanthakhat
    0x0e4d: 0x0ded, // XK_Thai_nikhahit
    0x0e50: 0x0df0, // XK_Thai_leksun
    0x0e51: 0x0df1, // XK_Thai_leknung
    0x0e52: 0x0df2, // XK_Thai_leksong
    0x0e53: 0x0df3, // XK_Thai_leksam
    0x0e54: 0x0df4, // XK_Thai_leksi
    0x0e55: 0x0df5, // XK_Thai_lekha
    0x0e56: 0x0df6, // XK_Thai_lekhok
    0x0e57: 0x0df7, // XK_Thai_lekchet
    0x0e58: 0x0df8, // XK_Thai_lekpaet
    0x0e59: 0x0df9, // XK_Thai_lekkao
    0x2002: 0x0aa2, // XK_enspace
    0x2003: 0x0aa1, // XK_emspace
    0x2004: 0x0aa3, // XK_em3space
    0x2005: 0x0aa4, // XK_em4space
    0x2007: 0x0aa5, // XK_digitspace
    0x2008: 0x0aa6, // XK_punctspace
    0x2009: 0x0aa7, // XK_thinspace
    0x200a: 0x0aa8, // XK_hairspace
    0x2012: 0x0abb, // XK_figdash
    0x2013: 0x0aaa, // XK_endash
    0x2014: 0x0aa9, // XK_emdash
    0x2015: 0x07af, // XK_Greek_horizbar
    0x2017: 0x0cdf, // XK_hebrew_doublelowline
    0x2018: 0x0ad0, // XK_leftsinglequotemark
    0x2019: 0x0ad1, // XK_rightsinglequotemark
    0x201a: 0x0afd, // XK_singlelowquotemark
    0x201c: 0x0ad2, // XK_leftdoublequotemark
    0x201d: 0x0ad3, // XK_rightdoublequotemark
    0x201e: 0x0afe, // XK_doublelowquotemark
    0x2020: 0x0af1, // XK_dagger
    0x2021: 0x0af2, // XK_doubledagger
    0x2022: 0x0ae6, // XK_enfilledcircbullet
    0x2025: 0x0aaf, // XK_doubbaselinedot
    0x2026: 0x0aae, // XK_ellipsis
    0x2030: 0x0ad5, // XK_permille
    0x2032: 0x0ad6, // XK_minutes
    0x2033: 0x0ad7, // XK_seconds
    0x2038: 0x0afc, // XK_caret
    0x203e: 0x047e, // XK_overline
    0x20a9: 0x0eff, // XK_Korean_Won
    0x20ac: 0x20ac, // XK_EuroSign
    0x2105: 0x0ab8, // XK_careof
    0x2116: 0x06b0, // XK_numerosign
    0x2117: 0x0afb, // XK_phonographcopyright
    0x211e: 0x0ad4, // XK_prescription
    0x2122: 0x0ac9, // XK_trademark
    0x2153: 0x0ab0, // XK_onethird
    0x2154: 0x0ab1, // XK_twothirds
    0x2155: 0x0ab2, // XK_onefifth
    0x2156: 0x0ab3, // XK_twofifths
    0x2157: 0x0ab4, // XK_threefifths
    0x2158: 0x0ab5, // XK_fourfifths
    0x2159: 0x0ab6, // XK_onesixth
    0x215a: 0x0ab7, // XK_fivesixths
    0x215b: 0x0ac3, // XK_oneeighth
    0x215c: 0x0ac4, // XK_threeeighths
    0x215d: 0x0ac5, // XK_fiveeighths
    0x215e: 0x0ac6, // XK_seveneighths
    0x2190: 0x08fb, // XK_leftarrow
    0x2191: 0x08fc, // XK_uparrow
    0x2192: 0x08fd, // XK_rightarrow
    0x2193: 0x08fe, // XK_downarrow
    0x21d2: 0x08ce, // XK_implies
    0x21d4: 0x08cd, // XK_ifonlyif
    0x2202: 0x08ef, // XK_partialderivative
    0x2207: 0x08c5, // XK_nabla
    0x2218: 0x0bca, // XK_jot
    0x221a: 0x08d6, // XK_radical
    0x221d: 0x08c1, // XK_variation
    0x221e: 0x08c2, // XK_infinity
    0x2227: 0x08de, // XK_logicaland
    0x2228: 0x08df, // XK_logicalor
    0x2229: 0x08dc, // XK_intersection
    0x222a: 0x08dd, // XK_union
    0x222b: 0x08bf, // XK_integral
    0x2234: 0x08c0, // XK_therefore
    0x223c: 0x08c8, // XK_approximate
    0x2243: 0x08c9, // XK_similarequal
    0x2245: 0x1002248, // XK_approxeq
    0x2260: 0x08bd, // XK_notequal
    0x2261: 0x08cf, // XK_identical
    0x2264: 0x08bc, // XK_lessthanequal
    0x2265: 0x08be, // XK_greaterthanequal
    0x2282: 0x08da, // XK_includedin
    0x2283: 0x08db, // XK_includes
    0x22a2: 0x0bfc, // XK_righttack
    0x22a3: 0x0bdc, // XK_lefttack
    0x22a4: 0x0bc2, // XK_downtack
    0x22a5: 0x0bce, // XK_uptack
    0x2308: 0x0bd3, // XK_upstile
    0x230a: 0x0bc4, // XK_downstile
    0x2315: 0x0afa, // XK_telephonerecorder
    0x2320: 0x08a4, // XK_topintegral
    0x2321: 0x08a5, // XK_botintegral
    0x2395: 0x0bcc, // XK_quad
    0x239b: 0x08ab, // XK_topleftparens
    0x239d: 0x08ac, // XK_botleftparens
    0x239e: 0x08ad, // XK_toprightparens
    0x23a0: 0x08ae, // XK_botrightparens
    0x23a1: 0x08a7, // XK_topleftsqbracket
    0x23a3: 0x08a8, // XK_botleftsqbracket
    0x23a4: 0x08a9, // XK_toprightsqbracket
    0x23a6: 0x08aa, // XK_botrightsqbracket
    0x23a8: 0x08af, // XK_leftmiddlecurlybrace
    0x23ac: 0x08b0, // XK_rightmiddlecurlybrace
    0x23b7: 0x08a1, // XK_leftradical
    0x23ba: 0x09ef, // XK_horizlinescan1
    0x23bb: 0x09f0, // XK_horizlinescan3
    0x23bc: 0x09f2, // XK_horizlinescan7
    0x23bd: 0x09f3, // XK_horizlinescan9
    0x2409: 0x09e2, // XK_ht
    0x240a: 0x09e5, // XK_lf
    0x240b: 0x09e9, // XK_vt
    0x240c: 0x09e3, // XK_ff
    0x240d: 0x09e4, // XK_cr
    0x2423: 0x0aac, // XK_signifblank
    0x2424: 0x09e8, // XK_nl
    0x2500: 0x08a3, // XK_horizconnector
    0x2502: 0x08a6, // XK_vertconnector
    0x250c: 0x08a2, // XK_topleftradical
    0x2510: 0x09eb, // XK_uprightcorner
    0x2514: 0x09ed, // XK_lowleftcorner
    0x2518: 0x09ea, // XK_lowrightcorner
    0x251c: 0x09f4, // XK_leftt
    0x2524: 0x09f5, // XK_rightt
    0x252c: 0x09f7, // XK_topt
    0x2534: 0x09f6, // XK_bott
    0x253c: 0x09ee, // XK_crossinglines
    0x2592: 0x09e1, // XK_checkerboard
    0x25aa: 0x0ae7, // XK_enfilledsqbullet
    0x25ab: 0x0ae1, // XK_enopensquarebullet
    0x25ac: 0x0adb, // XK_filledrectbullet
    0x25ad: 0x0ae2, // XK_openrectbullet
    0x25ae: 0x0adf, // XK_emfilledrect
    0x25af: 0x0acf, // XK_emopenrectangle
    0x25b2: 0x0ae8, // XK_filledtribulletup
    0x25b3: 0x0ae3, // XK_opentribulletup
    0x25b6: 0x0add, // XK_filledrighttribullet
    0x25b7: 0x0acd, // XK_rightopentriangle
    0x25bc: 0x0ae9, // XK_filledtribulletdown
    0x25bd: 0x0ae4, // XK_opentribulletdown
    0x25c0: 0x0adc, // XK_filledlefttribullet
    0x25c1: 0x0acc, // XK_leftopentriangle
    0x25c6: 0x09e0, // XK_soliddiamond
    0x25cb: 0x0ace, // XK_emopencircle
    0x25cf: 0x0ade, // XK_emfilledcircle
    0x25e6: 0x0ae0, // XK_enopencircbullet
    0x2606: 0x0ae5, // XK_openstar
    0x260e: 0x0af9, // XK_telephone
    0x2613: 0x0aca, // XK_signaturemark
    0x261c: 0x0aea, // XK_leftpointer
    0x261e: 0x0aeb, // XK_rightpointer
    0x2640: 0x0af8, // XK_femalesymbol
    0x2642: 0x0af7, // XK_malesymbol
    0x2663: 0x0aec, // XK_club
    0x2665: 0x0aee, // XK_heart
    0x2666: 0x0aed, // XK_diamond
    0x266d: 0x0af6, // XK_musicalflat
    0x266f: 0x0af5, // XK_musicalsharp
    0x2713: 0x0af3, // XK_checkmark
    0x2717: 0x0af4, // XK_ballotcross
    0x271d: 0x0ad9, // XK_latincross
    0x2720: 0x0af0, // XK_maltesecross
    0x27e8: 0x0abc, // XK_leftanglebracket
    0x27e9: 0x0abe, // XK_rightanglebracket
    0x3001: 0x04a4, // XK_kana_comma
    0x3002: 0x04a1, // XK_kana_fullstop
    0x300c: 0x04a2, // XK_kana_openingbracket
    0x300d: 0x04a3, // XK_kana_closingbracket
    0x309b: 0x04de, // XK_voicedsound
    0x309c: 0x04df, // XK_semivoicedsound
    0x30a1: 0x04a7, // XK_kana_a
    0x30a2: 0x04b1, // XK_kana_A
    0x30a3: 0x04a8, // XK_kana_i
    0x30a4: 0x04b2, // XK_kana_I
    0x30a5: 0x04a9, // XK_kana_u
    0x30a6: 0x04b3, // XK_kana_U
    0x30a7: 0x04aa, // XK_kana_e
    0x30a8: 0x04b4, // XK_kana_E
    0x30a9: 0x04ab, // XK_kana_o
    0x30aa: 0x04b5, // XK_kana_O
    0x30ab: 0x04b6, // XK_kana_KA
    0x30ad: 0x04b7, // XK_kana_KI
    0x30af: 0x04b8, // XK_kana_KU
    0x30b1: 0x04b9, // XK_kana_KE
    0x30b3: 0x04ba, // XK_kana_KO
    0x30b5: 0x04bb, // XK_kana_SA
    0x30b7: 0x04bc, // XK_kana_SHI
    0x30b9: 0x04bd, // XK_kana_SU
    0x30bb: 0x04be, // XK_kana_SE
    0x30bd: 0x04bf, // XK_kana_SO
    0x30bf: 0x04c0, // XK_kana_TA
    0x30c1: 0x04c1, // XK_kana_CHI
    0x30c3: 0x04af, // XK_kana_tsu
    0x30c4: 0x04c2, // XK_kana_TSU
    0x30c6: 0x04c3, // XK_kana_TE
    0x30c8: 0x04c4, // XK_kana_TO
    0x30ca: 0x04c5, // XK_kana_NA
    0x30cb: 0x04c6, // XK_kana_NI
    0x30cc: 0x04c7, // XK_kana_NU
    0x30cd: 0x04c8, // XK_kana_NE
    0x30ce: 0x04c9, // XK_kana_NO
    0x30cf: 0x04ca, // XK_kana_HA
    0x30d2: 0x04cb, // XK_kana_HI
    0x30d5: 0x04cc, // XK_kana_FU
    0x30d8: 0x04cd, // XK_kana_HE
    0x30db: 0x04ce, // XK_kana_HO
    0x30de: 0x04cf, // XK_kana_MA
    0x30df: 0x04d0, // XK_kana_MI
    0x30e0: 0x04d1, // XK_kana_MU
    0x30e1: 0x04d2, // XK_kana_ME
    0x30e2: 0x04d3, // XK_kana_MO
    0x30e3: 0x04ac, // XK_kana_ya
    0x30e4: 0x04d4, // XK_kana_YA
    0x30e5: 0x04ad, // XK_kana_yu
    0x30e6: 0x04d5, // XK_kana_YU
    0x30e7: 0x04ae, // XK_kana_yo
    0x30e8: 0x04d6, // XK_kana_YO
    0x30e9: 0x04d7, // XK_kana_RA
    0x30ea: 0x04d8, // XK_kana_RI
    0x30eb: 0x04d9, // XK_kana_RU
    0x30ec: 0x04da, // XK_kana_RE
    0x30ed: 0x04db, // XK_kana_RO
    0x30ef: 0x04dc, // XK_kana_WA
    0x30f2: 0x04a6, // XK_kana_WO
    0x30f3: 0x04dd, // XK_kana_N
    0x30fb: 0x04a5, // XK_kana_conjunctive
    0x30fc: 0x04b0 // XK_prolongedsound
};

exports.default = {
    lookup: function (u) {
        // Latin-1 is one-to-one mapping
        if (u >= 0x20 && u <= 0xff) {
            return u;
        }

        // Lookup table (fairly random)
        var keysym = codepoints[u];
        if (keysym !== undefined) {
            return keysym;
        }

        // General mapping as final fallback
        return 0x01000000 | u;
    }
};
},{}],14:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = Mouse;

var _logging = require('../util/logging.js');

var Log = _interopRequireWildcard(_logging);

var _browser = require('../util/browser.js');

var _events = require('../util/events.js');

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

var WHEEL_STEP = 10; // Delta threshold for a mouse wheel step
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Copyright (C) 2013 Samuel Mannehed for Cendio AB
 * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
 */

var WHEEL_STEP_TIMEOUT = 50; // ms
var WHEEL_LINE_HEIGHT = 19;

function Mouse(target) {
    this._target = target || document;

    this._doubleClickTimer = null;
    this._lastTouchPos = null;

    this._pos = null;
    this._wheelStepXTimer = null;
    this._wheelStepYTimer = null;
    this._accumulatedWheelDeltaX = 0;
    this._accumulatedWheelDeltaY = 0;

    this._eventHandlers = {
        'mousedown': this._handleMouseDown.bind(this),
        'mouseup': this._handleMouseUp.bind(this),
        'mousemove': this._handleMouseMove.bind(this),
        'mousewheel': this._handleMouseWheel.bind(this),
        'mousedisable': this._handleMouseDisable.bind(this)
    };
};

Mouse.prototype = {
    // ===== PROPERTIES =====

    touchButton: 1, // Button mask (1, 2, 4) for touch devices (0 means ignore clicks)

    // ===== EVENT HANDLERS =====

    onmousebutton: function () {}, // Handler for mouse button click/release
    onmousemove: function () {}, // Handler for mouse movement

    // ===== PRIVATE METHODS =====

    _resetDoubleClickTimer: function () {
        this._doubleClickTimer = null;
    },

    _handleMouseButton: function (e, down) {
        this._updateMousePosition(e);
        var pos = this._pos;

        var bmask;
        if (e.touches || e.changedTouches) {
            // Touch device

            // When two touches occur within 500 ms of each other and are
            // close enough together a double click is triggered.
            if (down == 1) {
                if (this._doubleClickTimer === null) {
                    this._lastTouchPos = pos;
                } else {
                    clearTimeout(this._doubleClickTimer);

                    // When the distance between the two touches is small enough
                    // force the position of the latter touch to the position of
                    // the first.

                    var xs = this._lastTouchPos.x - pos.x;
                    var ys = this._lastTouchPos.y - pos.y;
                    var d = Math.sqrt(xs * xs + ys * ys);

                    // The goal is to trigger on a certain physical width, the
                    // devicePixelRatio brings us a bit closer but is not optimal.
                    var threshold = 20 * (window.devicePixelRatio || 1);
                    if (d < threshold) {
                        pos = this._lastTouchPos;
                    }
                }
                this._doubleClickTimer = setTimeout(this._resetDoubleClickTimer.bind(this), 500);
            }
            bmask = this.touchButton;
            // If bmask is set
        } else if (e.which) {
            /* everything except IE */
            bmask = 1 << e.button;
        } else {
            /* IE including 9 */
            bmask = (e.button & 0x1) + // Left
            (e.button & 0x2) * 2 + // Right
            (e.button & 0x4) / 2; // Middle
        }

        Log.Debug("onmousebutton " + (down ? "down" : "up") + ", x: " + pos.x + ", y: " + pos.y + ", bmask: " + bmask);
        this.onmousebutton(pos.x, pos.y, down, bmask);

        (0, _events.stopEvent)(e);
    },

    _handleMouseDown: function (e) {
        // Touch events have implicit capture
        if (e.type === "mousedown") {
            (0, _events.setCapture)(this._target);
        }

        this._handleMouseButton(e, 1);
    },

    _handleMouseUp: function (e) {
        this._handleMouseButton(e, 0);
    },

    // Mouse wheel events are sent in steps over VNC. This means that the VNC
    // protocol can't handle a wheel event with specific distance or speed.
    // Therefor, if we get a lot of small mouse wheel events we combine them.
    _generateWheelStepX: function () {

        if (this._accumulatedWheelDeltaX < 0) {
            this.onmousebutton(this._pos.x, this._pos.y, 1, 1 << 5);
            this.onmousebutton(this._pos.x, this._pos.y, 0, 1 << 5);
        } else if (this._accumulatedWheelDeltaX > 0) {
            this.onmousebutton(this._pos.x, this._pos.y, 1, 1 << 6);
            this.onmousebutton(this._pos.x, this._pos.y, 0, 1 << 6);
        }

        this._accumulatedWheelDeltaX = 0;
    },

    _generateWheelStepY: function () {

        if (this._accumulatedWheelDeltaY < 0) {
            this.onmousebutton(this._pos.x, this._pos.y, 1, 1 << 3);
            this.onmousebutton(this._pos.x, this._pos.y, 0, 1 << 3);
        } else if (this._accumulatedWheelDeltaY > 0) {
            this.onmousebutton(this._pos.x, this._pos.y, 1, 1 << 4);
            this.onmousebutton(this._pos.x, this._pos.y, 0, 1 << 4);
        }

        this._accumulatedWheelDeltaY = 0;
    },

    _resetWheelStepTimers: function () {
        window.clearTimeout(this._wheelStepXTimer);
        window.clearTimeout(this._wheelStepYTimer);
        this._wheelStepXTimer = null;
        this._wheelStepYTimer = null;
    },

    _handleMouseWheel: function (e) {
        this._resetWheelStepTimers();

        this._updateMousePosition(e);

        var dX = e.deltaX;
        var dY = e.deltaY;

        // Pixel units unless it's non-zero.
        // Note that if deltamode is line or page won't matter since we aren't
        // sending the mouse wheel delta to the server anyway.
        // The difference between pixel and line can be important however since
        // we have a threshold that can be smaller than the line height.
        if (e.deltaMode !== 0) {
            dX *= WHEEL_LINE_HEIGHT;
            dY *= WHEEL_LINE_HEIGHT;
        }

        this._accumulatedWheelDeltaX += dX;
        this._accumulatedWheelDeltaY += dY;

        // Generate a mouse wheel step event when the accumulated delta
        // for one of the axes is large enough.
        // Small delta events that do not pass the threshold get sent
        // after a timeout.
        if (Math.abs(this._accumulatedWheelDeltaX) > WHEEL_STEP) {
            this._generateWheelStepX();
        } else {
            this._wheelStepXTimer = window.setTimeout(this._generateWheelStepX.bind(this), WHEEL_STEP_TIMEOUT);
        }
        if (Math.abs(this._accumulatedWheelDeltaY) > WHEEL_STEP) {
            this._generateWheelStepY();
        } else {
            this._wheelStepYTimer = window.setTimeout(this._generateWheelStepY.bind(this), WHEEL_STEP_TIMEOUT);
        }

        (0, _events.stopEvent)(e);
    },

    _handleMouseMove: function (e) {
        this._updateMousePosition(e);
        this.onmousemove(this._pos.x, this._pos.y);
        (0, _events.stopEvent)(e);
    },

    _handleMouseDisable: function (e) {
        /*
         * Stop propagation if inside canvas area
         * Note: This is only needed for the 'click' event as it fails
         *       to fire properly for the target element so we have
         *       to listen on the document element instead.
         */
        if (e.target == this._target) {
            (0, _events.stopEvent)(e);
        }
    },

    // Update coordinates relative to target
    _updateMousePosition: function (e) {
        e = (0, _events.getPointerEvent)(e);
        var bounds = this._target.getBoundingClientRect();
        var x, y;
        // Clip to target bounds
        if (e.clientX < bounds.left) {
            x = 0;
        } else if (e.clientX >= bounds.right) {
            x = bounds.width - 1;
        } else {
            x = e.clientX - bounds.left;
        }
        if (e.clientY < bounds.top) {
            y = 0;
        } else if (e.clientY >= bounds.bottom) {
            y = bounds.height - 1;
        } else {
            y = e.clientY - bounds.top;
        }
        this._pos = { x: x, y: y };
    },

    // ===== PUBLIC METHODS =====

    grab: function () {
        var c = this._target;

        if (_browser.isTouchDevice) {
            c.addEventListener('touchstart', this._eventHandlers.mousedown);
            c.addEventListener('touchend', this._eventHandlers.mouseup);
            c.addEventListener('touchmove', this._eventHandlers.mousemove);
        }
        c.addEventListener('mousedown', this._eventHandlers.mousedown);
        c.addEventListener('mouseup', this._eventHandlers.mouseup);
        c.addEventListener('mousemove', this._eventHandlers.mousemove);
        c.addEventListener('wheel', this._eventHandlers.mousewheel);

        /* Prevent middle-click pasting (see above for why we bind to document) */
        document.addEventListener('click', this._eventHandlers.mousedisable);

        /* preventDefault() on mousedown doesn't stop this event for some
           reason so we have to explicitly block it */
        c.addEventListener('contextmenu', this._eventHandlers.mousedisable);
    },

    ungrab: function () {
        var c = this._target;

        this._resetWheelStepTimers();

        if (_browser.isTouchDevice) {
            c.removeEventListener('touchstart', this._eventHandlers.mousedown);
            c.removeEventListener('touchend', this._eventHandlers.mouseup);
            c.removeEventListener('touchmove', this._eventHandlers.mousemove);
        }
        c.removeEventListener('mousedown', this._eventHandlers.mousedown);
        c.removeEventListener('mouseup', this._eventHandlers.mouseup);
        c.removeEventListener('mousemove', this._eventHandlers.mousemove);
        c.removeEventListener('wheel', this._eventHandlers.mousewheel);

        document.removeEventListener('click', this._eventHandlers.mousedisable);

        c.removeEventListener('contextmenu', this._eventHandlers.mousedisable);
    }
};
},{"../util/browser.js":19,"../util/events.js":20,"../util/logging.js":22}],15:[function(require,module,exports){
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
},{"../util/browser.js":19,"./domkeytable.js":9,"./fixedkeys.js":10,"./keysym.js":12,"./keysymdef.js":13,"./vkeys.js":16}],16:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
  value: true
});
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2017 Pierre Ossman for Cendio AB
 * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
 */

/*
 * Mapping between Microsoft® Windows® Virtual-Key codes and
 * HTML key codes.
 */

exports.default = {
  0x08: 'Backspace',
  0x09: 'Tab',
  0x0a: 'NumpadClear',
  0x0d: 'Enter',
  0x10: 'ShiftLeft',
  0x11: 'ControlLeft',
  0x12: 'AltLeft',
  0x13: 'Pause',
  0x14: 'CapsLock',
  0x15: 'Lang1',
  0x19: 'Lang2',
  0x1b: 'Escape',
  0x1c: 'Convert',
  0x1d: 'NonConvert',
  0x20: 'Space',
  0x21: 'PageUp',
  0x22: 'PageDown',
  0x23: 'End',
  0x24: 'Home',
  0x25: 'ArrowLeft',
  0x26: 'ArrowUp',
  0x27: 'ArrowRight',
  0x28: 'ArrowDown',
  0x29: 'Select',
  0x2c: 'PrintScreen',
  0x2d: 'Insert',
  0x2e: 'Delete',
  0x2f: 'Help',
  0x30: 'Digit0',
  0x31: 'Digit1',
  0x32: 'Digit2',
  0x33: 'Digit3',
  0x34: 'Digit4',
  0x35: 'Digit5',
  0x36: 'Digit6',
  0x37: 'Digit7',
  0x38: 'Digit8',
  0x39: 'Digit9',
  0x5b: 'MetaLeft',
  0x5c: 'MetaRight',
  0x5d: 'ContextMenu',
  0x5f: 'Sleep',
  0x60: 'Numpad0',
  0x61: 'Numpad1',
  0x62: 'Numpad2',
  0x63: 'Numpad3',
  0x64: 'Numpad4',
  0x65: 'Numpad5',
  0x66: 'Numpad6',
  0x67: 'Numpad7',
  0x68: 'Numpad8',
  0x69: 'Numpad9',
  0x6a: 'NumpadMultiply',
  0x6b: 'NumpadAdd',
  0x6c: 'NumpadDecimal',
  0x6d: 'NumpadSubtract',
  0x6e: 'NumpadDecimal', // Duplicate, because buggy on Windows
  0x6f: 'NumpadDivide',
  0x70: 'F1',
  0x71: 'F2',
  0x72: 'F3',
  0x73: 'F4',
  0x74: 'F5',
  0x75: 'F6',
  0x76: 'F7',
  0x77: 'F8',
  0x78: 'F9',
  0x79: 'F10',
  0x7a: 'F11',
  0x7b: 'F12',
  0x7c: 'F13',
  0x7d: 'F14',
  0x7e: 'F15',
  0x7f: 'F16',
  0x80: 'F17',
  0x81: 'F18',
  0x82: 'F19',
  0x83: 'F20',
  0x84: 'F21',
  0x85: 'F22',
  0x86: 'F23',
  0x87: 'F24',
  0x90: 'NumLock',
  0x91: 'ScrollLock',
  0xa6: 'BrowserBack',
  0xa7: 'BrowserForward',
  0xa8: 'BrowserRefresh',
  0xa9: 'BrowserStop',
  0xaa: 'BrowserSearch',
  0xab: 'BrowserFavorites',
  0xac: 'BrowserHome',
  0xad: 'AudioVolumeMute',
  0xae: 'AudioVolumeDown',
  0xaf: 'AudioVolumeUp',
  0xb0: 'MediaTrackNext',
  0xb1: 'MediaTrackPrevious',
  0xb2: 'MediaStop',
  0xb3: 'MediaPlayPause',
  0xb4: 'LaunchMail',
  0xb5: 'MediaSelect',
  0xb6: 'LaunchApp1',
  0xb7: 'LaunchApp2',
  0xe1: 'AltRight' // Only when it is AltGraph
};
},{}],17:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
/*
 * This file is auto-generated from keymaps.csv on 2017-05-31 16:20
 * Database checksum sha256(92fd165507f2a3b8c5b3fa56e425d45788dbcb98cf067a307527d91ce22cab94)
 * To re-generate, run:
 *   keymap-gen --lang=js code-map keymaps.csv html atset1
*/
exports.default = {
  "Again": 0xe005, /* html:Again (Again) -> linux:129 (KEY_AGAIN) -> atset1:57349 */
  "AltLeft": 0x38, /* html:AltLeft (AltLeft) -> linux:56 (KEY_LEFTALT) -> atset1:56 */
  "AltRight": 0xe038, /* html:AltRight (AltRight) -> linux:100 (KEY_RIGHTALT) -> atset1:57400 */
  "ArrowDown": 0xe050, /* html:ArrowDown (ArrowDown) -> linux:108 (KEY_DOWN) -> atset1:57424 */
  "ArrowLeft": 0xe04b, /* html:ArrowLeft (ArrowLeft) -> linux:105 (KEY_LEFT) -> atset1:57419 */
  "ArrowRight": 0xe04d, /* html:ArrowRight (ArrowRight) -> linux:106 (KEY_RIGHT) -> atset1:57421 */
  "ArrowUp": 0xe048, /* html:ArrowUp (ArrowUp) -> linux:103 (KEY_UP) -> atset1:57416 */
  "AudioVolumeDown": 0xe02e, /* html:AudioVolumeDown (AudioVolumeDown) -> linux:114 (KEY_VOLUMEDOWN) -> atset1:57390 */
  "AudioVolumeMute": 0xe020, /* html:AudioVolumeMute (AudioVolumeMute) -> linux:113 (KEY_MUTE) -> atset1:57376 */
  "AudioVolumeUp": 0xe030, /* html:AudioVolumeUp (AudioVolumeUp) -> linux:115 (KEY_VOLUMEUP) -> atset1:57392 */
  "Backquote": 0x29, /* html:Backquote (Backquote) -> linux:41 (KEY_GRAVE) -> atset1:41 */
  "Backslash": 0x2b, /* html:Backslash (Backslash) -> linux:43 (KEY_BACKSLASH) -> atset1:43 */
  "Backspace": 0xe, /* html:Backspace (Backspace) -> linux:14 (KEY_BACKSPACE) -> atset1:14 */
  "BracketLeft": 0x1a, /* html:BracketLeft (BracketLeft) -> linux:26 (KEY_LEFTBRACE) -> atset1:26 */
  "BracketRight": 0x1b, /* html:BracketRight (BracketRight) -> linux:27 (KEY_RIGHTBRACE) -> atset1:27 */
  "BrowserBack": 0xe06a, /* html:BrowserBack (BrowserBack) -> linux:158 (KEY_BACK) -> atset1:57450 */
  "BrowserFavorites": 0xe066, /* html:BrowserFavorites (BrowserFavorites) -> linux:156 (KEY_BOOKMARKS) -> atset1:57446 */
  "BrowserForward": 0xe069, /* html:BrowserForward (BrowserForward) -> linux:159 (KEY_FORWARD) -> atset1:57449 */
  "BrowserHome": 0xe032, /* html:BrowserHome (BrowserHome) -> linux:172 (KEY_HOMEPAGE) -> atset1:57394 */
  "BrowserRefresh": 0xe067, /* html:BrowserRefresh (BrowserRefresh) -> linux:173 (KEY_REFRESH) -> atset1:57447 */
  "BrowserSearch": 0xe065, /* html:BrowserSearch (BrowserSearch) -> linux:217 (KEY_SEARCH) -> atset1:57445 */
  "BrowserStop": 0xe068, /* html:BrowserStop (BrowserStop) -> linux:128 (KEY_STOP) -> atset1:57448 */
  "CapsLock": 0x3a, /* html:CapsLock (CapsLock) -> linux:58 (KEY_CAPSLOCK) -> atset1:58 */
  "Comma": 0x33, /* html:Comma (Comma) -> linux:51 (KEY_COMMA) -> atset1:51 */
  "ContextMenu": 0xe05d, /* html:ContextMenu (ContextMenu) -> linux:127 (KEY_COMPOSE) -> atset1:57437 */
  "ControlLeft": 0x1d, /* html:ControlLeft (ControlLeft) -> linux:29 (KEY_LEFTCTRL) -> atset1:29 */
  "ControlRight": 0xe01d, /* html:ControlRight (ControlRight) -> linux:97 (KEY_RIGHTCTRL) -> atset1:57373 */
  "Convert": 0x79, /* html:Convert (Convert) -> linux:92 (KEY_HENKAN) -> atset1:121 */
  "Copy": 0xe078, /* html:Copy (Copy) -> linux:133 (KEY_COPY) -> atset1:57464 */
  "Cut": 0xe03c, /* html:Cut (Cut) -> linux:137 (KEY_CUT) -> atset1:57404 */
  "Delete": 0xe053, /* html:Delete (Delete) -> linux:111 (KEY_DELETE) -> atset1:57427 */
  "Digit0": 0xb, /* html:Digit0 (Digit0) -> linux:11 (KEY_0) -> atset1:11 */
  "Digit1": 0x2, /* html:Digit1 (Digit1) -> linux:2 (KEY_1) -> atset1:2 */
  "Digit2": 0x3, /* html:Digit2 (Digit2) -> linux:3 (KEY_2) -> atset1:3 */
  "Digit3": 0x4, /* html:Digit3 (Digit3) -> linux:4 (KEY_3) -> atset1:4 */
  "Digit4": 0x5, /* html:Digit4 (Digit4) -> linux:5 (KEY_4) -> atset1:5 */
  "Digit5": 0x6, /* html:Digit5 (Digit5) -> linux:6 (KEY_5) -> atset1:6 */
  "Digit6": 0x7, /* html:Digit6 (Digit6) -> linux:7 (KEY_6) -> atset1:7 */
  "Digit7": 0x8, /* html:Digit7 (Digit7) -> linux:8 (KEY_7) -> atset1:8 */
  "Digit8": 0x9, /* html:Digit8 (Digit8) -> linux:9 (KEY_8) -> atset1:9 */
  "Digit9": 0xa, /* html:Digit9 (Digit9) -> linux:10 (KEY_9) -> atset1:10 */
  "Eject": 0xe07d, /* html:Eject (Eject) -> linux:162 (KEY_EJECTCLOSECD) -> atset1:57469 */
  "End": 0xe04f, /* html:End (End) -> linux:107 (KEY_END) -> atset1:57423 */
  "Enter": 0x1c, /* html:Enter (Enter) -> linux:28 (KEY_ENTER) -> atset1:28 */
  "Equal": 0xd, /* html:Equal (Equal) -> linux:13 (KEY_EQUAL) -> atset1:13 */
  "Escape": 0x1, /* html:Escape (Escape) -> linux:1 (KEY_ESC) -> atset1:1 */
  "F1": 0x3b, /* html:F1 (F1) -> linux:59 (KEY_F1) -> atset1:59 */
  "F10": 0x44, /* html:F10 (F10) -> linux:68 (KEY_F10) -> atset1:68 */
  "F11": 0x57, /* html:F11 (F11) -> linux:87 (KEY_F11) -> atset1:87 */
  "F12": 0x58, /* html:F12 (F12) -> linux:88 (KEY_F12) -> atset1:88 */
  "F13": 0x5d, /* html:F13 (F13) -> linux:183 (KEY_F13) -> atset1:93 */
  "F14": 0x5e, /* html:F14 (F14) -> linux:184 (KEY_F14) -> atset1:94 */
  "F15": 0x5f, /* html:F15 (F15) -> linux:185 (KEY_F15) -> atset1:95 */
  "F16": 0x55, /* html:F16 (F16) -> linux:186 (KEY_F16) -> atset1:85 */
  "F17": 0xe003, /* html:F17 (F17) -> linux:187 (KEY_F17) -> atset1:57347 */
  "F18": 0xe077, /* html:F18 (F18) -> linux:188 (KEY_F18) -> atset1:57463 */
  "F19": 0xe004, /* html:F19 (F19) -> linux:189 (KEY_F19) -> atset1:57348 */
  "F2": 0x3c, /* html:F2 (F2) -> linux:60 (KEY_F2) -> atset1:60 */
  "F20": 0x5a, /* html:F20 (F20) -> linux:190 (KEY_F20) -> atset1:90 */
  "F21": 0x74, /* html:F21 (F21) -> linux:191 (KEY_F21) -> atset1:116 */
  "F22": 0xe079, /* html:F22 (F22) -> linux:192 (KEY_F22) -> atset1:57465 */
  "F23": 0x6d, /* html:F23 (F23) -> linux:193 (KEY_F23) -> atset1:109 */
  "F24": 0x6f, /* html:F24 (F24) -> linux:194 (KEY_F24) -> atset1:111 */
  "F3": 0x3d, /* html:F3 (F3) -> linux:61 (KEY_F3) -> atset1:61 */
  "F4": 0x3e, /* html:F4 (F4) -> linux:62 (KEY_F4) -> atset1:62 */
  "F5": 0x3f, /* html:F5 (F5) -> linux:63 (KEY_F5) -> atset1:63 */
  "F6": 0x40, /* html:F6 (F6) -> linux:64 (KEY_F6) -> atset1:64 */
  "F7": 0x41, /* html:F7 (F7) -> linux:65 (KEY_F7) -> atset1:65 */
  "F8": 0x42, /* html:F8 (F8) -> linux:66 (KEY_F8) -> atset1:66 */
  "F9": 0x43, /* html:F9 (F9) -> linux:67 (KEY_F9) -> atset1:67 */
  "Find": 0xe041, /* html:Find (Find) -> linux:136 (KEY_FIND) -> atset1:57409 */
  "Help": 0xe075, /* html:Help (Help) -> linux:138 (KEY_HELP) -> atset1:57461 */
  "Hiragana": 0x77, /* html:Hiragana (Lang4) -> linux:91 (KEY_HIRAGANA) -> atset1:119 */
  "Home": 0xe047, /* html:Home (Home) -> linux:102 (KEY_HOME) -> atset1:57415 */
  "Insert": 0xe052, /* html:Insert (Insert) -> linux:110 (KEY_INSERT) -> atset1:57426 */
  "IntlBackslash": 0x56, /* html:IntlBackslash (IntlBackslash) -> linux:86 (KEY_102ND) -> atset1:86 */
  "IntlRo": 0x73, /* html:IntlRo (IntlRo) -> linux:89 (KEY_RO) -> atset1:115 */
  "IntlYen": 0x7d, /* html:IntlYen (IntlYen) -> linux:124 (KEY_YEN) -> atset1:125 */
  "KanaMode": 0x70, /* html:KanaMode (KanaMode) -> linux:93 (KEY_KATAKANAHIRAGANA) -> atset1:112 */
  "Katakana": 0x78, /* html:Katakana (Lang3) -> linux:90 (KEY_KATAKANA) -> atset1:120 */
  "KeyA": 0x1e, /* html:KeyA (KeyA) -> linux:30 (KEY_A) -> atset1:30 */
  "KeyB": 0x30, /* html:KeyB (KeyB) -> linux:48 (KEY_B) -> atset1:48 */
  "KeyC": 0x2e, /* html:KeyC (KeyC) -> linux:46 (KEY_C) -> atset1:46 */
  "KeyD": 0x20, /* html:KeyD (KeyD) -> linux:32 (KEY_D) -> atset1:32 */
  "KeyE": 0x12, /* html:KeyE (KeyE) -> linux:18 (KEY_E) -> atset1:18 */
  "KeyF": 0x21, /* html:KeyF (KeyF) -> linux:33 (KEY_F) -> atset1:33 */
  "KeyG": 0x22, /* html:KeyG (KeyG) -> linux:34 (KEY_G) -> atset1:34 */
  "KeyH": 0x23, /* html:KeyH (KeyH) -> linux:35 (KEY_H) -> atset1:35 */
  "KeyI": 0x17, /* html:KeyI (KeyI) -> linux:23 (KEY_I) -> atset1:23 */
  "KeyJ": 0x24, /* html:KeyJ (KeyJ) -> linux:36 (KEY_J) -> atset1:36 */
  "KeyK": 0x25, /* html:KeyK (KeyK) -> linux:37 (KEY_K) -> atset1:37 */
  "KeyL": 0x26, /* html:KeyL (KeyL) -> linux:38 (KEY_L) -> atset1:38 */
  "KeyM": 0x32, /* html:KeyM (KeyM) -> linux:50 (KEY_M) -> atset1:50 */
  "KeyN": 0x31, /* html:KeyN (KeyN) -> linux:49 (KEY_N) -> atset1:49 */
  "KeyO": 0x18, /* html:KeyO (KeyO) -> linux:24 (KEY_O) -> atset1:24 */
  "KeyP": 0x19, /* html:KeyP (KeyP) -> linux:25 (KEY_P) -> atset1:25 */
  "KeyQ": 0x10, /* html:KeyQ (KeyQ) -> linux:16 (KEY_Q) -> atset1:16 */
  "KeyR": 0x13, /* html:KeyR (KeyR) -> linux:19 (KEY_R) -> atset1:19 */
  "KeyS": 0x1f, /* html:KeyS (KeyS) -> linux:31 (KEY_S) -> atset1:31 */
  "KeyT": 0x14, /* html:KeyT (KeyT) -> linux:20 (KEY_T) -> atset1:20 */
  "KeyU": 0x16, /* html:KeyU (KeyU) -> linux:22 (KEY_U) -> atset1:22 */
  "KeyV": 0x2f, /* html:KeyV (KeyV) -> linux:47 (KEY_V) -> atset1:47 */
  "KeyW": 0x11, /* html:KeyW (KeyW) -> linux:17 (KEY_W) -> atset1:17 */
  "KeyX": 0x2d, /* html:KeyX (KeyX) -> linux:45 (KEY_X) -> atset1:45 */
  "KeyY": 0x15, /* html:KeyY (KeyY) -> linux:21 (KEY_Y) -> atset1:21 */
  "KeyZ": 0x2c, /* html:KeyZ (KeyZ) -> linux:44 (KEY_Z) -> atset1:44 */
  "Lang3": 0x78, /* html:Lang3 (Lang3) -> linux:90 (KEY_KATAKANA) -> atset1:120 */
  "Lang4": 0x77, /* html:Lang4 (Lang4) -> linux:91 (KEY_HIRAGANA) -> atset1:119 */
  "Lang5": 0x76, /* html:Lang5 (Lang5) -> linux:85 (KEY_ZENKAKUHANKAKU) -> atset1:118 */
  "LaunchApp1": 0xe06b, /* html:LaunchApp1 (LaunchApp1) -> linux:157 (KEY_COMPUTER) -> atset1:57451 */
  "LaunchApp2": 0xe021, /* html:LaunchApp2 (LaunchApp2) -> linux:140 (KEY_CALC) -> atset1:57377 */
  "LaunchMail": 0xe06c, /* html:LaunchMail (LaunchMail) -> linux:155 (KEY_MAIL) -> atset1:57452 */
  "MediaPlayPause": 0xe022, /* html:MediaPlayPause (MediaPlayPause) -> linux:164 (KEY_PLAYPAUSE) -> atset1:57378 */
  "MediaSelect": 0xe06d, /* html:MediaSelect (MediaSelect) -> linux:226 (KEY_MEDIA) -> atset1:57453 */
  "MediaStop": 0xe024, /* html:MediaStop (MediaStop) -> linux:166 (KEY_STOPCD) -> atset1:57380 */
  "MediaTrackNext": 0xe019, /* html:MediaTrackNext (MediaTrackNext) -> linux:163 (KEY_NEXTSONG) -> atset1:57369 */
  "MediaTrackPrevious": 0xe010, /* html:MediaTrackPrevious (MediaTrackPrevious) -> linux:165 (KEY_PREVIOUSSONG) -> atset1:57360 */
  "MetaLeft": 0xe05b, /* html:MetaLeft (MetaLeft) -> linux:125 (KEY_LEFTMETA) -> atset1:57435 */
  "MetaRight": 0xe05c, /* html:MetaRight (MetaRight) -> linux:126 (KEY_RIGHTMETA) -> atset1:57436 */
  "Minus": 0xc, /* html:Minus (Minus) -> linux:12 (KEY_MINUS) -> atset1:12 */
  "NonConvert": 0x7b, /* html:NonConvert (NonConvert) -> linux:94 (KEY_MUHENKAN) -> atset1:123 */
  "NumLock": 0x45, /* html:NumLock (NumLock) -> linux:69 (KEY_NUMLOCK) -> atset1:69 */
  "Numpad0": 0x52, /* html:Numpad0 (Numpad0) -> linux:82 (KEY_KP0) -> atset1:82 */
  "Numpad1": 0x4f, /* html:Numpad1 (Numpad1) -> linux:79 (KEY_KP1) -> atset1:79 */
  "Numpad2": 0x50, /* html:Numpad2 (Numpad2) -> linux:80 (KEY_KP2) -> atset1:80 */
  "Numpad3": 0x51, /* html:Numpad3 (Numpad3) -> linux:81 (KEY_KP3) -> atset1:81 */
  "Numpad4": 0x4b, /* html:Numpad4 (Numpad4) -> linux:75 (KEY_KP4) -> atset1:75 */
  "Numpad5": 0x4c, /* html:Numpad5 (Numpad5) -> linux:76 (KEY_KP5) -> atset1:76 */
  "Numpad6": 0x4d, /* html:Numpad6 (Numpad6) -> linux:77 (KEY_KP6) -> atset1:77 */
  "Numpad7": 0x47, /* html:Numpad7 (Numpad7) -> linux:71 (KEY_KP7) -> atset1:71 */
  "Numpad8": 0x48, /* html:Numpad8 (Numpad8) -> linux:72 (KEY_KP8) -> atset1:72 */
  "Numpad9": 0x49, /* html:Numpad9 (Numpad9) -> linux:73 (KEY_KP9) -> atset1:73 */
  "NumpadAdd": 0x4e, /* html:NumpadAdd (NumpadAdd) -> linux:78 (KEY_KPPLUS) -> atset1:78 */
  "NumpadComma": 0x7e, /* html:NumpadComma (NumpadComma) -> linux:121 (KEY_KPCOMMA) -> atset1:126 */
  "NumpadDecimal": 0x53, /* html:NumpadDecimal (NumpadDecimal) -> linux:83 (KEY_KPDOT) -> atset1:83 */
  "NumpadDivide": 0xe035, /* html:NumpadDivide (NumpadDivide) -> linux:98 (KEY_KPSLASH) -> atset1:57397 */
  "NumpadEnter": 0xe01c, /* html:NumpadEnter (NumpadEnter) -> linux:96 (KEY_KPENTER) -> atset1:57372 */
  "NumpadEqual": 0x59, /* html:NumpadEqual (NumpadEqual) -> linux:117 (KEY_KPEQUAL) -> atset1:89 */
  "NumpadMultiply": 0x37, /* html:NumpadMultiply (NumpadMultiply) -> linux:55 (KEY_KPASTERISK) -> atset1:55 */
  "NumpadParenLeft": 0xe076, /* html:NumpadParenLeft (NumpadParenLeft) -> linux:179 (KEY_KPLEFTPAREN) -> atset1:57462 */
  "NumpadParenRight": 0xe07b, /* html:NumpadParenRight (NumpadParenRight) -> linux:180 (KEY_KPRIGHTPAREN) -> atset1:57467 */
  "NumpadSubtract": 0x4a, /* html:NumpadSubtract (NumpadSubtract) -> linux:74 (KEY_KPMINUS) -> atset1:74 */
  "Open": 0x64, /* html:Open (Open) -> linux:134 (KEY_OPEN) -> atset1:100 */
  "PageDown": 0xe051, /* html:PageDown (PageDown) -> linux:109 (KEY_PAGEDOWN) -> atset1:57425 */
  "PageUp": 0xe049, /* html:PageUp (PageUp) -> linux:104 (KEY_PAGEUP) -> atset1:57417 */
  "Paste": 0x65, /* html:Paste (Paste) -> linux:135 (KEY_PASTE) -> atset1:101 */
  "Pause": 0xe046, /* html:Pause (Pause) -> linux:119 (KEY_PAUSE) -> atset1:57414 */
  "Period": 0x34, /* html:Period (Period) -> linux:52 (KEY_DOT) -> atset1:52 */
  "Power": 0xe05e, /* html:Power (Power) -> linux:116 (KEY_POWER) -> atset1:57438 */
  "PrintScreen": 0x54, /* html:PrintScreen (PrintScreen) -> linux:99 (KEY_SYSRQ) -> atset1:84 */
  "Props": 0xe006, /* html:Props (Props) -> linux:130 (KEY_PROPS) -> atset1:57350 */
  "Quote": 0x28, /* html:Quote (Quote) -> linux:40 (KEY_APOSTROPHE) -> atset1:40 */
  "ScrollLock": 0x46, /* html:ScrollLock (ScrollLock) -> linux:70 (KEY_SCROLLLOCK) -> atset1:70 */
  "Semicolon": 0x27, /* html:Semicolon (Semicolon) -> linux:39 (KEY_SEMICOLON) -> atset1:39 */
  "ShiftLeft": 0x2a, /* html:ShiftLeft (ShiftLeft) -> linux:42 (KEY_LEFTSHIFT) -> atset1:42 */
  "ShiftRight": 0x36, /* html:ShiftRight (ShiftRight) -> linux:54 (KEY_RIGHTSHIFT) -> atset1:54 */
  "Slash": 0x35, /* html:Slash (Slash) -> linux:53 (KEY_SLASH) -> atset1:53 */
  "Sleep": 0xe05f, /* html:Sleep (Sleep) -> linux:142 (KEY_SLEEP) -> atset1:57439 */
  "Space": 0x39, /* html:Space (Space) -> linux:57 (KEY_SPACE) -> atset1:57 */
  "Suspend": 0xe025, /* html:Suspend (Suspend) -> linux:205 (KEY_SUSPEND) -> atset1:57381 */
  "Tab": 0xf, /* html:Tab (Tab) -> linux:15 (KEY_TAB) -> atset1:15 */
  "Undo": 0xe007, /* html:Undo (Undo) -> linux:131 (KEY_UNDO) -> atset1:57351 */
  "WakeUp": 0xe063 /* html:WakeUp (WakeUp) -> linux:143 (KEY_WAKEUP) -> atset1:57443 */
};
},{}],18:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = RFB;

var _logging = require('./util/logging.js');

var Log = _interopRequireWildcard(_logging);

var _strings = require('./util/strings.js');

var _browser = require('./util/browser.js');

var _eventtarget = require('./util/eventtarget.js');

var _eventtarget2 = _interopRequireDefault(_eventtarget);

var _display = require('./display.js');

var _display2 = _interopRequireDefault(_display);

var _keyboard = require('./input/keyboard.js');

var _keyboard2 = _interopRequireDefault(_keyboard);

var _mouse = require('./input/mouse.js');

var _mouse2 = _interopRequireDefault(_mouse);

var _websock = require('./websock.js');

var _websock2 = _interopRequireDefault(_websock);

var _des = require('./des.js');

var _des2 = _interopRequireDefault(_des);

var _keysym = require('./input/keysym.js');

var _keysym2 = _interopRequireDefault(_keysym);

var _xtscancodes = require('./input/xtscancodes.js');

var _xtscancodes2 = _interopRequireDefault(_xtscancodes);

var _inflator = require('./inflator.js');

var _inflator2 = _interopRequireDefault(_inflator);

var _encodings = require('./encodings.js');

require('./util/polyfill.js');

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

/*jslint white: false, browser: true */
/*global window, Util, Display, Keyboard, Mouse, Websock, Websock_native, Base64, DES, KeyTable, Inflator, XtScancode */

// How many seconds to wait for a disconnect to finish
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Copyright (C) 2017 Samuel Mannehed for Cendio AB
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 *
 * TIGHT decoder portion:
 * (c) 2012 Michael Tinglof, Joe Balaz, Les Piech (Mercuri.ca)
 */

var DISCONNECT_TIMEOUT = 3;

function RFB(target, url, options) {
    if (!target) {
        throw Error("Must specify target");
    }
    if (!url) {
        throw Error("Must specify URL");
    }

    this._target = target;
    this._url = url;

    // Connection details
    options = options || {};
    this._rfb_credentials = options.credentials || {};
    this._shared = 'shared' in options ? !!options.shared : true;
    this._repeaterID = options.repeaterID || '';

    // Internal state
    this._rfb_connection_state = '';
    this._rfb_init_state = '';
    this._rfb_auth_scheme = '';
    this._rfb_clean_disconnect = true;

    // Server capabilities
    this._rfb_version = 0;
    this._rfb_max_version = 3.8;
    this._rfb_tightvnc = false;
    this._rfb_xvp_ver = 0;

    this._fb_width = 0;
    this._fb_height = 0;

    this._fb_name = "";

    this._capabilities = { power: false };

    this._supportsFence = false;

    this._supportsContinuousUpdates = false;
    this._enabledContinuousUpdates = false;

    this._supportsSetDesktopSize = false;
    this._screen_id = 0;
    this._screen_flags = 0;

    this._qemuExtKeyEventSupported = false;

    // Internal objects
    this._sock = null; // Websock object
    this._display = null; // Display object
    this._flushing = false; // Display flushing state
    this._keyboard = null; // Keyboard input handler object
    this._mouse = null; // Mouse input handler object

    // Timers
    this._disconnTimer = null; // disconnection timer
    this._resizeTimeout = null; // resize rate limiting

    // Decoder states and stats
    this._encHandlers = {};
    this._encStats = {};

    this._FBU = {
        rects: 0,
        subrects: 0, // RRE and HEXTILE
        lines: 0, // RAW
        tiles: 0, // HEXTILE
        bytes: 0,
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        encoding: 0,
        subencoding: -1,
        background: null,
        zlibs: [] // TIGHT zlib streams
    };
    for (var i = 0; i < 4; i++) {
        this._FBU.zlibs[i] = new _inflator2.default();
    }

    this._destBuff = null;
    this._paletteBuff = new Uint8Array(1024); // 256 * 4 (max palette size * max bytes-per-pixel)

    this._rre_chunk_sz = 100;

    this._timing = {
        last_fbu: 0,
        fbu_total: 0,
        fbu_total_cnt: 0,
        full_fbu_total: 0,
        full_fbu_cnt: 0,

        fbu_rt_start: 0,
        fbu_rt_total: 0,
        fbu_rt_cnt: 0,
        pixels: 0
    };

    // Mouse state
    this._mouse_buttonMask = 0;
    this._mouse_arr = [];
    this._viewportDragging = false;
    this._viewportDragPos = {};
    this._viewportHasMoved = false;

    // Bound event handlers
    this._eventHandlers = {
        focusCanvas: this._focusCanvas.bind(this),
        windowResize: this._windowResize.bind(this)
    };

    // main setup
    Log.Debug(">> RFB.constructor");

    // Create DOM elements
    this._screen = document.createElement('div');
    this._screen.style.display = 'flex';
    this._screen.style.width = '100%';
    this._screen.style.height = '100%';
    this._screen.style.overflow = 'auto';
    this._screen.style.backgroundColor = 'rgb(40, 40, 40)';
    this._canvas = document.createElement('canvas');
    this._canvas.style.margin = 'auto';
    // Some browsers add an outline on focus
    this._canvas.style.outline = 'none';
    // IE miscalculates width without this :(
    this._canvas.style.flexShrink = '0';
    this._canvas.width = 0;
    this._canvas.height = 0;
    this._canvas.tabIndex = -1;
    this._screen.appendChild(this._canvas);

    // populate encHandlers with bound versions
    this._encHandlers[_encodings.encodings.encodingRaw] = RFB.encodingHandlers.RAW.bind(this);
    this._encHandlers[_encodings.encodings.encodingCopyRect] = RFB.encodingHandlers.COPYRECT.bind(this);
    this._encHandlers[_encodings.encodings.encodingRRE] = RFB.encodingHandlers.RRE.bind(this);
    this._encHandlers[_encodings.encodings.encodingHextile] = RFB.encodingHandlers.HEXTILE.bind(this);
    this._encHandlers[_encodings.encodings.encodingTight] = RFB.encodingHandlers.TIGHT.bind(this);

    this._encHandlers[_encodings.encodings.pseudoEncodingDesktopSize] = RFB.encodingHandlers.DesktopSize.bind(this);
    this._encHandlers[_encodings.encodings.pseudoEncodingLastRect] = RFB.encodingHandlers.last_rect.bind(this);
    this._encHandlers[_encodings.encodings.pseudoEncodingCursor] = RFB.encodingHandlers.Cursor.bind(this);
    this._encHandlers[_encodings.encodings.pseudoEncodingQEMUExtendedKeyEvent] = RFB.encodingHandlers.QEMUExtendedKeyEvent.bind(this);
    this._encHandlers[_encodings.encodings.pseudoEncodingExtendedDesktopSize] = RFB.encodingHandlers.ExtendedDesktopSize.bind(this);

    // NB: nothing that needs explicit teardown should be done
    // before this point, since this can throw an exception
    try {
        this._display = new _display2.default(this._canvas);
    } catch (exc) {
        Log.Error("Display exception: " + exc);
        throw exc;
    }
    this._display.onflush = this._onFlush.bind(this);
    this._display.clear();

    this._keyboard = new _keyboard2.default(this._canvas);
    this._keyboard.onkeyevent = this._handleKeyEvent.bind(this);

    this._mouse = new _mouse2.default(this._canvas);
    this._mouse.onmousebutton = this._handleMouseButton.bind(this);
    this._mouse.onmousemove = this._handleMouseMove.bind(this);

    this._sock = new _websock2.default();
    this._sock.on('message', this._handle_message.bind(this));
    this._sock.on('open', function () {
        if (this._rfb_connection_state === 'connecting' && this._rfb_init_state === '') {
            this._rfb_init_state = 'ProtocolVersion';
            Log.Debug("Starting VNC handshake");
        } else {
            this._fail("Unexpected server connection while " + this._rfb_connection_state);
        }
    }.bind(this));
    this._sock.on('close', function (e) {
        Log.Debug("WebSocket on-close event");
        var msg = "";
        if (e.code) {
            msg = "(code: " + e.code;
            if (e.reason) {
                msg += ", reason: " + e.reason;
            }
            msg += ")";
        }
        switch (this._rfb_connection_state) {
            case 'connecting':
                this._fail("Connection closed " + msg);
                break;
            case 'connected':
                // Handle disconnects that were initiated server-side
                this._updateConnectionState('disconnecting');
                this._updateConnectionState('disconnected');
                break;
            case 'disconnecting':
                // Normal disconnection path
                this._updateConnectionState('disconnected');
                break;
            case 'disconnected':
                this._fail("Unexpected server disconnect " + "when already disconnected " + msg);
                break;
            default:
                this._fail("Unexpected server disconnect before connecting " + msg);
                break;
        }
        this._sock.off('close');
    }.bind(this));
    this._sock.on('error', function (e) {
        Log.Warn("WebSocket on-error event");
    });

    // Slight delay of the actual connection so that the caller has
    // time to set up callbacks
    setTimeout(this._updateConnectionState.bind(this, 'connecting'));

    Log.Debug("<< RFB.constructor");
};

RFB.prototype = {
    // ===== PROPERTIES =====

    dragViewport: false,
    focusOnClick: true,

    _viewOnly: false,
    get viewOnly() {
        return this._viewOnly;
    },
    set viewOnly(viewOnly) {
        this._viewOnly = viewOnly;

        if (this._rfb_connection_state === "connecting" || this._rfb_connection_state === "connected") {
            if (viewOnly) {
                this._keyboard.ungrab();
                this._mouse.ungrab();
            } else {
                this._keyboard.grab();
                this._mouse.grab();
            }
        }
    },

    get capabilities() {
        return this._capabilities;
    },

    get touchButton() {
        return this._mouse.touchButton;
    },
    set touchButton(button) {
        this._mouse.touchButton = button;
    },

    _clipViewport: false,
    get clipViewport() {
        return this._clipViewport;
    },
    set clipViewport(viewport) {
        this._clipViewport = viewport;
        this._updateClip();
    },

    _scaleViewport: false,
    get scaleViewport() {
        return this._scaleViewport;
    },
    set scaleViewport(scale) {
        this._scaleViewport = scale;
        // Scaling trumps clipping, so we may need to adjust
        // clipping when enabling or disabling scaling
        if (scale && this._clipViewport) {
            this._updateClip();
        }
        this._updateScale();
        if (!scale && this._clipViewport) {
            this._updateClip();
        }
    },

    _resizeSession: false,
    get resizeSession() {
        return this._resizeSession;
    },
    set resizeSession(resize) {
        this._resizeSession = resize;
        if (resize) {
            this._requestRemoteResize();
        }
    },

    // ===== PUBLIC METHODS =====

    disconnect: function () {
        this._updateConnectionState('disconnecting');
        this._sock.off('error');
        this._sock.off('message');
        this._sock.off('open');
    },

    sendCredentials: function (creds) {
        this._rfb_credentials = creds;
        setTimeout(this._init_msg.bind(this), 0);
    },

    sendCtrlAltDel: function () {
        if (this._rfb_connection_state !== 'connected' || this._viewOnly) {
            return;
        }
        Log.Info("Sending Ctrl-Alt-Del");

        this.sendKey(_keysym2.default.XK_Control_L, "ControlLeft", true);
        this.sendKey(_keysym2.default.XK_Alt_L, "AltLeft", true);
        this.sendKey(_keysym2.default.XK_Delete, "Delete", true);
        this.sendKey(_keysym2.default.XK_Delete, "Delete", false);
        this.sendKey(_keysym2.default.XK_Alt_L, "AltLeft", false);
        this.sendKey(_keysym2.default.XK_Control_L, "ControlLeft", false);
    },

    machineShutdown: function () {
        this._xvpOp(1, 2);
    },

    machineReboot: function () {
        this._xvpOp(1, 3);
    },

    machineReset: function () {
        this._xvpOp(1, 4);
    },

    // Send a key press. If 'down' is not specified then send a down key
    // followed by an up key.
    sendKey: function (keysym, code, down) {
        if (this._rfb_connection_state !== 'connected' || this._viewOnly) {
            return;
        }

        if (down === undefined) {
            this.sendKey(keysym, code, true);
            this.sendKey(keysym, code, false);
            return;
        }

        var scancode = _xtscancodes2.default[code];

        if (this._qemuExtKeyEventSupported && scancode) {
            // 0 is NoSymbol
            keysym = keysym || 0;

            Log.Info("Sending key (" + (down ? "down" : "up") + "): keysym " + keysym + ", scancode " + scancode);

            RFB.messages.QEMUExtendedKeyEvent(this._sock, keysym, down, scancode);
        } else {
            if (!keysym) {
                return;
            }
            Log.Info("Sending keysym (" + (down ? "down" : "up") + "): " + keysym);
            RFB.messages.keyEvent(this._sock, keysym, down ? 1 : 0);
        }
    },

    focus: function () {
        this._canvas.focus();
    },

    blur: function () {
        this._canvas.blur();
    },

    clipboardPasteFrom: function (text) {
        if (this._rfb_connection_state !== 'connected' || this._viewOnly) {
            return;
        }
        RFB.messages.clientCutText(this._sock, text);
    },

    // ===== PRIVATE METHODS =====

    _connect: function () {
        Log.Debug(">> RFB.connect");

        Log.Info("connecting to " + this._url);

        try {
            // WebSocket.onopen transitions to the RFB init states
            this._sock.open(this._url, ['binary']);
        } catch (e) {
            if (e.name === 'SyntaxError') {
                this._fail("Invalid host or port (" + e + ")");
            } else {
                this._fail("Error when opening socket (" + e + ")");
            }
        }

        // Make our elements part of the page
        this._target.appendChild(this._screen);

        // Monitor size changes of the screen
        // FIXME: Use ResizeObserver, or hidden overflow
        window.addEventListener('resize', this._eventHandlers.windowResize);

        // Always grab focus on some kind of click event
        this._canvas.addEventListener("mousedown", this._eventHandlers.focusCanvas);
        this._canvas.addEventListener("touchstart", this._eventHandlers.focusCanvas);

        Log.Debug("<< RFB.connect");
    },

    _disconnect: function () {
        Log.Debug(">> RFB.disconnect");
        this._canvas.removeEventListener("mousedown", this._eventHandlers.focusCanvas);
        this._canvas.removeEventListener("touchstart", this._eventHandlers.focusCanvas);
        window.removeEventListener('resize', this._eventHandlers.windowResize);
        this._keyboard.ungrab();
        this._mouse.ungrab();
        this._sock.close();
        this._print_stats();
        try {
            this._target.removeChild(this._screen);
        } catch (e) {
            if (e.name === 'NotFoundError') {
                // Some cases where the initial connection fails
                // can disconnect before the _screen is created
            } else {
                throw e;
            }
        }
        clearTimeout(this._resizeTimeout);
        Log.Debug("<< RFB.disconnect");
    },

    _print_stats: function () {
        var stats = this._encStats;

        Log.Info("Encoding stats for this connection:");
        Object.keys(stats).forEach(function (key) {
            var s = stats[key];
            if (s[0] + s[1] > 0) {
                Log.Info("    " + (0, _encodings.encodingName)(key) + ": " + s[0] + " rects");
            }
        });

        Log.Info("Encoding stats since page load:");
        Object.keys(stats).forEach(function (key) {
            var s = stats[key];
            Log.Info("    " + (0, _encodings.encodingName)(key) + ": " + s[1] + " rects");
        });
    },

    _focusCanvas: function (event) {
        // Respect earlier handlers' request to not do side-effects
        if (event.defaultPrevented) {
            return;
        }

        if (!this.focusOnClick) {
            return;
        }

        this.focus();
    },

    _windowResize: function (event) {
        // If the window resized then our screen element might have
        // as well. Update the viewport dimensions.
        window.requestAnimationFrame(function () {
            this._updateClip();
            this._updateScale();
        }.bind(this));

        if (this._resizeSession) {
            // Request changing the resolution of the remote display to
            // the size of the local browser viewport.

            // In order to not send multiple requests before the browser-resize
            // is finished we wait 0.5 seconds before sending the request.
            clearTimeout(this._resizeTimeout);
            this._resizeTimeout = setTimeout(this._requestRemoteResize.bind(this), 500);
        }
    },

    // Update state of clipping in Display object, and make sure the
    // configured viewport matches the current screen size
    _updateClip: function () {
        var cur_clip = this._display.clipViewport;
        var new_clip = this._clipViewport;

        if (this._scaleViewport) {
            // Disable viewport clipping if we are scaling
            new_clip = false;
        }

        if (cur_clip !== new_clip) {
            this._display.clipViewport = new_clip;
        }

        if (new_clip) {
            // When clipping is enabled, the screen is limited to
            // the size of the container.
            let size = this._screenSize();
            this._display.viewportChangeSize(size.w, size.h);
            this._fixScrollbars();
        }
    },

    _updateScale: function () {
        if (!this._scaleViewport) {
            this._display.scale = 1.0;
        } else {
            let size = this._screenSize();
            this._display.autoscale(size.w, size.h);
        }
        this._fixScrollbars();
    },

    // Requests a change of remote desktop size. This message is an extension
    // and may only be sent if we have received an ExtendedDesktopSize message
    _requestRemoteResize: function () {
        clearTimeout(this._resizeTimeout);
        this._resizeTimeout = null;

        if (!this._resizeSession || this._viewOnly || !this._supportsSetDesktopSize) {
            return;
        }

        let size = this._screenSize();
        RFB.messages.setDesktopSize(this._sock, size.w, size.h, this._screen_id, this._screen_flags);

        Log.Debug('Requested new desktop size: ' + size.w + 'x' + size.h);
    },

    // Gets the the size of the available screen
    _screenSize: function () {
        return { w: this._screen.offsetWidth,
            h: this._screen.offsetHeight };
    },

    _fixScrollbars: function () {
        // This is a hack because Chrome screws up the calculation
        // for when scrollbars are needed. So to fix it we temporarily
        // toggle them off and on.
        var orig = this._screen.style.overflow;
        this._screen.style.overflow = 'hidden';
        // Force Chrome to recalculate the layout by asking for
        // an element's dimensions
        this._screen.getBoundingClientRect();
        this._screen.style.overflow = orig;
    },

    /*
     * Connection states:
     *   connecting
     *   connected
     *   disconnecting
     *   disconnected - permanent state
     */
    _updateConnectionState: function (state) {
        var oldstate = this._rfb_connection_state;

        if (state === oldstate) {
            Log.Debug("Already in state '" + state + "', ignoring");
            return;
        }

        // The 'disconnected' state is permanent for each RFB object
        if (oldstate === 'disconnected') {
            Log.Error("Tried changing state of a disconnected RFB object");
            return;
        }

        // Ensure proper transitions before doing anything
        switch (state) {
            case 'connected':
                if (oldstate !== 'connecting') {
                    Log.Error("Bad transition to connected state, " + "previous connection state: " + oldstate);
                    return;
                }
                break;

            case 'disconnected':
                if (oldstate !== 'disconnecting') {
                    Log.Error("Bad transition to disconnected state, " + "previous connection state: " + oldstate);
                    return;
                }
                break;

            case 'connecting':
                if (oldstate !== '') {
                    Log.Error("Bad transition to connecting state, " + "previous connection state: " + oldstate);
                    return;
                }
                break;

            case 'disconnecting':
                if (oldstate !== 'connected' && oldstate !== 'connecting') {
                    Log.Error("Bad transition to disconnecting state, " + "previous connection state: " + oldstate);
                    return;
                }
                break;

            default:
                Log.Error("Unknown connection state: " + state);
                return;
        }

        // State change actions

        this._rfb_connection_state = state;

        var smsg = "New state '" + state + "', was '" + oldstate + "'.";
        Log.Debug(smsg);

        if (this._disconnTimer && state !== 'disconnecting') {
            Log.Debug("Clearing disconnect timer");
            clearTimeout(this._disconnTimer);
            this._disconnTimer = null;

            // make sure we don't get a double event
            this._sock.off('close');
        }

        switch (state) {
            case 'connecting':
                this._connect();
                break;

            case 'connected':
                var event = new CustomEvent("connect", { detail: {} });
                this.dispatchEvent(event);
                break;

            case 'disconnecting':
                this._disconnect();

                this._disconnTimer = setTimeout(function () {
                    Log.Error("Disconnection timed out.");
                    this._updateConnectionState('disconnected');
                }.bind(this), DISCONNECT_TIMEOUT * 1000);
                break;

            case 'disconnected':
                event = new CustomEvent("disconnect", { detail: { clean: this._rfb_clean_disconnect } });
                this.dispatchEvent(event);
                break;
        }
    },

    /* Print errors and disconnect
     *
     * The parameter 'details' is used for information that
     * should be logged but not sent to the user interface.
     */
    _fail: function (details) {
        switch (this._rfb_connection_state) {
            case 'disconnecting':
                Log.Error("Failed when disconnecting: " + details);
                break;
            case 'connected':
                Log.Error("Failed while connected: " + details);
                break;
            case 'connecting':
                Log.Error("Failed when connecting: " + details);
                break;
            default:
                Log.Error("RFB failure: " + details);
                break;
        }
        this._rfb_clean_disconnect = false; //This is sent to the UI

        // Transition to disconnected without waiting for socket to close
        this._updateConnectionState('disconnecting');
        this._updateConnectionState('disconnected');

        return false;
    },

    _setCapability: function (cap, val) {
        this._capabilities[cap] = val;
        var event = new CustomEvent("capabilities", { detail: { capabilities: this._capabilities } });
        this.dispatchEvent(event);
    },

    _handle_message: function () {
        if (this._sock.rQlen() === 0) {
            Log.Warn("handle_message called on an empty receive queue");
            return;
        }

        switch (this._rfb_connection_state) {
            case 'disconnected':
                Log.Error("Got data while disconnected");
                break;
            case 'connected':
                while (true) {
                    if (this._flushing) {
                        break;
                    }
                    if (!this._normal_msg()) {
                        break;
                    }
                    if (this._sock.rQlen() === 0) {
                        break;
                    }
                }
                break;
            default:
                this._init_msg();
                break;
        }
    },

    _handleKeyEvent: function (keysym, code, down) {
        this.sendKey(keysym, code, down);
    },

    _handleMouseButton: function (x, y, down, bmask) {
        if (down) {
            this._mouse_buttonMask |= bmask;
        } else {
            this._mouse_buttonMask &= ~bmask;
        }

        if (this.dragViewport) {
            if (down && !this._viewportDragging) {
                this._viewportDragging = true;
                this._viewportDragPos = { 'x': x, 'y': y };
                this._viewportHasMoved = false;

                // Skip sending mouse events
                return;
            } else {
                this._viewportDragging = false;

                // If we actually performed a drag then we are done
                // here and should not send any mouse events
                if (this._viewportHasMoved) {
                    return;
                }

                // Otherwise we treat this as a mouse click event.
                // Send the button down event here, as the button up
                // event is sent at the end of this function.
                RFB.messages.pointerEvent(this._sock, this._display.absX(x), this._display.absY(y), bmask);
            }
        }

        if (this._viewOnly) {
            return;
        } // View only, skip mouse events

        if (this._rfb_connection_state !== 'connected') {
            return;
        }
        RFB.messages.pointerEvent(this._sock, this._display.absX(x), this._display.absY(y), this._mouse_buttonMask);
    },

    _handleMouseMove: function (x, y) {
        if (this._viewportDragging) {
            var deltaX = this._viewportDragPos.x - x;
            var deltaY = this._viewportDragPos.y - y;

            // The goal is to trigger on a certain physical width, the
            // devicePixelRatio brings us a bit closer but is not optimal.
            var dragThreshold = 10 * (window.devicePixelRatio || 1);

            if (this._viewportHasMoved || Math.abs(deltaX) > dragThreshold || Math.abs(deltaY) > dragThreshold) {
                this._viewportHasMoved = true;

                this._viewportDragPos = { 'x': x, 'y': y };
                this._display.viewportChangePos(deltaX, deltaY);
            }

            // Skip sending mouse events
            return;
        }

        if (this._viewOnly) {
            return;
        } // View only, skip mouse events

        if (this._rfb_connection_state !== 'connected') {
            return;
        }
        RFB.messages.pointerEvent(this._sock, this._display.absX(x), this._display.absY(y), this._mouse_buttonMask);
    },

    // Message Handlers

    _negotiate_protocol_version: function () {
        if (this._sock.rQlen() < 12) {
            return this._fail("Received incomplete protocol version.");
        }

        var sversion = this._sock.rQshiftStr(12).substr(4, 7);
        Log.Info("Server ProtocolVersion: " + sversion);
        var is_repeater = 0;
        switch (sversion) {
            case "000.000":
                // UltraVNC repeater
                is_repeater = 1;
                break;
            case "003.003":
            case "003.006": // UltraVNC
            case "003.889":
                // Apple Remote Desktop
                this._rfb_version = 3.3;
                break;
            case "003.007":
                this._rfb_version = 3.7;
                break;
            case "003.008":
            case "004.000": // Intel AMT KVM
            case "004.001": // RealVNC 4.6
            case "005.000":
                // RealVNC 5.3
                this._rfb_version = 3.8;
                break;
            default:
                return this._fail("Invalid server version " + sversion);
        }

        if (is_repeater) {
            var repeaterID = "ID:" + this._repeaterID;
            while (repeaterID.length < 250) {
                repeaterID += "\0";
            }
            this._sock.send_string(repeaterID);
            return true;
        }

        if (this._rfb_version > this._rfb_max_version) {
            this._rfb_version = this._rfb_max_version;
        }

        var cversion = "00" + parseInt(this._rfb_version, 10) + ".00" + this._rfb_version * 10 % 10;
        this._sock.send_string("RFB " + cversion + "\n");
        Log.Debug('Sent ProtocolVersion: ' + cversion);

        this._rfb_init_state = 'Security';
    },

    _negotiate_security: function () {
        // Polyfill since IE and PhantomJS doesn't have
        // TypedArray.includes()
        function includes(item, array) {
            for (var i = 0; i < array.length; i++) {
                if (array[i] === item) {
                    return true;
                }
            }
            return false;
        }

        if (this._rfb_version >= 3.7) {
            // Server sends supported list, client decides
            var num_types = this._sock.rQshift8();
            if (this._sock.rQwait("security type", num_types, 1)) {
                return false;
            }

            if (num_types === 0) {
                return this._handle_security_failure("no security types");
            }

            var types = this._sock.rQshiftBytes(num_types);
            Log.Debug("Server security types: " + types);

            // Look for each auth in preferred order
            this._rfb_auth_scheme = 0;
            if (includes(1, types)) {
                this._rfb_auth_scheme = 1; // None
            } else if (includes(22, types)) {
                this._rfb_auth_scheme = 22; // XVP
            } else if (includes(16, types)) {
                this._rfb_auth_scheme = 16; // Tight
            } else if (includes(2, types)) {
                this._rfb_auth_scheme = 2; // VNC Auth
            } else {
                return this._fail("Unsupported security types (types: " + types + ")");
            }

            this._sock.send([this._rfb_auth_scheme]);
        } else {
            // Server decides
            if (this._sock.rQwait("security scheme", 4)) {
                return false;
            }
            this._rfb_auth_scheme = this._sock.rQshift32();
        }

        this._rfb_init_state = 'Authentication';
        Log.Debug('Authenticating using scheme: ' + this._rfb_auth_scheme);

        return this._init_msg(); // jump to authentication
    },

    /*
     * Get the security failure reason if sent from the server and
     * send the 'securityfailure' event.
     *
     * - The optional parameter context can be used to add some extra
     *   context to the log output.
     *
     * - The optional parameter security_result_status can be used to
     *   add a custom status code to the event.
     */
    _handle_security_failure: function (context, security_result_status) {

        if (typeof context === 'undefined') {
            context = "";
        } else {
            context = " on " + context;
        }

        if (typeof security_result_status === 'undefined') {
            security_result_status = 1; // fail
        }

        if (this._sock.rQwait("reason length", 4)) {
            return false;
        }
        let strlen = this._sock.rQshift32();
        let reason = "";

        if (strlen > 0) {
            if (this._sock.rQwait("reason", strlen, 8)) {
                return false;
            }
            reason = this._sock.rQshiftStr(strlen);
        }

        if (reason !== "") {

            let event = new CustomEvent("securityfailure", { detail: { status: security_result_status, reason: reason } });
            this.dispatchEvent(event);

            return this._fail("Security negotiation failed" + context + " (reason: " + reason + ")");
        } else {

            let event = new CustomEvent("securityfailure", { detail: { status: security_result_status } });
            this.dispatchEvent(event);

            return this._fail("Security negotiation failed" + context);
        }
    },

    // authentication
    _negotiate_xvp_auth: function () {
        if (!this._rfb_credentials.username || !this._rfb_credentials.password || !this._rfb_credentials.target) {
            var event = new CustomEvent("credentialsrequired", { detail: { types: ["username", "password", "target"] } });
            this.dispatchEvent(event);
            return false;
        }

        var xvp_auth_str = String.fromCharCode(this._rfb_credentials.username.length) + String.fromCharCode(this._rfb_credentials.target.length) + this._rfb_credentials.username + this._rfb_credentials.target;
        this._sock.send_string(xvp_auth_str);
        this._rfb_auth_scheme = 2;
        return this._negotiate_authentication();
    },

    _negotiate_std_vnc_auth: function () {
        if (this._sock.rQwait("auth challenge", 16)) {
            return false;
        }

        if (!this._rfb_credentials.password) {
            var event = new CustomEvent("credentialsrequired", { detail: { types: ["password"] } });
            this.dispatchEvent(event);
            return false;
        }

        // TODO(directxman12): make genDES not require an Array
        var challenge = Array.prototype.slice.call(this._sock.rQshiftBytes(16));
        var response = RFB.genDES(this._rfb_credentials.password, challenge);
        this._sock.send(response);
        this._rfb_init_state = "SecurityResult";
        return true;
    },

    _negotiate_tight_tunnels: function (numTunnels) {
        var clientSupportedTunnelTypes = {
            0: { vendor: 'TGHT', signature: 'NOTUNNEL' }
        };
        var serverSupportedTunnelTypes = {};
        // receive tunnel capabilities
        for (var i = 0; i < numTunnels; i++) {
            var cap_code = this._sock.rQshift32();
            var cap_vendor = this._sock.rQshiftStr(4);
            var cap_signature = this._sock.rQshiftStr(8);
            serverSupportedTunnelTypes[cap_code] = { vendor: cap_vendor, signature: cap_signature };
        }

        // choose the notunnel type
        if (serverSupportedTunnelTypes[0]) {
            if (serverSupportedTunnelTypes[0].vendor != clientSupportedTunnelTypes[0].vendor || serverSupportedTunnelTypes[0].signature != clientSupportedTunnelTypes[0].signature) {
                return this._fail("Client's tunnel type had the incorrect " + "vendor or signature");
            }
            this._sock.send([0, 0, 0, 0]); // use NOTUNNEL
            return false; // wait until we receive the sub auth count to continue
        } else {
            return this._fail("Server wanted tunnels, but doesn't support " + "the notunnel type");
        }
    },

    _negotiate_tight_auth: function () {
        if (!this._rfb_tightvnc) {
            // first pass, do the tunnel negotiation
            if (this._sock.rQwait("num tunnels", 4)) {
                return false;
            }
            var numTunnels = this._sock.rQshift32();
            if (numTunnels > 0 && this._sock.rQwait("tunnel capabilities", 16 * numTunnels, 4)) {
                return false;
            }

            this._rfb_tightvnc = true;

            if (numTunnels > 0) {
                this._negotiate_tight_tunnels(numTunnels);
                return false; // wait until we receive the sub auth to continue
            }
        }

        // second pass, do the sub-auth negotiation
        if (this._sock.rQwait("sub auth count", 4)) {
            return false;
        }
        var subAuthCount = this._sock.rQshift32();
        if (subAuthCount === 0) {
            // empty sub-auth list received means 'no auth' subtype selected
            this._rfb_init_state = 'SecurityResult';
            return true;
        }

        if (this._sock.rQwait("sub auth capabilities", 16 * subAuthCount, 4)) {
            return false;
        }

        var clientSupportedTypes = {
            'STDVNOAUTH__': 1,
            'STDVVNCAUTH_': 2
        };

        var serverSupportedTypes = [];

        for (var i = 0; i < subAuthCount; i++) {
            var capNum = this._sock.rQshift32();
            var capabilities = this._sock.rQshiftStr(12);
            serverSupportedTypes.push(capabilities);
        }

        for (var authType in clientSupportedTypes) {
            if (serverSupportedTypes.indexOf(authType) != -1) {
                this._sock.send([0, 0, 0, clientSupportedTypes[authType]]);

                switch (authType) {
                    case 'STDVNOAUTH__':
                        // no auth
                        this._rfb_init_state = 'SecurityResult';
                        return true;
                    case 'STDVVNCAUTH_':
                        // VNC auth
                        this._rfb_auth_scheme = 2;
                        return this._init_msg();
                    default:
                        return this._fail("Unsupported tiny auth scheme " + "(scheme: " + authType + ")");
                }
            }
        }

        return this._fail("No supported sub-auth types!");
    },

    _negotiate_authentication: function () {
        switch (this._rfb_auth_scheme) {
            case 0:
                // connection failed
                return this._handle_security_failure("authentication scheme");

            case 1:
                // no auth
                if (this._rfb_version >= 3.8) {
                    this._rfb_init_state = 'SecurityResult';
                    return true;
                }
                this._rfb_init_state = 'ClientInitialisation';
                return this._init_msg();

            case 22:
                // XVP auth
                return this._negotiate_xvp_auth();

            case 2:
                // VNC authentication
                return this._negotiate_std_vnc_auth();

            case 16:
                // TightVNC Security Type
                return this._negotiate_tight_auth();

            default:
                return this._fail("Unsupported auth scheme (scheme: " + this._rfb_auth_scheme + ")");
        }
    },

    _handle_security_result: function () {
        if (this._sock.rQwait('VNC auth response ', 4)) {
            return false;
        }

        let status = this._sock.rQshift32();

        if (status === 0) {
            // OK
            this._rfb_init_state = 'ClientInitialisation';
            Log.Debug('Authentication OK');
            return this._init_msg();
        } else {
            if (this._rfb_version >= 3.8) {
                return this._handle_security_failure("security result", status);
            } else {
                let event = new CustomEvent("securityfailure", { detail: { status: status } });
                this.dispatchEvent(event);

                return this._fail("Security handshake failed");
            }
        }
    },

    _negotiate_server_init: function () {
        if (this._sock.rQwait("server initialization", 24)) {
            return false;
        }

        /* Screen size */
        var width = this._sock.rQshift16();
        var height = this._sock.rQshift16();

        /* PIXEL_FORMAT */
        var bpp = this._sock.rQshift8();
        var depth = this._sock.rQshift8();
        var big_endian = this._sock.rQshift8();
        var true_color = this._sock.rQshift8();

        var red_max = this._sock.rQshift16();
        var green_max = this._sock.rQshift16();
        var blue_max = this._sock.rQshift16();
        var red_shift = this._sock.rQshift8();
        var green_shift = this._sock.rQshift8();
        var blue_shift = this._sock.rQshift8();
        this._sock.rQskipBytes(3); // padding

        // NB(directxman12): we don't want to call any callbacks or print messages until
        //                   *after* we're past the point where we could backtrack

        /* Connection name/title */
        var name_length = this._sock.rQshift32();
        if (this._sock.rQwait('server init name', name_length, 24)) {
            return false;
        }
        this._fb_name = (0, _strings.decodeUTF8)(this._sock.rQshiftStr(name_length));

        if (this._rfb_tightvnc) {
            if (this._sock.rQwait('TightVNC extended server init header', 8, 24 + name_length)) {
                return false;
            }
            // In TightVNC mode, ServerInit message is extended
            var numServerMessages = this._sock.rQshift16();
            var numClientMessages = this._sock.rQshift16();
            var numEncodings = this._sock.rQshift16();
            this._sock.rQskipBytes(2); // padding

            var totalMessagesLength = (numServerMessages + numClientMessages + numEncodings) * 16;
            if (this._sock.rQwait('TightVNC extended server init header', totalMessagesLength, 32 + name_length)) {
                return false;
            }

            // we don't actually do anything with the capability information that TIGHT sends,
            // so we just skip the all of this.

            // TIGHT server message capabilities
            this._sock.rQskipBytes(16 * numServerMessages);

            // TIGHT client message capabilities
            this._sock.rQskipBytes(16 * numClientMessages);

            // TIGHT encoding capabilities
            this._sock.rQskipBytes(16 * numEncodings);
        }

        // NB(directxman12): these are down here so that we don't run them multiple times
        //                   if we backtrack
        Log.Info("Screen: " + width + "x" + height + ", bpp: " + bpp + ", depth: " + depth + ", big_endian: " + big_endian + ", true_color: " + true_color + ", red_max: " + red_max + ", green_max: " + green_max + ", blue_max: " + blue_max + ", red_shift: " + red_shift + ", green_shift: " + green_shift + ", blue_shift: " + blue_shift);

        if (big_endian !== 0) {
            Log.Warn("Server native endian is not little endian");
        }

        if (red_shift !== 16) {
            Log.Warn("Server native red-shift is not 16");
        }

        if (blue_shift !== 0) {
            Log.Warn("Server native blue-shift is not 0");
        }

        // we're past the point where we could backtrack, so it's safe to call this
        var event = new CustomEvent("desktopname", { detail: { name: this._fb_name } });
        this.dispatchEvent(event);

        this._resize(width, height);

        if (!this._viewOnly) {
            this._keyboard.grab();
        }
        if (!this._viewOnly) {
            this._mouse.grab();
        }

        this._fb_depth = 24;

        if (this._fb_name === "Intel(r) AMT KVM") {
            Log.Warn("Intel AMT KVM only supports 8/16 bit depths. Using low color mode.");
            this._fb_depth = 8;
        }

        RFB.messages.pixelFormat(this._sock, this._fb_depth, true);
        this._sendEncodings();
        RFB.messages.fbUpdateRequest(this._sock, false, 0, 0, this._fb_width, this._fb_height);

        this._timing.fbu_rt_start = new Date().getTime();
        this._timing.pixels = 0;

        // Cursor will be server side until the server decides to honor
        // our request and send over the cursor image
        this._display.disableLocalCursor();

        this._updateConnectionState('connected');
        return true;
    },

    _sendEncodings: function () {
        var encs = [];

        // In preference order
        encs.push(_encodings.encodings.encodingCopyRect);
        // Only supported with full depth support
        if (this._fb_depth == 24) {
            encs.push(_encodings.encodings.encodingTight);
            encs.push(_encodings.encodings.encodingHextile);
            encs.push(_encodings.encodings.encodingRRE);
        }
        encs.push(_encodings.encodings.encodingRaw);

        // Psuedo-encoding settings
        encs.push(_encodings.encodings.pseudoEncodingTightPNG);
        encs.push(_encodings.encodings.pseudoEncodingQualityLevel0 + 6);
        encs.push(_encodings.encodings.pseudoEncodingCompressLevel0 + 2);

        encs.push(_encodings.encodings.pseudoEncodingDesktopSize);
        encs.push(_encodings.encodings.pseudoEncodingLastRect);
        encs.push(_encodings.encodings.pseudoEncodingQEMUExtendedKeyEvent);
        encs.push(_encodings.encodings.pseudoEncodingExtendedDesktopSize);
        encs.push(_encodings.encodings.pseudoEncodingXvp);
        encs.push(_encodings.encodings.pseudoEncodingFence);
        encs.push(_encodings.encodings.pseudoEncodingContinuousUpdates);

        if ((0, _browser.supportsCursorURIs)() && !_browser.isTouchDevice && this._fb_depth == 24) {
            encs.push(_encodings.encodings.pseudoEncodingCursor);
        }

        RFB.messages.clientEncodings(this._sock, encs);
    },

    /* RFB protocol initialization states:
     *   ProtocolVersion
     *   Security
     *   Authentication
     *   SecurityResult
     *   ClientInitialization - not triggered by server message
     *   ServerInitialization
     */
    _init_msg: function () {
        switch (this._rfb_init_state) {
            case 'ProtocolVersion':
                return this._negotiate_protocol_version();

            case 'Security':
                return this._negotiate_security();

            case 'Authentication':
                return this._negotiate_authentication();

            case 'SecurityResult':
                return this._handle_security_result();

            case 'ClientInitialisation':
                this._sock.send([this._shared ? 1 : 0]); // ClientInitialisation
                this._rfb_init_state = 'ServerInitialisation';
                return true;

            case 'ServerInitialisation':
                return this._negotiate_server_init();

            default:
                return this._fail("Unknown init state (state: " + this._rfb_init_state + ")");
        }
    },

    _handle_set_colour_map_msg: function () {
        Log.Debug("SetColorMapEntries");

        return this._fail("Unexpected SetColorMapEntries message");
    },

    _handle_server_cut_text: function () {
        Log.Debug("ServerCutText");

        if (this._sock.rQwait("ServerCutText header", 7, 1)) {
            return false;
        }
        this._sock.rQskipBytes(3); // Padding
        var length = this._sock.rQshift32();
        if (this._sock.rQwait("ServerCutText", length, 8)) {
            return false;
        }

        var text = this._sock.rQshiftStr(length);

        if (this._viewOnly) {
            return true;
        }

        var event = new CustomEvent("clipboard", { detail: { text: text } });
        this.dispatchEvent(event);

        return true;
    },

    _handle_server_fence_msg: function () {
        if (this._sock.rQwait("ServerFence header", 8, 1)) {
            return false;
        }
        this._sock.rQskipBytes(3); // Padding
        var flags = this._sock.rQshift32();
        var length = this._sock.rQshift8();

        if (this._sock.rQwait("ServerFence payload", length, 9)) {
            return false;
        }

        if (length > 64) {
            Log.Warn("Bad payload length (" + length + ") in fence response");
            length = 64;
        }

        var payload = this._sock.rQshiftStr(length);

        this._supportsFence = true;

        /*
         * Fence flags
         *
         *  (1<<0)  - BlockBefore
         *  (1<<1)  - BlockAfter
         *  (1<<2)  - SyncNext
         *  (1<<31) - Request
         */

        if (!(flags & 1 << 31)) {
            return this._fail("Unexpected fence response");
        }

        // Filter out unsupported flags
        // FIXME: support syncNext
        flags &= 1 << 0 | 1 << 1;

        // BlockBefore and BlockAfter are automatically handled by
        // the fact that we process each incoming message
        // synchronuosly.
        RFB.messages.clientFence(this._sock, flags, payload);

        return true;
    },

    _handle_xvp_msg: function () {
        if (this._sock.rQwait("XVP version and message", 3, 1)) {
            return false;
        }
        this._sock.rQskip8(); // Padding
        var xvp_ver = this._sock.rQshift8();
        var xvp_msg = this._sock.rQshift8();

        switch (xvp_msg) {
            case 0:
                // XVP_FAIL
                Log.Error("XVP Operation Failed");
                break;
            case 1:
                // XVP_INIT
                this._rfb_xvp_ver = xvp_ver;
                Log.Info("XVP extensions enabled (version " + this._rfb_xvp_ver + ")");
                this._setCapability("power", true);
                break;
            default:
                this._fail("Illegal server XVP message (msg: " + xvp_msg + ")");
                break;
        }

        return true;
    },

    _normal_msg: function () {
        var msg_type;

        if (this._FBU.rects > 0) {
            msg_type = 0;
        } else {
            msg_type = this._sock.rQshift8();
        }

        switch (msg_type) {
            case 0:
                // FramebufferUpdate
                var ret = this._framebufferUpdate();
                if (ret && !this._enabledContinuousUpdates) {
                    RFB.messages.fbUpdateRequest(this._sock, true, 0, 0, this._fb_width, this._fb_height);
                }
                return ret;

            case 1:
                // SetColorMapEntries
                return this._handle_set_colour_map_msg();

            case 2:
                // Bell
                Log.Debug("Bell");
                var event = new CustomEvent("bell", { detail: {} });
                this.dispatchEvent(event);
                return true;

            case 3:
                // ServerCutText
                return this._handle_server_cut_text();

            case 150:
                // EndOfContinuousUpdates
                var first = !this._supportsContinuousUpdates;
                this._supportsContinuousUpdates = true;
                this._enabledContinuousUpdates = false;
                if (first) {
                    this._enabledContinuousUpdates = true;
                    this._updateContinuousUpdates();
                    Log.Info("Enabling continuous updates.");
                } else {
                    // FIXME: We need to send a framebufferupdaterequest here
                    // if we add support for turning off continuous updates
                }
                return true;

            case 248:
                // ServerFence
                return this._handle_server_fence_msg();

            case 250:
                // XVP
                return this._handle_xvp_msg();

            default:
                this._fail("Unexpected server message (type " + msg_type + ")");
                Log.Debug("sock.rQslice(0, 30): " + this._sock.rQslice(0, 30));
                return true;
        }
    },

    _onFlush: function () {
        this._flushing = false;
        // Resume processing
        if (this._sock.rQlen() > 0) {
            this._handle_message();
        }
    },

    _framebufferUpdate: function () {
        var ret = true;
        var now;

        if (this._FBU.rects === 0) {
            if (this._sock.rQwait("FBU header", 3, 1)) {
                return false;
            }
            this._sock.rQskip8(); // Padding
            this._FBU.rects = this._sock.rQshift16();
            this._FBU.bytes = 0;
            this._timing.cur_fbu = 0;
            if (this._timing.fbu_rt_start > 0) {
                now = new Date().getTime();
                Log.Info("First FBU latency: " + (now - this._timing.fbu_rt_start));
            }

            // Make sure the previous frame is fully rendered first
            // to avoid building up an excessive queue
            if (this._display.pending()) {
                this._flushing = true;
                this._display.flush();
                return false;
            }
        }

        while (this._FBU.rects > 0) {
            if (this._rfb_connection_state !== 'connected') {
                return false;
            }

            if (this._sock.rQwait("FBU", this._FBU.bytes)) {
                return false;
            }
            if (this._FBU.bytes === 0) {
                if (this._sock.rQwait("rect header", 12)) {
                    return false;
                }
                /* New FramebufferUpdate */

                var hdr = this._sock.rQshiftBytes(12);
                this._FBU.x = (hdr[0] << 8) + hdr[1];
                this._FBU.y = (hdr[2] << 8) + hdr[3];
                this._FBU.width = (hdr[4] << 8) + hdr[5];
                this._FBU.height = (hdr[6] << 8) + hdr[7];
                this._FBU.encoding = parseInt((hdr[8] << 24) + (hdr[9] << 16) + (hdr[10] << 8) + hdr[11], 10);

                if (!this._encHandlers[this._FBU.encoding]) {
                    this._fail("Unsupported encoding (encoding: " + this._FBU.encoding + ")");
                    return false;
                }
            }

            this._timing.last_fbu = new Date().getTime();

            ret = this._encHandlers[this._FBU.encoding]();

            now = new Date().getTime();
            this._timing.cur_fbu += now - this._timing.last_fbu;

            if (ret) {
                if (!(this._FBU.encoding in this._encStats)) {
                    this._encStats[this._FBU.encoding] = [0, 0];
                }
                this._encStats[this._FBU.encoding][0]++;
                this._encStats[this._FBU.encoding][1]++;
                this._timing.pixels += this._FBU.width * this._FBU.height;
            }

            if (this._timing.pixels >= this._fb_width * this._fb_height) {
                if (this._FBU.width === this._fb_width && this._FBU.height === this._fb_height || this._timing.fbu_rt_start > 0) {
                    this._timing.full_fbu_total += this._timing.cur_fbu;
                    this._timing.full_fbu_cnt++;
                    Log.Info("Timing of full FBU, curr: " + this._timing.cur_fbu + ", total: " + this._timing.full_fbu_total + ", cnt: " + this._timing.full_fbu_cnt + ", avg: " + this._timing.full_fbu_total / this._timing.full_fbu_cnt);
                }

                if (this._timing.fbu_rt_start > 0) {
                    var fbu_rt_diff = now - this._timing.fbu_rt_start;
                    this._timing.fbu_rt_total += fbu_rt_diff;
                    this._timing.fbu_rt_cnt++;
                    Log.Info("full FBU round-trip, cur: " + fbu_rt_diff + ", total: " + this._timing.fbu_rt_total + ", cnt: " + this._timing.fbu_rt_cnt + ", avg: " + this._timing.fbu_rt_total / this._timing.fbu_rt_cnt);
                    this._timing.fbu_rt_start = 0;
                }
            }

            if (!ret) {
                return ret;
            } // need more data
        }

        this._display.flip();

        return true; // We finished this FBU
    },

    _updateContinuousUpdates: function () {
        if (!this._enabledContinuousUpdates) {
            return;
        }

        RFB.messages.enableContinuousUpdates(this._sock, true, 0, 0, this._fb_width, this._fb_height);
    },

    _resize: function (width, height) {
        this._fb_width = width;
        this._fb_height = height;

        this._destBuff = new Uint8Array(this._fb_width * this._fb_height * 4);

        this._display.resize(this._fb_width, this._fb_height);

        // Adjust the visible viewport based on the new dimensions
        this._updateClip();
        this._updateScale();

        this._timing.fbu_rt_start = new Date().getTime();
        this._updateContinuousUpdates();
    },

    _xvpOp: function (ver, op) {
        if (this._rfb_xvp_ver < ver) {
            return;
        }
        Log.Info("Sending XVP operation " + op + " (version " + ver + ")");
        RFB.messages.xvpOp(this._sock, ver, op);
    }
};

Object.assign(RFB.prototype, _eventtarget2.default);

// Class Methods
RFB.messages = {
    keyEvent: function (sock, keysym, down) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 4; // msg-type
        buff[offset + 1] = down;

        buff[offset + 2] = 0;
        buff[offset + 3] = 0;

        buff[offset + 4] = keysym >> 24;
        buff[offset + 5] = keysym >> 16;
        buff[offset + 6] = keysym >> 8;
        buff[offset + 7] = keysym;

        sock._sQlen += 8;
        sock.flush();
    },

    QEMUExtendedKeyEvent: function (sock, keysym, down, keycode) {
        function getRFBkeycode(xt_scancode) {
            var upperByte = keycode >> 8;
            var lowerByte = keycode & 0x00ff;
            if (upperByte === 0xe0 && lowerByte < 0x7f) {
                lowerByte = lowerByte | 0x80;
                return lowerByte;
            }
            return xt_scancode;
        }

        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 255; // msg-type
        buff[offset + 1] = 0; // sub msg-type

        buff[offset + 2] = down >> 8;
        buff[offset + 3] = down;

        buff[offset + 4] = keysym >> 24;
        buff[offset + 5] = keysym >> 16;
        buff[offset + 6] = keysym >> 8;
        buff[offset + 7] = keysym;

        var RFBkeycode = getRFBkeycode(keycode);

        buff[offset + 8] = RFBkeycode >> 24;
        buff[offset + 9] = RFBkeycode >> 16;
        buff[offset + 10] = RFBkeycode >> 8;
        buff[offset + 11] = RFBkeycode;

        sock._sQlen += 12;
        sock.flush();
    },

    pointerEvent: function (sock, x, y, mask) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 5; // msg-type

        buff[offset + 1] = mask;

        buff[offset + 2] = x >> 8;
        buff[offset + 3] = x;

        buff[offset + 4] = y >> 8;
        buff[offset + 5] = y;

        sock._sQlen += 6;
        sock.flush();
    },

    // TODO(directxman12): make this unicode compatible?
    clientCutText: function (sock, text) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 6; // msg-type

        buff[offset + 1] = 0; // padding
        buff[offset + 2] = 0; // padding
        buff[offset + 3] = 0; // padding

        var n = text.length;

        buff[offset + 4] = n >> 24;
        buff[offset + 5] = n >> 16;
        buff[offset + 6] = n >> 8;
        buff[offset + 7] = n;

        for (var i = 0; i < n; i++) {
            buff[offset + 8 + i] = text.charCodeAt(i);
        }

        sock._sQlen += 8 + n;
        sock.flush();
    },

    setDesktopSize: function (sock, width, height, id, flags) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 251; // msg-type
        buff[offset + 1] = 0; // padding
        buff[offset + 2] = width >> 8; // width
        buff[offset + 3] = width;
        buff[offset + 4] = height >> 8; // height
        buff[offset + 5] = height;

        buff[offset + 6] = 1; // number-of-screens
        buff[offset + 7] = 0; // padding

        // screen array
        buff[offset + 8] = id >> 24; // id
        buff[offset + 9] = id >> 16;
        buff[offset + 10] = id >> 8;
        buff[offset + 11] = id;
        buff[offset + 12] = 0; // x-position
        buff[offset + 13] = 0;
        buff[offset + 14] = 0; // y-position
        buff[offset + 15] = 0;
        buff[offset + 16] = width >> 8; // width
        buff[offset + 17] = width;
        buff[offset + 18] = height >> 8; // height
        buff[offset + 19] = height;
        buff[offset + 20] = flags >> 24; // flags
        buff[offset + 21] = flags >> 16;
        buff[offset + 22] = flags >> 8;
        buff[offset + 23] = flags;

        sock._sQlen += 24;
        sock.flush();
    },

    clientFence: function (sock, flags, payload) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 248; // msg-type

        buff[offset + 1] = 0; // padding
        buff[offset + 2] = 0; // padding
        buff[offset + 3] = 0; // padding

        buff[offset + 4] = flags >> 24; // flags
        buff[offset + 5] = flags >> 16;
        buff[offset + 6] = flags >> 8;
        buff[offset + 7] = flags;

        var n = payload.length;

        buff[offset + 8] = n; // length

        for (var i = 0; i < n; i++) {
            buff[offset + 9 + i] = payload.charCodeAt(i);
        }

        sock._sQlen += 9 + n;
        sock.flush();
    },

    enableContinuousUpdates: function (sock, enable, x, y, width, height) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 150; // msg-type
        buff[offset + 1] = enable; // enable-flag

        buff[offset + 2] = x >> 8; // x
        buff[offset + 3] = x;
        buff[offset + 4] = y >> 8; // y
        buff[offset + 5] = y;
        buff[offset + 6] = width >> 8; // width
        buff[offset + 7] = width;
        buff[offset + 8] = height >> 8; // height
        buff[offset + 9] = height;

        sock._sQlen += 10;
        sock.flush();
    },

    pixelFormat: function (sock, depth, true_color) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        var bpp, bits;

        if (depth > 16) {
            bpp = 32;
        } else if (depth > 8) {
            bpp = 16;
        } else {
            bpp = 8;
        }

        bits = Math.floor(depth / 3);

        buff[offset] = 0; // msg-type

        buff[offset + 1] = 0; // padding
        buff[offset + 2] = 0; // padding
        buff[offset + 3] = 0; // padding

        buff[offset + 4] = bpp; // bits-per-pixel
        buff[offset + 5] = depth; // depth
        buff[offset + 6] = 0; // little-endian
        buff[offset + 7] = true_color ? 1 : 0; // true-color

        buff[offset + 8] = 0; // red-max
        buff[offset + 9] = (1 << bits) - 1; // red-max

        buff[offset + 10] = 0; // green-max
        buff[offset + 11] = (1 << bits) - 1; // green-max

        buff[offset + 12] = 0; // blue-max
        buff[offset + 13] = (1 << bits) - 1; // blue-max

        buff[offset + 14] = bits * 2; // red-shift
        buff[offset + 15] = bits * 1; // green-shift
        buff[offset + 16] = bits * 0; // blue-shift

        buff[offset + 17] = 0; // padding
        buff[offset + 18] = 0; // padding
        buff[offset + 19] = 0; // padding

        sock._sQlen += 20;
        sock.flush();
    },

    clientEncodings: function (sock, encodings) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 2; // msg-type
        buff[offset + 1] = 0; // padding

        buff[offset + 2] = encodings.length >> 8;
        buff[offset + 3] = encodings.length;

        var i,
            j = offset + 4;
        for (i = 0; i < encodings.length; i++) {
            var enc = encodings[i];
            buff[j] = enc >> 24;
            buff[j + 1] = enc >> 16;
            buff[j + 2] = enc >> 8;
            buff[j + 3] = enc;

            j += 4;
        }

        sock._sQlen += j - offset;
        sock.flush();
    },

    fbUpdateRequest: function (sock, incremental, x, y, w, h) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        if (typeof x === "undefined") {
            x = 0;
        }
        if (typeof y === "undefined") {
            y = 0;
        }

        buff[offset] = 3; // msg-type
        buff[offset + 1] = incremental ? 1 : 0;

        buff[offset + 2] = x >> 8 & 0xFF;
        buff[offset + 3] = x & 0xFF;

        buff[offset + 4] = y >> 8 & 0xFF;
        buff[offset + 5] = y & 0xFF;

        buff[offset + 6] = w >> 8 & 0xFF;
        buff[offset + 7] = w & 0xFF;

        buff[offset + 8] = h >> 8 & 0xFF;
        buff[offset + 9] = h & 0xFF;

        sock._sQlen += 10;
        sock.flush();
    },

    xvpOp: function (sock, ver, op) {
        var buff = sock._sQ;
        var offset = sock._sQlen;

        buff[offset] = 250; // msg-type
        buff[offset + 1] = 0; // padding

        buff[offset + 2] = ver;
        buff[offset + 3] = op;

        sock._sQlen += 4;
        sock.flush();
    }
};

RFB.genDES = function (password, challenge) {
    var passwd = [];
    for (var i = 0; i < password.length; i++) {
        passwd.push(password.charCodeAt(i));
    }
    return new _des2.default(passwd).encrypt(challenge);
};

RFB.encodingHandlers = {
    RAW: function () {
        if (this._FBU.lines === 0) {
            this._FBU.lines = this._FBU.height;
        }

        var pixelSize = this._fb_depth == 8 ? 1 : 4;
        this._FBU.bytes = this._FBU.width * pixelSize; // at least a line
        if (this._sock.rQwait("RAW", this._FBU.bytes)) {
            return false;
        }
        var cur_y = this._FBU.y + (this._FBU.height - this._FBU.lines);
        var curr_height = Math.min(this._FBU.lines, Math.floor(this._sock.rQlen() / (this._FBU.width * pixelSize)));
        var data = this._sock.get_rQ();
        var index = this._sock.get_rQi();
        if (this._fb_depth == 8) {
            var pixels = this._FBU.width * curr_height;
            var newdata = new Uint8Array(pixels * 4);
            var i;
            for (i = 0; i < pixels; i++) {
                newdata[i * 4 + 0] = (data[index + i] >> 0 & 0x3) * 255 / 3;
                newdata[i * 4 + 1] = (data[index + i] >> 2 & 0x3) * 255 / 3;
                newdata[i * 4 + 2] = (data[index + i] >> 4 & 0x3) * 255 / 3;
                newdata[i * 4 + 4] = 0;
            }
            data = newdata;
            index = 0;
        }
        this._display.blitImage(this._FBU.x, cur_y, this._FBU.width, curr_height, data, index);
        this._sock.rQskipBytes(this._FBU.width * curr_height * pixelSize);
        this._FBU.lines -= curr_height;

        if (this._FBU.lines > 0) {
            this._FBU.bytes = this._FBU.width * pixelSize; // At least another line
        } else {
            this._FBU.rects--;
            this._FBU.bytes = 0;
        }

        return true;
    },

    COPYRECT: function () {
        this._FBU.bytes = 4;
        if (this._sock.rQwait("COPYRECT", 4)) {
            return false;
        }
        this._display.copyImage(this._sock.rQshift16(), this._sock.rQshift16(), this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height);

        this._FBU.rects--;
        this._FBU.bytes = 0;
        return true;
    },

    RRE: function () {
        var color;
        if (this._FBU.subrects === 0) {
            this._FBU.bytes = 4 + 4;
            if (this._sock.rQwait("RRE", 4 + 4)) {
                return false;
            }
            this._FBU.subrects = this._sock.rQshift32();
            color = this._sock.rQshiftBytes(4); // Background
            this._display.fillRect(this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height, color);
        }

        while (this._FBU.subrects > 0 && this._sock.rQlen() >= 4 + 8) {
            color = this._sock.rQshiftBytes(4);
            var x = this._sock.rQshift16();
            var y = this._sock.rQshift16();
            var width = this._sock.rQshift16();
            var height = this._sock.rQshift16();
            this._display.fillRect(this._FBU.x + x, this._FBU.y + y, width, height, color);
            this._FBU.subrects--;
        }

        if (this._FBU.subrects > 0) {
            var chunk = Math.min(this._rre_chunk_sz, this._FBU.subrects);
            this._FBU.bytes = (4 + 8) * chunk;
        } else {
            this._FBU.rects--;
            this._FBU.bytes = 0;
        }

        return true;
    },

    HEXTILE: function () {
        var rQ = this._sock.get_rQ();
        var rQi = this._sock.get_rQi();

        if (this._FBU.tiles === 0) {
            this._FBU.tiles_x = Math.ceil(this._FBU.width / 16);
            this._FBU.tiles_y = Math.ceil(this._FBU.height / 16);
            this._FBU.total_tiles = this._FBU.tiles_x * this._FBU.tiles_y;
            this._FBU.tiles = this._FBU.total_tiles;
        }

        while (this._FBU.tiles > 0) {
            this._FBU.bytes = 1;
            if (this._sock.rQwait("HEXTILE subencoding", this._FBU.bytes)) {
                return false;
            }
            var subencoding = rQ[rQi]; // Peek
            if (subencoding > 30) {
                // Raw
                this._fail("Illegal hextile subencoding (subencoding: " + subencoding + ")");
                return false;
            }

            var subrects = 0;
            var curr_tile = this._FBU.total_tiles - this._FBU.tiles;
            var tile_x = curr_tile % this._FBU.tiles_x;
            var tile_y = Math.floor(curr_tile / this._FBU.tiles_x);
            var x = this._FBU.x + tile_x * 16;
            var y = this._FBU.y + tile_y * 16;
            var w = Math.min(16, this._FBU.x + this._FBU.width - x);
            var h = Math.min(16, this._FBU.y + this._FBU.height - y);

            // Figure out how much we are expecting
            if (subencoding & 0x01) {
                // Raw
                this._FBU.bytes += w * h * 4;
            } else {
                if (subencoding & 0x02) {
                    // Background
                    this._FBU.bytes += 4;
                }
                if (subencoding & 0x04) {
                    // Foreground
                    this._FBU.bytes += 4;
                }
                if (subencoding & 0x08) {
                    // AnySubrects
                    this._FBU.bytes++; // Since we aren't shifting it off
                    if (this._sock.rQwait("hextile subrects header", this._FBU.bytes)) {
                        return false;
                    }
                    subrects = rQ[rQi + this._FBU.bytes - 1]; // Peek
                    if (subencoding & 0x10) {
                        // SubrectsColoured
                        this._FBU.bytes += subrects * (4 + 2);
                    } else {
                        this._FBU.bytes += subrects * 2;
                    }
                }
            }

            if (this._sock.rQwait("hextile", this._FBU.bytes)) {
                return false;
            }

            // We know the encoding and have a whole tile
            this._FBU.subencoding = rQ[rQi];
            rQi++;
            if (this._FBU.subencoding === 0) {
                if (this._FBU.lastsubencoding & 0x01) {
                    // Weird: ignore blanks are RAW
                    Log.Debug("     Ignoring blank after RAW");
                } else {
                    this._display.fillRect(x, y, w, h, this._FBU.background);
                }
            } else if (this._FBU.subencoding & 0x01) {
                // Raw
                this._display.blitImage(x, y, w, h, rQ, rQi);
                rQi += this._FBU.bytes - 1;
            } else {
                if (this._FBU.subencoding & 0x02) {
                    // Background
                    this._FBU.background = [rQ[rQi], rQ[rQi + 1], rQ[rQi + 2], rQ[rQi + 3]];
                    rQi += 4;
                }
                if (this._FBU.subencoding & 0x04) {
                    // Foreground
                    this._FBU.foreground = [rQ[rQi], rQ[rQi + 1], rQ[rQi + 2], rQ[rQi + 3]];
                    rQi += 4;
                }

                this._display.startTile(x, y, w, h, this._FBU.background);
                if (this._FBU.subencoding & 0x08) {
                    // AnySubrects
                    subrects = rQ[rQi];
                    rQi++;

                    for (var s = 0; s < subrects; s++) {
                        var color;
                        if (this._FBU.subencoding & 0x10) {
                            // SubrectsColoured
                            color = [rQ[rQi], rQ[rQi + 1], rQ[rQi + 2], rQ[rQi + 3]];
                            rQi += 4;
                        } else {
                            color = this._FBU.foreground;
                        }
                        var xy = rQ[rQi];
                        rQi++;
                        var sx = xy >> 4;
                        var sy = xy & 0x0f;

                        var wh = rQ[rQi];
                        rQi++;
                        var sw = (wh >> 4) + 1;
                        var sh = (wh & 0x0f) + 1;

                        this._display.subTile(sx, sy, sw, sh, color);
                    }
                }
                this._display.finishTile();
            }
            this._sock.set_rQi(rQi);
            this._FBU.lastsubencoding = this._FBU.subencoding;
            this._FBU.bytes = 0;
            this._FBU.tiles--;
        }

        if (this._FBU.tiles === 0) {
            this._FBU.rects--;
        }

        return true;
    },

    TIGHT: function () {
        this._FBU.bytes = 1; // compression-control byte
        if (this._sock.rQwait("TIGHT compression-control", this._FBU.bytes)) {
            return false;
        }

        var checksum = function (data) {
            var sum = 0;
            for (var i = 0; i < data.length; i++) {
                sum += data[i];
                if (sum > 65536) sum -= 65536;
            }
            return sum;
        };

        var resetStreams = 0;
        var streamId = -1;
        var decompress = function (data, expected) {
            for (var i = 0; i < 4; i++) {
                if (resetStreams >> i & 1) {
                    this._FBU.zlibs[i].reset();
                    Log.Info("Reset zlib stream " + i);
                }
            }

            //var uncompressed = this._FBU.zlibs[streamId].uncompress(data, 0);
            var uncompressed = this._FBU.zlibs[streamId].inflate(data, true, expected);
            /*if (uncompressed.status !== 0) {
                Log.Error("Invalid data in zlib stream");
            }*/

            //return uncompressed.data;
            return uncompressed;
        }.bind(this);

        var indexedToRGBX2Color = function (data, palette, width, height) {
            // Convert indexed (palette based) image data to RGB
            // TODO: reduce number of calculations inside loop
            var dest = this._destBuff;
            var w = Math.floor((width + 7) / 8);
            var w1 = Math.floor(width / 8);

            /*for (var y = 0; y < height; y++) {
                var b, x, dp, sp;
                var yoffset = y * width;
                var ybitoffset = y * w;
                var xoffset, targetbyte;
                for (x = 0; x < w1; x++) {
                    xoffset = yoffset + x * 8;
                    targetbyte = data[ybitoffset + x];
                    for (b = 7; b >= 0; b--) {
                        dp = (xoffset + 7 - b) * 3;
                        sp = (targetbyte >> b & 1) * 3;
                        dest[dp] = palette[sp];
                        dest[dp + 1] = palette[sp + 1];
                        dest[dp + 2] = palette[sp + 2];
                    }
                }
                 xoffset = yoffset + x * 8;
                targetbyte = data[ybitoffset + x];
                for (b = 7; b >= 8 - width % 8; b--) {
                    dp = (xoffset + 7 - b) * 3;
                    sp = (targetbyte >> b & 1) * 3;
                    dest[dp] = palette[sp];
                    dest[dp + 1] = palette[sp + 1];
                    dest[dp + 2] = palette[sp + 2];
                }
            }*/

            for (var y = 0; y < height; y++) {
                var b, x, dp, sp;
                for (x = 0; x < w1; x++) {
                    for (b = 7; b >= 0; b--) {
                        dp = (y * width + x * 8 + 7 - b) * 4;
                        sp = (data[y * w + x] >> b & 1) * 3;
                        dest[dp] = palette[sp];
                        dest[dp + 1] = palette[sp + 1];
                        dest[dp + 2] = palette[sp + 2];
                        dest[dp + 3] = 255;
                    }
                }

                for (b = 7; b >= 8 - width % 8; b--) {
                    dp = (y * width + x * 8 + 7 - b) * 4;
                    sp = (data[y * w + x] >> b & 1) * 3;
                    dest[dp] = palette[sp];
                    dest[dp + 1] = palette[sp + 1];
                    dest[dp + 2] = palette[sp + 2];
                    dest[dp + 3] = 255;
                }
            }

            return dest;
        }.bind(this);

        var indexedToRGBX = function (data, palette, width, height) {
            // Convert indexed (palette based) image data to RGB
            var dest = this._destBuff;
            var total = width * height * 4;
            for (var i = 0, j = 0; i < total; i += 4, j++) {
                var sp = data[j] * 3;
                dest[i] = palette[sp];
                dest[i + 1] = palette[sp + 1];
                dest[i + 2] = palette[sp + 2];
                dest[i + 3] = 255;
            }

            return dest;
        }.bind(this);

        var rQi = this._sock.get_rQi();
        var rQ = this._sock.rQwhole();
        var cmode, data;
        var cl_header, cl_data;

        var handlePalette = function () {
            var numColors = rQ[rQi + 2] + 1;
            var paletteSize = numColors * 3;
            this._FBU.bytes += paletteSize;
            if (this._sock.rQwait("TIGHT palette " + cmode, this._FBU.bytes)) {
                return false;
            }

            var bpp = numColors <= 2 ? 1 : 8;
            var rowSize = Math.floor((this._FBU.width * bpp + 7) / 8);
            var raw = false;
            if (rowSize * this._FBU.height < 12) {
                raw = true;
                cl_header = 0;
                cl_data = rowSize * this._FBU.height;
                //clength = [0, rowSize * this._FBU.height];
            } else {
                // begin inline getTightCLength (returning two-item arrays is bad for performance with GC)
                var cl_offset = rQi + 3 + paletteSize;
                cl_header = 1;
                cl_data = 0;
                cl_data += rQ[cl_offset] & 0x7f;
                if (rQ[cl_offset] & 0x80) {
                    cl_header++;
                    cl_data += (rQ[cl_offset + 1] & 0x7f) << 7;
                    if (rQ[cl_offset + 1] & 0x80) {
                        cl_header++;
                        cl_data += rQ[cl_offset + 2] << 14;
                    }
                }
                // end inline getTightCLength
            }

            this._FBU.bytes += cl_header + cl_data;
            if (this._sock.rQwait("TIGHT " + cmode, this._FBU.bytes)) {
                return false;
            }

            // Shift ctl, filter id, num colors, palette entries, and clength off
            this._sock.rQskipBytes(3);
            //var palette = this._sock.rQshiftBytes(paletteSize);
            this._sock.rQshiftTo(this._paletteBuff, paletteSize);
            this._sock.rQskipBytes(cl_header);

            if (raw) {
                data = this._sock.rQshiftBytes(cl_data);
            } else {
                data = decompress(this._sock.rQshiftBytes(cl_data), rowSize * this._FBU.height);
            }

            // Convert indexed (palette based) image data to RGB
            var rgbx;
            if (numColors == 2) {
                rgbx = indexedToRGBX2Color(data, this._paletteBuff, this._FBU.width, this._FBU.height);
                this._display.blitRgbxImage(this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height, rgbx, 0, false);
            } else {
                rgbx = indexedToRGBX(data, this._paletteBuff, this._FBU.width, this._FBU.height);
                this._display.blitRgbxImage(this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height, rgbx, 0, false);
            }

            return true;
        }.bind(this);

        var handleCopy = function () {
            var raw = false;
            var uncompressedSize = this._FBU.width * this._FBU.height * 3;
            if (uncompressedSize < 12) {
                raw = true;
                cl_header = 0;
                cl_data = uncompressedSize;
            } else {
                // begin inline getTightCLength (returning two-item arrays is for peformance with GC)
                var cl_offset = rQi + 1;
                cl_header = 1;
                cl_data = 0;
                cl_data += rQ[cl_offset] & 0x7f;
                if (rQ[cl_offset] & 0x80) {
                    cl_header++;
                    cl_data += (rQ[cl_offset + 1] & 0x7f) << 7;
                    if (rQ[cl_offset + 1] & 0x80) {
                        cl_header++;
                        cl_data += rQ[cl_offset + 2] << 14;
                    }
                }
                // end inline getTightCLength
            }
            this._FBU.bytes = 1 + cl_header + cl_data;
            if (this._sock.rQwait("TIGHT " + cmode, this._FBU.bytes)) {
                return false;
            }

            // Shift ctl, clength off
            this._sock.rQshiftBytes(1 + cl_header);

            if (raw) {
                data = this._sock.rQshiftBytes(cl_data);
            } else {
                data = decompress(this._sock.rQshiftBytes(cl_data), uncompressedSize);
            }

            this._display.blitRgbImage(this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height, data, 0, false);

            return true;
        }.bind(this);

        var ctl = this._sock.rQpeek8();

        // Keep tight reset bits
        resetStreams = ctl & 0xF;

        // Figure out filter
        ctl = ctl >> 4;
        streamId = ctl & 0x3;

        if (ctl === 0x08) cmode = "fill";else if (ctl === 0x09) cmode = "jpeg";else if (ctl === 0x0A) cmode = "png";else if (ctl & 0x04) cmode = "filter";else if (ctl < 0x04) cmode = "copy";else return this._fail("Illegal tight compression received (ctl: " + ctl + ")");

        switch (cmode) {
            // fill use depth because TPIXELs drop the padding byte
            case "fill":
                // TPIXEL
                this._FBU.bytes += 3;
                break;
            case "jpeg":
                // max clength
                this._FBU.bytes += 3;
                break;
            case "png":
                // max clength
                this._FBU.bytes += 3;
                break;
            case "filter":
                // filter id + num colors if palette
                this._FBU.bytes += 2;
                break;
            case "copy":
                break;
        }

        if (this._sock.rQwait("TIGHT " + cmode, this._FBU.bytes)) {
            return false;
        }

        // Determine FBU.bytes
        switch (cmode) {
            case "fill":
                // skip ctl byte
                this._display.fillRect(this._FBU.x, this._FBU.y, this._FBU.width, this._FBU.height, [rQ[rQi + 3], rQ[rQi + 2], rQ[rQi + 1]], false);
                this._sock.rQskipBytes(4);
                break;
            case "png":
            case "jpeg":
                // begin inline getTightCLength (returning two-item arrays is for peformance with GC)
                var cl_offset = rQi + 1;
                cl_header = 1;
                cl_data = 0;
                cl_data += rQ[cl_offset] & 0x7f;
                if (rQ[cl_offset] & 0x80) {
                    cl_header++;
                    cl_data += (rQ[cl_offset + 1] & 0x7f) << 7;
                    if (rQ[cl_offset + 1] & 0x80) {
                        cl_header++;
                        cl_data += rQ[cl_offset + 2] << 14;
                    }
                }
                // end inline getTightCLength
                this._FBU.bytes = 1 + cl_header + cl_data; // ctl + clength size + jpeg-data
                if (this._sock.rQwait("TIGHT " + cmode, this._FBU.bytes)) {
                    return false;
                }

                // We have everything, render it
                this._sock.rQskipBytes(1 + cl_header); // shift off clt + compact length
                data = this._sock.rQshiftBytes(cl_data);
                this._display.imageRect(this._FBU.x, this._FBU.y, "image/" + cmode, data);
                break;
            case "filter":
                var filterId = rQ[rQi + 1];
                if (filterId === 1) {
                    if (!handlePalette()) {
                        return false;
                    }
                } else {
                    // Filter 0, Copy could be valid here, but servers don't send it as an explicit filter
                    // Filter 2, Gradient is valid but not use if jpeg is enabled
                    this._fail("Unsupported tight subencoding received " + "(filter: " + filterId + ")");
                }
                break;
            case "copy":
                if (!handleCopy()) {
                    return false;
                }
                break;
        }

        this._FBU.bytes = 0;
        this._FBU.rects--;

        return true;
    },

    last_rect: function () {
        this._FBU.rects = 0;
        return true;
    },

    ExtendedDesktopSize: function () {
        this._FBU.bytes = 1;
        if (this._sock.rQwait("ExtendedDesktopSize", this._FBU.bytes)) {
            return false;
        }

        var firstUpdate = !this._supportsSetDesktopSize;
        this._supportsSetDesktopSize = true;

        // Normally we only apply the current resize mode after a
        // window resize event. However there is no such trigger on the
        // initial connect. And we don't know if the server supports
        // resizing until we've gotten here.
        if (firstUpdate) {
            this._requestRemoteResize();
        }

        var number_of_screens = this._sock.rQpeek8();

        this._FBU.bytes = 4 + number_of_screens * 16;
        if (this._sock.rQwait("ExtendedDesktopSize", this._FBU.bytes)) {
            return false;
        }

        this._sock.rQskipBytes(1); // number-of-screens
        this._sock.rQskipBytes(3); // padding

        for (var i = 0; i < number_of_screens; i += 1) {
            // Save the id and flags of the first screen
            if (i === 0) {
                this._screen_id = this._sock.rQshiftBytes(4); // id
                this._sock.rQskipBytes(2); // x-position
                this._sock.rQskipBytes(2); // y-position
                this._sock.rQskipBytes(2); // width
                this._sock.rQskipBytes(2); // height
                this._screen_flags = this._sock.rQshiftBytes(4); // flags
            } else {
                this._sock.rQskipBytes(16);
            }
        }

        /*
         * The x-position indicates the reason for the change:
         *
         *  0 - server resized on its own
         *  1 - this client requested the resize
         *  2 - another client requested the resize
         */

        // We need to handle errors when we requested the resize.
        if (this._FBU.x === 1 && this._FBU.y !== 0) {
            var msg = "";
            // The y-position indicates the status code from the server
            switch (this._FBU.y) {
                case 1:
                    msg = "Resize is administratively prohibited";
                    break;
                case 2:
                    msg = "Out of resources";
                    break;
                case 3:
                    msg = "Invalid screen layout";
                    break;
                default:
                    msg = "Unknown reason";
                    break;
            }
            Log.Warn("Server did not accept the resize request: " + msg);
        } else {
            this._resize(this._FBU.width, this._FBU.height);
        }

        this._FBU.bytes = 0;
        this._FBU.rects -= 1;
        return true;
    },

    DesktopSize: function () {
        this._resize(this._FBU.width, this._FBU.height);
        this._FBU.bytes = 0;
        this._FBU.rects -= 1;
        return true;
    },

    Cursor: function () {
        Log.Debug(">> set_cursor");
        var x = this._FBU.x; // hotspot-x
        var y = this._FBU.y; // hotspot-y
        var w = this._FBU.width;
        var h = this._FBU.height;

        var pixelslength = w * h * 4;
        var masklength = Math.floor((w + 7) / 8) * h;

        this._FBU.bytes = pixelslength + masklength;
        if (this._sock.rQwait("cursor encoding", this._FBU.bytes)) {
            return false;
        }

        this._display.changeCursor(this._sock.rQshiftBytes(pixelslength), this._sock.rQshiftBytes(masklength), x, y, w, h);

        this._FBU.bytes = 0;
        this._FBU.rects--;

        Log.Debug("<< set_cursor");
        return true;
    },

    QEMUExtendedKeyEvent: function () {
        this._FBU.rects--;

        // Old Safari doesn't support creating keyboard events
        try {
            var keyboardEvent = document.createEvent("keyboardEvent");
            if (keyboardEvent.code !== undefined) {
                this._qemuExtKeyEventSupported = true;
            }
        } catch (err) {}
    }
};
},{"./des.js":5,"./display.js":6,"./encodings.js":7,"./inflator.js":8,"./input/keyboard.js":11,"./input/keysym.js":12,"./input/mouse.js":14,"./input/xtscancodes.js":17,"./util/browser.js":19,"./util/eventtarget.js":21,"./util/logging.js":22,"./util/polyfill.js":23,"./util/strings.js":24,"./websock.js":25}],19:[function(require,module,exports){
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
},{"./logging.js":22}],20:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.getPointerEvent = getPointerEvent;
exports.stopEvent = stopEvent;
exports.setCapture = setCapture;
exports.releaseCapture = releaseCapture;
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

/*
 * Cross-browser event and position routines
 */

function getPointerEvent(e) {
    return e.changedTouches ? e.changedTouches[0] : e.touches ? e.touches[0] : e;
};

function stopEvent(e) {
    e.stopPropagation();
    e.preventDefault();
};

// Emulate Element.setCapture() when not supported
var _captureRecursion = false;
var _captureElem = null;
function _captureProxy(e) {
    // Recursion protection as we'll see our own event
    if (_captureRecursion) return;

    // Clone the event as we cannot dispatch an already dispatched event
    var newEv = new e.constructor(e.type, e);

    _captureRecursion = true;
    _captureElem.dispatchEvent(newEv);
    _captureRecursion = false;

    // Avoid double events
    e.stopPropagation();

    // Respect the wishes of the redirected event handlers
    if (newEv.defaultPrevented) {
        e.preventDefault();
    }

    // Implicitly release the capture on button release
    if (e.type === "mouseup") {
        releaseCapture();
    }
};

// Follow cursor style of target element
function _captureElemChanged() {
    var captureElem = document.getElementById("noVNC_mouse_capture_elem");
    captureElem.style.cursor = window.getComputedStyle(_captureElem).cursor;
};
var _captureObserver = new MutationObserver(_captureElemChanged);

var _captureIndex = 0;

function setCapture(elem) {
    if (elem.setCapture) {

        elem.setCapture();

        // IE releases capture on 'click' events which might not trigger
        elem.addEventListener('mouseup', releaseCapture);
    } else {
        // Release any existing capture in case this method is
        // called multiple times without coordination
        releaseCapture();

        var captureElem = document.getElementById("noVNC_mouse_capture_elem");

        if (captureElem === null) {
            captureElem = document.createElement("div");
            captureElem.id = "noVNC_mouse_capture_elem";
            captureElem.style.position = "fixed";
            captureElem.style.top = "0px";
            captureElem.style.left = "0px";
            captureElem.style.width = "100%";
            captureElem.style.height = "100%";
            captureElem.style.zIndex = 10000;
            captureElem.style.display = "none";
            document.body.appendChild(captureElem);

            // This is to make sure callers don't get confused by having
            // our blocking element as the target
            captureElem.addEventListener('contextmenu', _captureProxy);

            captureElem.addEventListener('mousemove', _captureProxy);
            captureElem.addEventListener('mouseup', _captureProxy);
        }

        _captureElem = elem;
        _captureIndex++;

        // Track cursor and get initial cursor
        _captureObserver.observe(elem, { attributes: true });
        _captureElemChanged();

        captureElem.style.display = "";

        // We listen to events on window in order to keep tracking if it
        // happens to leave the viewport
        window.addEventListener('mousemove', _captureProxy);
        window.addEventListener('mouseup', _captureProxy);
    }
};

function releaseCapture() {
    if (document.releaseCapture) {

        document.releaseCapture();
    } else {
        if (!_captureElem) {
            return;
        }

        // There might be events already queued, so we need to wait for
        // them to flush. E.g. contextmenu in Microsoft Edge
        window.setTimeout(function (expected) {
            // Only clear it if it's the expected grab (i.e. no one
            // else has initiated a new grab)
            if (_captureIndex === expected) {
                _captureElem = null;
            }
        }, 0, _captureIndex);

        _captureObserver.disconnect();

        var captureElem = document.getElementById("noVNC_mouse_capture_elem");
        captureElem.style.display = "none";

        window.removeEventListener('mousemove', _captureProxy);
        window.removeEventListener('mouseup', _captureProxy);
    }
};
},{}],21:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
   value: true
});
/*
 * noVNC: HTML5 VNC client
 * Copyright 2017 Pierre Ossman for Cendio AB
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

var EventTargetMixin = {
   _listeners: null,

   addEventListener: function (type, callback) {
      if (!this._listeners) {
         this._listeners = new Map();
      }
      if (!this._listeners.has(type)) {
         this._listeners.set(type, new Set());
      }
      this._listeners.get(type).add(callback);
   },

   removeEventListener: function (type, callback) {
      if (!this._listeners || !this._listeners.has(type)) {
         return;
      }
      this._listeners.get(type).delete(callback);
   },

   dispatchEvent: function (event) {
      if (!this._listeners || !this._listeners.has(event.type)) {
         return true;
      }
      this._listeners.get(event.type).forEach(function (callback) {
         callback.call(this, event);
      }, this);
      return !event.defaultPrevented;
   }
};

exports.default = EventTargetMixin;
},{}],22:[function(require,module,exports){
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
},{}],23:[function(require,module,exports){
'use strict';

/*
 * noVNC: HTML5 VNC client
 * Copyright 2017 Pierre Ossman for noVNC
 * Licensed under MPL 2.0 or any later version (see LICENSE.txt)
 */

/* Polyfills to provide new APIs in old browsers */

/* Object.assign() (taken from MDN) */
if (typeof Object.assign != 'function') {
    // Must be writable: true, enumerable: false, configurable: true
    Object.defineProperty(Object, "assign", {
        value: function assign(target, varArgs) {
            // .length of function is 2
            'use strict';

            if (target == null) {
                // TypeError if undefined or null
                throw new TypeError('Cannot convert undefined or null to object');
            }

            var to = Object(target);

            for (var index = 1; index < arguments.length; index++) {
                var nextSource = arguments[index];

                if (nextSource != null) {
                    // Skip over if undefined or null
                    for (var nextKey in nextSource) {
                        // Avoid bugs when hasOwnProperty is shadowed
                        if (Object.prototype.hasOwnProperty.call(nextSource, nextKey)) {
                            to[nextKey] = nextSource[nextKey];
                        }
                    }
                }
            }
            return to;
        },
        writable: true,
        configurable: true
    });
}

/* CustomEvent constructor (taken from MDN) */
(function () {
    function CustomEvent(event, params) {
        params = params || { bubbles: false, cancelable: false, detail: undefined };
        var evt = document.createEvent('CustomEvent');
        evt.initCustomEvent(event, params.bubbles, params.cancelable, params.detail);
        return evt;
    }

    CustomEvent.prototype = window.Event.prototype;

    if (typeof window.CustomEvent !== "function") {
        window.CustomEvent = CustomEvent;
    }
})();
},{}],24:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.decodeUTF8 = decodeUTF8;
/*
 * noVNC: HTML5 VNC client
 * Copyright (C) 2012 Joel Martin
 * Licensed under MPL 2.0 (see LICENSE.txt)
 *
 * See README.md for usage and integration instructions.
 */

/*
 * Decode from UTF-8
 */
function decodeUTF8(utf8string) {
  "use strict";

  return decodeURIComponent(escape(utf8string));
};
},{}],25:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
    value: true
});
exports.default = Websock;

var _logging = require('./util/logging.js');

var Log = _interopRequireWildcard(_logging);

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

function Websock() {
    "use strict";

    this._websocket = null; // WebSocket object

    this._rQi = 0; // Receive queue index
    this._rQlen = 0; // Next write position in the receive queue
    this._rQbufferSize = 1024 * 1024 * 4; // Receive queue buffer size (4 MiB)
    this._rQmax = this._rQbufferSize / 8;
    // called in init: this._rQ = new Uint8Array(this._rQbufferSize);
    this._rQ = null; // Receive queue

    this._sQbufferSize = 1024 * 10; // 10 KiB
    // called in init: this._sQ = new Uint8Array(this._sQbufferSize);
    this._sQlen = 0;
    this._sQ = null; // Send queue

    this._eventHandlers = {
        'message': function () {},
        'open': function () {},
        'close': function () {},
        'error': function () {}
    };
} /*
   * Websock: high-performance binary WebSockets
   * Copyright (C) 2012 Joel Martin
   * Licensed under MPL 2.0 (see LICENSE.txt)
   *
   * Websock is similar to the standard WebSocket object but with extra
   * buffer handling.
   *
   * Websock has built-in receive queue buffering; the message event
   * does not contain actual data but is simply a notification that
   * there is new data available. Several rQ* methods are available to
   * read binary data off of the receive queue.
   */

;

// this has performance issues in some versions Chromium, and
// doesn't gain a tremendous amount of performance increase in Firefox
// at the moment.  It may be valuable to turn it on in the future.
var ENABLE_COPYWITHIN = false;

var MAX_RQ_GROW_SIZE = 40 * 1024 * 1024; // 40 MiB

var typedArrayToString = function () {
    // This is only for PhantomJS, which doesn't like apply-ing
    // with Typed Arrays
    try {
        var arr = new Uint8Array([1, 2, 3]);
        String.fromCharCode.apply(null, arr);
        return function (a) {
            return String.fromCharCode.apply(null, a);
        };
    } catch (ex) {
        return function (a) {
            return String.fromCharCode.apply(null, Array.prototype.slice.call(a));
        };
    }
}();

Websock.prototype = {
    // Getters and Setters
    get_sQ: function () {
        return this._sQ;
    },

    get_rQ: function () {
        return this._rQ;
    },

    get_rQi: function () {
        return this._rQi;
    },

    set_rQi: function (val) {
        this._rQi = val;
    },

    // Receive Queue
    rQlen: function () {
        return this._rQlen - this._rQi;
    },

    rQpeek8: function () {
        return this._rQ[this._rQi];
    },

    rQshift8: function () {
        return this._rQ[this._rQi++];
    },

    rQskip8: function () {
        this._rQi++;
    },

    rQskipBytes: function (num) {
        this._rQi += num;
    },

    // TODO(directxman12): test performance with these vs a DataView
    rQshift16: function () {
        return (this._rQ[this._rQi++] << 8) + this._rQ[this._rQi++];
    },

    rQshift32: function () {
        return (this._rQ[this._rQi++] << 24) + (this._rQ[this._rQi++] << 16) + (this._rQ[this._rQi++] << 8) + this._rQ[this._rQi++];
    },

    rQshiftStr: function (len) {
        if (typeof len === 'undefined') {
            len = this.rQlen();
        }
        var arr = new Uint8Array(this._rQ.buffer, this._rQi, len);
        this._rQi += len;
        return typedArrayToString(arr);
    },

    rQshiftBytes: function (len) {
        if (typeof len === 'undefined') {
            len = this.rQlen();
        }
        this._rQi += len;
        return new Uint8Array(this._rQ.buffer, this._rQi - len, len);
    },

    rQshiftTo: function (target, len) {
        if (len === undefined) {
            len = this.rQlen();
        }
        // TODO: make this just use set with views when using a ArrayBuffer to store the rQ
        target.set(new Uint8Array(this._rQ.buffer, this._rQi, len));
        this._rQi += len;
    },

    rQwhole: function () {
        return new Uint8Array(this._rQ.buffer, 0, this._rQlen);
    },

    rQslice: function (start, end) {
        if (end) {
            return new Uint8Array(this._rQ.buffer, this._rQi + start, end - start);
        } else {
            return new Uint8Array(this._rQ.buffer, this._rQi + start, this._rQlen - this._rQi - start);
        }
    },

    // Check to see if we must wait for 'num' bytes (default to FBU.bytes)
    // to be available in the receive queue. Return true if we need to
    // wait (and possibly print a debug message), otherwise false.
    rQwait: function (msg, num, goback) {
        var rQlen = this._rQlen - this._rQi; // Skip rQlen() function call
        if (rQlen < num) {
            if (goback) {
                if (this._rQi < goback) {
                    throw new Error("rQwait cannot backup " + goback + " bytes");
                }
                this._rQi -= goback;
            }
            return true; // true means need more data
        }
        return false;
    },

    // Send Queue

    flush: function () {
        if (this._sQlen > 0 && this._websocket.readyState === WebSocket.OPEN) {
            this._websocket.send(this._encode_message());
            this._sQlen = 0;
        }
    },

    send: function (arr) {
        this._sQ.set(arr, this._sQlen);
        this._sQlen += arr.length;
        this.flush();
    },

    send_string: function (str) {
        this.send(str.split('').map(function (chr) {
            return chr.charCodeAt(0);
        }));
    },

    // Event Handlers
    off: function (evt) {
        this._eventHandlers[evt] = function () {};
    },

    on: function (evt, handler) {
        this._eventHandlers[evt] = handler;
    },

    _allocate_buffers: function () {
        this._rQ = new Uint8Array(this._rQbufferSize);
        this._sQ = new Uint8Array(this._sQbufferSize);
    },

    init: function () {
        this._allocate_buffers();
        this._rQi = 0;
        this._websocket = null;
    },

    open: function (uri, protocols) {
        var ws_schema = uri.match(/^([a-z]+):\/\//)[1];
        this.init();

        this._websocket = new WebSocket(uri, protocols);
        this._websocket.binaryType = 'arraybuffer';

        this._websocket.onmessage = this._recv_message.bind(this);
        this._websocket.onopen = function () {
            Log.Debug('>> WebSock.onopen');
            if (this._websocket.protocol) {
                Log.Info("Server choose sub-protocol: " + this._websocket.protocol);
            }

            this._eventHandlers.open();
            Log.Debug("<< WebSock.onopen");
        }.bind(this);
        this._websocket.onclose = function (e) {
            Log.Debug(">> WebSock.onclose");
            this._eventHandlers.close(e);
            Log.Debug("<< WebSock.onclose");
        }.bind(this);
        this._websocket.onerror = function (e) {
            Log.Debug(">> WebSock.onerror: " + e);
            this._eventHandlers.error(e);
            Log.Debug("<< WebSock.onerror: " + e);
        }.bind(this);
    },

    close: function () {
        if (this._websocket) {
            if (this._websocket.readyState === WebSocket.OPEN || this._websocket.readyState === WebSocket.CONNECTING) {
                Log.Info("Closing WebSocket connection");
                this._websocket.close();
            }

            this._websocket.onmessage = function (e) {
                return;
            };
        }
    },

    // private methods
    _encode_message: function () {
        // Put in a binary arraybuffer
        // according to the spec, you can send ArrayBufferViews with the send method
        return new Uint8Array(this._sQ.buffer, 0, this._sQlen);
    },

    _expand_compact_rQ: function (min_fit) {
        var resizeNeeded = min_fit || this._rQlen - this._rQi > this._rQbufferSize / 2;
        if (resizeNeeded) {
            if (!min_fit) {
                // just double the size if we need to do compaction
                this._rQbufferSize *= 2;
            } else {
                // otherwise, make sure we satisy rQlen - rQi + min_fit < rQbufferSize / 8
                this._rQbufferSize = (this._rQlen - this._rQi + min_fit) * 8;
            }
        }

        // we don't want to grow unboundedly
        if (this._rQbufferSize > MAX_RQ_GROW_SIZE) {
            this._rQbufferSize = MAX_RQ_GROW_SIZE;
            if (this._rQbufferSize - this._rQlen - this._rQi < min_fit) {
                throw new Exception("Receive Queue buffer exceeded " + MAX_RQ_GROW_SIZE + " bytes, and the new message could not fit");
            }
        }

        if (resizeNeeded) {
            var old_rQbuffer = this._rQ.buffer;
            this._rQmax = this._rQbufferSize / 8;
            this._rQ = new Uint8Array(this._rQbufferSize);
            this._rQ.set(new Uint8Array(old_rQbuffer, this._rQi));
        } else {
            if (ENABLE_COPYWITHIN) {
                this._rQ.copyWithin(0, this._rQi);
            } else {
                this._rQ.set(new Uint8Array(this._rQ.buffer, this._rQi));
            }
        }

        this._rQlen = this._rQlen - this._rQi;
        this._rQi = 0;
    },

    _decode_message: function (data) {
        // push arraybuffer values onto the end
        var u8 = new Uint8Array(data);
        if (u8.length > this._rQbufferSize - this._rQlen) {
            this._expand_compact_rQ(u8.length);
        }
        this._rQ.set(u8, this._rQlen);
        this._rQlen += u8.length;
    },

    _recv_message: function (e) {
        this._decode_message(e.data);
        if (this.rQlen() > 0) {
            this._eventHandlers.message();
            // Compact the receive queue
            if (this._rQlen == this._rQi) {
                this._rQlen = 0;
                this._rQi = 0;
            } else if (this._rQlen > this._rQmax) {
                this._expand_compact_rQ();
            }
        } else {
            Log.Debug("Ignoring empty message");
        }
    }
};
},{"./util/logging.js":22}],26:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.shrinkBuf = shrinkBuf;
exports.arraySet = arraySet;
exports.flattenChunks = flattenChunks;
// reduce buffer size, avoiding mem copy
function shrinkBuf(buf, size) {
  if (buf.length === size) {
    return buf;
  }
  if (buf.subarray) {
    return buf.subarray(0, size);
  }
  buf.length = size;
  return buf;
};

function arraySet(dest, src, src_offs, len, dest_offs) {
  if (src.subarray && dest.subarray) {
    dest.set(src.subarray(src_offs, src_offs + len), dest_offs);
    return;
  }
  // Fallback to ordinary array
  for (var i = 0; i < len; i++) {
    dest[dest_offs + i] = src[src_offs + i];
  }
}

// Join array of chunks to single array.
function flattenChunks(chunks) {
  var i, l, len, pos, chunk, result;

  // calculate data length
  len = 0;
  for (i = 0, l = chunks.length; i < l; i++) {
    len += chunks[i].length;
  }

  // join chunks
  result = new Uint8Array(len);
  pos = 0;
  for (i = 0, l = chunks.length; i < l; i++) {
    chunk = chunks[i];
    result.set(chunk, pos);
    pos += chunk.length;
  }

  return result;
}

var Buf8 = exports.Buf8 = Uint8Array;
var Buf16 = exports.Buf16 = Uint16Array;
var Buf32 = exports.Buf32 = Int32Array;
},{}],27:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = adler32;
// Note: adler32 takes 12% for level 0 and 2% for level 6.
// It doesn't worth to make additional optimizationa as in original.
// Small size is preferable.

function adler32(adler, buf, len, pos) {
  var s1 = adler & 0xffff | 0,
      s2 = adler >>> 16 & 0xffff | 0,
      n = 0;

  while (len !== 0) {
    // Set limit ~ twice less than 5552, to keep
    // s2 in 31-bits, because we force signed ints.
    // in other case %= will fail.
    n = len > 2000 ? 2000 : len;
    len -= n;

    do {
      s1 = s1 + buf[pos++] | 0;
      s2 = s2 + s1 | 0;
    } while (--n);

    s1 %= 65521;
    s2 %= 65521;
  }

  return s1 | s2 << 16 | 0;
}
},{}],28:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = makeTable;
// Note: we can't get significant speed boost here.
// So write code to minimize size - no pregenerated tables
// and array tools dependencies.


// Use ordinary array, since untyped makes no boost here
function makeTable() {
  var c,
      table = [];

  for (var n = 0; n < 256; n++) {
    c = n;
    for (var k = 0; k < 8; k++) {
      c = c & 1 ? 0xEDB88320 ^ c >>> 1 : c >>> 1;
    }
    table[n] = c;
  }

  return table;
}

// Create table on load. Just 255 signed longs. Not a problem.
var crcTable = makeTable();

function crc32(crc, buf, len, pos) {
  var t = crcTable,
      end = pos + len;

  crc ^= -1;

  for (var i = pos; i < end; i++) {
    crc = crc >>> 8 ^ t[(crc ^ buf[i]) & 0xFF];
  }

  return crc ^ -1; // >>> 0;
}
},{}],29:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = inflate_fast;
// See state defs from inflate.js
var BAD = 30; /* got a data error -- remain here until reset */
var TYPE = 12; /* i: waiting for type bits, including last-flag bit */

/*
   Decode literal, length, and distance codes and write out the resulting
   literal and match bytes until either not enough input or output is
   available, an end-of-block is encountered, or a data error is encountered.
   When large enough input and output buffers are supplied to inflate(), for
   example, a 16K input buffer and a 64K output buffer, more than 95% of the
   inflate execution time is spent in this routine.

   Entry assumptions:

        state.mode === LEN
        strm.avail_in >= 6
        strm.avail_out >= 258
        start >= strm.avail_out
        state.bits < 8

   On return, state.mode is one of:

        LEN -- ran out of enough output space or enough available input
        TYPE -- reached end of block code, inflate() to interpret next block
        BAD -- error in block data

   Notes:

    - The maximum input bits used by a length/distance pair is 15 bits for the
      length code, 5 bits for the length extra, 15 bits for the distance code,
      and 13 bits for the distance extra.  This totals 48 bits, or six bytes.
      Therefore if strm.avail_in >= 6, then there is enough input to avoid
      checking for available input while decoding.

    - The maximum bytes that a single length/distance pair can output is 258
      bytes, which is the maximum length that can be coded.  inflate_fast()
      requires strm.avail_out >= 258 for each loop to avoid checking for
      output space.
 */
function inflate_fast(strm, start) {
  var state;
  var _in; /* local strm.input */
  var last; /* have enough input while in < last */
  var _out; /* local strm.output */
  var beg; /* inflate()'s initial strm.output */
  var end; /* while out < end, enough space available */
  //#ifdef INFLATE_STRICT
  var dmax; /* maximum distance from zlib header */
  //#endif
  var wsize; /* window size or zero if not using window */
  var whave; /* valid bytes in the window */
  var wnext; /* window write index */
  // Use `s_window` instead `window`, avoid conflict with instrumentation tools
  var s_window; /* allocated sliding window, if wsize != 0 */
  var hold; /* local strm.hold */
  var bits; /* local strm.bits */
  var lcode; /* local strm.lencode */
  var dcode; /* local strm.distcode */
  var lmask; /* mask for first level of length codes */
  var dmask; /* mask for first level of distance codes */
  var here; /* retrieved table entry */
  var op; /* code bits, operation, extra bits, or */
  /*  window position, window bytes to copy */
  var len; /* match length, unused bytes */
  var dist; /* match distance */
  var from; /* where to copy match from */
  var from_source;

  var input, output; // JS specific, because we have no pointers

  /* copy state to local variables */
  state = strm.state;
  //here = state.here;
  _in = strm.next_in;
  input = strm.input;
  last = _in + (strm.avail_in - 5);
  _out = strm.next_out;
  output = strm.output;
  beg = _out - (start - strm.avail_out);
  end = _out + (strm.avail_out - 257);
  //#ifdef INFLATE_STRICT
  dmax = state.dmax;
  //#endif
  wsize = state.wsize;
  whave = state.whave;
  wnext = state.wnext;
  s_window = state.window;
  hold = state.hold;
  bits = state.bits;
  lcode = state.lencode;
  dcode = state.distcode;
  lmask = (1 << state.lenbits) - 1;
  dmask = (1 << state.distbits) - 1;

  /* decode literals and length/distances until end-of-block or not enough
     input data or output space */

  top: do {
    if (bits < 15) {
      hold += input[_in++] << bits;
      bits += 8;
      hold += input[_in++] << bits;
      bits += 8;
    }

    here = lcode[hold & lmask];

    dolen: for (;;) {
      // Goto emulation
      op = here >>> 24 /*here.bits*/;
      hold >>>= op;
      bits -= op;
      op = here >>> 16 & 0xff /*here.op*/;
      if (op === 0) {
        /* literal */
        //Tracevv((stderr, here.val >= 0x20 && here.val < 0x7f ?
        //        "inflate:         literal '%c'\n" :
        //        "inflate:         literal 0x%02x\n", here.val));
        output[_out++] = here & 0xffff /*here.val*/;
      } else if (op & 16) {
        /* length base */
        len = here & 0xffff /*here.val*/;
        op &= 15; /* number of extra bits */
        if (op) {
          if (bits < op) {
            hold += input[_in++] << bits;
            bits += 8;
          }
          len += hold & (1 << op) - 1;
          hold >>>= op;
          bits -= op;
        }
        //Tracevv((stderr, "inflate:         length %u\n", len));
        if (bits < 15) {
          hold += input[_in++] << bits;
          bits += 8;
          hold += input[_in++] << bits;
          bits += 8;
        }
        here = dcode[hold & dmask];

        dodist: for (;;) {
          // goto emulation
          op = here >>> 24 /*here.bits*/;
          hold >>>= op;
          bits -= op;
          op = here >>> 16 & 0xff /*here.op*/;

          if (op & 16) {
            /* distance base */
            dist = here & 0xffff /*here.val*/;
            op &= 15; /* number of extra bits */
            if (bits < op) {
              hold += input[_in++] << bits;
              bits += 8;
              if (bits < op) {
                hold += input[_in++] << bits;
                bits += 8;
              }
            }
            dist += hold & (1 << op) - 1;
            //#ifdef INFLATE_STRICT
            if (dist > dmax) {
              strm.msg = 'invalid distance too far back';
              state.mode = BAD;
              break top;
            }
            //#endif
            hold >>>= op;
            bits -= op;
            //Tracevv((stderr, "inflate:         distance %u\n", dist));
            op = _out - beg; /* max distance in output */
            if (dist > op) {
              /* see if copy from window */
              op = dist - op; /* distance back in window */
              if (op > whave) {
                if (state.sane) {
                  strm.msg = 'invalid distance too far back';
                  state.mode = BAD;
                  break top;
                }

                // (!) This block is disabled in zlib defailts,
                // don't enable it for binary compatibility
                //#ifdef INFLATE_ALLOW_INVALID_DISTANCE_TOOFAR_ARRR
                //                if (len <= op - whave) {
                //                  do {
                //                    output[_out++] = 0;
                //                  } while (--len);
                //                  continue top;
                //                }
                //                len -= op - whave;
                //                do {
                //                  output[_out++] = 0;
                //                } while (--op > whave);
                //                if (op === 0) {
                //                  from = _out - dist;
                //                  do {
                //                    output[_out++] = output[from++];
                //                  } while (--len);
                //                  continue top;
                //                }
                //#endif
              }
              from = 0; // window index
              from_source = s_window;
              if (wnext === 0) {
                /* very common case */
                from += wsize - op;
                if (op < len) {
                  /* some from window */
                  len -= op;
                  do {
                    output[_out++] = s_window[from++];
                  } while (--op);
                  from = _out - dist; /* rest from output */
                  from_source = output;
                }
              } else if (wnext < op) {
                /* wrap around window */
                from += wsize + wnext - op;
                op -= wnext;
                if (op < len) {
                  /* some from end of window */
                  len -= op;
                  do {
                    output[_out++] = s_window[from++];
                  } while (--op);
                  from = 0;
                  if (wnext < len) {
                    /* some from start of window */
                    op = wnext;
                    len -= op;
                    do {
                      output[_out++] = s_window[from++];
                    } while (--op);
                    from = _out - dist; /* rest from output */
                    from_source = output;
                  }
                }
              } else {
                /* contiguous in window */
                from += wnext - op;
                if (op < len) {
                  /* some from window */
                  len -= op;
                  do {
                    output[_out++] = s_window[from++];
                  } while (--op);
                  from = _out - dist; /* rest from output */
                  from_source = output;
                }
              }
              while (len > 2) {
                output[_out++] = from_source[from++];
                output[_out++] = from_source[from++];
                output[_out++] = from_source[from++];
                len -= 3;
              }
              if (len) {
                output[_out++] = from_source[from++];
                if (len > 1) {
                  output[_out++] = from_source[from++];
                }
              }
            } else {
              from = _out - dist; /* copy direct from output */
              do {
                /* minimum length is three */
                output[_out++] = output[from++];
                output[_out++] = output[from++];
                output[_out++] = output[from++];
                len -= 3;
              } while (len > 2);
              if (len) {
                output[_out++] = output[from++];
                if (len > 1) {
                  output[_out++] = output[from++];
                }
              }
            }
          } else if ((op & 64) === 0) {
            /* 2nd level distance code */
            here = dcode[(here & 0xffff) + ( /*here.val*/hold & (1 << op) - 1)];
            continue dodist;
          } else {
            strm.msg = 'invalid distance code';
            state.mode = BAD;
            break top;
          }

          break; // need to emulate goto via "continue"
        }
      } else if ((op & 64) === 0) {
        /* 2nd level length code */
        here = lcode[(here & 0xffff) + ( /*here.val*/hold & (1 << op) - 1)];
        continue dolen;
      } else if (op & 32) {
        /* end-of-block */
        //Tracevv((stderr, "inflate:         end of block\n"));
        state.mode = TYPE;
        break top;
      } else {
        strm.msg = 'invalid literal/length code';
        state.mode = BAD;
        break top;
      }

      break; // need to emulate goto via "continue"
    }
  } while (_in < last && _out < end);

  /* return unused bytes (on entry, bits < 8, so in won't go too far back) */
  len = bits >> 3;
  _in -= len;
  bits -= len << 3;
  hold &= (1 << bits) - 1;

  /* update state and return */
  strm.next_in = _in;
  strm.next_out = _out;
  strm.avail_in = _in < last ? 5 + (last - _in) : 5 - (_in - last);
  strm.avail_out = _out < end ? 257 + (end - _out) : 257 - (_out - end);
  state.hold = hold;
  state.bits = bits;
  return;
};
},{}],30:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.inflateInfo = exports.inflateSetDictionary = exports.inflateGetHeader = exports.inflateEnd = exports.inflate = exports.inflateInit2 = exports.inflateInit = exports.inflateResetKeep = exports.inflateReset2 = exports.inflateReset = undefined;

var _common = require("../utils/common.js");

var utils = _interopRequireWildcard(_common);

var _adler = require("./adler32.js");

var _adler2 = _interopRequireDefault(_adler);

var _crc = require("./crc32.js");

var _crc2 = _interopRequireDefault(_crc);

var _inffast = require("./inffast.js");

var _inffast2 = _interopRequireDefault(_inffast);

var _inftrees = require("./inftrees.js");

var _inftrees2 = _interopRequireDefault(_inftrees);

function _interopRequireDefault(obj) { return obj && obj.__esModule ? obj : { default: obj }; }

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

var CODES = 0;
var LENS = 1;
var DISTS = 2;

/* Public constants ==========================================================*/
/* ===========================================================================*/

/* Allowed flush values; see deflate() and inflate() below for details */
//var Z_NO_FLUSH      = 0;
//var Z_PARTIAL_FLUSH = 1;
//var Z_SYNC_FLUSH    = 2;
//var Z_FULL_FLUSH    = 3;
var Z_FINISH = 4;
var Z_BLOCK = 5;
var Z_TREES = 6;

/* Return codes for the compression/decompression functions. Negative values
 * are errors, positive values are used for special but normal events.
 */
var Z_OK = 0;
var Z_STREAM_END = 1;
var Z_NEED_DICT = 2;
//var Z_ERRNO         = -1;
var Z_STREAM_ERROR = -2;
var Z_DATA_ERROR = -3;
var Z_MEM_ERROR = -4;
var Z_BUF_ERROR = -5;
//var Z_VERSION_ERROR = -6;

/* The deflate compression method */
var Z_DEFLATED = 8;

/* STATES ====================================================================*/
/* ===========================================================================*/

var HEAD = 1; /* i: waiting for magic header */
var FLAGS = 2; /* i: waiting for method and flags (gzip) */
var TIME = 3; /* i: waiting for modification time (gzip) */
var OS = 4; /* i: waiting for extra flags and operating system (gzip) */
var EXLEN = 5; /* i: waiting for extra length (gzip) */
var EXTRA = 6; /* i: waiting for extra bytes (gzip) */
var NAME = 7; /* i: waiting for end of file name (gzip) */
var COMMENT = 8; /* i: waiting for end of comment (gzip) */
var HCRC = 9; /* i: waiting for header crc (gzip) */
var DICTID = 10; /* i: waiting for dictionary check value */
var DICT = 11; /* waiting for inflateSetDictionary() call */
var TYPE = 12; /* i: waiting for type bits, including last-flag bit */
var TYPEDO = 13; /* i: same, but skip check to exit inflate on new block */
var STORED = 14; /* i: waiting for stored size (length and complement) */
var COPY_ = 15; /* i/o: same as COPY below, but only first time in */
var COPY = 16; /* i/o: waiting for input or output to copy stored block */
var TABLE = 17; /* i: waiting for dynamic block table lengths */
var LENLENS = 18; /* i: waiting for code length code lengths */
var CODELENS = 19; /* i: waiting for length/lit and distance code lengths */
var LEN_ = 20; /* i: same as LEN below, but only first time in */
var LEN = 21; /* i: waiting for length/lit/eob code */
var LENEXT = 22; /* i: waiting for length extra bits */
var DIST = 23; /* i: waiting for distance code */
var DISTEXT = 24; /* i: waiting for distance extra bits */
var MATCH = 25; /* o: waiting for output space to copy string */
var LIT = 26; /* o: waiting for output space to write literal */
var CHECK = 27; /* i: waiting for 32-bit check value */
var LENGTH = 28; /* i: waiting for 32-bit length (gzip) */
var DONE = 29; /* finished check, done -- remain here until reset */
var BAD = 30; /* got a data error -- remain here until reset */
var MEM = 31; /* got an inflate() memory error -- remain here until reset */
var SYNC = 32; /* looking for synchronization bytes to restart inflate() */

/* ===========================================================================*/

var ENOUGH_LENS = 852;
var ENOUGH_DISTS = 592;
//var ENOUGH =  (ENOUGH_LENS+ENOUGH_DISTS);

var MAX_WBITS = 15;
/* 32K LZ77 window */
var DEF_WBITS = MAX_WBITS;

function zswap32(q) {
  return (q >>> 24 & 0xff) + (q >>> 8 & 0xff00) + ((q & 0xff00) << 8) + ((q & 0xff) << 24);
}

function InflateState() {
  this.mode = 0; /* current inflate mode */
  this.last = false; /* true if processing last block */
  this.wrap = 0; /* bit 0 true for zlib, bit 1 true for gzip */
  this.havedict = false; /* true if dictionary provided */
  this.flags = 0; /* gzip header method and flags (0 if zlib) */
  this.dmax = 0; /* zlib header max distance (INFLATE_STRICT) */
  this.check = 0; /* protected copy of check value */
  this.total = 0; /* protected copy of output count */
  // TODO: may be {}
  this.head = null; /* where to save gzip header information */

  /* sliding window */
  this.wbits = 0; /* log base 2 of requested window size */
  this.wsize = 0; /* window size or zero if not using window */
  this.whave = 0; /* valid bytes in the window */
  this.wnext = 0; /* window write index */
  this.window = null; /* allocated sliding window, if needed */

  /* bit accumulator */
  this.hold = 0; /* input bit accumulator */
  this.bits = 0; /* number of bits in "in" */

  /* for string and stored block copying */
  this.length = 0; /* literal or length of data to copy */
  this.offset = 0; /* distance back to copy string from */

  /* for table and code decoding */
  this.extra = 0; /* extra bits needed */

  /* fixed and dynamic code tables */
  this.lencode = null; /* starting table for length/literal codes */
  this.distcode = null; /* starting table for distance codes */
  this.lenbits = 0; /* index bits for lencode */
  this.distbits = 0; /* index bits for distcode */

  /* dynamic table building */
  this.ncode = 0; /* number of code length code lengths */
  this.nlen = 0; /* number of length code lengths */
  this.ndist = 0; /* number of distance code lengths */
  this.have = 0; /* number of code lengths in lens[] */
  this.next = null; /* next available space in codes[] */

  this.lens = new utils.Buf16(320); /* temporary storage for code lengths */
  this.work = new utils.Buf16(288); /* work area for code table building */

  /*
   because we don't have pointers in js, we use lencode and distcode directly
   as buffers so we don't need codes
  */
  //this.codes = new utils.Buf32(ENOUGH);       /* space for code tables */
  this.lendyn = null; /* dynamic table for length/literal codes (JS specific) */
  this.distdyn = null; /* dynamic table for distance codes (JS specific) */
  this.sane = 0; /* if false, allow invalid distance too far */
  this.back = 0; /* bits back of last unprocessed length/lit */
  this.was = 0; /* initial length of match */
}

function inflateResetKeep(strm) {
  var state;

  if (!strm || !strm.state) {
    return Z_STREAM_ERROR;
  }
  state = strm.state;
  strm.total_in = strm.total_out = state.total = 0;
  strm.msg = ''; /*Z_NULL*/
  if (state.wrap) {
    /* to support ill-conceived Java test suite */
    strm.adler = state.wrap & 1;
  }
  state.mode = HEAD;
  state.last = 0;
  state.havedict = 0;
  state.dmax = 32768;
  state.head = null /*Z_NULL*/;
  state.hold = 0;
  state.bits = 0;
  //state.lencode = state.distcode = state.next = state.codes;
  state.lencode = state.lendyn = new utils.Buf32(ENOUGH_LENS);
  state.distcode = state.distdyn = new utils.Buf32(ENOUGH_DISTS);

  state.sane = 1;
  state.back = -1;
  //Tracev((stderr, "inflate: reset\n"));
  return Z_OK;
}

function inflateReset(strm) {
  var state;

  if (!strm || !strm.state) {
    return Z_STREAM_ERROR;
  }
  state = strm.state;
  state.wsize = 0;
  state.whave = 0;
  state.wnext = 0;
  return inflateResetKeep(strm);
}

function inflateReset2(strm, windowBits) {
  var wrap;
  var state;

  /* get the state */
  if (!strm || !strm.state) {
    return Z_STREAM_ERROR;
  }
  state = strm.state;

  /* extract wrap request from windowBits parameter */
  if (windowBits < 0) {
    wrap = 0;
    windowBits = -windowBits;
  } else {
    wrap = (windowBits >> 4) + 1;
    if (windowBits < 48) {
      windowBits &= 15;
    }
  }

  /* set number of window bits, free window if different */
  if (windowBits && (windowBits < 8 || windowBits > 15)) {
    return Z_STREAM_ERROR;
  }
  if (state.window !== null && state.wbits !== windowBits) {
    state.window = null;
  }

  /* update state and reset the rest of it */
  state.wrap = wrap;
  state.wbits = windowBits;
  return inflateReset(strm);
}

function inflateInit2(strm, windowBits) {
  var ret;
  var state;

  if (!strm) {
    return Z_STREAM_ERROR;
  }
  //strm.msg = Z_NULL;                 /* in case we return an error */

  state = new InflateState();

  //if (state === Z_NULL) return Z_MEM_ERROR;
  //Tracev((stderr, "inflate: allocated\n"));
  strm.state = state;
  state.window = null /*Z_NULL*/;
  ret = inflateReset2(strm, windowBits);
  if (ret !== Z_OK) {
    strm.state = null /*Z_NULL*/;
  }
  return ret;
}

function inflateInit(strm) {
  return inflateInit2(strm, DEF_WBITS);
}

/*
 Return state with length and distance decoding tables and index sizes set to
 fixed code decoding.  Normally this returns fixed tables from inffixed.h.
 If BUILDFIXED is defined, then instead this routine builds the tables the
 first time it's called, and returns those tables the first time and
 thereafter.  This reduces the size of the code by about 2K bytes, in
 exchange for a little execution time.  However, BUILDFIXED should not be
 used for threaded applications, since the rewriting of the tables and virgin
 may not be thread-safe.
 */
var virgin = true;

var lenfix, distfix; // We have no pointers in JS, so keep tables separate

function fixedtables(state) {
  /* build fixed huffman tables if first call (may not be thread safe) */
  if (virgin) {
    var sym;

    lenfix = new utils.Buf32(512);
    distfix = new utils.Buf32(32);

    /* literal/length table */
    sym = 0;
    while (sym < 144) {
      state.lens[sym++] = 8;
    }
    while (sym < 256) {
      state.lens[sym++] = 9;
    }
    while (sym < 280) {
      state.lens[sym++] = 7;
    }
    while (sym < 288) {
      state.lens[sym++] = 8;
    }

    (0, _inftrees2.default)(LENS, state.lens, 0, 288, lenfix, 0, state.work, { bits: 9 });

    /* distance table */
    sym = 0;
    while (sym < 32) {
      state.lens[sym++] = 5;
    }

    (0, _inftrees2.default)(DISTS, state.lens, 0, 32, distfix, 0, state.work, { bits: 5 });

    /* do this just once */
    virgin = false;
  }

  state.lencode = lenfix;
  state.lenbits = 9;
  state.distcode = distfix;
  state.distbits = 5;
}

/*
 Update the window with the last wsize (normally 32K) bytes written before
 returning.  If window does not exist yet, create it.  This is only called
 when a window is already in use, or when output has been written during this
 inflate call, but the end of the deflate stream has not been reached yet.
 It is also called to create a window for dictionary data when a dictionary
 is loaded.

 Providing output buffers larger than 32K to inflate() should provide a speed
 advantage, since only the last 32K of output is copied to the sliding window
 upon return from inflate(), and since all distances after the first 32K of
 output will fall in the output data, making match copies simpler and faster.
 The advantage may be dependent on the size of the processor's data caches.
 */
function updatewindow(strm, src, end, copy) {
  var dist;
  var state = strm.state;

  /* if it hasn't been done already, allocate space for the window */
  if (state.window === null) {
    state.wsize = 1 << state.wbits;
    state.wnext = 0;
    state.whave = 0;

    state.window = new utils.Buf8(state.wsize);
  }

  /* copy state->wsize or less output bytes into the circular window */
  if (copy >= state.wsize) {
    utils.arraySet(state.window, src, end - state.wsize, state.wsize, 0);
    state.wnext = 0;
    state.whave = state.wsize;
  } else {
    dist = state.wsize - state.wnext;
    if (dist > copy) {
      dist = copy;
    }
    //zmemcpy(state->window + state->wnext, end - copy, dist);
    utils.arraySet(state.window, src, end - copy, dist, state.wnext);
    copy -= dist;
    if (copy) {
      //zmemcpy(state->window, end - copy, copy);
      utils.arraySet(state.window, src, end - copy, copy, 0);
      state.wnext = copy;
      state.whave = state.wsize;
    } else {
      state.wnext += dist;
      if (state.wnext === state.wsize) {
        state.wnext = 0;
      }
      if (state.whave < state.wsize) {
        state.whave += dist;
      }
    }
  }
  return 0;
}

function inflate(strm, flush) {
  var state;
  var input, output; // input/output buffers
  var next; /* next input INDEX */
  var put; /* next output INDEX */
  var have, left; /* available input and output */
  var hold; /* bit buffer */
  var bits; /* bits in bit buffer */
  var _in, _out; /* save starting available input and output */
  var copy; /* number of stored or match bytes to copy */
  var from; /* where to copy match bytes from */
  var from_source;
  var here = 0; /* current decoding table entry */
  var here_bits, here_op, here_val; // paked "here" denormalized (JS specific)
  //var last;                   /* parent table entry */
  var last_bits, last_op, last_val; // paked "last" denormalized (JS specific)
  var len; /* length to copy for repeats, bits to drop */
  var ret; /* return code */
  var hbuf = new utils.Buf8(4); /* buffer for gzip header crc calculation */
  var opts;

  var n; // temporary var for NEED_BITS

  var order = /* permutation of code lengths */
  [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15];

  if (!strm || !strm.state || !strm.output || !strm.input && strm.avail_in !== 0) {
    return Z_STREAM_ERROR;
  }

  state = strm.state;
  if (state.mode === TYPE) {
    state.mode = TYPEDO;
  } /* skip check */

  //--- LOAD() ---
  put = strm.next_out;
  output = strm.output;
  left = strm.avail_out;
  next = strm.next_in;
  input = strm.input;
  have = strm.avail_in;
  hold = state.hold;
  bits = state.bits;
  //---

  _in = have;
  _out = left;
  ret = Z_OK;

  inf_leave: // goto emulation
  for (;;) {
    switch (state.mode) {
      case HEAD:
        if (state.wrap === 0) {
          state.mode = TYPEDO;
          break;
        }
        //=== NEEDBITS(16);
        while (bits < 16) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        if (state.wrap & 2 && hold === 0x8b1f) {
          /* gzip header */
          state.check = 0 /*crc32(0L, Z_NULL, 0)*/;
          //=== CRC2(state.check, hold);
          hbuf[0] = hold & 0xff;
          hbuf[1] = hold >>> 8 & 0xff;
          state.check = (0, _crc2.default)(state.check, hbuf, 2, 0);
          //===//

          //=== INITBITS();
          hold = 0;
          bits = 0;
          //===//
          state.mode = FLAGS;
          break;
        }
        state.flags = 0; /* expect zlib header */
        if (state.head) {
          state.head.done = false;
        }
        if (!(state.wrap & 1) || /* check if zlib header allowed */
        (((hold & 0xff) << /*BITS(8)*/8) + (hold >> 8)) % 31) {
          strm.msg = 'incorrect header check';
          state.mode = BAD;
          break;
        }
        if ((hold & 0x0f) !== /*BITS(4)*/Z_DEFLATED) {
          strm.msg = 'unknown compression method';
          state.mode = BAD;
          break;
        }
        //--- DROPBITS(4) ---//
        hold >>>= 4;
        bits -= 4;
        //---//
        len = (hold & 0x0f) + /*BITS(4)*/8;
        if (state.wbits === 0) {
          state.wbits = len;
        } else if (len > state.wbits) {
          strm.msg = 'invalid window size';
          state.mode = BAD;
          break;
        }
        state.dmax = 1 << len;
        //Tracev((stderr, "inflate:   zlib header ok\n"));
        strm.adler = state.check = 1 /*adler32(0L, Z_NULL, 0)*/;
        state.mode = hold & 0x200 ? DICTID : TYPE;
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        break;
      case FLAGS:
        //=== NEEDBITS(16); */
        while (bits < 16) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        state.flags = hold;
        if ((state.flags & 0xff) !== Z_DEFLATED) {
          strm.msg = 'unknown compression method';
          state.mode = BAD;
          break;
        }
        if (state.flags & 0xe000) {
          strm.msg = 'unknown header flags set';
          state.mode = BAD;
          break;
        }
        if (state.head) {
          state.head.text = hold >> 8 & 1;
        }
        if (state.flags & 0x0200) {
          //=== CRC2(state.check, hold);
          hbuf[0] = hold & 0xff;
          hbuf[1] = hold >>> 8 & 0xff;
          state.check = (0, _crc2.default)(state.check, hbuf, 2, 0);
          //===//
        }
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        state.mode = TIME;
      /* falls through */
      case TIME:
        //=== NEEDBITS(32); */
        while (bits < 32) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        if (state.head) {
          state.head.time = hold;
        }
        if (state.flags & 0x0200) {
          //=== CRC4(state.check, hold)
          hbuf[0] = hold & 0xff;
          hbuf[1] = hold >>> 8 & 0xff;
          hbuf[2] = hold >>> 16 & 0xff;
          hbuf[3] = hold >>> 24 & 0xff;
          state.check = (0, _crc2.default)(state.check, hbuf, 4, 0);
          //===
        }
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        state.mode = OS;
      /* falls through */
      case OS:
        //=== NEEDBITS(16); */
        while (bits < 16) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        if (state.head) {
          state.head.xflags = hold & 0xff;
          state.head.os = hold >> 8;
        }
        if (state.flags & 0x0200) {
          //=== CRC2(state.check, hold);
          hbuf[0] = hold & 0xff;
          hbuf[1] = hold >>> 8 & 0xff;
          state.check = (0, _crc2.default)(state.check, hbuf, 2, 0);
          //===//
        }
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        state.mode = EXLEN;
      /* falls through */
      case EXLEN:
        if (state.flags & 0x0400) {
          //=== NEEDBITS(16); */
          while (bits < 16) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          state.length = hold;
          if (state.head) {
            state.head.extra_len = hold;
          }
          if (state.flags & 0x0200) {
            //=== CRC2(state.check, hold);
            hbuf[0] = hold & 0xff;
            hbuf[1] = hold >>> 8 & 0xff;
            state.check = (0, _crc2.default)(state.check, hbuf, 2, 0);
            //===//
          }
          //=== INITBITS();
          hold = 0;
          bits = 0;
          //===//
        } else if (state.head) {
          state.head.extra = null /*Z_NULL*/;
        }
        state.mode = EXTRA;
      /* falls through */
      case EXTRA:
        if (state.flags & 0x0400) {
          copy = state.length;
          if (copy > have) {
            copy = have;
          }
          if (copy) {
            if (state.head) {
              len = state.head.extra_len - state.length;
              if (!state.head.extra) {
                // Use untyped array for more conveniend processing later
                state.head.extra = new Array(state.head.extra_len);
              }
              utils.arraySet(state.head.extra, input, next,
              // extra field is limited to 65536 bytes
              // - no need for additional size check
              copy,
              /*len + copy > state.head.extra_max - len ? state.head.extra_max : copy,*/
              len);
              //zmemcpy(state.head.extra + len, next,
              //        len + copy > state.head.extra_max ?
              //        state.head.extra_max - len : copy);
            }
            if (state.flags & 0x0200) {
              state.check = (0, _crc2.default)(state.check, input, copy, next);
            }
            have -= copy;
            next += copy;
            state.length -= copy;
          }
          if (state.length) {
            break inf_leave;
          }
        }
        state.length = 0;
        state.mode = NAME;
      /* falls through */
      case NAME:
        if (state.flags & 0x0800) {
          if (have === 0) {
            break inf_leave;
          }
          copy = 0;
          do {
            // TODO: 2 or 1 bytes?
            len = input[next + copy++];
            /* use constant limit because in js we should not preallocate memory */
            if (state.head && len && state.length < 65536 /*state.head.name_max*/) {
              state.head.name += String.fromCharCode(len);
            }
          } while (len && copy < have);

          if (state.flags & 0x0200) {
            state.check = (0, _crc2.default)(state.check, input, copy, next);
          }
          have -= copy;
          next += copy;
          if (len) {
            break inf_leave;
          }
        } else if (state.head) {
          state.head.name = null;
        }
        state.length = 0;
        state.mode = COMMENT;
      /* falls through */
      case COMMENT:
        if (state.flags & 0x1000) {
          if (have === 0) {
            break inf_leave;
          }
          copy = 0;
          do {
            len = input[next + copy++];
            /* use constant limit because in js we should not preallocate memory */
            if (state.head && len && state.length < 65536 /*state.head.comm_max*/) {
              state.head.comment += String.fromCharCode(len);
            }
          } while (len && copy < have);
          if (state.flags & 0x0200) {
            state.check = (0, _crc2.default)(state.check, input, copy, next);
          }
          have -= copy;
          next += copy;
          if (len) {
            break inf_leave;
          }
        } else if (state.head) {
          state.head.comment = null;
        }
        state.mode = HCRC;
      /* falls through */
      case HCRC:
        if (state.flags & 0x0200) {
          //=== NEEDBITS(16); */
          while (bits < 16) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          if (hold !== (state.check & 0xffff)) {
            strm.msg = 'header crc mismatch';
            state.mode = BAD;
            break;
          }
          //=== INITBITS();
          hold = 0;
          bits = 0;
          //===//
        }
        if (state.head) {
          state.head.hcrc = state.flags >> 9 & 1;
          state.head.done = true;
        }
        strm.adler = state.check = 0;
        state.mode = TYPE;
        break;
      case DICTID:
        //=== NEEDBITS(32); */
        while (bits < 32) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        strm.adler = state.check = zswap32(hold);
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        state.mode = DICT;
      /* falls through */
      case DICT:
        if (state.havedict === 0) {
          //--- RESTORE() ---
          strm.next_out = put;
          strm.avail_out = left;
          strm.next_in = next;
          strm.avail_in = have;
          state.hold = hold;
          state.bits = bits;
          //---
          return Z_NEED_DICT;
        }
        strm.adler = state.check = 1 /*adler32(0L, Z_NULL, 0)*/;
        state.mode = TYPE;
      /* falls through */
      case TYPE:
        if (flush === Z_BLOCK || flush === Z_TREES) {
          break inf_leave;
        }
      /* falls through */
      case TYPEDO:
        if (state.last) {
          //--- BYTEBITS() ---//
          hold >>>= bits & 7;
          bits -= bits & 7;
          //---//
          state.mode = CHECK;
          break;
        }
        //=== NEEDBITS(3); */
        while (bits < 3) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        state.last = hold & 0x01 /*BITS(1)*/;
        //--- DROPBITS(1) ---//
        hold >>>= 1;
        bits -= 1;
        //---//

        switch (hold & 0x03) {/*BITS(2)*/case 0:
            /* stored block */
            //Tracev((stderr, "inflate:     stored block%s\n",
            //        state.last ? " (last)" : ""));
            state.mode = STORED;
            break;
          case 1:
            /* fixed block */
            fixedtables(state);
            //Tracev((stderr, "inflate:     fixed codes block%s\n",
            //        state.last ? " (last)" : ""));
            state.mode = LEN_; /* decode codes */
            if (flush === Z_TREES) {
              //--- DROPBITS(2) ---//
              hold >>>= 2;
              bits -= 2;
              //---//
              break inf_leave;
            }
            break;
          case 2:
            /* dynamic block */
            //Tracev((stderr, "inflate:     dynamic codes block%s\n",
            //        state.last ? " (last)" : ""));
            state.mode = TABLE;
            break;
          case 3:
            strm.msg = 'invalid block type';
            state.mode = BAD;
        }
        //--- DROPBITS(2) ---//
        hold >>>= 2;
        bits -= 2;
        //---//
        break;
      case STORED:
        //--- BYTEBITS() ---// /* go to byte boundary */
        hold >>>= bits & 7;
        bits -= bits & 7;
        //---//
        //=== NEEDBITS(32); */
        while (bits < 32) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        if ((hold & 0xffff) !== (hold >>> 16 ^ 0xffff)) {
          strm.msg = 'invalid stored block lengths';
          state.mode = BAD;
          break;
        }
        state.length = hold & 0xffff;
        //Tracev((stderr, "inflate:       stored length %u\n",
        //        state.length));
        //=== INITBITS();
        hold = 0;
        bits = 0;
        //===//
        state.mode = COPY_;
        if (flush === Z_TREES) {
          break inf_leave;
        }
      /* falls through */
      case COPY_:
        state.mode = COPY;
      /* falls through */
      case COPY:
        copy = state.length;
        if (copy) {
          if (copy > have) {
            copy = have;
          }
          if (copy > left) {
            copy = left;
          }
          if (copy === 0) {
            break inf_leave;
          }
          //--- zmemcpy(put, next, copy); ---
          utils.arraySet(output, input, next, copy, put);
          //---//
          have -= copy;
          next += copy;
          left -= copy;
          put += copy;
          state.length -= copy;
          break;
        }
        //Tracev((stderr, "inflate:       stored end\n"));
        state.mode = TYPE;
        break;
      case TABLE:
        //=== NEEDBITS(14); */
        while (bits < 14) {
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
        }
        //===//
        state.nlen = (hold & 0x1f) + /*BITS(5)*/257;
        //--- DROPBITS(5) ---//
        hold >>>= 5;
        bits -= 5;
        //---//
        state.ndist = (hold & 0x1f) + /*BITS(5)*/1;
        //--- DROPBITS(5) ---//
        hold >>>= 5;
        bits -= 5;
        //---//
        state.ncode = (hold & 0x0f) + /*BITS(4)*/4;
        //--- DROPBITS(4) ---//
        hold >>>= 4;
        bits -= 4;
        //---//
        //#ifndef PKZIP_BUG_WORKAROUND
        if (state.nlen > 286 || state.ndist > 30) {
          strm.msg = 'too many length or distance symbols';
          state.mode = BAD;
          break;
        }
        //#endif
        //Tracev((stderr, "inflate:       table sizes ok\n"));
        state.have = 0;
        state.mode = LENLENS;
      /* falls through */
      case LENLENS:
        while (state.have < state.ncode) {
          //=== NEEDBITS(3);
          while (bits < 3) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          state.lens[order[state.have++]] = hold & 0x07; //BITS(3);
          //--- DROPBITS(3) ---//
          hold >>>= 3;
          bits -= 3;
          //---//
        }
        while (state.have < 19) {
          state.lens[order[state.have++]] = 0;
        }
        // We have separate tables & no pointers. 2 commented lines below not needed.
        //state.next = state.codes;
        //state.lencode = state.next;
        // Switch to use dynamic table
        state.lencode = state.lendyn;
        state.lenbits = 7;

        opts = { bits: state.lenbits };
        ret = (0, _inftrees2.default)(CODES, state.lens, 0, 19, state.lencode, 0, state.work, opts);
        state.lenbits = opts.bits;

        if (ret) {
          strm.msg = 'invalid code lengths set';
          state.mode = BAD;
          break;
        }
        //Tracev((stderr, "inflate:       code lengths ok\n"));
        state.have = 0;
        state.mode = CODELENS;
      /* falls through */
      case CODELENS:
        while (state.have < state.nlen + state.ndist) {
          for (;;) {
            here = state.lencode[hold & (1 << state.lenbits) - 1]; /*BITS(state.lenbits)*/
            here_bits = here >>> 24;
            here_op = here >>> 16 & 0xff;
            here_val = here & 0xffff;

            if (here_bits <= bits) {
              break;
            }
            //--- PULLBYTE() ---//
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
            //---//
          }
          if (here_val < 16) {
            //--- DROPBITS(here.bits) ---//
            hold >>>= here_bits;
            bits -= here_bits;
            //---//
            state.lens[state.have++] = here_val;
          } else {
            if (here_val === 16) {
              //=== NEEDBITS(here.bits + 2);
              n = here_bits + 2;
              while (bits < n) {
                if (have === 0) {
                  break inf_leave;
                }
                have--;
                hold += input[next++] << bits;
                bits += 8;
              }
              //===//
              //--- DROPBITS(here.bits) ---//
              hold >>>= here_bits;
              bits -= here_bits;
              //---//
              if (state.have === 0) {
                strm.msg = 'invalid bit length repeat';
                state.mode = BAD;
                break;
              }
              len = state.lens[state.have - 1];
              copy = 3 + (hold & 0x03); //BITS(2);
              //--- DROPBITS(2) ---//
              hold >>>= 2;
              bits -= 2;
              //---//
            } else if (here_val === 17) {
              //=== NEEDBITS(here.bits + 3);
              n = here_bits + 3;
              while (bits < n) {
                if (have === 0) {
                  break inf_leave;
                }
                have--;
                hold += input[next++] << bits;
                bits += 8;
              }
              //===//
              //--- DROPBITS(here.bits) ---//
              hold >>>= here_bits;
              bits -= here_bits;
              //---//
              len = 0;
              copy = 3 + (hold & 0x07); //BITS(3);
              //--- DROPBITS(3) ---//
              hold >>>= 3;
              bits -= 3;
              //---//
            } else {
              //=== NEEDBITS(here.bits + 7);
              n = here_bits + 7;
              while (bits < n) {
                if (have === 0) {
                  break inf_leave;
                }
                have--;
                hold += input[next++] << bits;
                bits += 8;
              }
              //===//
              //--- DROPBITS(here.bits) ---//
              hold >>>= here_bits;
              bits -= here_bits;
              //---//
              len = 0;
              copy = 11 + (hold & 0x7f); //BITS(7);
              //--- DROPBITS(7) ---//
              hold >>>= 7;
              bits -= 7;
              //---//
            }
            if (state.have + copy > state.nlen + state.ndist) {
              strm.msg = 'invalid bit length repeat';
              state.mode = BAD;
              break;
            }
            while (copy--) {
              state.lens[state.have++] = len;
            }
          }
        }

        /* handle error breaks in while */
        if (state.mode === BAD) {
          break;
        }

        /* check for end-of-block code (better have one) */
        if (state.lens[256] === 0) {
          strm.msg = 'invalid code -- missing end-of-block';
          state.mode = BAD;
          break;
        }

        /* build code tables -- note: do not change the lenbits or distbits
           values here (9 and 6) without reading the comments in inftrees.h
           concerning the ENOUGH constants, which depend on those values */
        state.lenbits = 9;

        opts = { bits: state.lenbits };
        ret = (0, _inftrees2.default)(LENS, state.lens, 0, state.nlen, state.lencode, 0, state.work, opts);
        // We have separate tables & no pointers. 2 commented lines below not needed.
        // state.next_index = opts.table_index;
        state.lenbits = opts.bits;
        // state.lencode = state.next;

        if (ret) {
          strm.msg = 'invalid literal/lengths set';
          state.mode = BAD;
          break;
        }

        state.distbits = 6;
        //state.distcode.copy(state.codes);
        // Switch to use dynamic table
        state.distcode = state.distdyn;
        opts = { bits: state.distbits };
        ret = (0, _inftrees2.default)(DISTS, state.lens, state.nlen, state.ndist, state.distcode, 0, state.work, opts);
        // We have separate tables & no pointers. 2 commented lines below not needed.
        // state.next_index = opts.table_index;
        state.distbits = opts.bits;
        // state.distcode = state.next;

        if (ret) {
          strm.msg = 'invalid distances set';
          state.mode = BAD;
          break;
        }
        //Tracev((stderr, 'inflate:       codes ok\n'));
        state.mode = LEN_;
        if (flush === Z_TREES) {
          break inf_leave;
        }
      /* falls through */
      case LEN_:
        state.mode = LEN;
      /* falls through */
      case LEN:
        if (have >= 6 && left >= 258) {
          //--- RESTORE() ---
          strm.next_out = put;
          strm.avail_out = left;
          strm.next_in = next;
          strm.avail_in = have;
          state.hold = hold;
          state.bits = bits;
          //---
          (0, _inffast2.default)(strm, _out);
          //--- LOAD() ---
          put = strm.next_out;
          output = strm.output;
          left = strm.avail_out;
          next = strm.next_in;
          input = strm.input;
          have = strm.avail_in;
          hold = state.hold;
          bits = state.bits;
          //---

          if (state.mode === TYPE) {
            state.back = -1;
          }
          break;
        }
        state.back = 0;
        for (;;) {
          here = state.lencode[hold & (1 << state.lenbits) - 1]; /*BITS(state.lenbits)*/
          here_bits = here >>> 24;
          here_op = here >>> 16 & 0xff;
          here_val = here & 0xffff;

          if (here_bits <= bits) {
            break;
          }
          //--- PULLBYTE() ---//
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
          //---//
        }
        if (here_op && (here_op & 0xf0) === 0) {
          last_bits = here_bits;
          last_op = here_op;
          last_val = here_val;
          for (;;) {
            here = state.lencode[last_val + ((hold & (1 << last_bits + last_op) - 1) >> /*BITS(last.bits + last.op)*/last_bits)];
            here_bits = here >>> 24;
            here_op = here >>> 16 & 0xff;
            here_val = here & 0xffff;

            if (last_bits + here_bits <= bits) {
              break;
            }
            //--- PULLBYTE() ---//
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
            //---//
          }
          //--- DROPBITS(last.bits) ---//
          hold >>>= last_bits;
          bits -= last_bits;
          //---//
          state.back += last_bits;
        }
        //--- DROPBITS(here.bits) ---//
        hold >>>= here_bits;
        bits -= here_bits;
        //---//
        state.back += here_bits;
        state.length = here_val;
        if (here_op === 0) {
          //Tracevv((stderr, here.val >= 0x20 && here.val < 0x7f ?
          //        "inflate:         literal '%c'\n" :
          //        "inflate:         literal 0x%02x\n", here.val));
          state.mode = LIT;
          break;
        }
        if (here_op & 32) {
          //Tracevv((stderr, "inflate:         end of block\n"));
          state.back = -1;
          state.mode = TYPE;
          break;
        }
        if (here_op & 64) {
          strm.msg = 'invalid literal/length code';
          state.mode = BAD;
          break;
        }
        state.extra = here_op & 15;
        state.mode = LENEXT;
      /* falls through */
      case LENEXT:
        if (state.extra) {
          //=== NEEDBITS(state.extra);
          n = state.extra;
          while (bits < n) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          state.length += hold & (1 << state.extra) - 1 /*BITS(state.extra)*/;
          //--- DROPBITS(state.extra) ---//
          hold >>>= state.extra;
          bits -= state.extra;
          //---//
          state.back += state.extra;
        }
        //Tracevv((stderr, "inflate:         length %u\n", state.length));
        state.was = state.length;
        state.mode = DIST;
      /* falls through */
      case DIST:
        for (;;) {
          here = state.distcode[hold & (1 << state.distbits) - 1]; /*BITS(state.distbits)*/
          here_bits = here >>> 24;
          here_op = here >>> 16 & 0xff;
          here_val = here & 0xffff;

          if (here_bits <= bits) {
            break;
          }
          //--- PULLBYTE() ---//
          if (have === 0) {
            break inf_leave;
          }
          have--;
          hold += input[next++] << bits;
          bits += 8;
          //---//
        }
        if ((here_op & 0xf0) === 0) {
          last_bits = here_bits;
          last_op = here_op;
          last_val = here_val;
          for (;;) {
            here = state.distcode[last_val + ((hold & (1 << last_bits + last_op) - 1) >> /*BITS(last.bits + last.op)*/last_bits)];
            here_bits = here >>> 24;
            here_op = here >>> 16 & 0xff;
            here_val = here & 0xffff;

            if (last_bits + here_bits <= bits) {
              break;
            }
            //--- PULLBYTE() ---//
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
            //---//
          }
          //--- DROPBITS(last.bits) ---//
          hold >>>= last_bits;
          bits -= last_bits;
          //---//
          state.back += last_bits;
        }
        //--- DROPBITS(here.bits) ---//
        hold >>>= here_bits;
        bits -= here_bits;
        //---//
        state.back += here_bits;
        if (here_op & 64) {
          strm.msg = 'invalid distance code';
          state.mode = BAD;
          break;
        }
        state.offset = here_val;
        state.extra = here_op & 15;
        state.mode = DISTEXT;
      /* falls through */
      case DISTEXT:
        if (state.extra) {
          //=== NEEDBITS(state.extra);
          n = state.extra;
          while (bits < n) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          state.offset += hold & (1 << state.extra) - 1 /*BITS(state.extra)*/;
          //--- DROPBITS(state.extra) ---//
          hold >>>= state.extra;
          bits -= state.extra;
          //---//
          state.back += state.extra;
        }
        //#ifdef INFLATE_STRICT
        if (state.offset > state.dmax) {
          strm.msg = 'invalid distance too far back';
          state.mode = BAD;
          break;
        }
        //#endif
        //Tracevv((stderr, "inflate:         distance %u\n", state.offset));
        state.mode = MATCH;
      /* falls through */
      case MATCH:
        if (left === 0) {
          break inf_leave;
        }
        copy = _out - left;
        if (state.offset > copy) {
          /* copy from window */
          copy = state.offset - copy;
          if (copy > state.whave) {
            if (state.sane) {
              strm.msg = 'invalid distance too far back';
              state.mode = BAD;
              break;
            }
            // (!) This block is disabled in zlib defailts,
            // don't enable it for binary compatibility
            //#ifdef INFLATE_ALLOW_INVALID_DISTANCE_TOOFAR_ARRR
            //          Trace((stderr, "inflate.c too far\n"));
            //          copy -= state.whave;
            //          if (copy > state.length) { copy = state.length; }
            //          if (copy > left) { copy = left; }
            //          left -= copy;
            //          state.length -= copy;
            //          do {
            //            output[put++] = 0;
            //          } while (--copy);
            //          if (state.length === 0) { state.mode = LEN; }
            //          break;
            //#endif
          }
          if (copy > state.wnext) {
            copy -= state.wnext;
            from = state.wsize - copy;
          } else {
            from = state.wnext - copy;
          }
          if (copy > state.length) {
            copy = state.length;
          }
          from_source = state.window;
        } else {
          /* copy from output */
          from_source = output;
          from = put - state.offset;
          copy = state.length;
        }
        if (copy > left) {
          copy = left;
        }
        left -= copy;
        state.length -= copy;
        do {
          output[put++] = from_source[from++];
        } while (--copy);
        if (state.length === 0) {
          state.mode = LEN;
        }
        break;
      case LIT:
        if (left === 0) {
          break inf_leave;
        }
        output[put++] = state.length;
        left--;
        state.mode = LEN;
        break;
      case CHECK:
        if (state.wrap) {
          //=== NEEDBITS(32);
          while (bits < 32) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            // Use '|' insdead of '+' to make sure that result is signed
            hold |= input[next++] << bits;
            bits += 8;
          }
          //===//
          _out -= left;
          strm.total_out += _out;
          state.total += _out;
          if (_out) {
            strm.adler = state.check =
            /*UPDATE(state.check, put - _out, _out);*/
            state.flags ? (0, _crc2.default)(state.check, output, _out, put - _out) : (0, _adler2.default)(state.check, output, _out, put - _out);
          }
          _out = left;
          // NB: crc32 stored as signed 32-bit int, zswap32 returns signed too
          if ((state.flags ? hold : zswap32(hold)) !== state.check) {
            strm.msg = 'incorrect data check';
            state.mode = BAD;
            break;
          }
          //=== INITBITS();
          hold = 0;
          bits = 0;
          //===//
          //Tracev((stderr, "inflate:   check matches trailer\n"));
        }
        state.mode = LENGTH;
      /* falls through */
      case LENGTH:
        if (state.wrap && state.flags) {
          //=== NEEDBITS(32);
          while (bits < 32) {
            if (have === 0) {
              break inf_leave;
            }
            have--;
            hold += input[next++] << bits;
            bits += 8;
          }
          //===//
          if (hold !== (state.total & 0xffffffff)) {
            strm.msg = 'incorrect length check';
            state.mode = BAD;
            break;
          }
          //=== INITBITS();
          hold = 0;
          bits = 0;
          //===//
          //Tracev((stderr, "inflate:   length matches trailer\n"));
        }
        state.mode = DONE;
      /* falls through */
      case DONE:
        ret = Z_STREAM_END;
        break inf_leave;
      case BAD:
        ret = Z_DATA_ERROR;
        break inf_leave;
      case MEM:
        return Z_MEM_ERROR;
      case SYNC:
      /* falls through */
      default:
        return Z_STREAM_ERROR;
    }
  }

  // inf_leave <- here is real place for "goto inf_leave", emulated via "break inf_leave"

  /*
     Return from inflate(), updating the total counts and the check value.
     If there was no progress during the inflate() call, return a buffer
     error.  Call updatewindow() to create and/or update the window state.
     Note: a memory error from inflate() is non-recoverable.
   */

  //--- RESTORE() ---
  strm.next_out = put;
  strm.avail_out = left;
  strm.next_in = next;
  strm.avail_in = have;
  state.hold = hold;
  state.bits = bits;
  //---

  if (state.wsize || _out !== strm.avail_out && state.mode < BAD && (state.mode < CHECK || flush !== Z_FINISH)) {
    if (updatewindow(strm, strm.output, strm.next_out, _out - strm.avail_out)) {
      state.mode = MEM;
      return Z_MEM_ERROR;
    }
  }
  _in -= strm.avail_in;
  _out -= strm.avail_out;
  strm.total_in += _in;
  strm.total_out += _out;
  state.total += _out;
  if (state.wrap && _out) {
    strm.adler = state.check = /*UPDATE(state.check, strm.next_out - _out, _out);*/
    state.flags ? (0, _crc2.default)(state.check, output, _out, strm.next_out - _out) : (0, _adler2.default)(state.check, output, _out, strm.next_out - _out);
  }
  strm.data_type = state.bits + (state.last ? 64 : 0) + (state.mode === TYPE ? 128 : 0) + (state.mode === LEN_ || state.mode === COPY_ ? 256 : 0);
  if ((_in === 0 && _out === 0 || flush === Z_FINISH) && ret === Z_OK) {
    ret = Z_BUF_ERROR;
  }
  return ret;
}

function inflateEnd(strm) {

  if (!strm || !strm.state /*|| strm->zfree == (free_func)0*/) {
      return Z_STREAM_ERROR;
    }

  var state = strm.state;
  if (state.window) {
    state.window = null;
  }
  strm.state = null;
  return Z_OK;
}

function inflateGetHeader(strm, head) {
  var state;

  /* check state */
  if (!strm || !strm.state) {
    return Z_STREAM_ERROR;
  }
  state = strm.state;
  if ((state.wrap & 2) === 0) {
    return Z_STREAM_ERROR;
  }

  /* save header structure */
  state.head = head;
  head.done = false;
  return Z_OK;
}

function inflateSetDictionary(strm, dictionary) {
  var dictLength = dictionary.length;

  var state;
  var dictid;
  var ret;

  /* check state */
  if (!strm /* == Z_NULL */ || !strm.state /* == Z_NULL */) {
      return Z_STREAM_ERROR;
    }
  state = strm.state;

  if (state.wrap !== 0 && state.mode !== DICT) {
    return Z_STREAM_ERROR;
  }

  /* check for correct dictionary identifier */
  if (state.mode === DICT) {
    dictid = 1; /* adler32(0, null, 0)*/
    /* dictid = adler32(dictid, dictionary, dictLength); */
    dictid = (0, _adler2.default)(dictid, dictionary, dictLength, 0);
    if (dictid !== state.check) {
      return Z_DATA_ERROR;
    }
  }
  /* copy dictionary to window using updatewindow(), which will amend the
   existing dictionary if appropriate */
  ret = updatewindow(strm, dictionary, dictLength, dictLength);
  if (ret) {
    state.mode = MEM;
    return Z_MEM_ERROR;
  }
  state.havedict = 1;
  // Tracev((stderr, "inflate:   dictionary set\n"));
  return Z_OK;
}

exports.inflateReset = inflateReset;
exports.inflateReset2 = inflateReset2;
exports.inflateResetKeep = inflateResetKeep;
exports.inflateInit = inflateInit;
exports.inflateInit2 = inflateInit2;
exports.inflate = inflate;
exports.inflateEnd = inflateEnd;
exports.inflateGetHeader = inflateGetHeader;
exports.inflateSetDictionary = inflateSetDictionary;
var inflateInfo = exports.inflateInfo = 'pako inflate (from Nodeca project)';

/* Not implemented
exports.inflateCopy = inflateCopy;
exports.inflateGetDictionary = inflateGetDictionary;
exports.inflateMark = inflateMark;
exports.inflatePrime = inflatePrime;
exports.inflateSync = inflateSync;
exports.inflateSyncPoint = inflateSyncPoint;
exports.inflateUndermine = inflateUndermine;
*/
},{"../utils/common.js":26,"./adler32.js":27,"./crc32.js":28,"./inffast.js":29,"./inftrees.js":31}],31:[function(require,module,exports){
"use strict";

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = inflate_table;

var _common = require("../utils/common.js");

var utils = _interopRequireWildcard(_common);

function _interopRequireWildcard(obj) { if (obj && obj.__esModule) { return obj; } else { var newObj = {}; if (obj != null) { for (var key in obj) { if (Object.prototype.hasOwnProperty.call(obj, key)) newObj[key] = obj[key]; } } newObj.default = obj; return newObj; } }

var MAXBITS = 15;
var ENOUGH_LENS = 852;
var ENOUGH_DISTS = 592;
//var ENOUGH = (ENOUGH_LENS+ENOUGH_DISTS);

var CODES = 0;
var LENS = 1;
var DISTS = 2;

var lbase = [/* Length codes 257..285 base */
3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258, 0, 0];

var lext = [/* Length codes 257..285 extra */
16, 16, 16, 16, 16, 16, 16, 16, 17, 17, 17, 17, 18, 18, 18, 18, 19, 19, 19, 19, 20, 20, 20, 20, 21, 21, 21, 21, 16, 72, 78];

var dbase = [/* Distance codes 0..29 base */
1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577, 0, 0];

var dext = [/* Distance codes 0..29 extra */
16, 16, 16, 16, 17, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 23, 24, 24, 25, 25, 26, 26, 27, 27, 28, 28, 29, 29, 64, 64];

function inflate_table(type, lens, lens_index, codes, table, table_index, work, opts) {
  var bits = opts.bits;
  //here = opts.here; /* table entry for duplication */

  var len = 0; /* a code's length in bits */
  var sym = 0; /* index of code symbols */
  var min = 0,
      max = 0; /* minimum and maximum code lengths */
  var root = 0; /* number of index bits for root table */
  var curr = 0; /* number of index bits for current table */
  var drop = 0; /* code bits to drop for sub-table */
  var left = 0; /* number of prefix codes available */
  var used = 0; /* code entries in table used */
  var huff = 0; /* Huffman code */
  var incr; /* for incrementing code, index */
  var fill; /* index for replicating entries */
  var low; /* low bits for current root entry */
  var mask; /* mask for low root bits */
  var next; /* next available space in table */
  var base = null; /* base value table to use */
  var base_index = 0;
  //  var shoextra;    /* extra bits table to use */
  var end; /* use base and extra for symbol > end */
  var count = new utils.Buf16(MAXBITS + 1); //[MAXBITS+1];    /* number of codes of each length */
  var offs = new utils.Buf16(MAXBITS + 1); //[MAXBITS+1];     /* offsets in table for each length */
  var extra = null;
  var extra_index = 0;

  var here_bits, here_op, here_val;

  /*
   Process a set of code lengths to create a canonical Huffman code.  The
   code lengths are lens[0..codes-1].  Each length corresponds to the
   symbols 0..codes-1.  The Huffman code is generated by first sorting the
   symbols by length from short to long, and retaining the symbol order
   for codes with equal lengths.  Then the code starts with all zero bits
   for the first code of the shortest length, and the codes are integer
   increments for the same length, and zeros are appended as the length
   increases.  For the deflate format, these bits are stored backwards
   from their more natural integer increment ordering, and so when the
   decoding tables are built in the large loop below, the integer codes
   are incremented backwards.
    This routine assumes, but does not check, that all of the entries in
   lens[] are in the range 0..MAXBITS.  The caller must assure this.
   1..MAXBITS is interpreted as that code length.  zero means that that
   symbol does not occur in this code.
    The codes are sorted by computing a count of codes for each length,
   creating from that a table of starting indices for each length in the
   sorted table, and then entering the symbols in order in the sorted
   table.  The sorted table is work[], with that space being provided by
   the caller.
    The length counts are used for other purposes as well, i.e. finding
   the minimum and maximum length codes, determining if there are any
   codes at all, checking for a valid set of lengths, and looking ahead
   at length counts to determine sub-table sizes when building the
   decoding tables.
   */

  /* accumulate lengths for codes (assumes lens[] all in 0..MAXBITS) */
  for (len = 0; len <= MAXBITS; len++) {
    count[len] = 0;
  }
  for (sym = 0; sym < codes; sym++) {
    count[lens[lens_index + sym]]++;
  }

  /* bound code lengths, force root to be within code lengths */
  root = bits;
  for (max = MAXBITS; max >= 1; max--) {
    if (count[max] !== 0) {
      break;
    }
  }
  if (root > max) {
    root = max;
  }
  if (max === 0) {
    /* no symbols to code at all */
    //table.op[opts.table_index] = 64;  //here.op = (var char)64;    /* invalid code marker */
    //table.bits[opts.table_index] = 1;   //here.bits = (var char)1;
    //table.val[opts.table_index++] = 0;   //here.val = (var short)0;
    table[table_index++] = 1 << 24 | 64 << 16 | 0;

    //table.op[opts.table_index] = 64;
    //table.bits[opts.table_index] = 1;
    //table.val[opts.table_index++] = 0;
    table[table_index++] = 1 << 24 | 64 << 16 | 0;

    opts.bits = 1;
    return 0; /* no symbols, but wait for decoding to report error */
  }
  for (min = 1; min < max; min++) {
    if (count[min] !== 0) {
      break;
    }
  }
  if (root < min) {
    root = min;
  }

  /* check for an over-subscribed or incomplete set of lengths */
  left = 1;
  for (len = 1; len <= MAXBITS; len++) {
    left <<= 1;
    left -= count[len];
    if (left < 0) {
      return -1;
    } /* over-subscribed */
  }
  if (left > 0 && (type === CODES || max !== 1)) {
    return -1; /* incomplete set */
  }

  /* generate offsets into symbol table for each length for sorting */
  offs[1] = 0;
  for (len = 1; len < MAXBITS; len++) {
    offs[len + 1] = offs[len] + count[len];
  }

  /* sort symbols by length, by symbol order within each length */
  for (sym = 0; sym < codes; sym++) {
    if (lens[lens_index + sym] !== 0) {
      work[offs[lens[lens_index + sym]]++] = sym;
    }
  }

  /*
   Create and fill in decoding tables.  In this loop, the table being
   filled is at next and has curr index bits.  The code being used is huff
   with length len.  That code is converted to an index by dropping drop
   bits off of the bottom.  For codes where len is less than drop + curr,
   those top drop + curr - len bits are incremented through all values to
   fill the table with replicated entries.
    root is the number of index bits for the root table.  When len exceeds
   root, sub-tables are created pointed to by the root entry with an index
   of the low root bits of huff.  This is saved in low to check for when a
   new sub-table should be started.  drop is zero when the root table is
   being filled, and drop is root when sub-tables are being filled.
    When a new sub-table is needed, it is necessary to look ahead in the
   code lengths to determine what size sub-table is needed.  The length
   counts are used for this, and so count[] is decremented as codes are
   entered in the tables.
    used keeps track of how many table entries have been allocated from the
   provided *table space.  It is checked for LENS and DIST tables against
   the constants ENOUGH_LENS and ENOUGH_DISTS to guard against changes in
   the initial root table size constants.  See the comments in inftrees.h
   for more information.
    sym increments through all symbols, and the loop terminates when
   all codes of length max, i.e. all codes, have been processed.  This
   routine permits incomplete codes, so another loop after this one fills
   in the rest of the decoding tables with invalid code markers.
   */

  /* set up for code type */
  // poor man optimization - use if-else instead of switch,
  // to avoid deopts in old v8
  if (type === CODES) {
    base = extra = work; /* dummy value--not used */
    end = 19;
  } else if (type === LENS) {
    base = lbase;
    base_index -= 257;
    extra = lext;
    extra_index -= 257;
    end = 256;
  } else {
    /* DISTS */
    base = dbase;
    extra = dext;
    end = -1;
  }

  /* initialize opts for loop */
  huff = 0; /* starting code */
  sym = 0; /* starting code symbol */
  len = min; /* starting code length */
  next = table_index; /* current table to fill in */
  curr = root; /* current table index bits */
  drop = 0; /* current bits to drop from code for index */
  low = -1; /* trigger new sub-table when len > root */
  used = 1 << root; /* use root table entries */
  mask = used - 1; /* mask for comparing low */

  /* check available table space */
  if (type === LENS && used > ENOUGH_LENS || type === DISTS && used > ENOUGH_DISTS) {
    return 1;
  }

  /* process all codes and make table entries */
  for (;;) {
    /* create table entry */
    here_bits = len - drop;
    if (work[sym] < end) {
      here_op = 0;
      here_val = work[sym];
    } else if (work[sym] > end) {
      here_op = extra[extra_index + work[sym]];
      here_val = base[base_index + work[sym]];
    } else {
      here_op = 32 + 64; /* end of block */
      here_val = 0;
    }

    /* replicate for those indices with low len bits equal to huff */
    incr = 1 << len - drop;
    fill = 1 << curr;
    min = fill; /* save offset to next table */
    do {
      fill -= incr;
      table[next + (huff >> drop) + fill] = here_bits << 24 | here_op << 16 | here_val | 0;
    } while (fill !== 0);

    /* backwards increment the len-bit code huff */
    incr = 1 << len - 1;
    while (huff & incr) {
      incr >>= 1;
    }
    if (incr !== 0) {
      huff &= incr - 1;
      huff += incr;
    } else {
      huff = 0;
    }

    /* go to next symbol, update count, len */
    sym++;
    if (--count[len] === 0) {
      if (len === max) {
        break;
      }
      len = lens[lens_index + work[sym]];
    }

    /* create new sub-table if needed */
    if (len > root && (huff & mask) !== low) {
      /* if first time, transition to sub-tables */
      if (drop === 0) {
        drop = root;
      }

      /* increment past last table */
      next += min; /* here min is 1 << curr */

      /* determine length of next table */
      curr = len - drop;
      left = 1 << curr;
      while (curr + drop < max) {
        left -= count[curr + drop];
        if (left <= 0) {
          break;
        }
        curr++;
        left <<= 1;
      }

      /* check for enough space */
      used += 1 << curr;
      if (type === LENS && used > ENOUGH_LENS || type === DISTS && used > ENOUGH_DISTS) {
        return 1;
      }

      /* point entry in root table to sub-table */
      low = huff & mask;
      /*table.op[low] = curr;
      table.bits[low] = root;
      table.val[low] = next - opts.table_index;*/
      table[low] = root << 24 | curr << 16 | next - table_index | 0;
    }
  }

  /* fill in remaining table entry if code is incomplete (guaranteed to have
   at most one remaining entry, since if the code is incomplete, the
   maximum code length that was allowed to get this far is one bit) */
  if (huff !== 0) {
    //table.op[next + huff] = 64;            /* invalid code marker */
    //table.bits[next + huff] = len - drop;
    //table.val[next + huff] = 0;
    table[next + huff] = len - drop << 24 | 64 << 16 | 0;
  }

  /* set return parameters */
  //opts.table_index += used;
  opts.bits = root;
  return 0;
};
},{"../utils/common.js":26}],32:[function(require,module,exports){
'use strict';

Object.defineProperty(exports, "__esModule", {
  value: true
});
exports.default = ZStream;
function ZStream() {
  /* next input byte */
  this.input = null; // JS specific, because we have no pointers
  this.next_in = 0;
  /* number of bytes available at input */
  this.avail_in = 0;
  /* total number of input bytes read so far */
  this.total_in = 0;
  /* next output byte should be put there */
  this.output = null; // JS specific, because we have no pointers
  this.next_out = 0;
  /* remaining free space at output */
  this.avail_out = 0;
  /* total number of bytes output so far */
  this.total_out = 0;
  /* last error message, NULL if no error */
  this.msg = '' /*Z_NULL*/;
  /* not visible by applications */
  this.state = null;
  /* best guess about the data type: binary or text */
  this.data_type = 2 /*Z_UNKNOWN*/;
  /* adler32 value of the uncompressed data */
  this.adler = 0;
}
},{}]},{},[2]);
