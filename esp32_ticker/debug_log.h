#pragma once
#include <Arduino.h>
#include <functional>

// Push callback type — receives a JSON string to deliver to SSE clients.
using DbgPushFn = std::function<void(const char*)>;

// Register the SSE push callback. Called once by wifi_manager_init().
void dbg_register_push(DbgPushFn fn);

// Replay all buffered messages (oldest first per level) via fn.
// Call from the SSE onConnect handler to give new clients recent history.
void dbg_replay(DbgPushFn fn);

// Logging functions — printf-style, safe from any FreeRTOS task, never block.
void dbg_info (const char* fmt, ...);
void dbg_warn (const char* fmt, ...);
void dbg_error(const char* fmt, ...);
