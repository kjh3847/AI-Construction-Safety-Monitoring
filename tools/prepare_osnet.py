"""Download the author's trained MSMT17 OSNet x0.25 and official MIT source for offline export."""
import hashlib
import argparse
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
WEIGHTS='osnet_x0_25_msmt17_combineall_256x128_amsgrad_ep150_stp60_lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--variant',choices=['x0_25','x1_0'],default='x0_25')
    args=parser.parse_args()
    destination=ROOT/'models'
    destination.mkdir(exist_ok=True)
    with urllib.request.urlopen('https://api.github.com/repos/KaiyangZhou/deep-person-reid/commits/master',timeout=30) as response:
        commit=json.load(response)['sha']
    sources={
        'upstream_osnet.py':f'https://raw.githubusercontent.com/KaiyangZhou/deep-person-reid/{commit}/torchreid/models/osnet.py',
        'LICENSE.torchreid':f'https://raw.githubusercontent.com/KaiyangZhou/deep-person-reid/{commit}/LICENSE',
        f'osnet_{args.variant}_msmt17.pth':f'https://huggingface.co/kaiyangzhou/osnet/resolve/a5c5cc0/{WEIGHTS.replace("x0_25",args.variant)}',
    }
    manifest=json.loads((destination/'provenance.json').read_text('utf-8')) if (destination/'provenance.json').exists() else {}
    for name,url in sources.items():
        with urllib.request.urlopen(url,timeout=60) as response:
            data=response.read()
        (destination/name).write_bytes(data)
        manifest[name]={'url':url,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    (destination/'provenance.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Downloaded official OSNet {args.variant} source, MIT license and trained MSMT17 checkpoint to ignored models/.')
    print(f'Export with tools/export_osnet.py --source models/upstream_osnet.py --model osnet_{args.variant} --weights models/osnet_{args.variant}_msmt17.pth --output models/osnet_{args.variant}.onnx')


if __name__=='__main__': main()
