"""Explicit network-enabled setup. No user data are accepted by this command."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT_REVISION = '7ffa9a043d54d1be65afb281eddf0ffbe629385b'
SOURCE_REVISION = 'f7f00ca7fb869683eb732c010299d901457f19c3'


def main():
    cache = ROOT / 'artifacts/privacy/cache'
    os.environ['TIKTOKEN_CACHE_DIR'] = str(cache / 'tiktoken')
    from huggingface_hub import snapshot_download
    import tiktoken
    target = ROOT / 'artifacts/privacy/checkpoint'
    snapshot_download('openai/privacy-filter', revision=CHECKPOINT_REVISION,
                      allow_patterns=['original/*'], local_dir=target, cache_dir=cache / 'huggingface')
    tiktoken.get_encoding('o200k_base')
    tokenizer_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in (cache/'tiktoken').iterdir() if p.is_file()}
    files = {}
    for p in sorted((target/'original').glob('*')):
        if p.is_file():
            h = hashlib.sha256()
            with p.open('rb') as handle:
                for block in iter(lambda: handle.read(8*1024*1024), b''):
                    h.update(block)
            files[p.name] = h.hexdigest()
    (target/'manifest.json').write_text(json.dumps(dict(source_revision=SOURCE_REVISION,
        checkpoint_revision=CHECKPOINT_REVISION, files=files,tokenizer_files=tokenizer_files),indent=2)+'\n')
    print('Local privacy checkpoint and tokenizer installed.')


if __name__ == '__main__':
    main()
