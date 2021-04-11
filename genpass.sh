#!/bin/bash
rm -rf    webvirtcloud/settings.py
cp -arpf  webvirtcloud/settings.py.template webvirtcloud/settings.py
python conf/runit/secret_generator.py

sed -r "s/SECRET_KEY = \"\"/SECRET_KEY = \"`python3 conf/runit/secret_generator.py`\"/"  -i webvirtcloud/settings.py; cat webvirtcloud/settings.py|grep SECRET_KEY
