import React, {useEffect, useRef, useState} from 'react';
import {API_BASE} from './api';

const allowed = new Set(['CAM-01', 'CAM-02', 'CAM-03']);

function waitForICE(peer) {
  if (peer.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise(resolve => {
    function finish() {
      clearTimeout(timer);
      peer.removeEventListener('icegatheringstatechange', change);
      resolve();
    }
    function change() { if (peer.iceGatheringState === 'complete') finish(); }
    const timer = setTimeout(finish, 3500);
    peer.addEventListener('icegatheringstatechange', change);
  });
}

function closeSession(session) {
  clearInterval(session.heartbeat);
  clearTimeout(session.deadline);
  session.abort.abort();
  session.peer?.close();
  session.stream?.getTracks().forEach(track => track.stop());
  if (session.resource) {
    fetch(API_BASE + session.resource, {method: 'DELETE', keepalive: true}).catch(() => {});
  }
}

export default function ExhibitionJoin({camera}) {
  const video = useRef(null);
  const current = useRef(null);
  const [phase, setPhase] = useState('idle');
  const [message, setMessage] = useState('');

  function stop(note = '') {
    const session = current.current;
    current.current = null;
    if (session) closeSession(session);
    if (video.current) video.current.srcObject = null;
    setPhase('idle');
    setMessage(note);
  }

  useEffect(() => {
    const end = () => stop();
    const hide = () => { if (document.visibilityState === 'hidden') end(); };
    window.addEventListener('pagehide', end);
    document.addEventListener('visibilitychange', hide);
    return () => {
      window.removeEventListener('pagehide', end);
      document.removeEventListener('visibilitychange', hide);
      const session = current.current;
      current.current = null;
      if (session) closeSession(session);
    };
  }, []);

  async function start() {
    if (current.current) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) {
      setMessage('HTTPS로 열린 Chrome 또는 Safari에서 다시 시도하세요.');
      return;
    }
    const session = {abort: new AbortController()};
    current.current = session;
    const valid = () => current.current === session;
    setPhase('starting');
    setMessage('');
    try {
      session.stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {facingMode: {ideal: 'environment'}, width: {ideal: 960, max: 1280},
          height: {ideal: 540, max: 720}, frameRate: {ideal: 15, max: 20}},
      });
      if (!valid()) {
        session.stream.getTracks().forEach(track => track.stop());
        return;
      }
      video.current.srcObject = session.stream;
      const track = session.stream.getVideoTracks()[0];
      track.onended = () => { if (valid()) stop('카메라 연결을 종료했습니다.'); };
      const peer = new RTCPeerConnection();
      session.peer = peer;
      const transceiver = peer.addTransceiver(track, {direction: 'sendonly', streams: [session.stream]});
      const h264 = RTCRtpSender.getCapabilities?.('video')?.codecs.filter(codec => codec.mimeType.toLowerCase() === 'video/h264');
      if (transceiver.setCodecPreferences && h264?.length) transceiver.setCodecPreferences(h264);
      const senderParameters = transceiver.sender.getParameters();
      if (senderParameters.encodings?.length) {
        senderParameters.encodings[0].maxBitrate = 800000;
        await transceiver.sender.setParameters(senderParameters).catch(() => {});
      }
      peer.onconnectionstatechange = () => {
        if (!valid()) return;
        if (peer.connectionState === 'connected') {
          clearTimeout(session.deadline);
          setPhase('live');
        } else if (['failed', 'closed'].includes(peer.connectionState)) {
          stop('중계 연결이 끊겼습니다. 다시 시작해 주세요.');
        }
      };
      session.deadline = setTimeout(() => {
        if (valid()) stop('연결 시간이 초과됐습니다. 행사장 Wi-Fi 또는 모바일 데이터로 다시 시도하세요.');
      }, 16000);
      await peer.setLocalDescription(await peer.createOffer());
      await waitForICE(peer);
      if (!valid()) return;
      const response = await fetch(API_BASE + '/api/exhibition/publish/' + camera, {
        method: 'POST', headers: {'Content-Type': 'application/sdp'},
        body: peer.localDescription.sdp, signal: session.abort.signal,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || '연결에 실패했습니다.');
      }
      session.resource = response.headers.get('Location');
      if (!session.resource?.startsWith('/api/exhibition/publish/' + camera + '/')) {
        session.resource = null;
        throw new Error('카메라 연결 정보를 받아오지 못했습니다.');
      }
      if (!valid()) {
        closeSession(session);
        return;
      }
      await peer.setRemoteDescription({type: 'answer', sdp: await response.text()});
      if (!valid()) return;
      session.heartbeat = setInterval(async () => {
        try {
          const result = await fetch(API_BASE + session.resource, {
            method: 'POST', signal: AbortSignal.timeout(4000),
          });
          if (!result.ok) throw new Error();
        } catch {
          if (valid()) stop('연결이 종료되었습니다. 다시 시작해 주세요.');
        }
      }, 5000);
    } catch (error) {
      if (valid()) stop(error.name === 'NotAllowedError'
        ? '브라우저에서 카메라 권한을 허용하고 다시 시작하세요.' : error.message);
    }
  }

  if (!allowed.has(camera)) return <main className="exhibition-join"><h1>사용할 수 없는 체험 QR입니다.</h1></main>;
  return <main className="exhibition-join">
    <h1>{camera} 카메라 체험</h1>
    <p>영상은 연결된 동안 전시장 화면에 실시간으로 표시됩니다. 카메라 종료를 누르면 송출이 끝납니다.</p>
    <video ref={video} muted autoPlay playsInline aria-label="내 카메라 미리보기" hidden={phase === 'idle'}/>
    {phase === 'idle'
      ? <button className="primary" onClick={start}>카메라 시작</button>
      : <button className="danger-button" onClick={() => stop('카메라를 종료했습니다.')}>카메라 종료</button>}
    <p role="status">{message || (phase === 'live' ? '전시장에 송출 중' : phase === 'starting' ? '카메라 연결 중' : '')}</p>
  </main>;
}
