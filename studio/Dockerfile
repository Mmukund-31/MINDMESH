FROM node:22-alpine AS build
WORKDIR /studio
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx vite build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /studio/dist /usr/share/nginx/html
EXPOSE 80
