#pragma once
#include "protocol.h"

void display_init();       // call from setup() — starts display_task on Core 1
DisplayMode display_get_mode();  // returns the current display mode (thread-safe read)
