#!/bin/bash
set -e

docker-compose stop
docker build -t wvcapp .
docker-compose up -d --no-deps --build app
docker-compose start
