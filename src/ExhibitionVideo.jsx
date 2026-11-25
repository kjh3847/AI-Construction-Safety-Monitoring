import React, {useEffect, useRef, useState} from 'react';
import {API_BASE} from './api';
import {drawEquipmentBoxes, textLabels} from './frameProtocol';

export default function ExhibitionVideo({camera, status, onFrame}) {
  const video = useRef(null);
  const canvas = useRef(null);
  const callback = useRef(onFrame);
  callback.current = onFrame;
  const [error, setError] = useState('');
  const running = ['starting', 'running'].includes(status?.state);
  const configured = Boolean(status?.video_version);
  const version = status?.video_version;
  const recordingId = status?.recording_id;

  useEffect(() => {
    const player = video.current;
    const overlay = canvas.current;
    if (!player || !overlay) return;
    const context = overlay.getContext('2d');
    context.clearRect(0, 0, overlay.width, overlay.height);
    if (!running) {
      player.pause();
      callback.current(null);
      return;
    }
    let active = true, socket, retry, animation;
    let latest = null, packets = [];
    let positioned = false;
    setError('');

    function sync() {
      if (!latest || !player.duration) return;
      const age = Math.min(.4, Math.max(0, (performance.now() - latest.arrival) / 1000));
      const target = (latest.packet.video_seconds + age) % player.duration;
      const drift = Math.abs(player.currentTime - target);
      if (!positioned || Math.min(drift, player.duration - drift) > .55) {
        player.currentTime = target;
        positioned = true;
      }
      if (player.paused) player.play().catch(() => setError('영상을 시작할 수 없습니다. MP4 코덱을 확인하세요.'));
    }

    function render() {
      if (!active) return;
      if (player.videoWidth && player.videoHeight) {
        if (overlay.width !== player.videoWidth || overlay.height !== player.videoHeight) {
          overlay.width = player.videoWidth;
          overlay.height = player.videoHeight;
        }
        context.clearRect(0, 0, overlay.width, overlay.height);
        const now = performance.now();
        const sample = packets.find(({packet, arrival}) => now - arrival < 750
          && Math.abs(packet.video_seconds - player.currentTime) <= .3)?.packet;
        if (sample) {
          context.save();
          context.scale(overlay.width / sample.width, overlay.height / sample.height);
          drawEquipmentBoxes(context, sample, sample.width, sample.height);
          context.font = Math.max(14, Math.round(sample.width / 65)) + 'px "Malgun Gothic", sans-serif';
          context.lineWidth = 3;
          context.strokeStyle = '#07101e';
          for (const label of textLabels(sample, sample.width, sample.height, text => context.measureText(text).width)) {
            context.fillStyle = label.danger ? '#ff8585' : '#8aefc1';
            context.strokeText(label.text, label.x, label.y, sample.width);
            context.fillText(label.text, label.x, label.y, sample.width);
          }
          context.restore();
        }
      }
      animation = requestAnimationFrame(render);
    }

    function connect() {
      const url = new URL(API_BASE + '/api/metadata/' + camera.id, window.location.href);
      url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(url);
      socket.onmessage = event => {
        const packet = JSON.parse(event.data);
        if (packet.recording_id !== recordingId) return;
        if (latest && packet.video_seconds < latest.packet.video_seconds) packets = [];
        latest = {packet, arrival: performance.now()};
        packets.unshift(latest);
        packets.length = Math.min(packets.length, 8);
        sync();
        callback.current({...packet, mode: 'live', paused: false});
      };
      socket.onclose = () => { if (active) retry = setTimeout(connect, 1500); };
      socket.onerror = () => socket?.close();
    }

    function playbackError() { setError('MP4 파일을 재생할 수 없습니다. H.264 MP4인지 확인하세요.'); }
    player.addEventListener('loadedmetadata', sync);
    player.addEventListener('error', playbackError);
    connect();
    animation = requestAnimationFrame(render);
    return () => {
      active = false;
      clearTimeout(retry);
      cancelAnimationFrame(animation);
      socket?.close();
      player.pause();
      player.removeEventListener('loadedmetadata', sync);
      player.removeEventListener('error', playbackError);
      callback.current(null);
    };
  }, [camera.id, configured, running, recordingId, version]);

  return <div className="dvr-picture exhibition-demo-video">
    {configured && <video ref={video} className="webrtc-video" muted playsInline loop preload="metadata"
      src={API_BASE + '/api/exhibition/video/' + camera.id + '?v=' + version}
      aria-label={camera.name + ' 시연 영상'} hidden={!running}/>}
    {configured && <canvas ref={canvas} className="webrtc-overlay" hidden={!running} aria-label="보호구 감지 박스"/>}
    {(!running || error) && <div className="empty-feed"><h3>{running ? error : configured
      ? '감지·녹화 시작 대기' : 'S3 시연 영상 준비 중'}</h3></div>}
  </div>;
}
