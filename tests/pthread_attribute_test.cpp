#include "orbisfox/pthread_attribute_probe.h"
#include <assert.h>
#include <string.h>
using namespace orbisfox;
struct Attr { uint64_t opaque; };
static int destroys = 0;
static int init(Attr* a) { a->opaque = 0x1234; return 0; }
static int destroy(Attr* a) { assert(a->opaque == 0x1234); a->opaque = 0; ++destroys; return 0; }
static int bad_init(Attr* a) {
    const uint64_t bad[2]{0x1234, 0};
    memcpy(a, bad, sizeof(bad)); // Deliberate overwrite of guard inside the enclosing storage.
    return 0;
}
static int failed_init(Attr*) { return 12; }
int main() {
    auto ok = probe_attribute<Attr>(init, destroy);
    assert(ok.init_rc == 0 && ok.destroy_rc == 0 && ok.guard_ok && destroys == 1);
    auto bad = probe_attribute<Attr>(bad_init, destroy);
    assert(!bad.guard_ok && destroys == 1);
    auto failed = probe_attribute<Attr>(failed_init, destroy);
    assert(failed.init_rc == 12 && failed.guard_ok && destroys == 1);
}
