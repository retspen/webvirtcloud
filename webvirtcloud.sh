#!/bin/bash
# a failing step fails the pipeline that logs it
set -o pipefail
#/ Usage: webvirtcloud.sh [-vh]
#/
#/ Install Webvirtcloud virtualization web interface.
#/
#/ OPTIONS:
#/   -v | --verbose    Enable verbose output.
#/   -h | --help       Show this message.

########################################################
#            Webvirtcloud Install Script               #
# Script created by Mike Tucker(mtucker6784@gmail.com) #
#              adapted by catborise                    #
#              catborise@gmail.com                     #
#                                                      #
#  Feel free to modify, but please give                #
#  credit where it's due. Thanks!                      #
########################################################

# Parse arguments
while true; do
  case "$1" in
    -h|--help)
      show_help=true
      shift
      ;;
    -v|--verbose)
      set -x
      verbose=true
      shift
      ;;
    -*)
      echo "Error: invalid argument: '$1'" 1>&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

print_usage () {
  grep '^#/' <"$0" | cut -c 4-
  exit 1
}

if [ -n "$show_help" ]; then
  print_usage
else
  for x in "$@"; do
    if [ "$x" = "--help" ] || [ "$x" = "-h" ]; then
      print_usage
    fi
  done
fi

# ensure running as root
if [ "$(id -u)" != "0" ]; then
    #Debian doesnt have sudo if root has a password.
    if ! hash sudo 2>/dev/null; then
        exec su -c "$0" "$@"
    else
        exec sudo "$0" "$@"
    fi
fi

if [ -f /etc/supervisor/conf.d/webvirtcloud.conf ] || [ -f /etc/supervisord.d/webvirtcloud.ini ]; then
  echo "WebVirtCloud runs under supervisor here: move it to systemd first (README: Updating, Moving from supervisor to systemd)." >&2
  exit 1
fi

readonly APP_REPO_URL="${APP_REPO_URL:-https://github.com/retspen/webvirtcloud.git}"
readonly APP_NAME="webvirtcloud"
readonly APP_PATH="/srv/$APP_NAME"

PYTHON="python3"

progress () {
  spin[0]="-"
  spin[1]="\\"
  spin[2]="|"
  spin[3]="/"

  echo -n " "
  while kill -0 "$pid" > /dev/null 2>&1; do
    for i in "${spin[@]}"; do
      echo -ne "\\b$i"
      sleep .3
    done
  done
  echo ""
}

# shellcheck disable=SC2294
log () {
  if [ -n "$verbose" ]; then
    eval "$@" |& tee -a /var/log/webvirtcloud-install.log
  else
    eval "$@" |& tee -a /var/log/webvirtcloud-install.log >/dev/null 2>&1
  fi
}

get_timezone () {
  if [ -f /etc/timezone ]; then
    cat /etc/timezone
  elif command -v timedatectl >/dev/null 2>&1 && timedatectl 2>/dev/null | grep -q "Time zone"; then
    timedatectl | grep "Time zone" | awk '{print $3}'
  elif [ -L /etc/localtime ]; then
    readlink /etc/localtime | sed -n 's#.*/zoneinfo/##p'
  else
    echo "UTC"
  fi
}

install_packages () {
  case $distro in
    ubuntu|debian)
      for p in $PACKAGES; do
        if dpkg -s "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "DEBIAN_FRONTEND=noninteractive apt-get install -y $p" || { echo "Installing $p failed." >&2; exit 1; }
        fi
      done;
      ;;
    centos)
      for p in $PACKAGES; do
        if yum list installed "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "yum -y install $p" || { echo "Installing $p failed." >&2; exit 1; }
        fi
      done;
      ;;
    fedora|openEuler)
      for p in $PACKAGES; do
        if dnf list installed "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "dnf -y install $p" || { echo "Installing $p failed." >&2; exit 1; }
        fi
      done;
      ;;
    suse)
      for p in $PACKAGES; do
        if rpm -q "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "zypper --non-interactive install -y $p" || { echo "Installing $p failed." >&2; exit 1; }
        fi
      done
      ;;
  esac
}

configure_nginx () {
  # shellcheck source=conf/install-lib.sh
  . "$APP_PATH/conf/install-lib.sh"

  if [ -f /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
  fi

  chown -R "$nginx_group":"$nginx_group" /var/lib/nginx
  # Install the main nginx config on first run only (keeping a backup), always
  # refresh the app snippet; a re-run never clobbers an edited main config.
  echo "  * Installing Nginx configuration"
  local nginx_template_conf
  nginx_template_conf="${APP_PATH}/conf/nginx/${nginx_conf}_${codename}_nginx.conf"
  if ! test -f "${nginx_template_conf}"; then
    nginx_template_conf="${APP_PATH}/conf/nginx/${nginx_conf}_nginx.conf"
  fi
  wvc_install_nginx "${nginx_template_conf}" "$APP_PATH/conf/nginx/webvirtcloud.conf" /etc/nginx

  if [ -n "$fqdn" ]; then
     fqdn_escape="$(echo -n "$fqdn"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
     sed -i "s|\\(#server_name\\).*|server_name $fqdn_escape;|" "$nginxfile"
  fi

  novncd_port_escape="$(echo -n "$novncd_port"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  sed -i "s|server 127.0.0.1:6080;|server 127.0.0.1:$novncd_port_escape;|" "$nginxfile"

}

configure_systemd () {
  # The panel's services run as the web server's user; a re-run restarts them.
  units="webvirt-cloud webvirt-novncd webvirt-socketiod webvirt-worker"
  for unit in $units webvirt-backup; do
    sed "s/^\\(User\\|Group\\)=.*/\\1=$nginx_group/" "$APP_PATH/conf/systemd/$unit.service" > "/etc/systemd/system/$unit.service" || exit 1
  done
  cp "$APP_PATH/conf/systemd/webvirt-backup.timer" /etc/systemd/system/ || exit 1
  # shellcheck disable=SC2086
  systemctl daemon-reload && systemctl enable $units && systemctl restart $units &&
    systemctl enable --now webvirt-backup.timer || exit 1
}

add_service_groups () {
  # the panel's services reach a local libvirt and KVM as the web server's user
  usermod -a -G libvirt "$nginx_group" 2>/dev/null || true
  usermod -a -G kvm "$nginx_group" 2>/dev/null || true
}

check_python () {
  # dynamically find python >= 3.10 if default python3 is older
  for py_bin in python3.11 python3.12 python3.13 python3.10 python3; do
    if command -v "$py_bin" >/dev/null 2>&1; then
      if "$py_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PYTHON="$py_bin"
        break
      fi
    fi
  done

  # check if python3 is installed.
  if ! hash "$PYTHON" 2>/dev/null; then
    echo "Python3 is not installed. Please install Python3 and try again."
    exit 1
  fi

  # check if python3 version is greater than 3.10
  if ! "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
    echo "Your Python version is less than 3.10. This script requires Python 3.10 or greater."
    echo "Please install Python 3.10 or greater (such as python311) and try again."
    exit 1
  fi
}

activate_python_environment () {
    cd "$APP_PATH" || exit
    echo "* Creating virtual environment in $APP_PATH/venv"
    if "$PYTHON" -m venv --help >/dev/null 2>&1; then
      "$PYTHON" -m venv --system-site-packages venv
    elif command -v virtualenv >/dev/null 2>&1; then
      virtualenv -p "$PYTHON" --system-site-packages venv
    else
      echo "Neither python3 -m venv nor virtualenv is installed. Please install python3-venv or virtualenv."
      exit 1
    fi
    # shellcheck disable=SC1091
    source venv/bin/activate
}


install_webvirtcloud () {
  add_service_groups

  if [ ! -d "$APP_PATH/.git" ]; then
    echo "* Cloning $APP_NAME from github to the web directory."
    log "git clone $APP_REPO_URL $APP_PATH" || { echo "Cloning $APP_REPO_URL failed." >&2; exit 1; }
  else
    echo "* $APP_NAME already present in $APP_PATH."
  fi

  # shellcheck source=conf/install-lib.sh
  . "$APP_PATH/conf/install-lib.sh"

  echo "* Checking up Python3 version."
  check_python

  echo "* Ensuring Django secret key (data/secret_key, kept across re-runs)."
  wvc_ensure_secret_key "$APP_PATH/data" "$PYTHON" || { echo "The secret key could not be written." >&2; exit 1; }

  echo "* Configuring settings.py file."
  if wvc_ensure_settings "$APP_PATH/webvirtcloud/settings.py.template" "$APP_PATH/webvirtcloud/settings.py" >/dev/null; then
    # first install only: apply instance values. SECRET_KEY is NOT written here;
    # settings.py reads data/secret_key, so the key persists across re-runs.
    tzone_escape="$(echo -n "$tzone"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
    novncd_port_escape="$(echo -n "$novncd_port"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"

    #TODO escape SED delimiter in variables
    sed -i "s|^\\(TIME_ZONE = \\).*|\\1$tzone_escape|" "$APP_PATH/webvirtcloud/settings.py"
    sed -i "s|^\\(WS_PORT = \\).*|\\1$novncd_port_escape|" "$APP_PATH/webvirtcloud/settings.py"

    # set CSRF TRUSTED ORIGINS
    host_ip="'http://127.0.0.1', "
    if command -v hostname >/dev/null 2>&1; then
      for i in $(hostname -I 2>/dev/null); do
        host_ip+="'http://$i', "
      done
    fi
    sed -i "s|^\\(CSRF_TRUSTED_ORIGINS = \\).*|\\1\[ \'http://$fqdn\', $host_ip ]|" "$APP_PATH/webvirtcloud/settings.py"
    # shellcheck disable=SC2046
    allowed_hosts="$(wvc_allowed_hosts "$fqdn" $(hostname -I 2>/dev/null))"
    sed -i "s|^ALLOWED_HOSTS = .*|ALLOWED_HOSTS = $allowed_hosts|" "$APP_PATH/webvirtcloud/settings.py"
  else
    echo "* Keeping existing settings.py (not overwritten)."
  fi

  # Restrict modes before the long-running pip/migrate steps, so settings and the
  # key are not left world-readable during installation. The db is hardened again
  # after migrate creates it.
  wvc_harden_modes "$APP_PATH/webvirtcloud/settings.py" "" "$APP_PATH/data"

  echo "* Activate virtual environment."
  activate_python_environment

  echo "* Install App's Python requirements."
  pip3 install -U pip || exit 1
  pip3 install -r conf/requirements.txt -q || { echo "Installing the Python requirements failed." >&2; exit 1; }

  chown -R "$nginx_group":"$nginx_group" "$APP_PATH"

  echo "* Django Migrate."
  log "$PYTHON $APP_PATH/manage.py migrate" || { echo "manage.py migrate failed: see /var/log/webvirtcloud-install.log." >&2; exit 1; }

  echo "* Django Collect Static"
  log "$PYTHON $APP_PATH/manage.py collectstatic --noinput" || { echo "manage.py collectstatic failed: see /var/log/webvirtcloud-install.log." >&2; exit 1; }

  echo "* Restricting file modes on secret, settings and database."
  wvc_harden_modes "$APP_PATH/webvirtcloud/settings.py" "$APP_PATH/db.sqlite3" "$APP_PATH/data"

  chown -R "$nginx_group":"$nginx_group" "$APP_PATH"
}

set_firewall () {
  if test -n "$(command -v firewall-cmd)" && test "$(firewall-cmd --state)" == "running"; then
    echo "* Configuring firewall to allow HTTP traffic."
    log "firewall-cmd --zone=public --add-port=http/tcp --permanent"
    log "firewall-cmd --reload"
    #firewall-cmd --reload
  fi
}

# A file context rule (type, path pattern): added, or changed on a re-run
selinux_label () {
  semanage fcontext -a -t "$1" "$2" 2>/dev/null || semanage fcontext -m -t "$1" "$2"
}

set_selinux () {
  if selinuxenabled 2>/dev/null; then
    echo "* Configuring SELinux."
    # nginx reads the static files and systemd runs the venv's programs; rules
    # rather than chcon, so that a relabel keeps the labels
    selinux_label httpd_sys_content_t "$APP_PATH(/.*)?" &&
      selinux_label bin_t "$APP_PATH/venv/bin(/.*)?" &&
      restorecon -R "$APP_PATH" &&
      setsebool -P httpd_can_network_connect 1 || exit 1
  fi
}

set_hosts () {
  echo "* Setting up hosts file."
  local hname
  hname="$(hostname 2>/dev/null || uname -n)"
  if ! grep -q "$fqdn" /etc/hosts 2>/dev/null; then
    echo >> /etc/hosts "127.0.0.1 $hname $fqdn"
  fi
}

restart_nginx () {
  echo "* Setting Nginx to start on boot and starting Nginx."
  # nginx is not enabled on RHEL and openSUSE, and Debian's runs the default site until a reload
  nginx -t && systemctl enable nginx.service && systemctl restart nginx.service || exit 1
}


if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  distro="$(source /etc/os-release && echo "$ID")"
  # shellcheck disable=SC1091
  version="$(source /etc/os-release && echo "$VERSION_ID")"
  # shellcheck disable=SC1091
  codename="$(source /etc/os-release && echo "${VERSION_CODENAME:-$UBUNTU_CODENAME}")"
  # shellcheck disable=SC1091
  id_like="$(source /etc/os-release && echo "${ID_LIKE:-}")"
elif [[ -f /etc/lsb-release || -f /etc/debian_version ]]; then
  if command -v lsb_release >/dev/null 2>&1; then
    distro="$(lsb_release -is)"
    version="$(lsb_release -rs)"
    codename="$(lsb_release -cs)"
  elif [ -f /etc/debian_version ]; then
    distro="debian"
    version="$(cat /etc/debian_version)"
    codename=""
  fi
elif [ -f /etc/centos-release ]; then
  distro="centos"
  version="8"
elif [ -f /etc/SuSE-release ]; then
  distro="suse"
  version="15"
  codename=""
  id_like="suse"
else
  distro="unsupported"
fi


echo '
      WEBVIRTCLOUD
'

echo "" 
echo "  Welcome to Webvirtcloud Installer for RHEL Based OSes, Debian, Ubuntu, and SUSE!"
echo ""
shopt -s nocasematch
case $distro in
  *ubuntu*)
    echo "  The installer has detected $distro version $version codename $codename."
    distro=ubuntu
    nginx_group=www-data
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    ;;
  *debian*)
    echo "  The installer has detected $distro version $version codename $codename."
    distro=debian
    nginx_group=www-data
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    ;;
  *openEuler*)
    echo "  The installer has detected $distro version $version."
    distro=openEuler
    nginx_group=nginx
    nginx_conf=centos
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    ;;
  *centos*|*redhat*|*ol*|*rhel*|*rocky*|*Rocky*|*alma*)
    echo "  The installer has detected $distro version $version."
    distro=centos
    nginx_group=nginx
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    ;;
  *opensuse*|*sles*|*sled*|*suse*)
    echo "  The installer has detected $distro version $version."
    distro=suse
    nginx_group=nginx
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    ;;
  *)
    if [[ "$id_like" =~ suse ]]; then
      echo "  The installer has detected $distro (SUSE family) version $version."
      distro=suse
      nginx_group=nginx
      nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    else
      echo "  The installer was unable to determine your OS. Exiting for safety."
      exit 1
    fi
    ;;
esac

# the main nginx config of the distro family
nginx_conf="${nginx_conf:-$distro}"

fqdn="localhost"
setupfqdn=default
until [[ $setupfqdn == "yes" ]] || [[ $setupfqdn == "no" ]]; do
  echo -n "  Q. Do you want to configure fqdn for Nginx? (y/n) "
  read -r setupfqdn

  case $setupfqdn in
    [yY] | [yY][Ee][Ss] )
    fqdn=$(hostname --fqdn)
    echo -n "  Q. What is the FQDN of your server? ($fqdn): "
      read -r fqdn_from_user
      setupfqdn="yes"

      if [ -n "$fqdn_from_user" ]; then
        fqdn=$fqdn_from_user
      fi

      echo "     Setting to $fqdn"
      echo ""
      ;;
    [nN] | [n|N][O|o] )
      setupfqdn="no"
      ;;
    *)  echo "  Invalid answer. Please type y or n"
      ;;
  esac
done

echo -n "  Q. NOVNC service port number?(Default: 6080) "
read -r novncd_port
if [ -z "$novncd_port" ]; then
  readonly novncd_port=6080
fi
echo "     Setting novnc service port $novncd_port"
echo ""

echo "========="
echo "distro: ${distro}"
echo "========="
case $distro in
  debian)
  debian_major="${version%%.*}"
  if [[ -n "$debian_major" && "$debian_major" -ge 12 ]]; then
    # Install for Debian 12 and later
    tzone=\'$(get_timezone)\'

    echo -n "* Updating installed packages."
    log "apt-get update" & pid=$!
    progress
    wait "$pid" || { echo "Updating the package lists failed." >&2; exit 1; }

    echo "*  Installing OS requirements."
    PACKAGES="git python3-venv python3-virtualenv python3-pip python3-dev python3-lxml python3-libvirt libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs"
    
    install_packages
    
    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring systemd."
    configure_systemd

    restart_nginx
  else
    echo "Unsupported Debian version. Version found: $version"
    exit 1
  fi
  ;;
  ubuntu)
  if [[ "$version" =~ ^(22|24|26)\. ]]; then
    # Install for Ubuntu 22.04 / 24.04 / 26.04
    tzone=\'$(get_timezone)\'

    echo -n "* Updating installed packages."
    log "apt-get update" & pid=$!
    progress
    wait "$pid" || { echo "Updating the package lists failed." >&2; exit 1; }

    echo "*  Installing OS requirements."
    PACKAGES="git python3-venv python3-virtualenv python3-pip python3-dev python3-lxml python3-libvirt libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring systemd."
    configure_systemd

    restart_nginx
  else
    echo "Unsupported Ubuntu version. Version found: $version"
    exit 1
  fi  
  ;;
  centos)
  if [[ "$version" =~ ^10  ]]; then
    # Install for CentOS/Redhat 10
    tzone=\'$(get_timezone)\'

    if command -v "crb" >/dev/null 2>&1; then
      echo "* CRB Repo is found, enabling it."
      log "crb enable > /dev/null 2>&1"
    else
      echo "* Enabling CRB repository."
      log "dnf config-manager --set-enabled crb"
    fi

    echo "* Adding wget & epel-release repository."
    log "yum -y install wget epel-release"

    echo "* Installing OS requirements."
    PACKAGES="git hostname python3-devel libvirt-devel python3-libvirt glibc gcc nginx python3-lxml python3-libguestfs iproute-tc cyrus-sasl-md5 openssl-devel policycoreutils-python-utils"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    set_firewall

    set_selinux

    echo "* Configuring systemd."
    configure_systemd

    restart_nginx
  else
    echo "Unsupported RHEL Based OS($distro) version. Version found: $version"
    exit 1
  fi
  ;;
  openEuler)
  if [[ "$version" =~ ^24\. ]]; then
    # Install for openEuler 24.03 LTS
    tzone=\'$(get_timezone)\'

    echo "* Installing OS requirements."
    PACKAGES="git hostname python3-devel libvirt-devel python3-libvirt glibc gcc nginx python3-lxml python3-libguestfs iproute cyrus-sasl openssl-devel policycoreutils-python-utils"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    set_firewall

    set_selinux

    echo "* Configuring systemd."
    configure_systemd

    restart_nginx
  else
    echo "Unsupported openEuler version (24.03 LTS is supported). Version found: $version"
    exit 1
  fi
  ;;
  suse)
    # Install for openSUSE Leap 15.x / Tumbleweed / SLES 15
    tzone=\'$(get_timezone)\'

    echo -n "* Updating installed packages."
    log "zypper --non-interactive refresh" & pid=$!
    progress
    wait "$pid" || { echo "Updating the package lists failed." >&2; exit 1; }

    echo "* Installing OS requirements."
    # On SUSE, install Python 3.11 stack to satisfy Python >= 3.10 requirement along with the native libvirt bindings
    if zypper se -s python311-devel >/dev/null 2>&1; then
      PACKAGES="git hostname python311 python311-base python311-devel python311-pip python311-libvirt-python python311-lxml libvirt-devel libopenssl-devel gcc pkg-config nginx"
    else
      PACKAGES="git hostname python3-devel python3-pip python3-virtualenv libvirt-devel python3-libvirt python3-lxml libopenssl-devel gcc pkg-config nginx"
    fi
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    set_firewall

    echo "* Configuring systemd."
    configure_systemd

    restart_nginx
    ;;
esac


echo ""
echo "  ***Open http://$fqdn to login to webvirtcloud.***"
echo "  The admin password: cat $APP_PATH/data/admin_password"
echo ""
echo ""
echo "* Cleaning up..."
if [ ! -d .git ]; then
  rm -f webvirtcloud.sh
  rm -f install.sh
fi
echo "* Finished!"
sleep 1
