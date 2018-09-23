#!/bin/bash
set -e

docker exec -it \
        -e DJANGO_SETTINGS_MODULE=webvirtcloud.settings.dev \
        $(docker-compose ps -q app) bash