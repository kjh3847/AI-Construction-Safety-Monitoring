import React, {useState} from 'react';
import {ShieldCheck} from 'lucide-react';
import {accountRequest} from './api';
import './login.css';
export default function LoginPage({onLogin,user,onLogout}) {
  const [id,setId]=useState(''),[password,setPassword]=useState(''),[message,setMessage]=useState('');
  const [changing,setChanging]=useState(Boolean(user)),[next,setNext]=useState(''),[confirm,setConfirm]=useState(''),[busy,setBusy]=useState(false);
  async function submit(e){
    e.preventDefault();setBusy(true);setMessage('');
    try {
      if(changing){
        if(next!==confirm)throw new Error('새 비밀번호와 확인 입력이 일치하지 않습니다.');
        if(!user)await accountRequest('/api/auth/login',{method:'POST',body:JSON.stringify({employee_id:id,password})});
        const result=await accountRequest('/api/auth/password',{method:'POST',body:JSON.stringify({current_password:password,new_password:next,confirm_password:confirm})});
        setMessage(result.message);setChanging(false);setPassword('');setNext('');setConfirm('');onLogout?.();
      }else{
        const result=await accountRequest('/api/auth/login',{method:'POST',body:JSON.stringify({employee_id:id,password})});
        if(result.must_change_password)setChanging(true);
        onLogin(result);
      }
    }catch(error){setMessage(error.message);}finally{setBusy(false);}
  }
  return <div className="login-page"><section className="login-card">
    <div className="login-brand"><ShieldCheck size={36}/><span>현장지킴</span></div>
    <h1>{changing?'비밀번호 변경':'관리자 로그인'}</h1><p className="login-description">{user?.must_change_password?'처음 로그인했습니다. 임시 비밀번호를 변경하세요.':'회사에서 발급받은 사원번호로 로그인하세요.'}</p>
    <form className="login-form" onSubmit={submit}>
      {!user&&<label className="login-field">사원번호<input autoComplete="username" value={id} onChange={e=>setId(e.target.value)} required maxLength={32}/></label>}
      <label className="login-field">{changing?'현재 비밀번호':'비밀번호'}<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required maxLength={128}/></label>
      {changing&&<><label className="login-field">새 비밀번호<input type="password" autoComplete="new-password" value={next} onChange={e=>setNext(e.target.value)} required minLength={11} maxLength={128}/></label><label className="login-field">새 비밀번호 확인<input type="password" autoComplete="new-password" value={confirm} onChange={e=>setConfirm(e.target.value)} required minLength={11} maxLength={128}/></label><p className="login-help">11자리 이상, 영문 대소문자·숫자·특수문자 포함</p></>}
      <button className="login-submit" disabled={busy}>{busy?'처리 중…':changing?'비밀번호 변경':'로그인'}</button>{message&&<p className="login-message" role="status">{message}</p>}
    </form>
    {!user&&<button className="login-password-link" disabled={busy} onClick={()=>{setChanging(!changing);setMessage('');}}>{changing?'로그인으로 돌아가기':'비밀번호 변경'}</button>}
    {user&&<button className="login-password-link" disabled={busy} onClick={async()=>{try{await accountRequest('/api/auth/logout',{method:'POST'});onLogout();}catch(e){setMessage(e.message);}}}>로그아웃</button>}
    <p className="login-help">계정 문의는 시스템팀 담당자에게 연락하세요.</p>
  </section></div>;
}
