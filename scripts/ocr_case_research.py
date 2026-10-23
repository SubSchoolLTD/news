from pathlib import Path
import json,re,urllib.request,subprocess
from concurrent.futures import ThreadPoolExecutor
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
raw=ROOT/'.local'/'bank-pdfs';raw.mkdir(exist_ok=True,parents=True)
html=Path('/tmp/alfa-bank-drive.html').read_text()
from bs4 import BeautifulSoup
soup=BeautifulSoup(html,'html.parser')
names={}
for node in soup.select('[data-id]'):
 label=node.get('aria-label','')
 if '.pdf' in label:names[node['data-id']]=label.split('.pdf')[0]+'.pdf'
dates={
 '1yLCBrIoyIsubLTEBvBHh6io48ysnW-wn':'2021-04-15',
 '1HZDq3WGRFdzgm1TZ5hWL23Q3I9c2Eq64':'2026-09-01',
 '1riR1lhsb6EY1MwGMxdBlS_tI5ed9mIiz':'2026-09-01',
 '1shHG89LtMgHT1_uEebHmQSFZe_zbeq7-':'2026-09-11',
 '1khcHwoS0FkG9p_0J4XoHGaGq3B4V0ime':'2026-08-01',
 '1hq3Fhyz9ce_sRyGUQB1MdoHeQdfAJfhK':'2026-07-22',
 '1a7TXOCHARfKzUR0hn9Cm9gQSrIldxTDE':'2026-08-31',
 '19iW3Ph8_wO0HHQY7Ik4lTfC3jRc9gjWV':'2026-09-02',
 '1bPzix_332N2CyMY0tqCHuYtGsfJWnFGv':'2026-09-14'}
def process(path):
 doc=json.loads(path.read_text());ident=doc['id'];p=raw/f'{ident}.pdf'
 if not p.exists():p.write_bytes(urllib.request.urlopen(f'https://drive.google.com/uc?export=download&id={ident}',timeout=70).read())
 reader=PdfReader(p);pages=[]
 for i,page in enumerate(reader.pages):
  text=page.extract_text() or ''
  if len(text.strip())<100:
   images=list(page.images)
   if images:
    im=max(images,key=lambda x:x.image.width*x.image.height).image
    png=raw/f'{ident}-{i+1}.png';im.save(png)
    r=subprocess.run(['tesseract',str(png),'stdout','--tessdata-dir',str(ROOT/'.local/tessdata'),'-l','rus+eng','--psm','3'],capture_output=True,text=True,timeout=90)
    text=r.stdout
  pages.append({'page':i+1,'text':text.strip()})
 doc.update(title=names.get(ident,doc['title']),published_at=dates.get(ident),date_precision='document_or_reporting_period',ocr=True,pages_content=pages,text='\n\n'.join(f'[Page {p["page"]}]\n{p["text"]}' for p in pages))
 path.write_text(json.dumps(doc,ensure_ascii=False,indent=2));print(doc['title'],len(doc['text']),flush=True)
with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(process,sorted((ROOT/'data/bank').glob('*.json'))))
