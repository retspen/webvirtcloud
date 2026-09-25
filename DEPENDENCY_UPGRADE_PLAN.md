# WebVirtCloud - Bağımlılık ve Kütüphane Güncelleme Planı

Bu doküman, WebVirtCloud projesinde yer alan eski, desteği kesilmiş veya yeni Python/Django sürümleriyle uyumsuzluk riski taşıyan kütüphanelerin tespitini ve adım adım güncelleme yol haritasını içermektedir.

---

## 1. Tespit Edilen Kütüphaneler ve Durum Analizi

### 1.1. Kritik ve Acil Müdahale Gerektirenler (Python 3.12+ Uyumsuzlukları)

| Kütüphane / Dosya | Mevcut Durum | Risk Seviyesi | Tespit ve Sorun |
|---|---|---|---|
| **`vrtManager/rwlock.py`** | `currentThread()` kullanımı | 🔴 **Kritik (Bozucu)** | Python 3.10'da kullanımdan kaldırılmış (deprecated), **Python 3.12'de tamamen silinmiştir**. Python 3.12 üzerinde `ImportError: cannot import name 'currentThread' from 'threading'` hatası verir. `threading.current_thread()` ile değiştirilmelidir. |
| **`rwlock==0.0.7`** (`conf/requirements.txt`) | 2014 sürümü (Terk edilmiş) | 🟡 **Gereksiz Bağımlılık** | Projede kod zaten `vrtManager/rwlock.py` üzerinden yerel (vendored) çalışmaktadır. `requirements.txt` içerisindeki bu harici paket gereksizdir ve temizlenebilir. |
| **`console/novncd` & `socketiod` (`optparse`)** | `optparse` kullanımı | 🟠 **Orta (Kullanımdan Kaldırıldı)** | `optparse` Python 3.2'den beri deprecated olup yerini standart `argparse` kütüphanesine bırakmıştır. Modern Python standartlarına göre refactor edilmelidir. |
| **`eventlet==0.40.1`** | `socketiod` içinde kullanılır | 🟠 **Yüksek Risk** | Eventlet, Python 3.12+ C-API ve greenlet değişiklikleriyle uyumluluk sorunları yaşamaktadır. Gelecekte asyncio/ASGI mimarisine geçiş planlanmalıdır. |

---

### 1.2. Django & API Ekosistemi

| Kütüphane | Mevcut Sürüm | Hedef Sürüm | Açıklama & Strateji |
|---|---|---|---|
| **`Django`** | `4.2.23` (LTS) | `5.1.x` / `5.2` (LTS) | Django 4.2 LTS desteği Nisan 2026'da sona ermektedir. Django 5.x LTS'e yükseltme yapılarak performans kazanımları (asenkron ORM geliştirmeleri, yeni form alanları) elde edilmelidir. |
| **`django-login-required-middleware`** | `0.9.0` (2017) | **Kaldırılacak** (Native) | Paket 2017'den beri güncellenmemiştir. **Django 5.1 ile birlikte Django artık yerleşik `django.contrib.auth.middleware.LoginRequiredMiddleware` sunmaktadır.** Harici paket tamamen devreden çıkarılabilir. |
| **`drf-yasg`** | `1.21.10` | `drf-spectacular` ✅ | Terk edilmiş Swagger 2.0 kütüphanesi yerine modern OpenAPI 3.0 standardı olan **`drf-spectacular`** (sidecar ile offline/air-gapped destekli) kuruldu. |
| **`IPy.py`** (`vrtManager/IPy.py`) | Vendored 1.01 (2011) | Python Standard `ipaddress` ✅ | 1650+ satırlık eski harici kod silindi, standart `ipaddress` modülüne geçildi ve 15 adet unit test eklendi. |

---

### 1.3. Ön Yüz (Frontend) ve VNC İstemcisi

| Kütüphane | Mevcut Sürüm | Güncel Sürüm | Yenilikler & Faydalar |
|---|---|---|---|
| **`jQuery`** | `3.6.1` (2022) | `3.7.1` | Güvenlik yamaları, seçici (selector) optimizasyonları ve hata düzeltmeleri. |
| **`Bootstrap`** | `5.2.2` (2022) | `5.3.3` | Yerel Karanlık Mod (Dark Mode) desteği, CSS değişkenleri mimarisi, erişilebilirlik ve form iyileştirmeleri. |
| **`noVNC`** (`static/js/novnc`) | 2020 Sürümü | `1.5.0` | Çok daha kararlı WebSocket yeniden bağlanma (auto-reconnect), dokunmatik ekran desteği, güvenlik düzeltmeleri ve modern ES modül yapısı. |

---

### 1.4. Altyapı ve Konteyner

| Bileşen | Mevcut Durum | Önerilen Durum | Açıklama |
|---|---|---|---|
| **`Dockerfile` Base Image** | `phusion/baseimage:jammy-1.0.1` (Ubuntu 22.04) | `phusion/baseimage:noble-1.0.0` (Ubuntu 24.04 LTS) | Ubuntu 24.04 LTS tabanına geçilerek daha yeni sistem kütüphaneleri (`libvirt`, `openssl`, `gcc`) temin edilebilir. |

---

## 2. Aşamalı Güncelleme Yol Haritası (Migration Roadmap)

### Aşama 1: Hızlı Kazanımlar ve Python 3.12+ Uyumluluğu (Hemen Yapılabilir)
1. **`vrtManager/rwlock.py` Düzeltmesi**:
   - `currentThread()` çağrılarını `current_thread()` ile değiştirerek Python 3.12'deki kritik çökme riskini ortadan kaldırmak.
2. **`requirements.txt` Temizliği**:
   - Kullanılmayan `rwlock==0.0.7` paketini `conf/requirements.txt` dosyasından silmek.
3. **Frontend Kütüphanelerinin Güncellenmesi**:
   - `jQuery` 3.6.1 -> 3.7.1
   - `Bootstrap` 5.2.2 -> 5.3.3

---

### Aşama 2: API ve Dokümantasyon Modernizasyonu (Orta Vadeli)
1. **Swagger / OpenAPI Göçü**:
   - `drf-yasg` yerine `drf-spectacular` kurulumu.
   - `webvirtcloud/urls.py` ve `urls-api.py` rotalarının OpenAPI 3.0 şemasına güncellenmesi.
2. **CLI Argümanları Refactor**:
   - `console/novncd` ve `console/socketiod` içerisindeki `optparse` yerine standart `argparse` modülünün entegre edilmesi.

---

### Aşama 3: Django 5.x LTS Geçişi (Büyük Sürüm Güncellemesi)
1. **LoginRequiredMiddleware Değişimi**:
   - `django-login-required-middleware` paketinin kaldırılması.
   - Django 5.1+'ın yerleşik `django.contrib.auth.middleware.LoginRequiredMiddleware` sınıfına geçilmesi.
2. **Django 4.2 -> 5.1/5.2 Yükseltmesi**:
   - `conf/requirements.txt` içinde Django sürümünün artırılması.
   - `python3 manage.py check` ve test suitinin (`pytest` / `python manage.py test`) koşturularak deprecation uyarılarının temizlenmesi.

---

### Aşama 4: noVNC ve Ağ Modülleri Optimizasyonu
1. **noVNC 1.5.0 Entegrasyonu**:
   - `static/js/novnc/` klasörünün noVNC 1.5.0 resmi sürümüyle yenilenmesi.
2. **`vrtManager/IPy.py` Refactor**:
   - Harici IPy kütüphanesi yerine standart `ipaddress` kütüphanesine geçiş.
