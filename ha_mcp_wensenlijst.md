# Wensenlijst uitbreiding Home Assistant MCP

Deze lijst komt voort uit de Zendure/SMA-sessie waarin de Home Assistant MCP wel nuttig was voor bestanden, entiteiten en historie, maar tekort schoot bij veilig live ingrijpen, reloads, validatie en diagnose.

## Hoogste prioriteit

### 1. Generieke Home Assistant service call

Tijdens de sessie moest ik meerdere keren iets live doen, maar kon ik alleen YAML schrijven en de gebruiker vragen om handmatig te herladen of waarden te wijzigen.

Gewenst:

- `call_service(domain, service, target, data)`
- Ondersteuning voor onder andere:
  - `automation.reload`
  - `automation.turn_on`
  - `automation.turn_off`
  - `number.set_value`
  - `select.select_option`
  - `homeassistant.reload_config_entry`
  - `homeassistant.update_entity`
- Teruggeven van succes/foutmelding met HA-context-id.
- Optioneel een allowlist voor risicovolle services.

Waarom dit belangrijk is:

- Ik kon de Zendure niet direct naar `0 W` zetten.
- Ik moest een tijdelijke safety-stop automation schrijven als workaround.
- Bij energie-apparatuur wil je niet wachten op handmatige UI-stappen.

### 2. Reload-tools voor HA-config zonder restart

Gewenst:

- `reload_automations()`
- `reload_scripts()`
- `reload_template_entities()`
- `reload_python_scripts()`
- `reload_integration(entry_id)`

Waarom:

- De gebruiker moest steeds zelf herladen.
- Dat maakte foutzoeken traag en onprettig.
- Een restart is te zwaar voor iteraties aan automations.

### 3. Config-check en YAML-validatie

Gewenst:

- `check_config()`
- `validate_yaml_file(path)`
- `validate_automation_file(path)`
- Foutmeldingen met bestandsnaam, regelnummer en context.

Waarom:

- Een YAML-valkuil (`option: off` werd boolean `False`) kwam pas na reload/runtime naar voren.
- Zulke fouten moeten voor reload zichtbaar zijn.
- `ha core check` was niet betrouwbaar beschikbaar via de huidige MCP/CLI-laag.

### 4. Automation trace uitlezen

Gewenst:

- `get_automation_trace(entity_id, last_n=5)`
- Toon:
  - trigger
  - gekozen `choose`-tak
  - templatevariabelen
  - service calls
  - foutmelding per stap

Waarom:

- We moesten gedrag afleiden uit logs en entity history.
- Bij complexe Jinja-automations is trace essentieel.
- Dit had direct laten zien waarom de safety-stop faalde.

## Diagnose en observatie

### 5. Betere log-query

De huidige `read_file_filtered` op `home-assistant.log` timeoutte bij grotere filters.

Gewenst:

- `query_logs(since, level, logger_filter, text_filter, limit)`
- Ondersteuning voor meerdere patterns.
- Tijdvenster in lokale tijd of ISO.
- Geen volledige file scan bij elk verzoek.

Waarom:

- We zochten naar `sma`, `zendure_ha`, `unavailable`, `connection`, `Timeout`.
- Grote logfiles maakten dit traag en onbetrouwbaar.

### 6. Historie met flexibele relatieve tijden

Gewenst:

- Ondersteun `-30m`, `-90m`, `-2h`, `-7d`.
- Consistente lokale tijdweergave naast UTC.
- Optie om alleen transitions naar/van `unavailable` te tonen.

Waarom:

- `-30m` en `-90m` faalden; `-1h` werkte wel.
- Tijdens incidentanalyse wil je snel kleine vensters kunnen pakken.

### 7. Live state snapshot voor meerdere entiteiten

Gewenst:

- `get_states(entity_ids[])`
- Compacte output:
  - state
  - last_changed
  - last_updated
  - selected attributes

Waarom:

- Ik moest meerdere `list_ha_entities_devices` calls doen om Zendure-setpoints te controleren.
- Een atomic snapshot voorkomt verwarring bij snel veranderende waarden.

### 8. Device registry volledig beschikbaar

Gewenst:

- `get_device(device_id)`
- `list_devices(filter)`
- Toon:
  - fabrikant
  - model
  - integratie
  - config entry
  - identifiers
  - connections

Waarom:

- Device registry gaf deels `permission`-achtige beperkingen.
- Bij IP/netwerkdiagnose wil je apparaat, integratie en entiteiten in één beeld.

### 9. Config entries veilig lezen en beheren

Gewenst:

- `list_config_entries(domain)`
- `get_config_entry(entry_id)`
- `reload_config_entry(entry_id)`
- `disable_config_entry(entry_id)` met expliciete bevestiging

Waarom:

- We moesten in `.storage/core.config_entries` zoeken naar de SMA-host.
- Dat bestand bevat gevoelige data, zoals wachtwoorden/tokens.
- Een gestructureerde tool kan secrets maskeren.

## Veiligheid bij energie-apparaten

### 10. Emergency stop primitive

Gewenst:

- Configureerbare `safe_stop`-actie per apparaat/integratie.
- Bijvoorbeeld voor Zendure:
  - manager mode naar `off`
  - manual power naar `0`
  - charge limit naar `0`
  - output limit naar `0`
- Uitvoer als één gecontroleerde actie met verificatie erna.

Waarom:

- In deze sessie bleef de accu laden nadat de automation uit stond.
- Bij thuisaccu’s moet een agent direct naar veilige nulstand kunnen.

### 11. Dry-run voor service calls en automations

Gewenst:

- Template renderen met huidige states zonder uitvoeren.
- Toon berekende `target_manual_power`, voorwaarden en gekozen pad.
- Simuleer service calls zonder te schrijven.

Waarom:

- De Zendure-regeling had feedbackloops en onverwachte setpoints.
- Dry-run had veel sneller laten zien waarom waarden naar `-1000 W` liepen.

### 12. Rate limiting en write-audit

Gewenst:

- Tool om write-frequency per entiteit te tonen.
- Bijvoorbeeld: `number.zendure_manager_manual_power` had meer dan 100 wijzigingen per uur.
- Waarschuwing bij snelle herhaalde writes naar dezelfde entiteit.

Waarom:

- De Zendure werd te vaak aangestuurd.
- Dit is relevant voor cloud-integraties, apparaatbelasting en diagnose.

## Netwerkdiagnose

### 13. Netwerktools vanuit HA-host

Gewenst:

- `ping_from_ha(host)`
- `arp_from_ha(host)`
- `tcp_connect_from_ha(host, port)`
- `http_probe_from_ha(url)`

Waarom:

- Ik kon vanaf de pc pingen, maar dat is niet hetzelfde pad als HA.
- De SMA viel in HA en web UI weg; diagnose vanaf HA-host is betrouwbaarder.

### 14. IP/MAC-conflictdetectie

Gewenst:

- Toon MAC-adres voor een IP vanuit HA-host.
- Detecteer of MAC wisselt over tijd.
- Optioneel router/DHCP-koppeling als beschikbaar.

Waarom:

- De SMA heeft een fixed IP, maar een duplicate IP blijft mogelijk.
- Tijdens uitval wil je weten of `192.168.1.24` ineens een ander MAC-adres heeft.

## Bestandsbeheer

### 15. Veilige file write met diff

Gewenst:

- `write_file_with_diff(path, content)`
- Toon unified diff voor schrijven.
- Optioneel backup maken.
- Optioneel HA YAML-validatie na schrijven.

Waarom:

- We schreven meerdere automations naar `/config`.
- Bij live HA-config wil je altijd diff en validatie.

### 16. Automations als objecten beheren

Gewenst:

- `create_or_update_automation(id, yaml/object)`
- `disable_automation(id)`
- `delete_automation(id)`
- `get_automation_yaml(id)`

Waarom:

- Nu moest ik losse YAML-bestanden maken.
- Het is onduidelijk of HA al geladen versie, file-versie en UI-state gelijk lopen.

## Minder urgent, wel nuttig

### 17. Entity history als tabel/CSV

Gewenst:

- Export naar compacte tabel.
- Filter op minimale wijziging, unavailable, context_id, parent_id.
- Correlatie tussen meerdere entiteiten in één query.

Waarom:

- We moesten SMA-status, Zendure manual power en automation reloads naast elkaar leggen.

### 18. Recorder/statistics diagnose

Gewenst:

- Check of `unavailable` gaten invloed hebben op Energy Dashboard/statistics.
- Toon affected statistics metadata.
- Adviseer herstelopties.

Waarom:

- De gebruiker maakte zich terecht zorgen over HA energy logging.

### 19. Integration health endpoint

Gewenst:

- Per integratie:
  - laatste succesvolle poll
  - laatste fout
  - poll interval
  - config entry status
  - aantal unavailable entiteiten

Waarom:

- Bij SMA moesten we raden of het HA-polling, netwerk of apparaat zelf was.

### 20. Secrets maskeren in alle file reads

Gewenst:

- Automatisch maskeren van tokens, passwords, refresh tokens.
- Zeker voor `.storage/core.config_entries`.

Waarom:

- Bij het zoeken naar de SMA-host kwam ook gevoelige SmartThings/SMA-config mee.

## Samenvatting prioriteiten

1. Generieke HA service call.
2. Automation/script/template reload tools.
3. Config/YAML-validatie met regelnummer.
4. Automation trace uitlezen.
5. Betere logs en historie.
6. Emergency stop voor energie-apparaten.
7. Netwerkdiagnose vanaf de HA-host.

Met vooral punten 1 tot en met 4 was deze sessie veel veiliger en sneller verlopen: ik had direct kunnen stoppen, valideren, herladen, traces lezen en zonder omwegen kunnen vaststellen wat HA werkelijk uitvoerde.
