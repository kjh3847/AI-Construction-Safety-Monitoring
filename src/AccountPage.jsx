import React, {useEffect,useState} from 'react';
import {accountRequest} from './api';
import './login.css';
export default function AccountPage({onLogout}) {
  const [rows,setRows]=useState([]),[id,setId]=useState(''),[email,setEmail]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[selected,setSelected]=useState(null),[reason,setReason]=useState('');
  async function load(){const data=await accountRequest('/api/admin/accounts');setRows(data.accounts);}
  useEffect(()=>{load().catch(e=>setMessage(e.message));},[]);
  async function action(path,body){setBusy(true);setMessage('');try{const data=await accountRequest(path,{method:'POST',body:JSON.stringify(body)});setMessage(data.message);return true;}catch(e){setMessage(e.message);return false;}finally{try{await load();}catch(e){setMessage(e.message);}setBusy(false);}}
  const labels={pending:'발급 대기',active:'활성',disabled:'비활성'};
  return <div className="login-page"><section className="login-card account-card"><h1>관리자 계정 관리</h1><p className="login-description">시스템팀 전용 · 사원번호를 아이디로 발급합니다.</p>
    <div className="account-nav"><a href="/">대시보드</a><button disabled={busy} onClick={onLogout}>로그아웃</button></div>
    <form className="login-form" onSubmit={async e=>{e.preventDefault();if(await action('/api/admin/accounts',{employee_id:id,email})){setId('');setEmail('');}}}>
      <label className="login-field">사원번호<input value={id} onChange={e=>setId(e.target.value)} required pattern="[A-Za-z0-9_-]+" maxLength={32}/></label><label className="login-field">이메일<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required/></label><button className="login-submit" disabled={busy}>{busy?'처리 중…':'계정 생성 및 이메일 발송'}</button>
    </form><p className="login-message" role="status">{message}</p>
    <div className="account-table"><table><thead><tr><th>사원번호</th><th>이메일</th><th>상태</th><th>관리</th></tr></thead><tbody>{rows.map(row=><tr key={row.employee_id}><td>{row.employee_id}{row.role==='system'?' (시스템팀)':''}</td><td>{row.email}</td><td>{labels[row.status]}</td><td>{row.status==='pending'&&<button disabled={busy} onClick={()=>action(`/api/admin/accounts/${encodeURIComponent(row.employee_id)}/resend`,{})}>재전송</button>}{row.role==='admin'&&row.status!=='disabled'&&<button disabled={busy} onClick={()=>{setSelected(row.employee_id);setReason('');}}>삭제</button>}</td></tr>)}</tbody></table>{rows.length===0&&<p>등록된 계정이 없습니다.</p>}</div>
    {selected&&<form className="login-form" onSubmit={async e=>{e.preventDefault();if(await action(`/api/admin/accounts/${encodeURIComponent(selected)}/disable`,{reason}))setSelected(null);}}><p>{selected} 계정을 비활성화하고 로그인 세션을 종료합니다.</p><label className="login-field">삭제 사유<input value={reason} onChange={e=>setReason(e.target.value)} required maxLength={500}/></label><button disabled={busy||!reason.trim()} className="login-submit">최종 삭제</button><button type="button" disabled={busy} onClick={()=>setSelected(null)}>취소</button></form>}
  </section></div>;
}
