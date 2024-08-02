#!/bin/bash
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

clear

readonly APP_USER="wvcuser"
readonly APP_REPO_URL="https://github.com/retspen/webvirtcloud.git"
readonly APP_NAME="webvirtcloud"
readonly APP_PATH="/srv/$APP_NAME"

readonly PYTHON="python3"

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

log () {
  if [ -n "$verbose" ]; then
    eval "$@" |& tee -a /var/log/webvirtcloud-install.log
  else
    eval "$@" |& tee -a /var/log/webvirtcloud-install.log >/dev/null 2>&1
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
          log "DEBIAN_FRONTEND=noninteractive apt-get install -y $p"
        fi
      done;
      ;;
    centos)
      for p in $PACKAGES; do
        if yum list installed "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "yum -y install $p"
        fi
      done;
      ;;
    fedora|openEuler)
      for p in $PACKAGES; do
        if dnf list installed "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "dnf -y install $p"
        fi
      done;
      ;;
    uos)
      if test "${codename}" == "eagle"; then
        check_package_cmd=("dpkg" "-s")
        install_package_cmd="apt-get install -y"
      else
        check_package_cmd=("dnf" "list" "installed")
        install_package_cmd="dnf -y install"
      fi
      for p in $PACKAGES; do
        # shellcheck disable=SC2048
        if ${check_package_cmd[*]} "$p" >/dev/null 2>&1; then
          echo "  * $p already installed"
        else
          echo "  * Installing $p"
          log "${install_package_cmd} $p"
        fi
      done
      ;;
  esac
}

configure_nginx () {
  # Remove default configuration 
  rm /etc/nginx/nginx.conf
  if [ -f /etc/nginx/sites-enabled/default ]; then
    rm /etc/nginx/sites-enabled/default
  fi

  chown -R "$nginx_group":"$nginx_group" /var/lib/nginx
  # Copy new configuration and webvirtcloud.conf
  echo "  * Copying Nginx configuration"
  local nginx_template_conf
  nginx_template_conf="${APP_PATH}/conf/nginx/${distro}_${codename}_nginx.conf"
  if ! test -f "${nginx_template_conf}"; then
    nginx_template_conf="${APP_PATH}/conf/nginx/${distro}_nginx.conf"
  fi
  cp "${nginx_template_conf}" /etc/nginx/nginx.conf
  cp "$APP_PATH"/conf/nginx/webvirtcloud.conf /etc/nginx/conf.d/

  if [ -n "$fqdn" ]; then
     fqdn_escape="$(echo -n "$fqdn"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
     sed -i "s|\\(#server_name\\).*|server_name $fqdn_escape;|" "$nginxfile"
  fi

  novncd_port_escape="$(echo -n "$novncd_port"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  sed -i "s|server 127.0.0.1:6080;|server 127.0.0.1:$novncd_port_escape;|" "$nginxfile"

}

configure_supervisor () {
  # Copy template supervisor service for gunicorn and novnc
  echo "  * Copying supervisor configuration"
  cp "$APP_PATH"/conf/supervisor/webvirtcloud.conf "$supervisor_conf_path"/"$supervisor_file_name"
  nginx_group_escape="$(echo -n "$nginx_group"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  sed -i "s|^\\(user=\\).*|\\1$nginx_group_escape|" "$supervisor_conf_path/$supervisor_file_name"
}

create_user () {
  echo "* Creating webvirtcloud user."

  if [ "$distro" == "ubuntu" ] || [ "$distro" == "debian" ] ||
    [[ "$distro" == "uos" && "$codename" == "eagle" ]]; then
    adduser --quiet --disabled-password --gecos '""' "$APP_USER"
  else
    adduser "$APP_USER"
  fi

  usermod -a -G "$nginx_group" "$APP_USER"
  usermod -a -G libvirt "$nginx_group"
}

run_as_app_user () {
  if ! hash sudo 2>/dev/null; then
      su -c "$@" "$APP_USER"
  else
      sudo -i -u "$APP_USER" "$@"
  fi
}

activate_python_environment () {
    cd "$APP_PATH" || exit
    virtualenv -p "$PYTHON" venv
    # shellcheck disable=SC1091
    source venv/bin/activate
}

generate_secret_key() {
  "$PYTHON" - <<END
import random
print(''.join(random.SystemRandom().choice('abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)') for i in range(50)))
END
}


install_webvirtcloud () {
  create_user
 
  echo "* Cloning $APP_NAME from github to the web directory."
  log "git clone $APP_REPO_URL $APP_PATH"

  echo "* Configuring settings.py file."
  cp "$APP_PATH/webvirtcloud/settings.py.template" "$APP_PATH/webvirtcloud/settings.py"
  
  secret_key=$(generate_secret_key)
  echo "* Secret for Django generated: $secret_key"
  tzone_escape="$(echo -n "$tzone"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  secret_key_escape="$(echo -n "$secret_key"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  novncd_port_escape="$(echo -n "$novncd_port"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  novncd_public_port_escape="$(echo -n "$novncd_public_port"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"
  novncd_host_escape="$(echo -n "$novncd_host"|sed -e 's/[](){}<>=:\!\?\+\|\/\&$*.^[]/\\&/g')"

  #TODO escape SED delimiter in variables
  sed -i "s|^\\(TIME_ZONE = \\).*|\\1$tzone_escape|" "$APP_PATH/webvirtcloud/settings.py"
  sed -i "s|^\\(SECRET_KEY = \\).*|\\1\'$secret_key_escape\'|" "$APP_PATH/webvirtcloud/settings.py"
  sed -i "s|^\\(WS_PORT = \\).*|\\1$novncd_port_escape|" "$APP_PATH/webvirtcloud/settings.py"
  sed -i "s|^\\(WS_PUBLIC_PORT = \\).*|\\1$novncd_public_port_escape|" "$APP_PATH/webvirtcloud/settings.py"
  sed -i "s|^\\(WS_HOST = \\).*|\\1\'$novncd_host_escape\'|" "$APP_PATH/webvirtcloud/settings.py"

  # set CSRF TRUSTED ORIGINS
  host_ip="'http://127.0.0.1', "
  for i in $(hostname -I); do
    host_ip+="'http://$i', " 
  done
  sed -i "s|^\\(CSRF_TRUSTED_ORIGINS = \\).*|\\1\[ \'http://$fqdn\', $host_ip ]|" /srv/webvirtcloud/webvirtcloud/settings.py

  echo "* Activate virtual environment."
  activate_python_environment

  echo "* Install App's Python requirements."
  pip3 install -U pip
  pip3 install -r conf/requirements.txt -q

  

  chown -R "$nginx_group":"$nginx_group" "$APP_PATH"

  
  echo "* Django Migrate."
  log "$PYTHON $APP_PATH/manage.py migrate"
  $PYTHON $APP_PATH/manage.py makemigrations
  $PYTHON $APP_PATH/manage.py migrate
  
  
  echo "* Django Collect Static"
  log "$PYTHON $APP_PATH/manage.py collectstatic --noinput"
  $PYTHON $APP_PATH/manage.py collectstatic --noinput
  
  chown -R "$nginx_group":"$nginx_group" "$APP_PATH"
}

set_firewall () {
  if test -n "$(command -v firewall-cmd)" && test "$(firewall-cmd --state)" == "running"; then
    echo "* Configuring firewall to allow HTTP & novnc traffic."
    log "firewall-cmd --zone=public --add-port=http/tcp --permanent"
    log "firewall-cmd --zone=public --add-port=$novncd_port/tcp --permanent"
    #firewall-cmd --zone=public --add-port=$novncd_port/tcp --permanent
    log "firewall-cmd --zone=public --add-port=$novncd_public_port/tcp --permanent"
    #firewall-cmd --zone=public --add-port=$novncd_public_port/tcp --permanent
    log "firewall-cmd --reload"
    #firewall-cmd --reload
  fi
}

set_selinux () {
  #Check if SELinux is enforcing
  if [ "$(getenforce)" == "Enforcing" ]; then
    echo "* Configuring SELinux."
    #Sets SELinux context type so that scripts running in the web server process are allowed read/write access
    chcon -R -h -t httpd_sys_rw_content_t "$APP_PATH/"
    setsebool -P httpd_can_network_connect 1
  fi
}

set_hosts () {
  echo "* Setting up hosts file."
  echo >> /etc/hosts "127.0.0.1 $(hostname) $fqdn"
}

restart_supervisor () {
    echo "* Setting Supervisor to start on boot and restart."
    log "systemctl enable $supervisor_service"
    #systemctl enable $supervisor_service
    log "systemctl restart $supervisor_service"
    #systemctl restart $supervisor_service
}

restart_nginx () {
    echo "* Setting Nginx to start on boot and starting Nginx."
    log "systemctl enable nginx.service"
    #systemctl enable nginx.service
    log "systemctl restart nginx.service"
    #systemctl restart nginx.service
}


if [[ -f /etc/lsb-release || -f /etc/debian_version ]]; then
  distro="$(lsb_release -is)"
  version="$(lsb_release -rs)"
  codename="$(lsb_release -cs)"
elif [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  distro="$(source /etc/os-release && echo "$ID")"
  # shellcheck disable=SC1091
  version="$(source /etc/os-release && echo "$VERSION_ID")"
  #Order is important here.  If /etc/os-release and /etc/centos-release exist, we're on centos 7.
  #If only /etc/centos-release exist, we're on centos6(or earlier).  Centos-release is less parsable,
  #so lets assume that it's version 6 (Plus, who would be doing a new install of anything on centos5 at this point..)
  #/etc/os-release properly detects fedora
elif [ -f /etc/centos-release ]; then
  distro="centos"
  version="8"
else
  distro="unsupported"
fi


echo '
      WEBVIRTCLOUD
'

echo "" 
echo "  Welcome to Webvirtcloud Installer for RHEL&Alternatives, Fedora, Debian and Ubuntu!"
echo ""
shopt -s nocasematch
case $distro in
  *ubuntu*)
    echo "  The installer has detected $distro version $version codename $codename."
    distro=ubuntu
    nginx_group=www-data
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    supervisor_service=supervisord
    supervisor_conf_path=/etc/supervisor/conf.d
    supervisor_file_name=webvirtcloud.conf
    ;;
  *debian*)
    echo "  The installer has detected $distro version $version codename $codename."
    distro=debian
    nginx_group=www-data
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    supervisor_service=supervisor
    supervisor_conf_path=/etc/supervisor/conf.d
    supervisor_file_name=webvirtcloud.conf
    ;;
  *centos*|*redhat*|*ol*|*rhel*|*rocky*|*Rocky*|*alma*)
    echo "  The installer has detected $distro version $version."
    distro=centos
    nginx_group=nginx
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    supervisor_service=supervisord
    supervisor_conf_path=/etc/supervisord.d
    supervisor_file_name=webvirtcloud.ini
    ;;
  *Uos*|*uos*)
    # codename may be fuyu, kongzi, eagle or empty string.
    output_expand=""
    if test -n "${codename}"; then
      output_expand=" codename ${codename}"
    fi
    echo "  The installer has detected $distro version $version${output_expand}."
    distro=uos
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    if test "${codename}" == "eagle"; then
      nginx_group=www-data
      supervisor_service=supervisor
      supervisor_conf_path=/etc/supervisor/conf.d
      supervisor_file_name=webvirtcloud.conf
    else
      nginx_group=nginx
      supervisor_service=supervisord
      supervisor_conf_path=/etc/supervisord.d
      supervisor_file_name=webvirtcloud.ini
    fi
    ;;
  *OpenEuler*|*openEuler*)
    echo "  The installer has detected $distro version $version."
    distro=openEuler
    nginx_group=nginx
    nginxfile=/etc/nginx/conf.d/$APP_NAME.conf
    supervisor_service=supervisord
    supervisor_conf_path=/etc/supervisord.d
    supervisor_file_name=webvirtcloud.ini
    ;;
  *)
    echo "  The installer was unable to determine your OS. Exiting for safety."
    exit 1
    ;;
esac

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

      if [ ! -z $fqdn_from_user ]; then
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

echo -n "  Q. NOVNC public port number for reverse proxy(e.g: 80 or 443)?(Default: 6080) "
read -r novncd_public_port
if [ -z "$novncd_public_port" ]; then
  readonly novncd_public_port=6080
fi
echo "     Setting novnc public port $novncd_public_port"
echo ""

echo -n "  Q. NOVNC host listen ip?(Default: 0.0.0.0) "
read -r novncd_host
if [ -z "$novncd_host" ]; then
  readonly novncd_host="0.0.0.0"
fi
echo "     Setting novnc host ip $novncd_host"
echo ""

echo "========="
echo "distro: ${distro}"
echo "========="
case $distro in
  debian)
  if [[ "$version" -ge 9 ]]; then
    # Install for Debian 9.x / 10.x
    tzone=\'$(cat /etc/timezone)\'

    echo -n "* Updating installed packages."
    log "apt-get update && apt-get -y upgrade" & pid=$!
    progress

    echo "*  Installing OS requirements."
    PACKAGES="git virtualenv python3-virtualenv python3-dev python3-lxml libvirt-dev zlib1g-dev libxslt1-dev libsasl2-dev libldap2-dev nginx smbios-utils libsasl2-modules gcc pkg-config python3-guestfs uuid"
    
    install_packages
    
    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring Supervisor."
    log "pip install supervisor "
    configure_supervisor

    restart_supervisor
    restart_nginx
  fi
  ;;
  ubuntu)
 if [ "$version" == "18.04" ] || [ "$version" == "20.04" ]; then
    # Install for Ubuntu 18 / 20
    tzone=\'$(cat /etc/timezone)\'

    echo -n "* Updating installed packages."
    log "apt-get update && apt-get -y upgrade" & pid=$!
    progress

    echo "*  Installing OS requirements."
    PACKAGES="git virtualenv python3-virtualenv python3-pip python3-dev python3-lxml libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring Supervisor."
    log "pip install supervisor "
    configure_supervisor

    restart_supervisor
    restart_nginx

  fi  
  ;;
  centos)
  if [[ "$version" =~ ^8 ]] || [[ "$version" =~ ^9  ]]; then
    # Install for CentOS/Redhat 8
    tzone=\'$(timedatectl|grep "Time zone"| awk '{print $3}')\'

    echo "* Adding wget & epel-release repository."
    log "yum -y install wget epel-release"

    echo "* Installing OS requirements."
    PACKAGES="git python3-virtualenv python3-devel libvirt-devel glibc gcc nginx python3-lxml python3-libguestfs iproute-tc cyrus-sasl-md5 openldap-devel"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring Supervisor."
    log "pip install supervisor "
    configure_supervisor
    
    set_firewall 
    
    set_selinux

    restart_supervisor
    restart_nginx
    

  else
    echo "Unsupported CentOS version. Version found: $version"
    exit 1
  fi
  ;;
  uos)
  if [[ "$version" == "20" ]]; then
    # Install for uos 20
    tzone=\'$(timedatectl|grep "Time zone"| awk '{print $3}')\'

    echo "* Installing OS requirements."
    if test "${codename}" == "eagle"; then
      PACKAGES="git virtualenv python3-virtualenv python3-dev python3-lxml libvirt-dev zlib1g-dev libxslt1-dev nginx libsasl2-modules gcc pkg-config python3-guestfs uuid"
    else
      PACKAGES="git python3-virtualenv python3-devel python3-pip libvirt-devel glibc gcc nginx python3-lxml python3-libguestfs iproute-tc cyrus-sasl-md5"
    fi
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring Supervisor."
    log "pip install supervisor "
    configure_supervisor

    set_firewall

    set_selinux

    restart_supervisor
    restart_nginx
  fi
  ;;
  openEuler)
  if [[ "$version" == "20.03" ]]; then
    # Install for openEuler 20.03
    tzone=\'$(timedatectl|grep "Time zone"| awk '{print $3}')\'

    echo "* Installing OS requirements."
    PACKAGES="git python3-virtualenv python3-devel python3-pip libvirt-devel glibc gcc nginx python3-lxml python3-libguestfs iproute-tc cyrus-sasl-md5"
    install_packages

    set_hosts

    install_webvirtcloud

    echo "* Configuring Nginx."
    configure_nginx

    echo "* Configuring Supervisor."
    log "pip install supervisor "
    configure_supervisor

    set_firewall

    set_selinux

    restart_supervisor
    restart_nginx
  fi
  ;;
esac


echo ""
echo "  ***Open http://$fqdn to login to webvirtcloud.***"
echo ""
echo ""
echo "* Cleaning up..."
rm -f webvirtcloud.sh
rm -f install.sh
echo "* Finished!"
sleep 1
