"use strict";
/*
   Copyright (C) 2016 by Oliver Gutierrez <ogutsua@gmail.com>
                         Miroslav Chodil <mchodil@redhat.com>

   This file is part of spice-html5.

   spice-html5 is free software: you can redistribute it and/or modify
   it under the terms of the GNU Lesser General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   spice-html5 is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU Lesser General Public License for more details.

   You should have received a copy of the GNU Lesser General Public License
   along with spice-html5.  If not, see <http://www.gnu.org/licenses/>.
*/

import { Constants } from './enums.js';
import { DEBUG } from './utils.js';
import { SpiceConn } from './spiceconn.js';
import { SpiceMsgPortInit } from './spicemsg.js';

/*----------------------------------------------------------------------------
**  SpicePortConn
**      Drive the Spice Port Channel
**--------------------------------------------------------------------------*/
function SpicePortConn()
{
    DEBUG > 0 && console.log('SPICE port: created SPICE port channel. Args:', arguments);
    SpiceConn.apply(this, arguments);
    this.port_name = null;
}

SpicePortConn.prototype = Object.create(SpiceConn.prototype);

SpicePortConn.prototype.process_channel_message = function(msg)
{
    if (msg.type == Constants.SPICE_MSG_PORT_INIT)
    {
        if (this.port_name === null)
        {
            var m = new SpiceMsgPortInit(msg.data);
            this.portName = arraybuffer_to_str(new Uint8Array(m.name));
            this.portOpened = m.opened
            DEBUG > 0 && console.log('SPICE port: Port', this.portName, 'initialized');
            return true;
        }

        DEBUG > 0 && console.log('SPICE port: Port', this.port_name, 'is already initialized.');
    }
    else if (msg.type == Constants.SPICE_MSG_PORT_EVENT)
    {
        DEBUG > 0 && console.log('SPICE port: Port event received for', this.portName, msg);
        var event = new CustomEvent('spice-port-event', {
            detail: {
                channel: this,
                spiceEvent: new Uint8Array(msg.data)
            },
            bubbles: true,
            cancelable: true
        });

        window.dispatchEvent(event);
        return true;
    }
    else if (msg.type == Constants.SPICE_MSG_SPICEVMC_DATA)
    {
        DEBUG > 0 && console.log('SPICE port: Data received in port', this.portName, msg);
        var event = new CustomEvent('spice-port-data', {
            detail: {
                channel: this,
                data: msg.data
            },
            bubbles: true,
            cancelable: true
        });
        window.dispatchEvent(event);
        return true;
    }
    else
    {
        DEBUG > 0 && console.log('SPICE port: SPICE message type not recognized:', msg)
    }

    return false;
};

export {
  SpicePortConn,
};
