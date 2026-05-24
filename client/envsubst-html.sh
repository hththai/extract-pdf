#!/bin/sh
envsubst '${API_URL}' < /usr/share/nginx/html/index.html.template > /usr/share/nginx/html/index.html
