#include "OrbisTableFault.h"
#include <atomic>
#include <unistd.h>
namespace orbisfox {
namespace {std::atomic<TableFaultWriter> writer{nullptr};}
void set_table_fault_writer(TableFaultWriter value){writer.store(value,std::memory_order_release);}
void record_table_fault(const char* operation,uintptr_t table,const void* key,const void* caller){
  // Diagnostic only: never fabricate an entry or mask the original bad access.
  char buffer[256];size_t used=0;
  const auto text=[&](const char* p){while(*p&&used<sizeof(buffer))buffer[used++]=*p++;};
  const auto hex=[&](uintptr_t value){text("0x");for(int shift=int(sizeof(value)*8)-4;shift>=0;shift-=4)if(used<sizeof(buffer))buffer[used++]="0123456789abcdef"[(value>>shift)&15];};
  text("ORBIS_TABLE_FAULT op=");text(operation);text(" table=");hex(table);text(" key=");hex(reinterpret_cast<uintptr_t>(key));text(" caller=");hex(reinterpret_cast<uintptr_t>(caller));text("\n");
  (void)write(2,buffer,used);
  if(auto save=writer.load(std::memory_order_acquire))(void)save(buffer,used);
}
}
