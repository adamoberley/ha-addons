# LedFX for Home Assistant.
#
# Pin the Debian base directly: the Supervisor doesn't always honor build.yaml's
# build_from and can fall back to an Alpine base, where run.sh's bash shebang
# fails. python:3.12-slim is multi-arch (amd64/arm64/armv7), and 3.12 satisfies
# Sendspin's Python >= 3.12 requirement.
FROM python:3.12-slim

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    # Blade's HASS-optimized frontend build: relative asset paths + ingress-aware,
    # which the official (absolute-path) bundle is not. Pinned for reproducibility.
    FRONTEND_URL=https://github.com/YeonV/LedFx-Frontend-v2/releases/download/2.1.6-b17/ledfx_frontend_hass.zip

WORKDIR /tmp/build
COPY requirements.txt patch_frontend.py ./

# One layer: toolchain + audio/crypto headers to install ledfx and its native
# deps, the runtime shared libs ledfx loads at import (portaudio, alsa), the
# ingress-ready frontend, our same-origin patch, then a cleanup pass.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential pkg-config cmake git \
        libasound2-dev portaudio19-dev libmbedtls-dev \
        libportaudio2 libasound2 curl unzip ca-certificates; \
    python3 -m pip install --no-cache-dir -r requirements.txt; \
    # Replace the pip-bundled frontend with the ingress-ready HASS build.
    curl -fL --retry 3 -o fe.zip "$FRONTEND_URL"; \
    unzip -q fe.zip; \
    SP="$(python3 -c 'import ledfx_frontend, os; print(os.path.dirname(ledfx_frontend.__file__))')"; \
    rm -rf "${SP:?}"/*; \
    cp -r ledfx_frontend_hass/* "$SP"/; \
    # Make the UI talk to its own origin (ingress + LAN), de-brand the page title.
    python3 patch_frontend.py; \
    # Trim.
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /root/.cache /tmp/build/*; \
    find /usr/local/lib/python3.12 -type d -name __pycache__ -prune -exec rm -rf {} +

WORKDIR /
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# init: false - run our process directly (no s6/bashio).
CMD [ "/run.sh" ]
