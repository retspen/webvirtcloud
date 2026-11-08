# The panel in one container: supervisord runs nginx, gunicorn, the job
# worker, the two console daemons and cron (conf/docker).
FROM ubuntu:26.04 AS base

RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -qqy --no-install-recommends \
        ca-certificates \
        cron \
        libldap2 \
        libsasl2-modules \
        libvirt0 \
        nginx \
        openssh-client \
        python3 \
        supervisor \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/webvirtcloud

# Compilers and headers for libvirt-python and python-ldap stay in this stage.
FROM base AS build

RUN apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -qqy --no-install-recommends \
        gcc \
        libldap2-dev \
        libsasl2-dev \
        libssl-dev \
        libvirt-dev \
        pkg-config \
        python3-dev \
        python3-venv \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY conf/requirements.txt conf/requirements-ldap.txt conf/
# pip's cache stays on the build host for the next build; pip itself is not
# shipped: a dependency change is a new image
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m venv venv \
    && venv/bin/pip install -r conf/requirements.txt -r conf/requirements-ldap.txt \
    && venv/bin/pip uninstall -y pip

FROM base

# 4 gunicorn workers of 4 threads (about 140 MB each); docker-compose.override.yml can set another number
ENV GUNICORN_CMD_ARGS="--workers 4"

COPY --from=build /srv/webvirtcloud/venv venv
COPY . .

# The code stays root's: the panel writes only to its data and backup
# directories (made its own at start). A settings file and a key exist only
# for collectstatic.
RUN cp webvirtcloud/settings.py.template webvirtcloud/settings.py \
    && SECRET_KEY=build-only WEBVIRTCLOUD_LOG_FILE=/tmp/build.log venv/bin/python3 manage.py collectstatic --noinput \
    && rm webvirtcloud/settings.py /tmp/build.log

COPY conf/docker/nginx.conf /etc/nginx/nginx.conf
COPY conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/
COPY conf/docker/supervisord.conf /etc/supervisor/supervisord.conf
COPY --chmod=644 conf/docker/backup.cron /etc/cron.d/webvirtcloud-backup
COPY --chmod=755 conf/docker/start conf/docker/healthcheck /usr/local/bin/

EXPOSE 80
# the database, secret key and logs; SSH keys and TLS certificates for the
# computes; the daily backups
VOLUME ["/srv/webvirtcloud/data", "/var/www/.ssh", "/var/www/.pki", "/srv/webvirtcloud/backups"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 CMD ["healthcheck"]

ENTRYPOINT ["start"]
CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
