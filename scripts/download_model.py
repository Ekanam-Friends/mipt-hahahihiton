"""Fetch pinned local GGUF weights; verify the digest before atomic replacement."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

MODEL = Path(__file__).resolve().parents[1] / 'models/qwen3-4b-instruct-2507-q4_k_m.gguf'
URL = 'https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/ae44f08e1392f39c0e474af10c3ff8355c8b6688/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf?download=true'
DIGEST = '2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


if __name__ == '__main__':
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL.exists() or digest(MODEL) != DIGEST:
        temp = MODEL.with_suffix('.gguf.part')
        with urlopen(URL, timeout=120) as response, temp.open('wb') as output:
            for block in iter(lambda: response.read(1024 * 1024), b''):
                output.write(block)
        if digest(temp) != DIGEST:
            raise ValueError('Model SHA-256 mismatch; partial download was not activated')
        temp.chmod(0o644)
        temp.replace(MODEL)
    print('Model SHA-256 verified:', DIGEST)
