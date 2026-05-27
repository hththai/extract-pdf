#!/bin/sh
envsubst '${API_URL} ${POLL_INTERVAL_MS}' < /usr/share/nginx/html/index.html.template > /usr/share/nginx/html/index.html
