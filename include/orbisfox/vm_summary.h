// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>
namespace orbisfox {
struct VmSummary {
  uint64_t regions=0, virtualBytes=0, flexibleBytes=0, directBytes=0, stackBytes=0;
  uint64_t committedFlexibleBytes=0;
  int32_t lastResult=0;
  bool truncated=false, malformed=false;
};
// Bounded, read-only census using the SDK's real public query structure.
// Virtual spans are not physical usage and names/addresses are never logged.
template<class Info, class Query> VmSummary summarizeVm(Query&& query) {
  VmSummary s; uintptr_t cursor=0;
  for (size_t i=0;i<2048;++i) {
    Info info{};
    s.lastResult=query(reinterpret_cast<const void*>(cursor),1,&info,sizeof(info));
    if (s.lastResult!=0) return s;
    const auto begin=reinterpret_cast<uintptr_t>(info.unk01);
    const auto end=reinterpret_cast<uintptr_t>(info.unk02);
    if (begin>=end || end<=cursor) { s.malformed=true; return s; }
    const uint64_t size=end-begin;
    ++s.regions; s.virtualBytes+=size;
    if (info.isFlexibleMemory) {
      s.flexibleBytes+=size;
      if (info.isCommitted) s.committedFlexibleBytes+=size;
    }
    if (info.isDirectMemory) s.directBytes+=size;
    if (info.isStack) s.stackBytes+=size;
    cursor=end;
  }
  s.truncated=true;
  return s;
}
} // namespace orbisfox
