# PulsON Alarm → Home Assistant — specyfikacja implementacyjna

Kompletny, zreversowany protokół chmury PulsON Alarm gotowy do zbudowania custom
componentu Home Assistant. Wszystko poniżej potwierdzone na żywej centrali
(PulsON Alarm 2.0 4G, PAV204G) + reverse `libpulson_arm64-v8a.so` (aplikacja `com.pulson.pulsonalarm`).

> **Legalność:** reverse w celu interoperacyjności z własnym urządzeniem — art. 75 ust. 2 pkt 3
> ustawy o prawie autorskim (dyr. 2009/24/WE). Protokół chmury MQTT, nie zamknięty „PulsonProtocol".

---

## 1. Architektura

```
Centrala PulsON ──(MQTT/TLS out)──► chmura producenta ◄──(MQTT/TLS)── aplikacja / HA
                                     (broker per-panel)
        │
        └── zdarzenia (arm/alarm) ──► Firebase FCM ──► push na telefon
```

- Centrala łączy się wychodząco do przydzielonego jej serwera chmury (broker MQTT).
- Aplikacja/HA łączą się do tego samego brokera **danymi wyprowadzonymi z kodu QR + PIN**.
- Sterowanie i odczyt stanu = MQTT. Powiadomienia zdarzeń = osobno przez FCM (nieistotne dla HA — HA czyta stan z MQTT).

**Dane z kodu QR** (Menu centrali → Kod QR → System), format:
```
1;<HOST>;<PORT>;<PIN>;<SYSTEM_ID>
np.  1;solid.pulsonalarm.pl;8883;1234;0011223344556677889900aa
```
- `HOST` — per-panel (spotykane: `solid.`, `nss.`, `serwer.pulsonalarm.pl`). Bierz z QR, nie zakładaj.
- `PORT` — 8883 (MQTT over TLS).
- `PIN` — kod użytkownika (4+ cyfr). Sekret.
- `SYSTEM_ID` — 24 hex (UID STM32 centrali). Sekret w parze z PIN.

---

## 2. Połączenie MQTT

| Parametr | Wartość |
|---|---|
| Transport | TCP/TLS na `HOST:8883` |
| Protokół MQTT | **3.1** (`MQIsdp`, protocol level 3) — nie 3.1.1! |
| Clean session | `true` |
| Keep-alive | `10 s` (wysyłaj PINGREQ) |
| Client ID | losowy (aplikacja: losowy UUID) |
| TLS | cert publicznie zaufany (Certum). `mosquitto` domyślnie leci v5 → daje „Protocol error"; wymuś v3.1 albo użyj klienta MQTT 3.1 |

**Wyprowadzenie credentiali** (sole wyłuskane z `libpulson.so`):
```python
import hashlib
def md5(s): return hashlib.md5(s.encode()).hexdigest()

USERNAME = f"{SYSTEM_ID}_" + md5("fqCxoqb7ys6wX582fza0" + PIN + "R9DmiPnoHEBVw9B39evU")
PASSWORD =                    md5("oh2Zp9BVs7JlrP5q1Ik2" + SYSTEM_ID + "_" + PIN + "cX0EyPCvL5ZjEaTBIwhe")
```
CONNACK `rc=0` = OK. `rc=4/5` = zły PIN/SYSTEM_ID.

> Biblioteka dla HA: `aiomqtt` (asyncio) lub `paho-mqtt`. Wymuś `protocol=MQTTv31`.
> `iot_class: cloud_push` (stan przychodzi push po subskrypcji).

---

## 3. Odczyt stanu (DWUSTOPNIOWY — kluczowe)

Panel publikuje wartość liścia **dopiero gdy zasubskrybujesz DOKŁADNY topic tego liścia**.
Wildcard `system/{sid}/#` **NIE** wyzwala publikacji (dostaniesz tylko retained listy). To subscribe-triggered.

**Krok 1** — subskrybuj listy (retained), by poznać ID elementów:
```
system/{sid}/users/{username}/partitions    → CSV, np. "1"
system/{sid}/users/{username}/inputs         → CSV, np. "1,2,3,4,5"
system/{sid}/users/{username}/permissions    → bitmaska uprawnień, np. "16367"
```

**Krok 2** — dla każdego ID subskrybuj konkretne liście (BEZ `/users/`!):
```
system/{sid}/{module}/{id}/{field}
```
Panel odpowie wartością każdego pola, i będzie wysyłał push przy każdej zmianie dopóki subskrypcja żyje.

### Pola i formaty

**Partycje** — `system/{sid}/partitions/{id}/{field}`:
| field | format | znaczenie |
|---|---|---|
| `status` | int 0-19 | stan (patrz enum niżej) — **to jest stan live** |
| `alarm` | `0`/`1` | alarm w partycji |
| `ready` | `0`/`1` | gotowa do uzbrojenia |
| `exit_time` | int | czas na wyjście (liczy tylko podczas uzbrajania, status 4/15) |
| `active` | `true`/`false` | partycja aktywna (config) |
| `night_mode` | `true`/`false` | tryb nocny dostępny (config, **nie** = uzbrojona nocnie) |
| `name` | tekst | nazwa |

**Enum `partitions/{id}/status`:**
```
0  rozbrojony            10 alarm zdefiniowany
1  uzbrojony (away)      11 sabotaż (tamper)
2  uzbrojony nocny       12 alarm zalanie
3  czas na wejście       13 alarm temperatura
4  czas na wyjście       14 czas na wejście (noc)
5  ALARM włamanie        15 czas na wyjście (noc)
6  ALARM pożar           16 alarm panika
7  ALARM gaz             17 alarm napad
8  ALARM czad (CO)       18 sabotaż linii
9  ALARM medyczny        19 alarm w pamięci
```

**Linie/wejścia** — `system/{sid}/inputs/{id}/{field}`:
| field | format | znaczenie |
|---|---|---|
| `status` | int 0-5 | 0=?, 1=zamknięta(OK), 2=OTWARTA, 3=sabotaż, 4=usterka |
| `block` | `0`/`1` | linia zablokowana (bypass) |
| `block_enable` | `0`/`1` | blokowanie dozwolone |
| `name` | tekst | nazwa |

**Wyjścia** — `system/{sid}/outputs/{id}/{field}`: `status` (int), `name` (tekst).
(Lista `outputs` może nie przyjść jeśli brak wyjść użytkowych skonfigurowanych.)

**Moduły online** — subskrybuj `system/{sid}/online/#`:
```
system/{sid}/online/esp     → true/false  (moduł IP/WiFi)
system/{sid}/online/simcom  → true/false  (moduł GSM)
```

**Tryb programowania (serwis)** — subskrybuj `system/{sid}/programming`:
- payload dzielony po `:`, pierwszy segment zawiera `'1'` ⇒ instalator w trybie programowania (bool).
- read-only (app nie przełącza). Przydatne jako sensor — w tym trybie alarmy z linii bywają wyciszone.

---

## 4. Sterowanie (WRITE) — potwierdzone działa

Publikuj na **krótki** topic `system/{sid}/{subtopic}`, payload **`{PIN}/{wartość}`**:

| Akcja | subtopic | payload |
|---|---|---|
| Uzbrój (away) | `partitions/{id}/set_arm` | `{PIN}/1` |
| Uzbrój nocne | `partitions/{id}/set_arm` | `{PIN}/2` |
| Rozbrój | `partitions/{id}/set_disarm` | `{PIN}/0` |
| Blokuj linię | `inputs/{id}/block_set` | `{PIN}/1` |
| Odblokuj linię | `inputs/{id}/block_set` | `{PIN}/0` |
| Wyjście on/off | `outputs/{id}/set` | `{PIN}/1` \| `{PIN}/0` |
| Alarm napadowy | `panic_alarm` | `{PIN}/1` |
| Pobierz logi | `log_get` | `{PIN}/{data yyyy-MM-dd}` → odpowiedź na `log_whole` |

Po komendzie panel wysyła push zaktualizowanego `partitions/{id}/status` na aktywną subskrypcję liścia.
Potwierdzenie: uzbrojenie/rozbrojenie z klienta zmienia stan widoczny w aplikacji mobilnej.

---

## 5. Ustawienia (zakres aplikacji) — potwierdzone reverse

**Cały ekran „Ustawienia" jest w praktyce APP-LOKALNY** (lokalna baza SQLite `systems`:
`id, name, server, port, systemId, code, biometricsUse, notification`). Aplikacja **NIE edytuje
konfiguracji centrali ani żadnego ustawienia po stronie panelu** — poza jednym publishem rejestracji
pushy FCM. Ustalenia z `SettingsController`, `System::set*`, `ParseProgrammingMessage`, `ParseUsersMessage`:

| Ustawienie | Zapis | Odczyt | Zakres |
|---|---|---|---|
| Nazwa systemu | `UPDATE systems SET name` (lokalne) | z SQLite | app-local (etykieta) |
| Użyj biometrii | `UPDATE systems SET biometricsUse` | z SQLite | app-local (lock apki) |
| Kod/PIN | `System::setCode` → pole lokalne | z SQLite | app-local (podpis komend; **nie** zmienia PIN na panelu) |
| Powiadomienia (37 kategorii) | bitmaska `notification bigint` w SQLite **+** publish `system/notification/phone/set` | 37× `hasSetNotification(bit)` z maski | lokalne + rejestracja FCM |
| Tryb programowania | **brak zapisu z app** | sub `system/{sid}/programming` | **read-only** (panel-side) |
| Uprawnienia użytkownika | **brak zapisu z app** | sub `system/{sid}/users/{userId}/inputs\|outputs` (CSV ID) | read-only, tylko własny user |

> Pełna konfiguracja centrali (linie, wyjścia, czasy, EN50131, monitoring, dodawanie/edycja
> użytkowników) — **tylko** windowsowy „AlarmConfiguration" (USB/chmura) lub klawiatura. Inny protokół.

### Powiadomienia (bitmaska) — szczegóły
- Przechowywane lokalnie: `systems.notification` (64-bit decimal). Toggle: `SettingsController::set(int,bool)`
  → OR/BIC bitu w `System[0x40]` → `UPDATE systems SET notification=<decimal>`.
- Rejestracja u dostawcy: `SystemsController::registerNotifications()` buduje `{systemId}{maska}` i publikuje
  na `system/notification/phone/set` (payload: systemId + `getNotification()` decimal + token FCM),
  przez osobną sesję `PushNotification` (creds `phone_notification`/`SypDmDHyhc5kAQMI`, QoS0, retain=false).
- **Dla HA bezużyteczne** — steruje wyłącznie tym, które zdarzenia backend pushuje **FCM na telefon**.
  HA czyta stan z MQTT (§3), nie potrzebuje FCM. Pomiń, chyba że chcesz replikować push na inny kanał.

### Programming mode — jedyne panelowe „ustawienie" do ODCZYTU (użyteczne w HA)
- Subskrybuj `system/{sid}/programming`. Payload dzielony po `:`, pierwszy segment zawiera `'1'` → tryb aktywny.
- Parser: `ParseProgrammingMessage` → `System::setProgramming(bool)`.
- **HA:** `binary_sensor` „Instalator w trybie programowania" (`device_class: problem` lub własny).
  Gdy aktywny, centrala jest w serwisie (alarmy z linii mogą być wyciszone).

### Uprawnienia użytkownika — do ODCZYTU (opcjonalnie)
- `system/{sid}/users/{userId}/inputs` = CSV ID linii które ten user może sterować/blokować.
- `system/{sid}/users/{userId}/outputs` = CSV ID wyjść które user może sterować.
- `system/{sid}/users/{userId}/permissions` = bitmaska uprawnień (np. `16367`).
- `userId` = własny `username` (`{sid}_{md5}`); nie odczytasz cudzych. Użyj do ukrycia encji
  których user nie ma prawa sterować.

**Wniosek dla integracji:** brak nowych akcji „zmiany ustawień" do dodania — komendy z §4 to komplet.
Warto dodać tylko dwa **read-only** sensory: tryb programowania i (opcjonalnie) filtr encji wg uprawnień.

---

## 6. Kanał FCM (informacyjnie)

Zdarzenia (arm/disarm/alarm) trafiają na telefon przez **Firebase Cloud Messaging**, nie MQTT.
Rejestracja tokenu FCM = osobna sesja MQTT (publish-only): creds `phone_notification` /
`SypDmDHyhc5kAQMI`, topic `system/notification/phone/set`. **HA tego nie potrzebuje** — stan live
mamy z MQTT (§3). Sekcja tylko dla kompletności.

---

## 7. Projekt integracji Home Assistant

### Encje

| Encja HA | Źródło | Uwagi |
|---|---|---|
| `alarm_control_panel` (per partycja) | `partitions/{id}/status` | stany → `AlarmControlPanelState`; komendy → publish |
| `binary_sensor` (per linia) | `inputs/{id}/status` | `device_class: motion/door/window`; on = status 2 (otwarta) |
| `binary_sensor` (sabotaż/usterka linii) | `inputs/{id}/status` 3/4 | `device_class: problem/tamper` |
| `switch` (bypass per linia) | `inputs/{id}/block` | write `inputs/{id}/block_set` |
| `switch` (per wyjście) | `outputs/{id}/status` | write `outputs/{id}/set` |
| `binary_sensor` alarm (per partycja) | `partitions/{id}/alarm` | `device_class: safety` |
| `binary_sensor` online esp/simcom | `online/esp`, `online/simcom` | `device_class: connectivity` |
| `binary_sensor` tryb programowania | `system/{sid}/programming` | `device_class: problem`; on = instalator w serwisie |
| `button` napad | — | publish `panic_alarm` (ukryj/potwierdzaj) |

### Mapowanie stanu partycji → `AlarmControlPanelState`
```python
0            -> DISARMED
1            -> ARMED_AWAY
2            -> ARMED_NIGHT
3, 14        -> PENDING            # czas na wejście
4, 15        -> ARMING             # czas na wyjście
5..13,16..18 -> TRIGGERED          # alarmy
19           -> DISARMED (+ atrybut "alarm w pamięci")
```
`supported_features`: `ARM_AWAY | ARM_NIGHT` (+ `ARM_HOME` mapowane na away, jeśli chcesz).
`code_arm_required`: PIN jest wymagany w payloadzie — trzymaj PIN w config entry, nie żądaj od usera
przy każdej akcji (albo opcjonalnie `code_format`).

### config_flow
Zbierz: `host`, `system_id`, `pin` (parsuj z wklejonego stringa QR `1;host;port;pin;sid`).
Wylicz `username`/`password` (§2). Waliduj przez próbne CONNACK. Zapisz w config entry
(PIN/sid = sekrety). Jedna centrala = jeden config entry; partycje/linie jako encje.

### Klient / coordinator
- Trzymaj **jedno** trwałe połączenie MQTT (aiomqtt), subskrybuj `users/{username}/#` + `online/#`.
- Po odebraniu list → dosubskrybuj granularne liście wszystkich elementów (§3 krok 2). **To warunek
  otrzymywania stanu.**
- Push-based: aktualizuj encje w handlerze wiadomości (`async_write_ha_state`), nie polling.
  `should_poll = False`.
- Reconnect z backoffem; po reconnekcie powtórz pełną (re)subskrypcję granularną.
- Keep-alive 10 s (PINGREQ), inaczej broker rozłączy.

### Pułapki
- **MQTT 3.1** (nie 3.1.1/5) — inaczej broker odrzuca / „Protocol error".
- Stan przychodzi **tylko** po subskrypcji konkretnego liścia — nie polegaj na `#`.
- Payloady komend: `{PIN}/{wartość}` (PIN prefiksowany, nie samo value).
- `night_mode`/`active` to config, nie stan live — stan czytaj z `status`.
- Host jest per-panel — z QR, nie hardkoduj.
- Zależność od chmury producenta (awaria chmury = brak sterowania). Rozważ sprzętowy backup
  (wyjścia PGM → ESPHome/Shelly → `binary_sensor`) dla krytycznych stanów.

---

## 8. Referencyjny klient (destylat)

Działający, samodzielny klient stdlib: `pulson.py` (w repo) — `status` / `watch` / `arm` / `disarm`
/ `night` / `block` / `unblock` / `output` / `panic`. Zawiera pełną implementację §2-§4
(MQTT 3.1 od zera, granularna subskrypcja, dekodowanie). Użyj jako wzorca logiki dla integracji.

Rdzeń credentiali + topiki — patrz §2, §3, §4. Enkoding MQTT 3.1 CONNECT/SUBSCRIBE/PUBLISH
w `pulson.py` (funkcje `_rl`, `_s`, `Pulson.connect/subscribe/publish`).

---

## 9. Bezpieczeństwo

- `SYSTEM_ID` + `PIN` = pełne zdalne sterowanie alarmem. Trzymaj w HA (config entry/secrets),
  nigdy w kodzie/repo/logach.
- Nie publikuj kodu QR ani serial+PIN publicznie.
- `panic_alarm` wywołuje realny alarm napadowy (stacja monitorowania) — w HA ukryj za potwierdzeniem.
- Zmiana slotu monitoringu w żywej instalacji Grade-2 może alarmować agencję — nie dotyczy tej
  integracji (używa chmury), ale pamiętaj przy testach sprzętowych.

## Kontakt producenta
BCS Sp. z o.o., KRS 0000092488 · `kontakt@pulsonalarm.pl` · `wsparcie@pulsonalarm.pl` · +48 882 481 935
