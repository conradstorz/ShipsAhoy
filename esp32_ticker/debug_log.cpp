#include "debug_log.h"
#include "config.h"
#include <stdarg.h>
#include <freertos/semphr.h>

// ── Per-message storage ───────────────────────────────────────────────────────

struct DbgMsg {
    uint32_t ts;
    char     level;      // 'i', 'w', 'e'
    char     text[120];
};

static DbgMsg info_buf [DBG_BUF_INFO];
static DbgMsg warn_buf [DBG_BUF_WARN];
static DbgMsg error_buf[DBG_BUF_ERROR];

static uint16_t info_head  = 0, info_count  = 0;
static uint16_t warn_head  = 0, warn_count  = 0;
static uint16_t error_head = 0, error_count = 0;

static SemaphoreHandle_t _mutex = nullptr;
static DbgPushFn         _push;

// ── Internal helpers ──────────────────────────────────────────────────────────

static void ensure_mutex() {
    if (!_mutex) _mutex = xSemaphoreCreateMutex();
}

static void append_buf(DbgMsg* buf, uint16_t cap, uint16_t& head,
                       uint16_t& count, char level, uint32_t ts,
                       const char* text) {
    DbgMsg& m = buf[head];
    m.ts    = ts;
    m.level = level;
    strncpy(m.text, text, sizeof(m.text) - 1);
    m.text[sizeof(m.text) - 1] = '\0';
    head = (head + 1) % cap;
    if (count < cap) count++;
}

static void replay_buf(DbgPushFn& fn, DbgMsg* buf, uint16_t cap,
                       uint16_t head, uint16_t count, const char* ls) {
    uint16_t start = (count < cap) ? 0 : head;
    char json[160];
    for (uint16_t i = 0; i < count; i++) {
        DbgMsg& m = buf[(start + i) % cap];
        snprintf(json, sizeof(json),
                 "{\"l\":\"%s\",\"t\":%u,\"m\":\"%s\"}", ls, m.ts, m.text);
        fn(json);
    }
}

static void log_msg(char lc, const char* ls, const char* fmt, va_list args) {
    char text[120];
    vsnprintf(text, sizeof(text), fmt, args);
    // Strip trailing newline (compatibility with Serial.printf callers)
    size_t len = strlen(text);
    if (len > 0 && text[len - 1] == '\n') text[len - 1] = '\0';

    ensure_mutex();
    xSemaphoreTake(_mutex, portMAX_DELAY);

    uint32_t ts = millis();
    if      (lc == 'i') append_buf(info_buf,  DBG_BUF_INFO,  info_head,  info_count,  'i', ts, text);
    else if (lc == 'w') append_buf(warn_buf,  DBG_BUF_WARN,  warn_head,  warn_count,  'w', ts, text);
    else                append_buf(error_buf, DBG_BUF_ERROR, error_head, error_count, 'e', ts, text);

    if (_push) {
        char json[160];
        snprintf(json, sizeof(json),
                 "{\"l\":\"%s\",\"t\":%u,\"m\":\"%s\"}", ls, ts, text);
        _push(json);
    }

    xSemaphoreGive(_mutex);
}

// ── Public API ────────────────────────────────────────────────────────────────

void dbg_register_push(DbgPushFn fn) {
    ensure_mutex();
    xSemaphoreTake(_mutex, portMAX_DELAY);
    _push = fn;
    xSemaphoreGive(_mutex);
}

void dbg_replay(DbgPushFn fn) {
    if (!fn) return;
    ensure_mutex();
    xSemaphoreTake(_mutex, portMAX_DELAY);
    replay_buf(fn, info_buf,  DBG_BUF_INFO,  info_head,  info_count,  "info");
    replay_buf(fn, warn_buf,  DBG_BUF_WARN,  warn_head,  warn_count,  "warn");
    replay_buf(fn, error_buf, DBG_BUF_ERROR, error_head, error_count, "error");
    xSemaphoreGive(_mutex);
}

void dbg_info(const char* fmt, ...) {
    va_list a; va_start(a, fmt); log_msg('i', "info",  fmt, a); va_end(a);
}
void dbg_warn(const char* fmt, ...) {
    va_list a; va_start(a, fmt); log_msg('w', "warn",  fmt, a); va_end(a);
}
void dbg_error(const char* fmt, ...) {
    va_list a; va_start(a, fmt); log_msg('e', "error", fmt, a); va_end(a);
}
