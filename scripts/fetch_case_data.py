"""Download the exact public case resources recorded in the committed manifest.

Existing OCR corpus records are preserved. Full raw datasets remain in .local.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import urllib.request,json,hashlib,io
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/case-resources.json').read_text())

def bank(resource):
    ident=resource['id'];out=ROOT/'data/bank'/f'{ident}.json'
    if out.exists() and len(json.loads(out.read_text()).get('text','').strip())>200:
        print('Retained prepared OCR corpus:',resource['title'],flush=True);return
    data=urllib.request.urlopen(f'https://drive.google.com/uc?export=download&id={ident}',timeout=60).read()
    digest=hashlib.sha256(data).hexdigest()
    if resource.get('sha256') and resource['sha256']!=digest:raise ValueError('Source checksum changed: '+ident)
    raw=ROOT/'.local/bank-pdfs';raw.mkdir(parents=True,exist_ok=True);(raw/f'{ident}.pdf').write_bytes(data)
    reader=PdfReader(io.BytesIO(data));pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
    out.write_text(json.dumps({**resource,'pages':len(reader.pages),'pages_content':pages,'text':'\n\n'.join(f'[Page {p["page"]}]\n{p["text"]}' for p in pages),'sha256':digest},ensure_ascii=False,indent=2))
    print('Downloaded:',resource['title'],'(run OCR helper if text is missing)',flush=True)

def dataset(resource):
    out=ROOT/'.local/case-data'/f'{resource["id"]}.csv';out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists() and out.stat().st_size>0:print('Retained local dataset:',resource['name'],flush=True);return
    out.write_bytes(urllib.request.urlopen(f'https://drive.google.com/uc?export=download&id={resource["id"]}',timeout=90).read())
    print('Downloaded local dataset:',resource['name'],flush=True)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as p:list(p.map(bank,manifest['bank']))
    with ThreadPoolExecutor(max_workers=3) as p:list(p.map(dataset,manifest['datasets']))
