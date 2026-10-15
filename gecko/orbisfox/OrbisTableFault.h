#ifndef ORBISFOX_TABLE_FAULT_H
#define ORBISFOX_TABLE_FAULT_H
#include <stddef.h>
#include <stdint.h>
namespace orbisfox {
using TableFaultWriter=bool (*)(const char*,size_t);
// Installed before XPCOM by the native embedder; no dependency on an invented
// engine-owned file or native service before the real writer is initialized.
void set_table_fault_writer(TableFaultWriter writer);
void record_table_fault(const char* operation,uintptr_t table,const void* key,const void* caller);
}
#endif
