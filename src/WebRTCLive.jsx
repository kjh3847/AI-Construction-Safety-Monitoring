import React,{useEffect,useRef,useState} from 'react';
import {API_BASE,accountRequest} from './api';
import {MetadataBuffer} from './mediaClock';
import {textLabels} from './frameProtocol';

export default function WebRTCLive({cameraId,status,paused,onFrame}){
  const video=useRef(null),canvas=useRef(null),callback=useRef(onFrame),pauseRef=useRef(paused);
  callback.current=onFrame;pauseRef.current=paused;
  const [message,setMessage]=useState('송출 대기'),[fps,setFps]=useState(0),[analysis,setAnalysis]=useState(null);
  const [aligned,setAligned]=useState(false),[latency,setLatency]=useState(null);
  useEffect(()=>{if(video.current){if(paused)video.current.pause();else video.current.play().catch(()=>{});}},[paused]);
  useEffect(()=>{
    let active=true,pc=null,socket=null,resource=null,retry=null,heartbeat=null,metadataRetry=null,frameCallback=null;
    let received=0,clock=performance.now(),buffer=new MetadataBuffer(cameraId),alignedFrames=0;
    let attempt=0,offerAbort=null,connectionDeadline=null,lastMetadata=0,lastRendered=performance.now();
    setAnalysis(null);setAligned(false);setFps(0);setMessage(status?.relay?.online?'WebRTC 연결 중':'스마트폰 송출 대기');
    const element=video.current,overlay=canvas.current,context=overlay.getContext('2d');
    context.clearRect(0,0,overlay.width,overlay.height);
    function render(now,frame){
      if(!active)return;
      if(!pauseRef.current && element.videoWidth){
        received++;
        lastRendered=now;
        if(now-clock>=1000){setFps(received*1000/(now-clock));received=0;clock=now;}
        overlay.width=element.videoWidth;overlay.height=element.videoHeight;
        const meta=buffer.exact(frame.rtpTimestamp);
        if(meta){
          alignedFrames++;setAligned(true);
          context.save();context.scale(element.videoWidth/meta.width,element.videoHeight/meta.height);
          context.font=`${Math.max(14,Math.round(meta.width/65))}px "Malgun Gothic",sans-serif`;
          context.lineWidth=3;context.strokeStyle='#07101e';
          for(const label of textLabels(meta,meta.width,meta.height,text=>context.measureText(text).width)){
            context.fillStyle=label.danger?'#ff8585':'#8aefc1';context.strokeText(label.text,label.x,label.y,meta.width);context.fillText(label.text,label.x,label.y,meta.width);
          }
          context.restore();callback.current?.({...meta,mode:'live',paused:false,alignment:'exact-rtp'});
        }
        element.dataset.rtpTimestamp=String(frame.rtpTimestamp??'');element.dataset.alignedFrames=String(alignedFrames);
      }
      frameCallback=element.requestVideoFrameCallback(render);
    }
    function cleanupConnection(){
      attempt++;offerAbort?.abort();clearTimeout(connectionDeadline);
      clearInterval(heartbeat);
      if(pc){pc.onconnectionstatechange=null;pc.close();pc=null;}
      if(resource){accountRequest(resource,{method:'DELETE'}).catch(()=>{});resource=null;}
      if(frameCallback!=null)element.cancelVideoFrameCallback?.(frameCallback);
    }
    async function connect(){
      if(!active || !status?.relay?.online)return;
      const serial=++attempt;
      try{
        const peer=new RTCPeerConnection();pc=peer;peer.addTransceiver('video',{direction:'recvonly'});
        const current=()=>active && serial===attempt;
        connectionDeadline=setTimeout(()=>{if(current()){setMessage('영상 연결 시간 초과 · 재연결 중');cleanupConnection();retry=setTimeout(connect,3000);}},20000);
        peer.ontrack=event=>{
          if(!current())return;
          element.srcObject=new MediaStream([event.track]);if(!pauseRef.current)element.play().catch(()=>{});
          if(element.requestVideoFrameCallback)frameCallback=element.requestVideoFrameCallback(render);
          else setMessage('프레임 동기화 미지원 · 위치 텍스트 숨김');
        };
        peer.onconnectionstatechange=()=>{
          if(!current())return;
          if(peer.connectionState==='connected'){setMessage('');clearTimeout(connectionDeadline);}
          if(['failed','disconnected'].includes(peer.connectionState)){setMessage('영상 연결 끊김 · 재연결 중');cleanupConnection();retry=setTimeout(connect,3000);}
        };
        await peer.setLocalDescription(await peer.createOffer());
        if(peer.iceGatheringState!=='complete')await new Promise(resolve=>{
          const timeout=setTimeout(resolve,3000);
          peer.addEventListener('icegatheringstatechange',()=>{if(peer.iceGatheringState==='complete'){clearTimeout(timeout);resolve();}});
        });
        if(!current())return;
        offerAbort=new AbortController();
        const response=await fetch(`${API_BASE}/api/media/${cameraId}/whep`,{method:'POST',credentials:'include',
          headers:{'Content-Type':'application/sdp'},body:peer.localDescription.sdp,signal:AbortSignal.any([offerAbort.signal,AbortSignal.timeout(12000)])});
        if(!response.ok)throw new Error('송출 대기 또는 WebRTC 연결 실패');
        const location=response.headers.get('Location');
        if(!current()){if(location)accountRequest(location,{method:'DELETE'}).catch(()=>{});return;}
        if(!location?.startsWith('/api/media/sessions/'))throw new Error('영상 세션 응답 오류');
        resource=location;
        await peer.setRemoteDescription({type:'answer',sdp:await response.text()});
        if(!current())return;
        for(const receiver of peer.getReceivers())if('jitterBufferTarget' in receiver)receiver.jitterBufferTarget=150;
        heartbeat=setInterval(async()=>{
          try{
            await accountRequest(location+'/keepalive',{method:'POST'});
            for(const report of (await peer.getStats()).values())if(current() && report.type==='inbound-rtp' && report.kind==='video' && report.jitterBufferEmittedCount)
              setLatency(1000*report.jitterBufferDelay/report.jitterBufferEmittedCount);
          }catch{if(current()){cleanupConnection();retry=setTimeout(connect,3000);}}
        },10000);
      }catch(error){if(active && serial===attempt){setMessage(error.message);cleanupConnection();retry=setTimeout(connect,3000);}}
    }
    function metadata(){
      if(!active)return;
      const url=new URL(`${API_BASE}/api/metadata/${cameraId}`,window.location.href);url.protocol=url.protocol==='https:'?'wss:':'ws:';
      socket=new WebSocket(url);
      socket.onmessage=event=>{try{const meta=JSON.parse(event.data);if(buffer.add(meta)){lastMetadata=performance.now();setAnalysis(meta);}}catch{}};
      socket.onclose=()=>{if(active)metadataRetry=setTimeout(metadata,2000);};
    }
    connect();metadata();
    const freshness=setInterval(()=>{
      if(performance.now()-lastMetadata>5000){setAnalysis(null);setAligned(false);}
      if(performance.now()-lastRendered>2000)setFps(0);
    },1000);
    return()=>{active=false;clearInterval(freshness);clearTimeout(retry);clearTimeout(metadataRetry);socket?.close(1000);cleanupConnection();element.srcObject=null;};
  },[cameraId,status?.relay?.online,status?.relay?.ready_time]);
  return <>
    <video ref={video} className="webrtc-video" autoPlay muted playsInline aria-label={`${cameraId} WebRTC 실시간 영상`}/>
    <canvas ref={canvas} className="webrtc-overlay" aria-label="동일 RTP 프레임의 텍스트 분석 결과"/>
    <span className="webrtc-metrics">표시 {fps.toFixed(1)} FPS · AI {status?.metrics?.analysis_fps??'—'} FPS{latency!=null?` · 지터 버퍼 ${latency.toFixed(0)}ms`:''}</span>
    {message && <div className="video-message" role="status">{message}</div>}
    <div className="webrtc-analysis">{analysis?<><span>{aligned?'RTP 프레임 동기화 확인':'위치 텍스트는 일치하는 프레임에서만 표시'}</span>
      {analysis.person_safety?.map(person=><span key={person.local_track_id}>{person.global_person_id??person.local_track_id} · {person.violations.length?person.violations.join(' / '):'미착용 증거 없음'}</span>)}</>:<span>영상 독립 재생 · AI 분석 결과 대기</span>}</div>
    {status?.relay?.test_source && <span className="source-label">TEST SOURCE · 합성 송출 테스트</span>}
  </>;
}
