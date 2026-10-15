#include <cassert>
#include <string>
struct nsAtom {};
namespace nsGkAtoms { nsAtom atom; nsAtom* remote = &atom; }
bool contentProcess = false;
bool XRE_IsContentProcess() { return contentProcess; }
struct Element {
  bool xul = true, present = false;
  std::string attributeValue;
  bool IsXULElement() const { return xul; }
  bool HasAttr(nsAtom* atom) const { assert(atom == nsGkAtoms::remote); return present; }
#include "accessor.inc"
};
#include "policy.inc"
int main() {
  for (unsigned cycle=0;cycle<32;++cycle) {
    for (bool content : {false,true}) for (bool xul : {false,true}) {
      contentProcess = content;
      Element e; e.xul = xul;
      assert(!InitialLoadIsRemote(&e));
      e.present = true;
      for (const auto& value : {"false","true","","0","no"}) {
        e.attributeValue = value;
        assert(InitialLoadIsRemote(&e) == (!content && xul));
        assert(e.GetBoolAttr(nsGkAtoms::remote));
      }
      e.present = false;
      assert(!InitialLoadIsRemote(&e));
    }
  }
}
