# Local verification gateway; select/review the actual host gateway separately.
FROM nginx:stable-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951
# Compatible Alpine security patch for CVE-2026-111497; no application packages.
RUN apk upgrade --no-cache brotli-libs
