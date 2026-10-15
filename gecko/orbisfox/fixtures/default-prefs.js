/* Native Orbis single-process/offline defaults, loaded before XPCOM services.
 * The privileged fixture also sets these, but that is too late for startup. */
pref("network.process.enabled", false);
pref("layers.gpu-process.enabled", false);
pref("browser.tabs.remote.autostart", false);
pref("dom.ipc.processPrelaunch.enabled", false);
pref("media.rdd-process.enabled", false);
pref("media.utility-process.enabled", false);
pref("media.gmp-provider.enabled", false);
pref("media.hardware-video-decoding.enabled", false);
pref("media.hardware-video-encoding.enabled", false);
// Native shared-code capability is chosen before JS_Init; fallback disables
// the backend. Keep advanced tiers off for the first measured Baseline lane.
pref("javascript.options.baselinejit", true);
pref("javascript.options.baselinejit.unsafe_eager_compilation", false);
pref("javascript.options.native_regexp", true);
pref("javascript.options.ion", false);
pref("javascript.options.wasm", false);
pref("webgl.disabled", true);
pref("toolkit.telemetry.enabled", false);
pref("toolkit.telemetry.unified", false);
pref("datareporting.healthreport.uploadEnabled", false);
pref("dom.push.enabled", false);
pref("gfx.webrender.all", true);
pref("gfx.webrender.software", true);
pref("gfx.webrender.compositor", false);
pref("layers.acceleration.disabled", true);
