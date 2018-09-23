#!/bin/bash
set -e

docker exec -it \
        -e PYTHONOPTIMIZE=1 \
        -e DJANGO_SETTINGS_MODULE=webvirtcloud.settings.dev \
        $(docker-compose ps -q app) celery -A webvirtcloud worker -E -l INFO
