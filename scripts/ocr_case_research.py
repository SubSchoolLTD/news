"""Prepare page-indexed OCR for the supplied scanned research; optional offline tool."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,urllib.request,subprocess
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'data/case-resources.json').read_text())
raw=ROOT/'.local/bank-pdfs';raw.mkdir(parents=True,exist_ok=True)

def process(resource):
    ident=resource['id'];path=ROOT/'data/bank'/f'{ident}.json';doc=json.loads(path.read_text()) if path.exists() else resource.copy();pdf=raw/f'{ident}.pdf'
    if not pdf.exists():pdf.write_bytes(urllib.request.urlopen(f'https://drive.google.com/uc?export=download&id={ident}',timeout=90).read())
    reader=PdfReader(pdf);pages=[]
    for i,page in enumerate(reader.pages):
        text=page.extract_text() or ''
        if len(text.strip())<100:
            images=list(page.images)
            if images:
                image=max(images,key=lambda x:x.image.width*x.image.height).image
                png=raw/f'{ident}-{i+1}.png';image.save(png)
                args=['tesseract',str(png),'stdout','-l','rus+eng','--psm','3']
                if (ROOT/'.local/tessdata/rus.traineddata').exists():args.extend(['--tessdata-dir',str(ROOT/'.local/tessdata')])
                result=subprocess.run(args,capture_output=True,text=True,timeout=90,check=True);text=result.stdout
        pages.append({'page':i+1,'text':text.strip()})
    doc.update(**resource,ocr=True,pages=len(reader.pages),pages_content=pages,text='\n\n'.join(f'[Page {p["page"]}]\n{p["text"]}' for p in pages))
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2));print(resource['title'],len(doc['text']),flush=True)

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(process,manifest['bank']))
