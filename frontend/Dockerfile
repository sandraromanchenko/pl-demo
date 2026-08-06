# Build the static bundle, then serve it with nginx.
FROM node:20-alpine AS build
WORKDIR /app

# VITE_API_BASE is baked into the bundle at build time (browsers call the
# backend directly). Override per environment via the compose build arg.
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE

COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
