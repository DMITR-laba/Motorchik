FROM nginx:alpine

# Удалим дефолтный сайт
RUN rm -rf /usr/share/nginx/html/*

# Копируем статические файлы
COPY index.html /usr/share/nginx/html/index.html

# Пользователь Nginx по умолчанию
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
