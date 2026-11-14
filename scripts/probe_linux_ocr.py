from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from regnav.core.extract import extract
root = Path(__file__).resolve().parents[1]
doc = '10v_yQPOkUAmu0d5-_zuzRQZxm8AdPH0l'
result = extract(root / 'data/official/raw' / (doc + '.pdf'))
Path('/out/datacenter-linux.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print('\n'.join(b['text'] for b in result['blocks'] if b.get('page') == 2), flush=True)
