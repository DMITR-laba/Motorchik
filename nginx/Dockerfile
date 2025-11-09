FROM nginx:alpine

# Install openssl for certificate generation
RUN apk add --no-cache openssl

# Copy configuration files
COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/ /etc/nginx/conf.d/

# Create directories for certbot
RUN mkdir -p /var/www/certbot

# Copy script for generating self-signed certificate
COPY generate-self-signed-cert.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/generate-self-signed-cert.sh

# Expose ports
EXPOSE 80 443

# Start nginx
CMD ["nginx", "-g", "daemon off;"]

