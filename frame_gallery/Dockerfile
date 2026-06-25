# Pin the Debian base directly. The Supervisor was not honoring build.yaml's
# `build_from` and fell back to its Alpine base image, where run.sh's `bash`
# shebang fails ("bash: not found") and the app never starts. python:3.12-slim
# is multi-arch (amd64/arm64/armv7) and matches build.yaml.
FROM python:3.12-slim

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# No s6/bashio (init: false) - run our process directly.
CMD [ "/run.sh" ]
