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

# Set SECRET_KEY if placeholder exists
if grep -q 'SECRET_KEY = ""' "$APP_DIR/webvirtcloud/settings.py" || grep -q "SECRET_KEY = ''" "$APP_DIR/webvirtcloud/settings.py"; then
    KEY="${SECRET_KEY:-$("$APP_DIR/venv/bin/python3" -c 'import secrets; print(secrets.token_urlsafe(50))')}"
    sed -i "s|^SECRET_KEY = .*|SECRET_KEY = \"${KEY}\"|" "$APP_DIR/webvirtcloud/settings.py"
fi

# Configure CSRF_TRUSTED_ORIGINS if environment variable is set
if [ -n "$CSRF_TRUSTED_ORIGINS" ]; then
    echo "* Setting CSRF_TRUSTED_ORIGINS from environment..."
    origins=""
    IFS=',' read -ra ADDR <<< "$CSRF_TRUSTED_ORIGINS"
    for o in "${ADDR[@]}"; do
        clean_o=$(echo "$o" | xargs)
        [ -n "$clean_o" ] && origins="${origins}'${clean_o}', "
    done
    sed -i "s|^CSRF_TRUSTED_ORIGINS = .*|CSRF_TRUSTED_ORIGINS = [ ${origins} ]|" "$APP_DIR/webvirtcloud/settings.py"
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
