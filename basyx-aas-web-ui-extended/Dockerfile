FROM node:lts-slim AS build-stage
ARG COMMIT_SHA=bf1a6a9
ENV NODE_OPTIONS=--max-old-space-size=8192

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone https://github.com/eclipse-basyx/basyx-aas-web-ui.git . \
    && git checkout ${COMMIT_SHA}

WORKDIR /src/aas-web-ui

COPY plugins/*.vue src/components/Plugins/SubmodelElements/
# Fix upstream bug: return→continue in convertInfluxCSVtoArray so LinkedSegment CSV is actually parsed
RUN sed -i '/headerLine = line/{n;s/        return$/        continue/}' \
    src/components/Plugins/Submodels/TimeSeries_v1_1.vue

RUN corepack enable
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

ENV NODE_OPTIONS=--max-old-space-size=4096
RUN pnpm run build-only

FROM nginx:mainline-alpine-slim AS production-stage
COPY --from=build-stage /src/aas-web-ui/dist /usr/src/app/dist
# Use our template (adds conf.d include for the InfluxDB proxy)
COPY nginx.conf.template /etc/nginx/nginx.conf.template
# Remove the stock default.conf — it contains a server{} block that
# conflicts with our include inside server{}.
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=build-stage /src/aas-web-ui/entrypoint.sh /usr/src/app/entrypoint.sh
RUN chmod +x /usr/src/app/entrypoint.sh
# Wrapper: generates /etc/nginx/conf.d/influxdb-proxy.conf at startup
COPY entrypoint-wrapper.sh /usr/src/app/entrypoint-wrapper.sh
RUN chmod +x /usr/src/app/entrypoint-wrapper.sh

EXPOSE 3000
ENTRYPOINT ["/usr/src/app/entrypoint-wrapper.sh"]
