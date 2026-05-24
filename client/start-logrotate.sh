#!/bin/sh
# Run logrotate once at startup (catches any missed rotation), then daily.
logrotate /etc/logrotate.d/nginx-access 2>/dev/null || true
while true; do
    sleep 86400
    logrotate /etc/logrotate.d/nginx-access 2>/dev/null || true
done &
