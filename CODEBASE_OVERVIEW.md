# WebVirtCloud - Kod Tabanı İnceleme ve Mimari Dokümantasyonu

Bu doküman, **WebVirtCloud** projesinin mimari yapısını, temel bileşenlerini, veri akışını ve modüller arası ilişkilerini açıklamak amacıyla hazırlanmıştır.

---

## 1. Genel Tanım ve Amacı

**WebVirtCloud**, QEMU/KVM tabanlı hipervizörlerin ve bu hipervizörler üzerinde koşan sanal makinelerin (VM/Instance) web tabanlı arayüz ve REST API aracılığıyla yönetilmesini sağlayan açık kaynaklı bir sanallaştırma yönetim platformudur.

Platform, hem sistem yöneticilerine birden fazla fiziksel KVM sunucusunu tek noktadan yönetme imkânı sunar, hem de son kullanıcılara kendilerine atanan sanal makineleri kontrol etme (başlatma, durdurma, yeniden başlatma, konsol erişimi, snapshot alma, kaynak izleme) yetkisi tanır.

---

## 2. Teknoloji Yığını (Tech Stack)

| Katman | Teknoloji / Kütüphane | Açıklama |
|---|---|---|
| **Çalışma Zamanı** | Python >= 3.11 | Modern Python çalışma ortamı |
| **Web Çatısı** | Django 4.2 LTS | MVC tabanlı ana web altyapısı ve ORM |
| **API** | Django REST Framework (DRF) + drf-spectacular | RESTful API uçları ve OpenAPI 3.0 / Swagger dokümantasyonu |
| **Sanallaştırma API** | `libvirt-python` (11.4.0) + `lxml` | Libvirt API çağrıları ve XML domain/storage/network tanımlamaları |
| **Konsol / VNC** | WebSockify + noVNC | Web tarayıcısı üzerinden HTML5 VNC/SPICE konsol erişimi |
| **Ön Yüz (Frontend)** | Django Templates, Bootstrap 5, Bootstrap Icons, jQuery | Sunucu taraflı render edilen dinamik kullanıcı arayüzü |
| **Kimlik & Güvenlik** | Django Auth, `django-otp` (2FA/TOTP), `django-auth-ldap` | Rol bazlı yetkilendirme, 2 faktörlü doğrulama, LDAP/Active Directory desteği |
| **Web / WSGI Sunucu** | Nginx + Gunicorn + WhiteNoise | Statik dosya dağıtımı ve ters vekil sunucu mimarisi |
| **Süreç Yöneticisi** | Supervisor / Runit / Systemd | Gunicorn ve novncd arka plan servislerinin yönetimi |

---

## 3. Sistem Mimarisi ve Temel Katmanlar

```
                               +-----------------------------+
                               |     Web Tarayıcısı / İstemci |
                               +--------------+--------------+
                                              |
                       HTTP / HTTPS (Port 80/443)   WebSockets (Port 6080)
                                              |              |
                                              v              v
+------------------------------------------------------------------------------------+
| Nginx Reverse Proxy                                                                |
|   ├── /static/  --> Statik Dosyalar (WhiteNoise / Nginx)                           |
|   ├── /         --> Gunicorn (Django WSGI Application)                             |
|   └── :6080     --> WebSockify (novncd arka plan servisi)                         |
+-------------------------------------+----------------------------------------------+
                                      |
                                      v
+------------------------------------------------------------------------------------+
| Django Uygulama Katmanı (WebVirtCloud)                                             |
|                                                                                    |
|  [accounts]      Kullanıcılar, Roller, Kotalar, SSH Keyler, 2FA, LDAP             |
|  [computes]      Hipervizör (Compute Node) bağlantı tanımları                     |
|  [instances]     Sanal makine modelleri, yaşam döngüsü, migrate, flavor            |
|  [storages]      Storage havuzları ve disk hacimleri (dir, lvm, rbd/ceph vb.)     |
|  [networks]      Sanal ağlar (NAT, isolated, bridge vb.)                           |
|  [interfaces]    Fiziksel / köprü ağ arayüzleri                                    |
|  [nwfilters]     Ağ filtreleme ve güvenlik duvarı kuralları                        |
|  [virtsecrets]   Libvirt gizli anahtarları (Ceph auth vb.)                        |
|  [datasource]    Cloud-init metadata / userdata servisleri                        |
|  [logs]          Kullanıcı ve sistem işlem denetim kayıtları (audit log)          |
|  [api/v1]        DRF Nested Routers ile REST API uçları                            |
+-------------------------------------+----------------------------------------------+
                                      |
                                      v
+------------------------------------------------------------------------------------+
| vrtManager Katmanı (Libvirt Abstraction Engine)                                    |
|   ├── connection.py  --> TCP, SSH, TLS veya yerel Socket ile Libvirt bağlantısı    |
|   ├── instance.py    --> XML Domain üretimi, CPU/RAM/Disk/Snapshot/Metrics         |
|   ├── storage.py     --> Storage pool & volume XML yönetimi                        |
|   ├── network.py     --> Network XML konfigürasyonu ve IP yönetimi                 |
|   └── hostdetails.py --> Node info, bellek ve CPU kullanım metrikleri             |
+-------------------------------------+----------------------------------------------+
                                      |
                       Libvirt Protokolü (TCP/SSH/TLS/Socket)
                                      |
                                      v
+------------------------------------------------------------------------------------+
| KVM / QEMU Hipervizör Sunucuları                                                   |
|   ├── libvirtd / virtqemud                                                         |
|   ├── QEMU Guest Domainleri (VMs) + QEMU Guest Agent                               |
|   └── Storage & Network Altyapısı (ZFS, LVM, Ceph RBD, Linux Bridge, OVS)          |
+------------------------------------------------------------------------------------+
```

---

## 4. Modüller ve Dizin Yapısı Analizi

### 4.1. `vrtManager/` (Çekirdek Libvirt Motoru)
Projenin en kritik Python paketidir. Django modelleri veritabanında hipervizörlerin durumlarını statik tutmak yerine, libvirt ile doğrudan canlı haberleşir.
- **`connection.py`**: Farklı bağlantı tipleri (`CONN_TCP`, `CONN_SSH`, `CONN_TLS`, `CONN_SOCKET`) üzerinden libvirt bağlantı havuzunu (`connection_manager`) yönetir. Eşzamanlı erişimler için `ReadWriteLock` kullanır.
- **`instance.py`**: `wvmInstance` sınıfı aracılığıyla sanal makinelerin başlatılması, kapatılması, duraklatılması, yeniden başlatılması, CPU/RAM boyutlandırması, disk ekleme/çıkarma, XML düzenleme, snapshot işlemleri ve anlık donanım istatistiklerini (vCPU, ağ I/O, disk I/O) çeker.
- **`create.py`**: XML şablonlarını dinamik üreterek yeni sanal makineler oluşturan motor.
- **`storage.py` & `network.py`**: Depolama havuzları (dir, lvm, iscsi, rbd/ceph) ve libvirt sanal ağlarının yönetimini üstlenir.
- **`hostdetails.py`**: Hipervizörün toplam bellek, CPU kullanımı ve donanım mimarisi bilgilerini sağlar.

### 4.2. `computes/` (Hipervizör Yönetimi)
- Hipervizör ana makine (host) kayıtlarını barındırır (`hostname`, `login`, `password`, `type`).
- Canlı bağlantı nesnesini `connection_manager` üzerinden lazy olarak temin eder (`cached_property`).
- REST API üzerinden mimarileri (`archs`), işlemci ve bellek durumlarını dışa aktarır.

### 4.3. `instances/` (Sanal Makine Yönetimi)
- **`Instance` Modeli**: Sanal makinenin `compute` ilişkisini, benzersiz `uuid` değerini ve `name` bilgisini saklar. Dinamik tüm durumlar (durum, bellek, vcpu, diskler, ağ kartları vb.) `vrtManager.instance.wvmInstance` vekili (proxy) üzerinden okunur.
- **`Flavor` Modeli**: AWS EC2 veya OpenStack benzeri hazır boyut şablonlarını (vcpu, ram, disk) tanımlar.
- **`MigrateInstance`**: Sanal makinelerin canlı (live), çevrimdışı (offline), sıkıştırmalı (compressed) veya güvensiz (unsafe) yöntemlerle başka bir compute host'a taşınmasını sağlar.
- **`views.py`**: VM oluşturma sihirbazı, düzenleme, klonlama, snapshot ve güç kontrollerini içerir.

### 4.4. `accounts/` (Kullanıcılar, İzinler ve Kotalar)
- Standart Django `User` modeline ek olarak:
  - **`UserInstance`**: Kullanıcıya belirli bir VM üzerinde okuma, değiştirme (`is_change`), silme (`is_delete`) ve konsol açma (`is_vnc`) yetkilerini delege eder.
  - **`UserAttributes`**: Kullanıcı bazında kota belirler (Maksimum VM adedi, maksimum vCPU, maksimum RAM ve maksimum disk boyutu).
  - **`UserSSHKey`**: Kullanıcının VM'lere otomatik enjekte edilecek açık anahtarlarını depolar.
  - İki faktörlü kimlik doğrulama (TOTP/QR) ve opsiyonel LDAP/AD senkronizasyonunu yönetir.

### 4.5. `console/` (Uzak Konsol Erişimi)
- **`novncd`**: Python tabanlı WebSockify uygulamasını çalıştırarak tarayıcıdaki noVNC istemcisi ile KVM üzerindeki VNC/SPICE portu arasında WebSocket köprüsü kurar.
- **`sshtunnels.py`**: Compute host uzak bir sunucuda ise ve doğrudan VNC portu dışarıya açık değilse, güvenli SSH tüneli açarak konsol bağlantısını yerel sokete yönlendirir.

### 4.6. `datasource/` (Cloud-Init Desteği)
- Cloud-init uyumlu bir HTTP metadata/userdata sunucusudur.
- VM ilk açıldığında `http://<webvirtcloud>/datasource/` adresine istek atar.
- İstemci IP'sinden hostname ve VM adı çözülerek, VM sahibine ait SSH açık anahtarları `user-data` şablonu halinde VM'e teslim edilir. Böylece şifresiz SSH erişimi otomatik ayarlanır.

### 4.7. `storages/`, `networks/`, `interfaces/`, `nwfilters/`, `virtsecrets/`
- **`storages`**: Dizin, LVM, NFS, iSCSI ve Ceph RBD depolama havuzları oluşturma, ISO yükleme, disk hacmi (volume) klonlama ve silme.
- **`networks`**: NAT, Routed, Bridge ve Isolated sanal ağ oluşturma, DHCP havuzu ve statik IP/MAC eşleme.
- **`interfaces`**: Fiziksel host ağ arayüzlerini ve köprüleri (bridges) listeleme ve yönetme.
- **`nwfilters`**: MAC/IP sahteciliğini önleyen (anti-spoofing) ve paket filtreleyen kuralları yönetme.
- **`virtsecrets`**: Özellikle Ceph kimlik doğrulaması için gereken Libvirt secret tanımlarını yönetme.

### 4.8. `logs/` & `appsettings/` & `admin/`
- **`logs`**: Hangi kullanıcının hangi instance üzerinde ne zaman ne işlem yaptığını (güç açma, kapatma, disk ekleme vb.) kaydeden denetim günlüğü.
- **`appsettings`**: Veritabanı üzerinde dinamik olarak uygulama parametrelerini (site başlığı, izinler vb.) saklar ve context processor ile arayüze taşır.
- **`admin`**: Kullanıcı, grup ve genel sistem yönetim paneli.

---

## 5. REST API Mimarisi (`/api/v1/`)

Django REST Framework (`drf-nested-routers`) kullanılarak hiyerarşik bir kaynak yapısı kurgulanmıştır:

- `/api/v1/computes/` : Hipervizör listesi ve yönetimi
  - `/api/v1/computes/{id}/instances/` : İlgili hipervizördeki sanal makineler
  - `/api/v1/computes/{id}/instances/create/{arch}/{machine}/` : Yeni sanal makine oluşturma
  - `/api/v1/computes/{id}/networks/` : Sanal ağlar
  - `/api/v1/computes/{id}/interfaces/` : Ağ arayüzleri
  - `/api/v1/computes/{id}/storages/` : Depolama havuzları
    - `/api/v1/computes/{id}/storages/{id}/volumes/` : Depolama birimleri (diskler)
  - `/api/v1/computes/{id}/archs/` : Desteklenen mimariler
- `/api/v1/instances/` : Genel sanal makine listesi
- `/api/v1/flavor/` : Boyut şablonları
- `/api/v1/migrate/` : Sanal makine taşıma operasyonları
- `/swagger/` & `/redoc/` : Canlı API dokümantasyonu

---

## 6. Dağıtım ve Servis Yaşam Döngüsü

1. **Gunicorn**: WSGI uygulaması olarak `webvirtcloud.wsgi:application` çalışır (Port: Nginx unix socket veya 8000).
2. **novncd**: Arka planda çalışarak VNC/SPICE portlarını `6080` portundan WebSocket'e çevirir.
3. **Nginx**: 80/443 portlarından dış dünyayı karşılar, statik dosyaları sunar, dinamik istekleri Gunicorn'a, VNC WebSocket trafiğini ise `novncd` servisine iletir.
4. **Supervisor / Runit**: Docker ortamında (`Dockerfile`) Phusion BaseImage tabanlı runit kullanılırken, standart Linux sunucularında Supervisor veya Systemd servisleri kullanılır.

---

## 7. Özet Değerlendirme

WebVirtCloud, **Django ORM**'in gücünü doğrudan **libvirt C API binding'leri** ile hibrit şekilde birleştiren, veritabanında sadece temel ilişkileri tutup asıl durum ve metrikleri gerçek zamanlı olarak doğrudan sanallaştırma katmanından okuyan esnek ve hafif bir yönetim panelidir.
