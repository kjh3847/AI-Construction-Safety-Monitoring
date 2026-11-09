"""Issue isolated publish/read/control credentials to private files, never stdout."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import urlencode,urlsplit

ROOT=Path(__file__).resolve().parents[1]


def private_write(path,content):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:stream.write(content)
    if os.name=='nt':
        account=os.environ.get('USERDOMAIN','')+'\\'+os.environ['USERNAME']
        completed=subprocess.run(['icacls',str(path),'/inheritance:r','/grant:r',account+':F'],capture_output=True)
        if completed.returncode:raise RuntimeError('Could not restrict credential file permissions')


def issue(host,port,env_file,phone_file):
    if urlsplit('https://'+host).hostname!=host:raise ValueError('Provide a DNS hostname without protocol or path')
    values={}
    phones={}
    for number in range(1,4):
        user=f'cam{number:02}_publisher';password=secrets.token_urlsafe(32)
        values[f'CAMERA_{number:02}_PUBLISH_USER']=user
        values[f'CAMERA_{number:02}_PUBLISH_PASSWORD']=password
        query=urlencode({'user':user,'pass':password})
        phones[f'CAM-{number:02}']={'connection_url':f'rtmps://{host}:{port}/cam{number:02}?{query}',
            'username':user,'password':password,'larix_auth_fields':'leave blank; credentials are query parameters',
            'video':'H.264, 1280x720, 15 FPS, no B-frames, keyframe 1s',
            'prism_server':f'rtmps://{host}:{port}','prism_stream_key':f'cam{number:02}?{query}'}
    for role,user in [('AI','ai_reader'),('WEB','web_gateway'),('CONTROL','control')]:
        values[f'MEDIA_{role}_USER']=user;values[f'MEDIA_{role}_PASSWORD']=secrets.token_urlsafe(40)
    private_write(env_file,''.join(f'{key}={value}\n' for key,value in values.items()))
    private_write(phone_file,json.dumps(phones,ensure_ascii=False,indent=2))
    return values


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--port',type=int,default=1936)
    parser.add_argument('--env-file',default=str(ROOT/'.env.media'))
    parser.add_argument('--phone-file',default=str(ROOT/'.local-run/phone-live-connections.json'))
    args=parser.parse_args()
    if Path(args.env_file).exists() or Path(args.phone_file).exists():raise SystemExit('Credential output already exists; refusing to overwrite')
    issue(args.host,args.port,args.env_file,args.phone_file)
    print('Created private credential files. No credentials were printed. Keep both files out of Git.')


if __name__=='__main__':main()
