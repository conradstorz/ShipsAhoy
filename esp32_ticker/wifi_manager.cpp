#include "wifi_manager.h"
#include "config.h"
#include "debug_log.h"
#include "display.h"
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoOTA.h>

static AsyncWebServer    _server(80);
static AsyncEventSource  _events("/events");

// ── Embedded debug web page ───────────────────────────────────────────────────

static const char HTML_PAGE[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head><meta charset="utf-8">
<title>ShipsAhoy Debug</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:monospace;font-size:12px;background:#111;color:#eee;height:100vh;display:flex;flex-direction:column}
#hdr{padding:6px 10px;background:#222;border-bottom:1px solid #333;display:flex;align-items:center;gap:12px}
#dot{width:10px;height:10px;border-radius:50%;background:#666}
#dot.ok{background:#4f4}
#cols{display:flex;flex:1;overflow:hidden}
.col{flex:1;display:flex;flex-direction:column;border-right:1px solid #333}
.col:last-child{border-right:none}
.hd{padding:4px 8px;font-weight:bold;border-bottom:1px solid #333}
#ci .hd{color:#8af}#cw .hd{color:#fa8}#ce .hd{color:#f66}
.bd{flex:1;overflow-y:auto;padding:4px}
.row{padding:2px 4px;border-bottom:1px solid #1a1a1a;line-height:1.4}
.ts{color:#555;margin-right:6px}
</style></head><body>
<div id="hdr">
  <div id="dot"></div><span id="st">Connecting...</span>
  <span style="margin-left:auto;color:#555">ShipsAhoy Debug &mdash;
  <a href="/status" style="color:#777">/status</a></span>
</div>
<div id="cols">
  <div class="col" id="ci"><div class="hd">Info</div><div class="bd" id="bi"></div></div>
  <div class="col" id="cw"><div class="hd">Warnings</div><div class="bd" id="bw"></div></div>
  <div class="col" id="ce"><div class="hd">Errors</div><div class="bd" id="be"></div></div>
</div>
<script>
const cols={info:document.getElementById('bi'),warn:document.getElementById('bw'),error:document.getElementById('be')};
const dot=document.getElementById('dot'),st=document.getElementById('st');
function addRow(col,ts,msg){
  const r=document.createElement('div');r.className='row';
  r.innerHTML='<span class="ts">+'+ts+'s</span>'+msg.replace(/</g,'&lt;');
  col.appendChild(r);col.scrollTop=col.scrollHeight;
}
function connect(){
  const es=new EventSource('/events');
  es.onopen=()=>{dot.className='ok';st.textContent='Connected';};
  es.onerror=()=>{dot.className='';st.textContent='Reconnecting...';setTimeout(connect,3000);es.close();};
  es.onmessage=e=>{
    const d=JSON.parse(e.data);
    addRow(cols[d.l]||cols.info,(d.t/1000).toFixed(1),d.m);
  };
}
connect();
</script></body></html>
)rawliteral";

// ── WiFi task — polls OTA ─────────────────────────────────────────────────────

static void wifi_task(void* pvParameters) {
    for (;;) {
        ArduinoOTA.handle();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

// ── Public init ───────────────────────────────────────────────────────────────

void wifi_manager_init() {
    // 1. Soft-AP (IP will be 192.168.4.1)
    WiFi.softAP(WIFI_AP_SSID, WIFI_AP_PASSWORD, WIFI_AP_CHANNEL,
                0, WIFI_AP_MAX_CONN);

    // 2. Register SSE push with debug_log
    dbg_register_push([](const char* json) {
        _events.send(json, "message", millis());
    });

    // 3. OTA
    ArduinoOTA.setHostname(OTA_HOSTNAME);
    ArduinoOTA.setPassword(OTA_PASSWORD);
    ArduinoOTA.setPort(OTA_PORT);
    ArduinoOTA.onStart([]()             { dbg_info("[ota] update started"); });
    ArduinoOTA.onEnd([]()               { dbg_info("[ota] complete — rebooting"); });
    ArduinoOTA.onError([](ota_error_t e){ dbg_error("[ota] error %u", (unsigned)e); });
    ArduinoOTA.begin();

    // 4. Web server routes
    _server.on("/", HTTP_GET, [](AsyncWebServerRequest* req) {
        req->send_P(200, "text/html", HTML_PAGE);
    });

    _server.on("/status", HTTP_GET, [](AsyncWebServerRequest* req) {
        const char* mode_str;
        switch (display_get_mode()) {
            case MODE_SCROLL:      mode_str = "scroll";     break;
            case MODE_STATIC:      mode_str = "static";     break;
            case MODE_FRAME:       mode_str = "frame";      break;
            case MODE_CLEAR:       mode_str = "clear";      break;
            case MODE_BRIGHTNESS:  mode_str = "brightness"; break;
            default:               mode_str = "unknown";    break;
        }
        char json[160];
        snprintf(json, sizeof(json),
            "{\"uptime_ms\":%u,\"free_heap\":%u,\"display_mode\":\"%s\",\"wifi_clients\":%u}",
            (unsigned)millis(),
            (unsigned)ESP.getFreeHeap(),
            mode_str,
            (unsigned)WiFi.softAPgetStationNum());
        req->send(200, "application/json", json);
    });

    // SSE — replay history to new clients, then push live events
    _events.onConnect([](AsyncEventSourceClient* client) {
        dbg_replay([client](const char* json) {
            client->send(json, "message", millis(), 0);
        });
    });
    _server.addHandler(&_events);
    _server.begin();

    // 5. FreeRTOS task for OTA polling (Core 0, alongside uart_task)
    xTaskCreatePinnedToCore(wifi_task, "wifi_task", 4096, nullptr, 1, nullptr, 0);

    dbg_info("[wifi] AP \"%s\" up at 192.168.4.1", WIFI_AP_SSID);
}
