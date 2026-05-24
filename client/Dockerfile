FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html.template
COPY envsubst-html.sh /docker-entrypoint.d/40-envsubst-html.sh
RUN chmod +x /docker-entrypoint.d/40-envsubst-html.sh

ENV API_URL=http://localhost:8000

EXPOSE 80
