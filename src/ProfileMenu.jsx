import React, {useEffect, useRef, useState} from 'react';
import {LogOut} from 'lucide-react';

export default function ProfileMenu({onLogout, user}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const container = useRef(null);
  const trigger = useRef(null);
  const logoutButton = useRef(null);
  const dialog = useRef(null);
  const cancel = useRef(null);

  useEffect(() => {
    if (!open) return;
    logoutButton.current?.focus();
    const outside = event => {
      if (!container.current?.contains(event.target)) setOpen(false);
    };
    const escape = event => {
      if (event.key === 'Escape') {setOpen(false); trigger.current?.focus();}
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  function confirm() {
    setOpen(false);
    setError('');
    dialog.current.showModal();
    cancel.current?.focus();
  }
  function close() {
    if (busy) return;
    dialog.current.close();
    trigger.current?.focus();
  }
  async function logout() {
    if (busy) return;
    setBusy(true); setError('');
    try {
      if (await onLogout() === false) {
        setError('로그아웃하지 못했습니다. 서버 연결을 확인하고 다시 시도하세요.');
      }
    } catch (error) {setError(error.message);}
    finally {setBusy(false);}
  }

  return <div className="profile-menu" ref={container}>
    <button type="button" className="avatar profile-trigger" ref={trigger}
      aria-label="관리자 프로필" aria-expanded={open} aria-controls="profile-actions"
      title={user?.employee_id ? `${user.employee_id} · 프로필` : '프로필'}
      onClick={() => setOpen(value => !value)}>관</button>
    {open && <div className="profile-actions" id="profile-actions">
      <button type="button" className="profile-logout" ref={logoutButton} onClick={confirm}>
        <LogOut size={16}/> 로그아웃
      </button>
    </div>}
    <dialog ref={dialog} className="logout-dialog" aria-labelledby="logout-title"
      aria-describedby="logout-description" aria-busy={busy}
      onCancel={event => {event.preventDefault();close();}}>
      <div className="logout-symbol"><LogOut size={25}/></div>
      <h2 id="logout-title">로그아웃 하시겠습니까?</h2>
      <p id="logout-description">로그아웃하면 로그인 화면으로 이동합니다.</p>
      {error && <p className="logout-error" role="alert">{error}</p>}
      <div className="logout-dialog-actions">
        <button type="button" className="logout-cancel" ref={cancel} disabled={busy} onClick={close}>아니오</button>
        <button type="button" className="logout-confirm" disabled={busy} onClick={logout}>{busy ? '로그아웃 중…' : '예'}</button>
      </div>
    </dialog>
  </div>;
}
