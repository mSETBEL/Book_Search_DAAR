FROM nginx:1.28-alpine

# Suppression de la configuration par défaut
RUN rm /etc/nginx/conf.d/default.conf

# Configuration Nginx
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copie des fichiers frontend
COPY ./frontend /usr/share/nginx/html

# Exposition du port
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]