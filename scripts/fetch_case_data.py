"""Fetch the public resources linked by the supplied case; keep raw client CSVs local."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import urllib.request, json, re, hashlib, io
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
def fetch_group(group, folder):
 html=urllib.request.urlopen(f'https://drive.google.com/drive/folders/{folder}',timeout=30).read().decode()
 ids=list(dict.fromkeys(re.findall(r'data-id="([a-zA-Z0-9_-]{20,})"',html)))
 def get(ident):
  url=f'https://drive.google.com/uc?export=download&id={ident}'
  data=urllib.request.urlopen(url,timeout=60).read()
  if group=='bank':
   reader=PdfReader(io.BytesIO(data))
   text='\n\n'.join(f'[Page {i+1}]\n{p.extract_text() or ""}' for i,p in enumerate(reader.pages))
   out=ROOT/'data'/'bank'/f'{ident}.json'
   out.write_text(json.dumps({'id':ident,'url':f'https://drive.google.com/file/d/{ident}/view','title':reader.metadata.title or text[:180].replace('\n',' '),'pages':len(reader.pages),'text':text,'sha256':hashlib.sha256(data).hexdigest()},ensure_ascii=False,indent=2))
   print('bank',ident,len(text),len(reader.pages))
  else:
   out=ROOT/'.local'/'case-data'/f'{ident}.csv'
   out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
   print('dataset',ident,len(data),data[:180].decode('utf-8-sig',errors='replace'))
 with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(get,ids))
if __name__=='__main__':
 fetch_group('bank','15xZTLF1lZ65p6o5xpNA_fRbxjoV-UlG1')
 fetch_group('datasets','1Ep8wWoEHTg5Q8kwrLx2j_xFyxGUEVxFq')
