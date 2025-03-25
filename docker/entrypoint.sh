#!/bin/sh

set -e  # Exit on error

echo "Running with DEBUG=$DEBUG"

cd /opt/uniticket

# Ensure settings file is only copied if it does not exist
if [ ! -f /opt/uniticket/uni_ticket_project/settingslocal.py ]; then
    echo "Copying settings file..."
    cp /opt/uniticket/uni_ticket_project/settingslocal.py.example /opt/uniticket/uni_ticket_project/settingslocal.py
fi

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate --noinput

# Collect static files (always needed for production)
echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Compiling messages..."
python manage.py compilemessages

# Start the appropriate server
if [ $# -eq 0 ]; then
    case "$DEBUG" in
        "1"|"true"|"TRUE"|"True")
            echo "Starting Django in DEBUG mode..."
            exec python manage.py runserver 0.0.0.0:8000
            ;;
        *)
            echo "Starting uWSGI in PRODUCTION mode..."
            exec uwsgi --ini /etc/uwsgi/uwsgi.ini
            ;;
    esac
else
    # If arguments are provided, execute them instead of the default behavior
    echo "Executing custom command: $@"
    exec "$@"
fi
