FROM nginx:alpine

RUN apk add --no-cache logrotate

COPY nginx_logformat.conf /etc/nginx/conf.d/00-logformat.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html.template
COPY envsubst-html.sh /docker-entrypoint.d/40-envsubst-html.sh
COPY logrotate-nginx.conf /etc/logrotate.d/nginx-access
COPY start-logrotate.sh /docker-entrypoint.d/50-start-logrotate.sh
RUN chmod +x /docker-entrypoint.d/40-envsubst-html.sh \
             /docker-entrypoint.d/50-start-logrotate.sh

ENV API_URL=http://localhost:8000

EXPOSE 80
