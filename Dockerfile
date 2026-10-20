FROM python:3.12-slim

ENV PYTHONTDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install FFmpeg 7.0.3
RUN echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4 && \
    echo 'Acquire::http::Timeout "15";' >> /etc/apt/apt.conf.d/99timeout && \
    echo 'Acquire::Languages "none";' >> /etc/apt/apt.conf.d/99no-languages && \
    apt-get update && apt-get install -y --no-install-recommends \
    wget \
    build-essential \
    pkg-config \
    yasm \
    git \
    && wget https://ffmpeg.org/releases/ffmpeg-7.0.3.tar.xz \
    && tar -xf ffmpeg-7.0.3.tar.xz \
    && cd ffmpeg-7.0.3 \
    && ./configure --prefix=/usr/local --enable-gpl --enable-version3 --disable-doc --disable-debug \
    && make -j$(nproc) \
    && make install \
    && cd .. \
    && rm -rf ffmpeg-7.0.3* \
    && apt-get purge -y wget build-essential pkg-config yasm git \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Install Python reqs
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# static files
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]
