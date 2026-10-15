#!/usr/bin/env python3
"""Generate real VP9/Opus and H.264/AAC fixtures; bounded read-only LAN server."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import BoundedSemaphore
import json
from pathlib import Path
import subprocess
import time
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'build/media-fixture'
HTML = b'''<!doctype html><meta charset="utf-8"><title>OrbisFox real media check</title>
<style>body{background:#18202a;color:white;font:24px sans-serif}video{width:640px;max-width:95vw}pre{white-space:pre-wrap}</style>
<h1>Real software media check</h1><p>Choose a format, then press Play. Moving pattern plus 440 Hz tone should last five seconds.</p><p><button id="webm">VP9 / Opus</button> <button id="mp4">H.264 / AAC</button> <button id="mse">H.264 / AAC via MediaSource</button></p>
<video controls preload="metadata" src="/clip.webm"></video><p><button id="play">Play / Pause</button> <button id="replay">Replay</button> <label>Volume <input id="volume" type="range" min="0" max="100" value="50"></label></p><pre id="status">Awaiting real decoder</pre>
<script>const v=document.querySelector('video'),s=document.querySelector('#status');
function report(event){const q=v.getVideoPlaybackQuality?.();s.textContent=JSON.stringify({event,time:v.currentTime,ready:v.readyState,
width:v.videoWidth,height:v.videoHeight,paused:v.paused,ended:v.ended,error:v.error?.code??null,
frames:q?.totalVideoFrames,dropped:q?.droppedVideoFrames},null,2);console.log('ORBISFOX_MEDIA '+s.textContent);}
v.volume=.5;let sourceURL='';
function reset(){v.pause();if(sourceURL)URL.revokeObjectURL(sourceURL);sourceURL='';v.removeAttribute('src');v.load();}
document.querySelector('#webm').onclick=()=>{reset();v.src='/clip.webm';report('VP9/Opus selected; press Play');};
document.querySelector('#mp4').onclick=()=>{reset();v.src='/clip.mp4';report('H264/AAC selected; press Play');};
document.querySelector('#mse').onclick=()=>{reset();const mime='video/mp4; codecs="avc1.42C01E,mp4a.40.2"';
if(!window.MediaSource||!MediaSource.isTypeSupported(mime)){s.textContent='Actual MediaSource capability rejects '+mime;return;}
const media=new MediaSource();sourceURL=URL.createObjectURL(media);v.src=sourceURL;
media.addEventListener('sourceopen',async()=>{try{const response=await fetch('/fragmented.mp4');if(!response.ok)throw Error('HTTP '+response.status);const data=await response.arrayBuffer();const buffer=media.addSourceBuffer(mime);
buffer.addEventListener('error',()=>{s.textContent='Real SourceBuffer error';});buffer.addEventListener('updateend',()=>{if(media.readyState==='open'){media.endOfStream();report('MSE appended; press Play');}},{once:true});buffer.appendBuffer(data);
}catch(error){s.textContent='Actual MediaSource failure: '+error;}},{once:true});};
window.addEventListener('pagehide',()=>{if(sourceURL)URL.revokeObjectURL(sourceURL);},{once:true});
document.querySelector('#play').onclick=async()=>{try{if(v.paused)await v.play();else v.pause();report('explicit-play-pause');}catch(error){s.textContent='Playback failed: '+error;console.log('ORBISFOX_MEDIA_PLAY_FAILURE '+error);}};
document.querySelector('#replay').onclick=async()=>{try{v.currentTime=0;await v.play();report('explicit-replay');}catch(error){s.textContent='Replay failed: '+error;}};
document.querySelector('#volume').oninput=e=>{v.volume=Number(e.target.value)/100;};
for(const e of ['loadedmetadata','loadeddata','playing','waiting','stalled','ended','error','pause'])v.addEventListener(e,()=>report(e));
setInterval(()=>report('sample'),1000);</script>'''


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    temporary = OUT / 'clip.pending.webm'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '5', '-c:v', 'libvpx-vp9', '-threads', '1', '-b:v', '220k',
                    '-pix_fmt', 'yuv420p', '-c:a', 'libopus', '-b:a', '48k',
                    '-ac', '2', str(temporary)], check=True)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(temporary)]))
    if {s['codec_name'] for s in probe['streams']} != {'vp9', 'opus'}:
        raise RuntimeError('Fixture must contain actual VP9 and Opus streams')
    if not 0 < temporary.stat().st_size <= 2*1024*1024:
        raise RuntimeError('Media fixture exceeds bounded size')
    # Independently decode actual bytes; this is host proof, NOT PS4 playback.
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', str(temporary), '-f', 'null', '-'], check=True)
    temporary.replace(OUT / 'clip.webm')
    for name, flags in [('clip.mp4', 'faststart'), ('fragmented.mp4', 'frag_keyframe+empty_moov+default_base_moof')]:
        pending = OUT / ('pending-' + name)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                        '-t', '5', '-c:v', 'libx264', '-threads', '1', '-profile:v', 'baseline',
                        '-level:v', '3.0', '-pix_fmt', 'yuv420p', '-g', '24', '-b:v', '220k',
                        '-c:a', 'aac', '-profile:a', 'aac_low', '-b:a', '48k', '-ac', '2',
                        '-movflags', flags, str(pending)], check=True)
        streams = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(pending)]))['streams']
        if {stream['codec_name'] for stream in streams} != {'h264', 'aac'} or not 0 < pending.stat().st_size <= 2*1024*1024:
            raise RuntimeError('Invalid H264/AAC fixture')
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(pending), '-f', 'null', '-'], check=True)
        pending.replace(OUT / name)
    (OUT / 'index.html').write_bytes(HTML)
    report = {'host_encoded_and_decoded': True, 'firmware_playback_verified': False,
              'streams': probe['streams'], 'files': {p.name: {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
              for p in (OUT / 'clip.webm', OUT / 'clip.mp4', OUT / 'fragmented.mp4', OUT / 'index.html')}}
    (OUT / 'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def serve(host, port, seconds):
    frozen = {'/': (HTML, 'text/html; charset=utf-8'), '/clip.webm': ((OUT/'clip.webm').read_bytes(), 'video/webm'),
              '/clip.mp4': ((OUT/'clip.mp4').read_bytes(), 'video/mp4'),
              '/fragmented.mp4': ((OUT/'fragmented.mp4').read_bytes(), 'video/mp4')}
    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def __init__(self, *args, **kwargs):
            self.slots = BoundedSemaphore(8)
            super().__init__(*args, **kwargs)

        def process_request(self, request, address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request)
                return
            try:
                super().process_request(request, address)
            except BaseException:
                self.slots.release()
                raise

        def process_request_thread(self, request, address):
            try:
                super().process_request_thread(request, address)
            finally:
                self.slots.release()

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in frozen:
                self.send_error(404); return
            content, kind = frozen[self.path]
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store'); self.send_header('Connection', 'close')
            self.send_header('Content-Security-Policy', "default-src 'none'; media-src 'self' blob:; connect-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
            self.end_headers(); self.wfile.write(content); self.close_connection = True
    with Server((host, port), Handler) as server:
        server.timeout = 1
        end = time.monotonic()+seconds
        print(f'Frozen real media fixture: http://{host}:{port}/ ({seconds}s)', flush=True)
        while time.monotonic() < end:
            server.handle_request()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve-seconds', type=int, default=0)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    if not 0 <= args.serve_seconds <= 7200 or not 1 <= args.port <= 65535:
        parser.error('bounded lifetime 0..7200 and valid port required')
    print(json.dumps(prepare(), indent=2), flush=True)
    if args.serve_seconds:
        serve(args.host, args.port, args.serve_seconds)

if __name__ == '__main__':
    main()
