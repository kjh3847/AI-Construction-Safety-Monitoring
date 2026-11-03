"""System-team desktop app; run using the project's .venv-accounts Python."""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from api_client import AccountClient


class AccountApp:
    def __init__(self, window):
        self.window = window
        self.client = None
        self.user = None
        self.busy = False
        self.results = queue.Queue()
        window.title('현장지킴 · 관리자 계정 발급')
        window.geometry('1000x760')
        self.frame = ttk.Frame(window, padding=24)
        self.frame.pack(fill='both', expand=True)
        self.status = tk.StringVar()
        self.show_login()
        window.after(100, self.poll)

    def clear(self, title):
        for child in self.frame.winfo_children():
            child.destroy()
        ttk.Label(self.frame, text=title, font=('맑은 고딕', 18)).pack(pady=12)

    def field(self, label, default='', secret=False):
        ttk.Label(self.frame, text=label).pack(anchor='w', pady=(8, 2))
        entry = ttk.Entry(self.frame, show='*' if secret else '', width=65)
        entry.insert(0, default)
        entry.pack(fill='x')
        return entry

    def footer(self):
        ttk.Label(self.frame, textvariable=self.status, wraplength=900).pack(pady=12)

    def run(self, work, success):
        if self.busy:
            return
        self.busy = True
        self.status.set('처리 중… 잠시 기다려주세요.')
        def task():
            try:
                self.results.put((success, work(), None))
            except Exception as error:
                self.results.put((success, None, str(error)))
        threading.Thread(target=task, daemon=True).start()

    def poll(self):
        try:
            callback, result, error = self.results.get_nowait()
            self.busy = False
            if error:
                self.status.set(error)
            else:
                self.status.set('')
                callback(result)
        except queue.Empty:
            pass
        self.window.after(100, self.poll)

    def show_login(self):
        self.clear('시스템팀 로그인')
        self.server = self.field('API 서버 주소', os.getenv('ACCOUNTS_API_URL', 'https://safety-capstone-2026.duckdns.org'))
        self.origin = self.field('서비스 웹 주소 (서버 PUBLIC_APP_URL과 동일)', os.getenv('PUBLIC_APP_URL', 'http://localhost:5173'))
        self.employee = self.field('시스템팀 사원번호')
        self.password = self.field('비밀번호', secret=True)
        ttk.Button(self.frame, text='로그인', command=self.login).pack(pady=16)
        ttk.Label(self.frame, text='RDS 마스터 계정이 아닌 시스템팀 계정으로 로그인합니다.').pack()
        self.footer()

    def login(self):
        if self.busy:
            return
        server, origin = self.server.get().strip(), self.origin.get().strip()
        employee, password = self.employee.get().strip(), self.password.get()
        if not employee or not password:
            self.status.set('사원번호와 비밀번호를 입력하세요.')
            return
        def work():
            if self.client:
                self.client.close()
            self.client = AccountClient(server, origin)
            return self.client.login(employee, password)
        def success(user):
            self.password.delete(0, 'end')
            self.user = user
            self.show_password() if user['must_change_password'] else self.show_accounts()
        self.run(work, success)

    def show_password(self):
        self.clear('비밀번호 변경')
        current = self.field('현재 비밀번호', secret=True)
        new = self.field('새 비밀번호 (11자리 이상, 영문 대소문자·숫자·특수문자)', secret=True)
        confirm = self.field('새 비밀번호 확인', secret=True)
        def submit():
            payload = {'current_password': current.get(), 'new_password': new.get(), 'confirm_password': confirm.get()}
            def done(data):
                self.user = None
                self.show_login()
                self.status.set(data['message'])
            self.run(lambda: self.client.request('POST', '/api/auth/password', json=payload), done)
        ttk.Button(self.frame, text='비밀번호 변경', command=submit).pack(pady=12)
        self.footer()

    def show_accounts(self):
        self.clear('관리자 계정 발급')
        ttk.Label(self.frame, text=f"담당자: {self.user['employee_id']}").pack()
        self.new_employee = self.field('발급할 사원번호')
        self.email = self.field('발급 안내를 받을 이메일')
        ttk.Button(self.frame, text='계정 생성 및 이메일 발송', command=self.create).pack(pady=10)
        self.tree = ttk.Treeview(self.frame, columns=('id', 'email', 'status'), show='headings', height=12)
        for key, title in [('id','사원번호'), ('email','이메일'), ('status','상태')]:
            self.tree.heading(key, text=title)
        self.tree.pack(fill='both', expand=True)
        buttons = ttk.Frame(self.frame)
        buttons.pack(pady=8)
        for title, command in [('목록 새로고침', self.refresh), ('선택 계정 재전송', self.resend),
                               ('계정 비활성화', lambda: self.manage_account('disable')),
                               ('계정 영구 삭제', lambda: self.manage_account('delete')),
                               ('비밀번호 변경', lambda: None if self.busy else self.show_password()),
                               ('로그아웃', self.logout)]:
            ttk.Button(buttons, text=title, command=command).pack(side='left', padx=5)
        self.footer()
        self.refresh()

    def refresh(self, preserve_message=False):
        previous = self.status.get() if preserve_message else ''
        def done(data):
            self.accounts = {row['employee_id']: row for row in data['accounts']}
            self.tree.delete(*self.tree.get_children())
            for row in data['accounts']:
                self.tree.insert('', 'end', iid=row['employee_id'], values=(row['employee_id'], row['email'],
                    {'pending':'발급 대기', 'active':'활성', 'disabled':'비활성'}[row['status']]))
            self.status.set(previous)
        self.run(lambda: self.client.request('GET', '/api/admin/accounts'), done)

    def create(self):
        payload = {'employee_id': self.new_employee.get().strip(), 'email': self.email.get().strip()}
        if not all(payload.values()):
            self.status.set('사원번호와 이메일을 입력하세요.')
            return
        def done(data):
            self.new_employee.delete(0, 'end')
            self.email.delete(0, 'end')
            self.status.set(data['message'])
            self.refresh(preserve_message=True)
        self.run(lambda: self.client.request('POST', '/api/admin/accounts', json=payload), done)

    def resend(self):
        selection = self.tree.selection()
        if not selection:
            self.status.set('목록에서 발급 대기 계정을 선택하세요.')
            return
        from urllib.parse import quote
        def done(data):
            self.status.set(data['message'])
            self.refresh(preserve_message=True)
        self.run(lambda: self.client.request('POST', f'/api/admin/accounts/{quote(selection[0], safe="")}/resend'), done)

    def logout(self):
        def done(data):
            self.user = None
            self.show_login()
            self.status.set(data['message'])
        self.run(lambda: self.client.request('POST', '/api/auth/logout'), done)

    def manage_account(self, action):
        if self.busy:
            return
        selection = self.tree.selection()
        if not selection:
            self.status.set('목록에서 처리할 계정을 선택하세요.')
            return
        employee_id = selection[0]
        row = self.accounts[employee_id]
        if row['role'] == 'system':
            self.status.set('시스템팀 계정은 비활성화·삭제할 수 없습니다.')
            return
        if action == 'delete' and row['status'] != 'disabled':
            self.status.set('영구 삭제 전 먼저 계정을 비활성화하세요.')
            return
        if action == 'disable' and row['status'] == 'disabled':
            self.status.set('이미 비활성화된 계정입니다.')
            return
        title = '계정 비활성화' if action == 'disable' else '계정 영구 삭제'
        reason = simpledialog.askstring(title, f'{employee_id} 처리 사유를 입력하세요. (필수, 500자 이내)', parent=self.window)
        if reason is None:
            return
        if not reason.strip() or len(reason) > 500:
            self.status.set('사유는 공백을 제외한 내용이 있어야 하며 500자 이내여야 합니다.')
            return
        detail = '로그인이 차단되고 기존 로그인 세션이 모두 종료됩니다.' if action == 'disable' else '계정 정보가 DB에서 삭제되며 복구할 수 없습니다. 처리 이력은 보존됩니다.'
        if not messagebox.askyesno(title, f'{employee_id}\n{detail}\n\n계속하시겠습니까?', parent=self.window):
            return
        from urllib.parse import quote
        def done(data):
            self.status.set(data['message'])
            self.refresh(preserve_message=True)
        self.run(lambda: self.client.request('POST', f'/api/admin/accounts/{quote(employee_id, safe="")}/{action}', json={'reason':reason.strip()}), done)


if __name__ == '__main__':
    import sys
    window = tk.Tk()
    if '--smoke-test' in sys.argv:
        window.withdraw()
    AccountApp(window)
    if '--smoke-test' in sys.argv:
        client = AccountClient('http://127.0.0.1:8000', 'http://localhost:5173')
        client.close()
        window.update_idletasks()
        window.destroy()
    else:
        window.mainloop()
