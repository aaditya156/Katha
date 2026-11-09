#!/bin/sh
set -e

echo "Applying database migrations..."
alembic upgrade head || echo "Migration command completed with status $?"

echo "Starting Katha Studio application server..."
exec "$@"

