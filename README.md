# ZENTINEL NVR 🎥

[![License: Open Source](https://img.shields.io/badge/License-Open%20Source-blue.svg)](LICENSE)
[![Status: Beta](https://img.shields.io/badge/Status-1.0%20Beta-orange.svg)]()
[![Python: Django](https://img.shields.io/badge/Backend-Django-green.svg)](https://www.djangoproject.com/)
[![Proxy: go2rtc](https://img.shields.io/badge/Stream%20Proxy-go2rtc-purple.svg)](https://github.com/AlexxIT/go2rtc)

---

## 📌 GENERAL OVERVIEW

**Zentinel NVR** is a modern and modular application designed for managing IP video surveillance systems. It focuses on high efficiency and low hardware resource consumption, minimizing video transcoding through native integration with **go2rtc**.

Zentinel adopts a **Stream-Copy First** approach: all video feeds (ONVIF, RTSP, HTTP) are normalized via `go2rtc` using local RTSP and WebRTC loopback endpoints (`rtsp://127.0.0.1:8554`). Live streaming and video recording occur without video re-encoding, preserving CPU performance unless strict transcoding is required by the source codec.

### Key Features
* **Modular Architecture:** Django-based backend with streaming operations delegated to `go2rtc` and `ffmpeg`.
* **Multilingual Support:** Native support for **English** and **Italian** (additional languages can be added upon request).
* **User Management:** Integrated Django Dashboard and Admin Panel (`/admin`) for user authentication, roles, and access control.
* **Supported Protocols:**
  * **ONVIF:** Automatic stream discovery and URL resolution via `go2rtc` API.
  * **RTSP:** Native direct support for standard RTSP feeds.
  * **HTTP:** Adaptive streaming for non-standard HTTP endpoints (FLV, TS, MJPEG). The system analyzes the source (codec/format) and applies the most efficient encapsulation to prevent unnecessary transcoding.

> ⚠️ **Note on HTTP:** Since HTTP lacks standardized IP camera specifications, it requires higher hardware resources compared to RTSP/ONVIF and may exhibit lower stability. Thorough testing is recommended prior to production deployment.

---

## 🛠️ INSTALLATION & USEFUL COMMANDS

### Prerequisites
* [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) installed on your host system.

### Quick Start Guide

1. **Clone the repository and set up environment variables:**
   ```bash
   cp .env.example .env
   ```
   *Edit `.env` to configure network variables and secret keys.*

2. **Start Docker containers:**
   ```bash
   docker compose up -d --build
   ```

3. **Apply database migrations:**
   ```bash
   docker compose exec web python manage.py migrate
   ```

4. **Create an Admin Superuser:**
   ```bash
   docker compose exec web python manage.py createsuperuser
   ```
   *(Ensure you choose a strong password)*

5. **Monitor realtime logs:**
   ```bash
   docker compose logs -f
   ```
6. **Create a View-Only User (Optional):**
   To create a restricted user with permissions limited solely to viewing camera feeds (without access to configuration settings or user management):
   - Log into the Django Admin panel at `http://app_ip/admin/` using your superuser credentials.
   - Go to **Users** and click **Add user**.
   - Set an `Username` and `Password` for the new user and click **Save**.
   - On the user details page, ensure **Active** is checked, but leave **Staff status** and **Superuser status** UNCHECKED.
   - Under **User permissions**, assign only read access: `camera | camera | Can view camera` (or assign the user to a dedicated `Viewers` group).
---
7. **Firewall Setup (Recommended):**
   Since the services run in `network_mode: host`, it is recommended to execute the script to restrict external access solely to web port `80` (and port `22` for SSH), blocking direct access to internal ports `8000` (Django) and `1984` (go2rtc):

   ```bash
   chmod +x set_firewall.sh
   sudo ./set_firewall.sh

## 📹 CAMERA CONFIGURATION

### Discovery & Probing
Zentinel features an automated **Discovery** tool that analyzes IP addresses (for ONVIF and RTSP) or HTTP URLs. It verifies stream availability and extracts metadata (resolution, FPS, codec), helping users easily distinguish between **Main Stream** and **Sub Stream**.

* **Main Stream:** High-resolution feed intended for full-screen viewing and primary recording.
* **Sub Stream:** Lower-resolution feed used in multi-camera dashboard grids to reduce CPU and bandwidth consumption.

### Storage Paths (`RECORDING_PATH`)
Recording storage volumes must be declared inside `docker-compose.yml`. When configuring cameras via the web panel, simply enter the target path mounted inside the container.

---

## 🏗️ PYTHON MODULES ARCHITECTURE

### 1. Module `go2rtc.py`
Handles state synchronization between the Django database and `go2rtc` REST API (`PUT` for stream creation via `sync_camera_to_go2rtc()`, `DELETE` for removal via `remove_camera_from_go2rtc()`).

* **`analyze_http_stream()`:** Inspects generic HTTP URLs using `ffprobe` to classify codec and format, ensuring optimal API setup without unnecessary transcoding.
* **`get_go2rtc_source()`:** Calls `analyze_http_stream()` if protocol is HTTP, constructs appropriate URLs for `go2rtc`, and flags streams requiring hardware-heavy transcoding.
* **`sync_camera_to_go2rtc()`:** Executes `PUT` requests to register camera streams in `go2rtc`.
* **`remove_camera_from_go2rtc()`:** Executes `DELETE` requests to remove streams using internal unique camera IDs.
* **`probe_stream_ffprobe()`:** Registers a temporary stream in `go2rtc` with a unique UUID, runs `ffprobe` against the local RTSP loopback (`rtsp://127.0.0.1:8554/{temp_id}`), returns detected metadata, and guarantees cleanup inside a `finally` block.
* **`discover_camera_streams()`:** Scans available feeds. For ONVIF, it queries `go2rtc` native endpoints; for RTSP, it probes standard path patterns; for HTTP, it parses the user-provided URL and provides availability, resolution, FPS, and codec info.

### 2. Module `recorder.py`
Controls the video recording pipeline. By leveraging the unified RTSP loopback provided by `go2rtc`, all stream recordings share a single generalized `ffmpeg` process.

* **`start_camera_recording()`:** Spawns `ffmpeg` processes using the camera's unique ID to capture the local RTSP loopback into segmented `.mp4` files within the assigned storage folder.
* **`stop_camera_recording()`:** Safely terminates active recording processes.
* **`check_recorders_health()`:** A watchdog process that checks active recording states and automatically reconnects dropped streams.

### 3. Module `disc_cleaner.py`
Automated storage cleanup utility powered by `APScheduler` (runs hourly by default). Manages storage health using two complementary rules: **Retention Days** and **Disk Usage Threshold**.

* **`get_active_recording_cameras()`:** Queries the database for active cameras with enabled recording.
* **`clean_directory()`:** Checks storage usage. If disk space exceeds **90.00%**, an emergency pass purges the oldest recording folder via `clean_directory_single_pass()`. It also deletes folders that exceed the user-defined retention days.
* **`main()`:** Calls `get_active_recording_cameras()` and executes `clean_directory()` for each camera path.
* **`clean_directory_single_pass()`:** Handles file deletion inside expired directories. Uses `is_file_open_or_locked()` to avoid deleting active files currently being written by `ffmpeg`.
* **Helper functions:** `get_disk_usage_percent()`, `is_file_open_or_locked()`, and `check_if_old_rec()` support date calculations and file locks.

---

## 💡 AUTHOR'S NOTES & DISCLAIMER

> ### Transparency & Development
> This is an Open Source project developed with a clear focus on architectural design and efficiency.
> **This is NOT a "vibe-coded" project.** The system architecture, module logic, and core workflows were designed and implemented manually. Generative AI was utilized solely as a learning and assistance tool for mastering the Django framework, optimizing complex algorithms, and automating tedious repetitive tasks (such as logging and internationalization).

### ⚠️ Beta Release Disclaimer
The application is currently released as **Version 1.0 BETA** as a showcase of its core features.
* As a Beta release, bugs or instabilities may be present.
* **It is NOT recommended for mission-critical or production security deployments.**
* The software is provided "as is", without warranty of any kind. The author assumes no liability for system bugs, data loss, or operational issues resulting from its use.

### 🚀 Roadmap
Future developments aim to:
1. Further stabilize HTTP stream handling and improve overall system encapsulation.
2. Deliver a completely seamless "Plug-and-Play" deployment experience.
3. Integrate support for additional protocols and advanced surveillance features.

*Feedback, bug reports, and pull requests are warmly welcomed!*

---
---

# 🇮🇹 DOCUMENTAZIONE IN ITALIANO 🇮🇹
---

## 📌 PANORAMICA GENERALE

**Zentinel NVR** è un'applicazione moderna per la gestione completa di un sistema di videosorveglianza, basata sull'uso di telecamere IP di varie marche e modelli e dei principali protocolli del settore. È stata progettata con un'architettura modulare, efficiente dal punto di vista della gestione video e della transcodifica (utilizzata solo dove è indispensabile).

Sfrutta le capacità di `go2rtc` per la creazione di loopback in WebRTC/RTSP per rendere standard la gestione di tutti gli stream video, applicando nella maggior parte dei casi una copia diretta del flusso (Stream-Copy) anziché una transcodifica.

### Caratteristiche Principali
* **Gestione Utenti:** Gestione completa tramite la dashboard e il pannello di amministrazione nativo Django.
* **Multilingua:** Supporto nativo per **Italiano** e **Inglese** (con predisposizione per l'inserimento di altre lingue).
* **Protocolli Supportati:**
  * **ONVIF:** Riconoscimento ed estrazione automatica degli stream tramite le funzionalità native di `go2rtc`.
  * **RTSP:** Supporto diretto per flussi RTSP standard.
  * **HTTP:** Implementazione adattiva per stream non standard (FLV, TS, MJPEG). Il sistema analizza le caratteristiche del flusso (codec e formato) per adottare la configurazione più efficiente ed evitare la transcodifica non necessaria.

> ⚠️ **Nota su HTTP:** Non essendo un protocollo con configurazione standard per la videosorveglianza, richiede più risorse hardware rispetto agli altri e rischia di essere instabile se non gestito accuratamente. Si consiglia di effettuare dei test prima di un impiego continuativo.

---

## 🛠️ INSTALLAZIONE E COMANDI UTILI

### Prerequisiti
* [Docker](https://www.docker.com/) e [Docker Compose](https://docs.docker.com/compose/) installati sul sistema.

### Procedura di Installazione

1. **Copia il file di configurazione delle variabili d'ambiente:**
   ```bash
   cp .env.example .env
   ```

2. **Avvia i container in background con build della struttura:**
   ```bash
   docker compose up -d --build
   ```

3. **Esegui le migrazioni del database:**
   ```bash
   docker compose exec web python manage.py migrate
   ```

4. **Crea l'utente Amministratore dell'NVR:**
   ```bash
   docker compose exec web python manage.py createsuperuser
   ```
   *(È importante utilizzare una password complessa)*

5. **Visualizzazione dei log in tempo reale:**
   ```bash
   docker compose logs -f
   ```
6. **Creare un Utente di Sola Visualizzazione (Opzionale):**
   Per creare un utente abilitato unicamente alla visione dei flussi video (senza permessi di modifica delle impostazioni o gestione utenti):
   - Accedi al pannello di amministrazione Django all'indirizzo `http://app_ip/admin/` con le tue credenziali da superuser.
   - Vai nella sezione **Users** e clicca su **Add user**.
   - Imposta `Username` e `Password` per il nuovo utente e clicca su **Save**.
   - Nella scheda del nuovo utente, assicurati che la spunta **Active** sia selezionata e che le opzioni **Staff status** e **Superuser status** rimangano DESELEZIONATE.
   - Nella sezione **User permissions**, assegna esclusivamente il permesso di lettura: `camera | camera | Can view camera` (oppure assegna l'utente a un gruppo dedicato, ad esempio `Viewers`).
---
7. **Configurazione del Firewall (Consigliato):**
   Poiché i servizi utilizzano la modalità `network_mode: host`, si raccomanda di eseguire lo script per limitare l'accesso dall'esterno alla sola porta web `80` (ed eventualmente `22` per SSH), bloccando l'accesso diretto alle porte interne `8000` (Django) e `1984` (go2rtc):

   ```bash
   chmod +x set_firewall.sh
   sudo ./set_firewall.sh

## 📹 AGGIUNTA E CONFIGURAZIONE TELECAMERE

### Discovery & Probing
La funzionalità di **Discovery** permette di analizzare gli indirizzi IP (per ONVIF e RTSP) e gli URL (per HTTP) per fornire informazioni utili alla configurazione. Controlla se gli stream sono disponibili ed estrae i dettagli del flusso (risoluzione, FPS, codec), permettendo di identificare facilmente quali siano il **Main Stream** e il **Sub Stream**.

* **Main Stream:** Flusso ad alta risoluzione dedicato alla visione singola di alta qualità e alla registrazione principale.
* **Sub Stream:** Flusso a qualità inferiore dedicato alla griglia multi-camera per alleggerire il carico sulla dashboard.

### Percorso di Registrazione (`RECORDING_PATH`)
Il percorso di registrazione (`RECORDING_PATH`) deve essere inserito nel file `docker-compose.yml`. Nel file è già presente un percorso di default montato come esempio. Nella configurazione della telecamera dall'interfaccia basterà inserire il percorso scelto e configurato in Docker Compose.

---

## 🏗️ ARCHITETTURA DETTAGLIATA DEI MODULI PYTHON

### 1. Modulo `go2rtc.py`
Lo script `go2rtc.py` si occupa delle chiamate API a `go2rtc` per la creazione ed eliminazione degli stream video, mantenendoli sincronizzati con il database Django. Le chiamate di creazione avvengono tramite richieste `PUT` (funzione `sync_camera_to_go2rtc(camera)`), mentre le chiamate di cancellazione avvengono tramite richieste `DELETE` (funzione `remove_camera_from_go2rtc(camera)`).

#### Funzioni del modulo:
* **`analyze_http_stream()`:** Prende un URL HTTP qualsiasi e lo analizza tramite `ffprobe` per classificarlo (codec e formato), in modo da impostare la giusta chiamata API ed evitare transcodifiche inutili.
* **`get_go2rtc_source()`:** Chiama `analyze_http_stream()` se il protocollo è HTTP e, in base alle informazioni raccolte, costruisce gli URL da passare all'API di `go2rtc`, segnalando se lo stream richiede transcodifica (con conseguente impatto sull'uso hardware). Se il protocollo non è HTTP, restituisce i parametri di input invariati.
* **`sync_camera_to_go2rtc()`:** Prende gli indirizzi restituiti da `get_go2rtc_source()` e li usa per le chiamate API `PUT` verso `go2rtc`.
* **`remove_camera_from_go2rtc()`:** Esegue le chiamate API `DELETE` a `go2rtc` utilizzando il nome interno dello stream creato tramite l'ID numerico univoco della telecamera.
* **`probe_stream_ffprobe()`:** Esegue l'analisi video mediante `ffprobe`. Riceve gli indirizzi tramite `get_go2rtc_source()`, crea stream temporanei su `go2rtc` utilizzando un codice UUID univoco, analizza il loopback RTSP locale (`rtsp://127.0.0.1:8554/{temp_id}`), restituisce le informazioni rilevate e rimuove gli stream temporanei nel blocco `finally`.
* **`discover_camera_streams()`:** Funzione invocata all'avvio della Discovery. In base al protocollo chiama `probe_stream_ffprobe()`. Per **ONVIF**, sfrutta le funzionalità di `go2rtc` per interrogare direttamente la telecamera sugli indirizzi degli stream aperti. Per **RTSP**, esegue una scansione dei percorsi e pattern comuni. Per **HTTP**, analizza l'input dell'utente fornendo informazioni sullo stato online, risoluzione, FPS, codec e tipo di flusso.

### 2. Modulo `recorder.py`
All'interno dello script `recorder.py` si trovano le funzioni riguardanti la gestione delle registrazioni dei flussi video. Tramite i loopback RTSP creati da `go2rtc`, è possibile catturare video di protocolli diversi in un unico formato standard e con una sola funzione generale.

* **`start_camera_recording()`:** Avvia il comando `ffmpeg` per registrare lo stream video dopo aver verificato che la registrazione per quella telecamera sia abilitata. Utilizzando l'ID univoco della telecamera, ricrea l'URL RTSP di loopback e lo passa ad `ffmpeg` insieme al percorso della cartella di destinazione e all'intervallo di minuti per la segmentazione dei file `.mp4`.
* **`stop_camera_recording()`:** Termina in modo pulito il processo di registrazione.
* **`check_recorders_health()`:** Monitora lo stato dei registratori: controlla se le telecamere che dovrebbero essere in registrazione hanno processi attivi e, in caso contrario, tenta il ripristino automatico.

### 3. Modulo `disc_cleaner.py`
Script che controlla e gestisce i file registrati basandosi su 2 parametri: lo spazio rimasto sul disco di ogni telecamera (supporta percorsi su dischi diversi) e il numero di giorni di retention impostati. Lo script viene eseguito ad intervalli regolari (default: 1 ora) tramite `APScheduler`.

* **`get_active_recording_cameras()`:** Esegue una query sul DB per ottenere e restituire la lista delle telecamere attive con registrazione abilitata.
* **`clean_directory()`:** Chiama `get_disk_usage_percent()` per verificare se l'uso del disco supera il **90.00%**. In caso affermativo, individua la cartella più vecchia nel percorso di salvataggio ed esegue la funzione di rimozione `clean_directory_single_pass()`. Successivamente, controlla per ogni directory se l'età dei file supera il limite di giorni di conservazione impostato dall'utente e, se superato, avvia la rimozione.
* **`main()`:** Richiama `get_active_recording_cameras()` ed esegue `clean_directory()` per ciascuna telecamera.
* **`clean_directory_single_pass()`:** Rimuove i file dalle cartelle obsolete. Utilizza `is_file_open_or_locked()` per verificare che un file non sia attualmente in uso o in fase di scrittura da parte di `ffmpeg`. Elimina i file tramite `os.remove()`; se tutti i file di una directory vengono eliminati con successo, viene rimossa anche la directory stessa.
* **Funzioni di supporto:** `get_disk_usage_percent()`, `is_file_open_or_locked()`, e `check_if_old_rec()` eseguono calcoli sulle date e controlli sui file tramite le librerie standard `datetime`, `os` e `shutil`.

---

## 💡 COMMENTI FINALI E DICHIARAZIONE DELL'AUTORE

### Note sul Progetto e Trasparenza
Questo è uno dei miei primi progetti pensati e strutturati per il rilascio al pubblico sotto licenza Open Source.

**NON È UN PROGETTO "VIBECODED"!** L'architettura del sistema, la struttura dei moduli e le scelte logiche sono state progettate e sviluppate in prima persona. L'Intelligenza Artificiale è stata utilizzata esclusivamente come supporto per approfondire il framework Django, per ottimizzare passaggi architetturali complessi e per automatizzare compiti tediosi (come l'implementazione del sistema di logging e la conversione multilingua).

### ⚠️ Disclaimer (Versione 1.0 BETA)
La versione corrente è una **1.0 BETA** rilasciata come *showcase* delle funzionalità e dell'architettura proposta.
* Trattandosi di una Beta, possono essere presenti bug o instabilità.
* **Non è consigliata per un'implementazione critica sul campo o in ambienti di produzione.**
* L'autore non si assume alcuna responsabilità per l'uso che viene fatto del software e per eventuali malfunzionamenti o perdite di dati.

### 🚀 Roadmap e Sviluppi Futuri
Nelle prossime versioni il progetto prevede di:
1. Consolidare la stabilità complessiva dell'applicazione, offrendo un pacchetto ancora più "Plug-and-Play".
2. Integrare nuovi protocolli video e funzionalità avanzate.

*Ogni feedback, segnalazione di bug o proposta di miglioramento è benvenuta!*
