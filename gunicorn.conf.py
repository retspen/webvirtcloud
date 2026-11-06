"""gunicorn's settings for the panel (systemd and Docker run it with -c)."""

import os

# behind nginx, on the loopback only
bind = '127.0.0.1:8000'
backlog = 2048

# Workers, each holding its own libvirt connections; capped so a big host
# does not start dozens of them against sqlite. Override with
# GUNICORN_CMD_ARGS="--workers N".
MAX_WORKERS = 8


def get_workers():
    procs = os.sysconf('SC_NPROCESSORS_ONLN')
    return min(procs * 2 + 1, MAX_WORKERS) if procs > 0 else 3


workers = get_workers()
# threads of a worker: a request waiting on a host that does not answer
# holds one thread, not the whole worker
worker_class = 'webvirtcloud.gunicorn_worker.Worker'
threads = 4
# a worker takes no more connections than it has threads: one whose threads
# are all busy leaves new requests to the others. nginx opens a connection
# per request, so none is kept alive.
worker_connections = threads
timeout = 600
keepalive = 0
# gunicorn 26's control socket is unused, and the service user cannot create it
control_socket_disable = True

debug = False
spew = False

daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# to the service's output: the journal, or docker logs
logfile = '-'
loglevel = 'info'
accesslog = '-'
# the client's address from nginx (gunicorn itself sees 127.0.0.1) and the
# request's ID, as on the app log's lines
access_log_format = '%({x-real-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %({x-request-id}o)s'

proc_name = None
