#!/bin/bash
set -e

APP_DIR="/srv/webvirtcloud"
DATA_DIR="$APP_DIR/data"
mkdir -p "$DATA_DIR" "/var/www/.ssh"

# If settings.py doesn't exist, generate from template
if [ ! -f "$APP_DIR/webvirtcloud/settings.py" ]; then
    echo "* Generating webvirtcloud/settings.py from template..."
    cp "$APP_DIR/webvirtcloud/settings.py.template" "$APP_DIR/webvirtcloud/settings.py"
fi

# Ensure SECRET_KEY is persisted across container restarts if not supplied via environment
if [ -z "$SECRET_KEY" ]; then
    if [ ! -s "$DATA_DIR/secret_key" ]; then
        echo "* Generating fresh random SECRET_KEY..."
        "$APP_DIR/venv/bin/python3" -c 'import secrets; print(secrets.token_urlsafe(50))' > "$DATA_DIR/secret_key"
        chmod 600 "$DATA_DIR/secret_key"
    fi
fi

# Persist SQLite database in DATA_DIR
if [ ! -f "$DATA_DIR/db.sqlite3" ] && [ -f "$APP_DIR/db.sqlite3" ] && [ ! -L "$APP_DIR/db.sqlite3" ]; then
    mv "$APP_DIR/db.sqlite3" "$DATA_DIR/db.sqlite3"
fi
touch "$DATA_DIR/db.sqlite3"
ln -sf "$DATA_DIR/db.sqlite3" "$APP_DIR/db.sqlite3"

# Run database migrations
echo "* Running database migrations..."
"$APP_DIR/venv/bin/python3" "$APP_DIR/manage.py" migrate --noinput

# Set proper permissions on runtime and data directories
chown -R www-data:www-data "$DATA_DIR" "/var/www/.ssh"
chown www-data:www-data "$APP_DIR/webvirtcloud/settings.py" 2>/dev/null || true
chmod 700 "/var/www/.ssh" 2>/dev/null || true
