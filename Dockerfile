FROM ubuntu:18.04

WORKDIR /usr/src/

COPY backend/requirements.txt /usr/src/requirements.txt
COPY backend/requirements-dev.txt /usr/src/requirements-dev.txt

RUN set -ex \
    && apt-get update -q \
    && apt-get -y install \
        python3-pip \
        libvirt-dev \
        libmariadbclient-dev

RUN pip3 install -r requirements-dev.txt
RUN rm -f requirements.txt requirements-dev.txt

WORKDIR /app
VOLUME /app

EXPOSE 8000 6080

CMD ["/bin/bash"]
