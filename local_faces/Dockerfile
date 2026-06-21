ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    OPENCV_VIDEOIO_PRIORITY_MSMF=0

WORKDIR /app

# Shared libraries the opencv-python-headless wheel loads at runtime (GUI libs
# are not needed - the headless build avoids them). ffmpeg for RTSP is bundled
# inside the wheel, so nothing else is required.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# No s6/bashio (init: false) - run our process directly.
CMD [ "/run.sh" ]
