"""Experimental GPU integration: host safety and pinned-producer regressions.

No console/WebRender execution claim. Set ORBISFOX_GECKO_INPUT to an existing
pinned checkout to test transformations in temporary copies, never in that tree.
"""
import ast
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('mesa_layout_patch', ROOT/'scripts/patch-gecko-layout.py')
PATCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCH)


class MesaWebRenderTests(unittest.TestCase):
    def test_gpu_readback_bounds_origin_channels_and_immutable_source(self):
        harness = r'''
#include "OrbisGpuReadback.h"
#include <array>
#include <cassert>
#include <limits>
int main() {
 std::array<uint8_t,36> source{};
 for(size_t y=0;y<3;++y)for(size_t x=0;x<2;++x)for(size_t c=0;c<4;++c)
  source[y*12+x*4+c]=uint8_t(1+y*30+x*8+c);
 const auto original=source;
 std::array<uint8_t,56> destination;destination.fill(0xcc);
 assert(orbisfox::ConvertGpuRgbaToBgra(source.data(),source.size(),12,
  destination.data()+4,48,16,2,3));
 for(size_t y=0;y<3;++y)for(size_t x=0;x<2;++x)for(size_t c=0;c<4;++c) {
  size_t channel=c==0?2:c==2?0:c;
  assert(destination[4+y*16+x*4+c]==source[(2-y)*12+x*4+channel]);
 }
 for(size_t i=0;i<destination.size();++i) {
  bool pixel=i>=4&&i<44&&((i-4)%16)<8;
  if(!pixel)assert(destination[i]==0xcc);
 }
 assert(source==original);
 const auto completed=destination;
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),31,12,destination.data()+4,48,16,2,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,12,destination.data()+4,39,16,2,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,7,destination.data()+4,48,16,2,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,12,source.data()+1,35,8,2,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(nullptr,36,12,destination.data(),56,16,2,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,12,destination.data(),56,16,0,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,12,destination.data(),56,16,1281,3));
 assert(!orbisfox::ConvertGpuRgbaToBgra(source.data(),36,std::numeric_limits<size_t>::max(),
  destination.data(),56,16,2,3));
 assert(source==original&&destination==completed);
 // Odd-width, single-row path (including its alpha channel).
 assert(orbisfox::ConvertGpuRgbaToBgra(source.data(),4,4,destination.data(),4,4,1,1));
 assert(destination[0]==3&&destination[1]==2&&destination[2]==1&&destination[3]==4);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            d=Path(directory);cpp=d/'readback.cpp';binary=d/'readback'
            cpp.write_text(harness)
            subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-fno-omit-frame-pointer',
                            '-I'+str(ROOT/'gecko/orbisfox'),cpp,'-o',binary],check=True)
            subprocess.run([binary],check=True)

    def test_mesa_transformation_is_byte_and_timestamp_stable(self):
        source=Path(os.environ.get('ORBISFOX_GECKO_INPUT',ROOT/'.deps/gecko-layout'))
        names=['gfx/gl/GLLibraryEGL.cpp','gfx/gl/GLContextProviderEGL.cpp',
               'gfx/webrender_bindings/RenderThread.cpp',
               'gfx/webrender_bindings/RenderCompositor.cpp',
               'gfx/webrender_bindings/moz.build','gfx/gl/moz.build',
               'gfx/thebes/gfxPlatform.cpp','gfx/config/gfxConfigManager.cpp',
               'widget/nsIWidget.cpp']
        if not all((source/name).is_file() for name in names):
            self.skipTest('Provide prepared pinned source via ORBISFOX_GECKO_INPUT')
        before={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names}
        with tempfile.TemporaryDirectory() as directory:
            copy=Path(directory)
            for name in names:
                p=copy/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes((source/name).read_bytes())
            PATCH.patch_orbis_mesa(copy)
            first={name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names}
            PATCH.patch_orbis_mesa(copy)
            second={name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names}
            self.assertEqual(first,second)
            library=(copy/names[0]).read_text()
            self.assertIn('const SymbolLoader libLoader(&eglGetProcAddress);',library)
            self.assertNotIn('reinterpret_cast<PRLibrary',library)
            self.assertIn('FORBID_SOFTWARE',(copy/names[2]).read_text())
            self.assertIn('MOZ_ORBIS_MESA',(copy/names[4]).read_text())
            self.assertIn('-Wl,@',(copy/names[5]).read_text())
        self.assertEqual(before,{name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names})

    def test_complete_vendor_patch_with_mesa_is_timestamp_stable(self):
        source=Path(os.environ.get('ORBISFOX_GECKO_INPUT',ROOT/'.deps/gecko-layout'))
        if not (source/'toolkit/moz.configure').is_file():
            self.skipTest('Provide prepared pinned source via ORBISFOX_GECKO_INPUT')
        script=ROOT/'scripts/patch-gecko-layout.py'
        names={node.value for node in ast.walk(ast.parse(script.read_text()))
               if isinstance(node,ast.Constant) and isinstance(node.value,str)
               and '\n' not in node.value and '/' in node.value
               and not node.value.startswith('/') and (source/node.value).is_file()}
        names.update({'dom/media/platforms/ffmpeg/FFmpegLibWrapper.cpp',
                      'dom/media/platforms/ffmpeg/FFmpegLibWrapper.h',
                      'dom/media/platforms/ffmpeg/OrbisStaticFFVPX.inc',
                      'media/ffvpx/libavcodec/avcodec.symbols',
                      'media/ffvpx/libavutil/avutil.symbols'})
        with tempfile.TemporaryDirectory() as directory:
            copy=Path(directory)
            for name in names:
                p=copy/name;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes((source/name).read_bytes())
            # A prepared checkout from another worktree embeds its original
            # codec path. Normalize only those paths in this disposable copy.
            p=copy/'dom/media/platforms/ffmpeg/moz.build'
            old=str(source.parent.parent/'build/media-codecs/native')+'/'
            p.write_text(p.read_text().replace(old,str(ROOT/'build/media-codecs/native')+'/'))
            subprocess.run([sys.executable,script,copy],capture_output=True,text=True,check=True)
            first={name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names}
            subprocess.run([sys.executable,script,copy],capture_output=True,text=True,check=True)
            self.assertEqual(first,{name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names})
            # Prepared checkouts hid an ordering dependency in printer selection:
            # exercise the actual unpatched widget input from the pinned commit.
            original=subprocess.check_output(['git','-C',str(source),'show',
                '83cebcf5a522bf49667fd07084f04e8497de0eba:widget/moz.build'],
                env=dict(os.environ,GIT_NO_LAZY_FETCH='1'))
            (copy/'widget/moz.build').write_bytes(original)
            subprocess.run([sys.executable,script,copy],capture_output=True,text=True,check=True)
            self.assertEqual(first['widget/moz.build'][0],(copy/'widget/moz.build').read_bytes())
            fresh={name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names}
            subprocess.run([sys.executable,script,copy],capture_output=True,text=True,check=True)
            self.assertEqual(fresh,{name:((copy/name).read_bytes(),(copy/name).stat().st_mtime_ns) for name in names})

    def test_actual_widget_selection_respects_native_gate_and_global_fallback(self):
        source=Path(os.environ.get('ORBISFOX_GECKO_INPUT',ROOT/'.deps/gecko-layout'))
        names=['gfx/gl/GLLibraryEGL.cpp','gfx/gl/GLContextProviderEGL.cpp',
               'gfx/webrender_bindings/RenderThread.cpp','gfx/webrender_bindings/RenderCompositor.cpp',
               'gfx/webrender_bindings/moz.build','gfx/gl/moz.build',
               'gfx/thebes/gfxPlatform.cpp','gfx/config/gfxConfigManager.cpp','widget/nsIWidget.cpp']
        if not all((source/name).is_file() for name in names):
            self.skipTest('Provide prepared pinned source via ORBISFOX_GECKO_INPUT')
        with tempfile.TemporaryDirectory() as directory:
            copy=Path(directory)
            for name in names:
                p=copy/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((source/name).read_bytes())
            PATCH.patch_orbis_mesa(copy)
            code=(copy/'widget/nsIWidget.cpp').read_text()
            begin=code.index('    // If widget type does not supports acceleration')
            end=code.index('    bool enableAPZ = UseAPZ();',begin)
            # Compile the real transformed widget selection, not a copied policy.
            harness=r'''
#include <cassert>
bool ready,globalSoftware,force;
namespace mozilla::widget {
bool IsOrbisMesaGpuReady(){return ready;}
void RecordOrbisCompositorSelection(bool,bool,bool,bool,bool){}
}
namespace gfx { struct gfxVars {static bool UseSoftwareWebRender(){return globalSoftware;}}; }
struct StaticPrefs {static bool gfx_webrender_unaccelerated_widget_force(){return force;}};
struct Widget {
 bool headless,supported;
 bool IsHeadlessWidget(){return headless;}
 bool WidgetTypeSupportsAcceleration(){return supported;}
 bool select(){
''' + code[begin:end] + r'''
 return enableSWWR;
 }
};
int main(){
 for(unsigned bits=0;bits<32;++bits){
  Widget w{bool(bits&1),bool(bits&2)};ready=bool(bits&4);globalSoftware=bool(bits&8);force=bool(bits&16);
#ifdef MOZ_ORBIS_MESA
  const bool permittedHeadless=ready;
#else
  const bool permittedHeadless=false;
#endif
  const bool eligible=(!w.headless||permittedHeadless)&&(w.supported||force);
  assert(w.select()==(eligible?globalSoftware:true));
 }
}
'''
            cpp=copy/'selection.cpp';cpp.write_text(harness)
            for mesa in (False,True):
                binary=copy/('selection-mesa' if mesa else 'selection-software')
                subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    *(['-DMOZ_ORBIS_MESA'] if mesa else []),cpp,'-o',binary],check=True)
                subprocess.run([binary],check=True)

    def test_gpu_failure_notifies_gecko_recovery_instead_of_freezing_mailbox(self):
        source=(ROOT/'gecko/gfx/webrender_bindings/RenderCompositorOrbis.cpp').read_text()
        self.assertIn('RenderThread::Get()->HandleWebRenderError(error)',source)
        self.assertEqual(source.count('mFailed=true;'),1)
        self.assertIn('WebRenderError::MAKE_CURRENT',source)
        self.assertIn('WebRenderError::RENDER',source)
        # Minimize/empty widgets must not permanently disable the backend.
        self.assertIn('if (mFailed || mPaused || size.width<=0 || size.height<=0)',source)
        self.assertIn('void RenderCompositorOrbis::Fail(',source)

    def test_mesa_producer_rejects_pinned_input_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            copy=Path(directory);p=copy/'gfx/thebes/gfxPlatform.cpp'
            p.parent.mkdir(parents=True);p.write_text('unrecognized upstream source\n')
            (p.parent/'moz.build').write_text('FINAL_LIBRARY = "xul"\n')
            with self.assertRaisesRegex(RuntimeError,'Pinned Gecko layout patch no longer matches'):
                PATCH.patch_orbis_mesa(copy)

    def test_runtime_policy_requests_hardware_only_for_real_boolean_capability(self):
        script=r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8');
const begin=source.indexOf('const applyRuntimePreferences=()=>{');
const end=source.indexOf('    const profile =',begin);
assert(begin>=0&&end>begin);
for(const capability of [undefined,false,0,1,'true',true]){
 const values=new Map();
 const context={host:{nativeGpuReady:capability,nativeJitReady:false},io:{},
  prefs:{setBoolPref:(k,v)=>values.set(k,v),setCharPref(){},setIntPref:(k,v)=>values.set(k,v)}};
 vm.runInNewContext(source.slice(begin,end)+'\napplyRuntimePreferences();',context);
 assert.equal(values.get('gfx.webrender.software'),capability!==true);
 assert.equal(values.get('layers.acceleration.disabled'),capability!==true);
 assert.equal(values.get('layers.gpu-process.enabled'),false);
 assert.equal(values.get('javascript.options.wasm'),false);
 assert.equal(values.get('javascript.options.baselinejit'),false);
 assert.equal(values.get('image.mem.shared.unmap.force-enabled'),true);
 assert.equal(values.get('image.mem.surfacecache.max_size_kb'),48*1024);
 assert.equal(values.get('image.mem.surfacecache.min_expiration_ms'),5000);
 assert.equal(values.get('image.mem.shared.unmap.min_expiration_ms'),5000);
 assert.equal(values.get('media.memory_caches_combined_limit_kb'),32*1024);
 assert.equal(values.get('browser.sessionhistory.max_total_viewers'),1);
}
'''
        subprocess.run(['node','-e',script,ROOT/'gecko/orbisfox/fixtures/gecko-startup.js'],check=True)

    def test_adapter_renders_on_gpu_without_opening_second_scanout(self):
        code=(ROOT/'gecko/gfx/webrender_bindings/RenderCompositorOrbis.cpp').read_text()
        self.assertIn('SingletonGL(error)',code)
        queue=(ROOT/'gecko/orbisfox/OrbisGpuReadbackQueue.h').read_text()
        self.assertIn('fReadPixels(',queue)
        self.assertIn('fClientWaitSync(slot.fence,0,0)',queue)
        self.assertIn('capacity = 2',queue)
        self.assertIn('waitOldest(*mGL,250000000)',code)
        self.assertIn('Orbis GPU readback backpressure deadline failed',code)
        self.assertIn('NS_NewTimerWithFuncCallback',code)
        self.assertIn('PostEvent(wr::WindowId{}',code)
        self.assertIn('WeakPtr<RenderCompositorOrbis>',code)
        self.assertIn('mCompleted=RenderedFrameId{completed}',code)
        self.assertNotIn('fTexSubImage2D',code)  # Not a software-frame upload backend.
        self.assertNotIn('CreateWindowSurface',code)
        self.assertNotIn('SwapBuffers',code)
        self.assertIn('output.forget()',code)
        # Capture/restore all pack and read-framebuffer state in the shared
        # implementation, also exercised against real GLES by orbis_resource_test.
        self.assertIn('struct PackState',queue)
        for state in ['&fbo','&buffer','&alignment','&row','&pixels','&rows']:
            self.assertIn(state,queue)
        config=(ROOT/'gecko/orbisfox/moz.configure').read_text()
        self.assertIn('option("--enable-orbis-mesa", default=False,',config)
        startup=(ROOT/'gecko/orbisfox/fixtures/gecko-startup.js').read_text()
        self.assertIn('const gpuReady=host.nativeGpuReady===true;',startup)
        self.assertIn('"gfx.webrender.software": !gpuReady',startup)
        self.assertIn('"layers.acceleration.disabled": !gpuReady',startup)


if __name__=='__main__':
    unittest.main()
