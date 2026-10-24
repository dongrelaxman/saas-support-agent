# ── Stage 1: build the React app ─────────────────────────────────────────────
FROM node:20-alpine3.20 AS build

WORKDIR /app

# Install dependencies (layer-cached unless package-lock.json changes)
COPY frontend/package*.json ./
RUN npm ci

# Copy source and build
COPY frontend/ ./
RUN npm run build
# Output: /app/dist


# ── Stage 2: serve with nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Replace the default nginx config with our reverse-proxy template.
# The official nginx image runs envsubst on everything in /etc/nginx/templates/
# at container start, writing results to /etc/nginx/conf.d/.
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy the built React app
COPY --from=build /app/dist /usr/share/nginx/html

# Remove the default nginx welcome page config to avoid conflicts
RUN rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80

# BACKEND_URL must be set at runtime:
#   docker-compose  →  http://backend:8001
#   Cloud Run       →  https://<backend-cloud-run-url>
ENV BACKEND_URL=http://backend:8001
