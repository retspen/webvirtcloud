#!/bin/bash
set -e

docker exec -it $(docker-compose ps -q app) python3.6 -m smtpd -n -c DebuggingServer localhost:1025
