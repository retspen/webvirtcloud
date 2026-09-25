FROM phusion/baseimage:noble-1.0.2

EXPOSE 80
EXPOSE 6080

# Use baseimage-docker's init system.
CMD ["/sbin/my_init"]

RUN echo 'APT::Get::Clean=always;' >> /etc/apt/apt.conf.d/99AutomaticClean

# hadolint ignore=DL3008
RUN apt-get update -qqy \
    && DEBIAN_FRONTEND=noninteractive apt-get -qyy install \
	--no-install-recommends \
	git \
	python3-venv \
	python3-pip \
	python3-dev \
	python3-lxml \
	python3-libvirt \
	libvirt-dev \
	zlib1g-dev \
	nginx \
	pkg-config \
	gcc \
	libldap2-dev \
	libssl-dev \
	libsasl2-dev \
	libsasl2-modules \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Setup webvirtcloud
WORKDIR /srv/webvirtcloud

# Install Python dependencies first with system-site-packages to leverage prebuilt bindings
COPY conf/requirements.txt conf/requirements.txt
# hadolint ignore=DL3013,DL3042,SC1091
RUN python3 -m venv --system-site-packages venv && \
	. venv/bin/activate && \
	pip3 install --no-cache-dir -U pip wheel && \
	pip3 install --no-cache-dir -r conf/requirements.txt

# Copy application source
COPY . /srv/webvirtcloud

# Run collectstatic with temporary dummy key, then remove temporary settings file
# hadolint ignore=SC1091
RUN . venv/bin/activate && \
	cp webvirtcloud/settings.py.template webvirtcloud/settings.py && \
	SECRET_KEY="build-dummy-key-only-for-collectstatic" python3 manage.py collectstatic --noinput && \
	rm -f webvirtcloud/settings.py && \
	chown -R www-data:www-data /srv/webvirtcloud

# Setup Nginx
RUN printf "\n%s" "daemon off;" >> /etc/nginx/nginx.conf && \
	rm -f /etc/nginx/sites-enabled/default && \
	chown -R www-data:www-data /var/lib/nginx

COPY conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/

# Register startup init script and services to runit
RUN mkdir -p /etc/my_init.d \
	/etc/service/nginx \
	/etc/service/nginx-log-forwarder \
	/etc/service/webvirtcloud \
	/etc/service/novnc
COPY conf/runit/10_webvirtcloud_init.sh	/etc/my_init.d/10_webvirtcloud_init.sh
COPY conf/runit/nginx				/etc/service/nginx/run
COPY conf/runit/nginx-log-forwarder	/etc/service/nginx-log-forwarder/run
COPY conf/runit/novncd.sh			/etc/service/novnc/run
COPY conf/runit/webvirtcloud.sh		/etc/service/webvirtcloud/run
RUN chmod +x /etc/my_init.d/10_webvirtcloud_init.sh \
	/etc/service/nginx/run \
	/etc/service/nginx-log-forwarder/run \
	/etc/service/novnc/run \
	/etc/service/webvirtcloud/run

# Declare mountable data directory for persistent SQLite and SSH keys
VOLUME ["/srv/webvirtcloud/data", "/var/www/.ssh"]

WORKDIR /srv/webvirtcloud
