#pragma once
// Exercises the actual NSPR initialization/static-library APIs, not a loader shim.
bool probe_orbisfox_static_nspr(void (*message)(const char*));
