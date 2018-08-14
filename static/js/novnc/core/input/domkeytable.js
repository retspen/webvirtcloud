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