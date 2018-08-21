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