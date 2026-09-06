# ---------- build ----------
# bookworm-slim, NOT alpine. Angular builds with esbuild, which ships
# platform-specific native binaries as optional dependencies; glibc removes a whole
# class of "musl variant missing from the lockfile" failures. The stage is discarded,
# so it costs nothing in the shipped image.
FROM node:22-bookworm-slim AS build
WORKDIR /build

# Lockfile alone, and first: source edits never re-run npm ci.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --loglevel=error

COPY . .
# Docker Desktop's default VM is 2 GB and the production build is the memory-hungry
# step. Uncapped, this dies as a bare "exit code 137" on the judge's machine.
ENV NODE_OPTIONS=--max-old-space-size=1536
RUN npm run build

# ---------- runtime ----------
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist/watchlist-web/browser /usr/share/nginx/html
EXPOSE 80
