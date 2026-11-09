"""Offline export using a trusted Torchreid checkout and locally supplied trained weights."""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--weights',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--source',help='Trusted upstream torchreid/models/osnet.py; avoids training-only dependencies')
    parser.add_argument('--model',default='osnet_x0_25',choices=['osnet_x0_25','osnet_x1_0'])
    args=parser.parse_args()
    import torch
    if args.source:
        import importlib.util
        spec=importlib.util.spec_from_file_location('upstream_osnet',args.source)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        model=getattr(module,args.model)(num_classes=1000,pretrained=False)
    else:
        import torchreid
        model=torchreid.models.build_model(args.model,num_classes=1000,pretrained=False,use_gpu=False)
    checkpoint=torch.load(args.weights,map_location='cpu',weights_only=True)
    checkpoint=checkpoint.get('state_dict',checkpoint)
    state={key.removeprefix('module.'):value for key,value in checkpoint.items()}
    expected=model.state_dict()
    trunk={key:value for key,value in state.items() if not key.startswith('classifier.')}
    missing=[key for key in expected if not key.startswith('classifier.') and key not in trunk]
    mismatch=[key for key in trunk if key not in expected or trunk[key].shape!=expected[key].shape]
    if missing or mismatch:
        raise ValueError('Checkpoint is not a complete trained checkpoint for the selected OSNet variant')
    model.load_state_dict(trunk,strict=False)
    model.eval()
    output=Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    pending=output.with_suffix('.pending.onnx')
    torch.onnx.export(model,torch.zeros(1,3,256,128),str(pending),input_names=['images'],
        output_names=['embeddings'],opset_version=17,dynamic_axes={'images':{0:'batch'},'embeddings':{0:'batch'}},dynamo=False)
    import numpy as np
    import onnxruntime as ort
    options=ort.SessionOptions();options.intra_op_num_threads=1
    session=ort.InferenceSession(str(pending),sess_options=options,providers=['CPUExecutionProvider'])
    samples=[np.zeros((1,3,256,128),np.float32),np.random.default_rng(42).normal(size=(1,3,256,128)).astype(np.float32)]
    for sample in samples:
        with torch.inference_mode(): expected=model(torch.from_numpy(sample)).numpy()
        actual=session.run(None,{'images':sample})[0]
        # Matching consumes unit vectors. Check that FP32 backend differences
        # preserve those vectors, including zero-valued ReLU channels.
        expected/=np.linalg.norm(expected,axis=1,keepdims=True)
        actual/=np.linalg.norm(actual,axis=1,keepdims=True)
        np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-4)
        if float((actual*expected).sum()) < .99999:
            raise AssertionError('ONNX and PyTorch embedding directions differ')
    del session
    pending.replace(output)
    print('Export validated against the supplied PyTorch checkpoint:',output.name)


if __name__=='__main__': main()
