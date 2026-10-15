import json
from pathlib import Path
import subprocess
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SoftwareCodecTests(unittest.TestCase):
    def test_real_isolated_h264_aac_and_existing_codecs(self):
        out = ROOT / 'build/media-codecs/decode-test'
        out.mkdir(parents=True, exist_ok=True)
        with (out / 'build.log').open('w') as log:
            subprocess.run(['python3', 'scripts/build-media-codecs.py', '--host'], cwd=ROOT,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        host = ROOT / 'build/media-codecs/host'
        report = json.loads((host / 'build-report.json').read_text())
        self.assertFalse(report['gpl'])
        self.assertFalse(report['network'])
        aliases = out / 'aliases.h'
        # Rename only the public API used here. Defining every exported name as
        # a macro would accidentally override libavutil's inline-selection guards.
        api = {'avcodec_find_decoder', 'avcodec_alloc_context3', 'avcodec_open2',
               'av_parser_init', 'av_frame_alloc', 'av_packet_alloc', 'av_mallocz',
               'av_parser_parse2', 'avcodec_send_packet', 'avcodec_receive_frame',
               'av_frame_unref', 'av_free', 'av_parser_close', 'av_packet_free',
               'av_frame_free', 'avcodec_free_context'}
        aliases.write_text(''.join('#define ' + line + '\n'
                                  for line in (host / 'symbol-map.txt').read_text().splitlines()
                                  if line.split()[0] in api))
        # Test-only encoders generate genuine elementary bitstreams. No encoder
        # or GPL library is linked into OrbisFox's LGPL decoder implementation.
        for name, source, args in (
            ('video.h264', 'testsrc2=size=128x72:rate=12', ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'h264']),
            ('audio.aac', 'sine=frequency=440:sample_rate=48000', ['-c:a', 'aac', '-f', 'adts'])):
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', source, '-t', '0.5',
                            *args, str(out / name)], check=True)
        # Packet/extradata fixtures exercise retained video/audio formats too.
        # ffprobe exports bytes only; it is not the decoder under test.
        for name, media, encoder, codec_id in (
            ('vp9', 'testsrc2=size=128x72:rate=12', 'libvpx-vp9', 1),
            ('opus', 'sine=frequency=440:sample_rate=48000', 'libopus', 2),
            ('vp8', 'testsrc2=size=128x72:rate=12', 'libvpx', 3),
            ('vorbis', 'sine=frequency=440:sample_rate=48000', 'libvorbis', 4),
            ('flac', 'sine=frequency=440:sample_rate=48000', 'flac', 5),
            ('mp3', 'sine=frequency=440:sample_rate=48000', 'libmp3lame', 6)):
            encoded = out / (name + '.mkv')
            options = ['-c:v', encoder, '-threads', '1'] if name in ('vp8', 'vp9') else ['-c:a', encoder, '-ac', '2']
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', media, '-t', '0.5', *options, str(encoded)], check=True)
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_packets', '-show_data', '-of', 'json', str(encoded)]))
            def unpack(text):
                return bytes.fromhex(''.join(line.split(': ', 1)[1].split('  ', 1)[0] for line in text.splitlines() if ': ' in line))
            extra = unpack(probe['streams'][0].get('extradata', ''))
            packets = [unpack(packet['data']) for packet in probe['packets']]
            (out / (name + '.packets')).write_bytes(struct.pack('<III', codec_id, len(extra), len(packets)) + extra + b''.join(struct.pack('<I', len(packet)) + packet for packet in packets))
        source = out / 'decode.c'
        source.write_text(r'''
#include <libavcodec/avcodec.h>
#include <libavutil/mem.h>
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
static void decode(const char* path,enum AVCodecID id) {
 const AVCodec* codec=avcodec_find_decoder(id);assert(codec);
 AVCodecContext* context=avcodec_alloc_context3(codec);assert(context);
 context->thread_count=2;assert(avcodec_open2(context,codec,NULL)>=0);
 AVCodecParserContext* parser=av_parser_init(id);assert(parser);
 AVFrame* frame=av_frame_alloc();AVPacket* packet=av_packet_alloc();assert(frame&&packet);
 FILE* file=fopen(path,"rb");assert(file);assert(fseek(file,0,SEEK_END)==0);
 long length=ftell(file);assert(length>0&&length<1024*1024);rewind(file);
 uint8_t* data=av_mallocz((size_t)length+AV_INPUT_BUFFER_PADDING_SIZE);assert(data);
 assert(fread(data,1,(size_t)length,file)==(size_t)length);assert(!fclose(file));
 uint8_t* cursor=data;int remaining=(int)length,frames=0,nonzero=0;
 for(int flush=0;flush<2;++flush){
  while(remaining>0||flush==1){
   int used=av_parser_parse2(parser,context,&packet->data,&packet->size,cursor,remaining,
                            AV_NOPTS_VALUE,AV_NOPTS_VALUE,0);assert(used>=0&&used<=remaining);
   cursor+=used;remaining-=used;
   if(!packet->size)break;
   assert(avcodec_send_packet(context,packet)>=0);
   while(avcodec_receive_frame(context,frame)==0){
    ++frames;
    if(id==AV_CODEC_ID_H264){assert(frame->width==128&&frame->height==72);nonzero|=frame->data[0][20]!=0;}
    else {assert(frame->nb_samples>0&&frame->sample_rate==48000);assert(frame->format==AV_SAMPLE_FMT_FLTP);
     for(int i=0;i<frame->nb_samples;++i){float v=((float*)frame->data[0])[i];assert(isfinite(v));nonzero|=fabsf(v)>0.0001f;}}
    av_frame_unref(frame);
   }
   if(!used&&remaining)assert(!"parser made no progress");
   if(flush)break;
  }
 }
 assert(avcodec_send_packet(context,NULL)>=0);
 while(avcodec_receive_frame(context,frame)==0){++frames;av_frame_unref(frame);}
 assert(frames>=3&&nonzero);printf("real decode id=%d frames=%d\n",id,frames);
 av_free(data);av_parser_close(parser);av_packet_free(&packet);av_frame_free(&frame);avcodec_free_context(&context);
}
static uint32_t number(FILE* file){uint32_t n=0;assert(fread(&n,4,1,file)==1);return n;}
static void decode_packets(const char* path){
 FILE* file=fopen(path,"rb");assert(file);unsigned marker=number(file);assert(marker>=1&&marker<=6);
 const enum AVCodecID codecs[]={AV_CODEC_ID_VP9,AV_CODEC_ID_OPUS,AV_CODEC_ID_VP8,AV_CODEC_ID_VORBIS,AV_CODEC_ID_FLAC,AV_CODEC_ID_MP3};enum AVCodecID id=codecs[marker-1];
 unsigned extra=number(file),count=number(file);assert(extra<65536&&count>0&&count<1000);
 const AVCodec* codec=avcodec_find_decoder(id);assert(codec);AVCodecContext* context=avcodec_alloc_context3(codec);assert(context);context->thread_count=2;
 if(extra){context->extradata=av_mallocz(extra+AV_INPUT_BUFFER_PADDING_SIZE);assert(context->extradata);context->extradata_size=(int)extra;assert(fread(context->extradata,1,extra,file)==extra);}
 assert(avcodec_open2(context,codec,NULL)>=0);AVFrame* frame=av_frame_alloc();AVPacket* packet=av_packet_alloc();assert(frame&&packet);unsigned frames=0;int nonzero=0;
 for(unsigned p=0;p<=count;++p){
  uint8_t* data=NULL;
  if(p<count){unsigned size=number(file);assert(size>0&&size<1024*1024);data=av_mallocz(size+AV_INPUT_BUFFER_PADDING_SIZE);assert(data);assert(fread(data,1,size,file)==size);packet->data=data;packet->size=(int)size;}
  assert(avcodec_send_packet(context,p<count?packet:NULL)>=0);
  while(avcodec_receive_frame(context,frame)==0){++frames;
   if(id==AV_CODEC_ID_VP9||id==AV_CODEC_ID_VP8){assert(frame->width==128&&frame->height==72);nonzero|=frame->data[0][20]!=0;}
   else {assert(frame->nb_samples>0&&frame->sample_rate==48000);for(int i=0;i<frame->nb_samples;++i){
    switch(frame->format){
     case AV_SAMPLE_FMT_FLTP:case AV_SAMPLE_FMT_FLT:{float value=((float*)frame->data[0])[i];assert(isfinite(value));nonzero|=fabsf(value)>0.0001f;break;}
     case AV_SAMPLE_FMT_S16P:case AV_SAMPLE_FMT_S16:nonzero|=((int16_t*)frame->data[0])[i]!=0;break;
     case AV_SAMPLE_FMT_S32P:case AV_SAMPLE_FMT_S32:nonzero|=((int32_t*)frame->data[0])[i]!=0;break;
     default:assert(!"unexpected audio sample format");
    }
   }}
   av_frame_unref(frame);
  }
  av_free(data);packet->data=NULL;packet->size=0;
 }
 assert(frames>=3&&nonzero);printf("real packet decode id=%d frames=%u\n",id,frames);assert(!fclose(file));av_packet_free(&packet);av_frame_free(&frame);avcodec_free_context(&context);
}
int main(int argc,char** argv){assert(argc==9);
 const enum AVCodecID existing[]={AV_CODEC_ID_VP8,AV_CODEC_ID_VP9,AV_CODEC_ID_OPUS,AV_CODEC_ID_VORBIS,AV_CODEC_ID_FLAC,AV_CODEC_ID_MP3};
 for(unsigned i=0;i<sizeof(existing)/sizeof(existing[0]);++i)assert(avcodec_find_decoder(existing[i]));
 decode(argv[1],AV_CODEC_ID_H264);decode(argv[2],AV_CODEC_ID_AAC);for(int i=3;i<argc;++i)decode_packets(argv[i]);return 0;
}
''')
        executable = out / 'decode'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-include', aliases, '-I' + str(ROOT / '.deps/ffmpeg-9.0.2'), '-I' + str(host),
                        source, '-Wl,--start-group', *[ROOT / x['path'] for x in report['archives']],
                        '-Wl,--end-group', '-lm', '-lpthread', '-o', executable], check=True)
        subprocess.run([executable, out / 'video.h264', out / 'audio.aac',
                        *[out / (name + '.packets') for name in ('vp9', 'opus', 'vp8', 'vorbis', 'flac', 'mp3')]], check=True)
        # Decode on host proves real codec algorithms, not firmware playback.


if __name__ == '__main__':
    unittest.main()
