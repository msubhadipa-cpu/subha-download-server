import asyncio, contextlib, hmac, json, os, re, secrets, shutil, tempfile, time, uuid
from pathlib import Path
from importlib.metadata import version
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(tempfile.gettempdir()) / 'subha-videos'
ROOT.mkdir(exist_ok=True)
JOBS = {}
SLOTS = asyncio.Semaphore(1)
KEY = os.environ.get('DOWNLOAD_API_KEY', '')
HOSTS = ('youtube.com','youtu.be','instagram.com','facebook.com','fb.watch','tiktok.com','twitter.com','x.com','vimeo.com','dailymotion.com','dai.ly')

async def cleanup():
    while True:
        await asyncio.sleep(60)
        for ident, job in list(JOBS.items()):
            if time.time() - job['created'] > 1800 and job['state'] not in ('queued','working'):
                JOBS.pop(ident, None)
                shutil.rmtree(ROOT / ident, ignore_errors=True)

@asynccontextmanager
async def lifespan(app):
    if len(KEY) < 24:
        raise RuntimeError('Set DOWNLOAD_API_KEY to a random secret of at least 24 characters')
    task = asyncio.create_task(cleanup())
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError): await task

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[os.getenv('SITE_ORIGIN','https://subha-video-save.msubhadipa.chatgpt.site')], allow_methods=['GET','POST'], allow_headers=['Authorization','Content-Type'], expose_headers=['Content-Disposition'])

def auth(authorization: str = Header(default='')):
    if not KEY or not hmac.compare_digest(authorization, 'Bearer ' + KEY):
        raise HTTPException(401, 'সার্ভারের অ্যাক্সেস কী সঠিক নয়।')

def validate_url(value):
    try:
        u = urlsplit(value)
        if u.scheme != 'https' or u.username or u.password or u.port not in (None,443): raise ValueError()
        if not any(u.hostname == h or u.hostname.endswith('.'+h) for h in HOSTS): raise ValueError()
        return value
    except (ValueError, AttributeError): raise HTTPException(400,'সমর্থিত প্ল্যাটফর্মের সঠিক HTTPS ভিডিও লিংক দাও।')

class VideoRequest(BaseModel):
    url: str

@app.get('/health')
def health(): return {'service':'subha-videosave','version':3,'engine_version':version('yt-dlp')}

async def download(ident, url):
    job = JOBS[ident]
    async with SLOTS:
        job['state'] = 'working'
        folder = ROOT / ident
        folder.mkdir()
        command = ['yt-dlp','--ignore-config','--js-runtimes','node','--no-playlist','--no-progress','--extractor-retries','1','--socket-timeout','20','--retries','1','--max-filesize','250M','--match-filters','!is_live & duration < 3600','-f','bv*[height<=1080]+ba/b[height<=1080]/b','--merge-output-format','mp4','--print','after_move:filepath','-o',str(folder/'video.%(ext)s'),'--',url]
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=240)
            if proc.returncode:
                safe_error = re.sub(r'https?://\S+', '[url]', err.decode(errors='replace'))[-6000:]
                print('Extractor detail:', safe_error, flush=True)
                details = safe_error.lower()
                if '429' in details: raise RuntimeError('platform_rate_limited')
                if 'confirm' in details and ('bot' in details or 'sign in' in details): raise RuntimeError('platform_bot_check')
                if '403' in details: raise RuntimeError('platform_access_denied')
                if 'logged-in' in details or 'login required' in details or 'provide account credentials' in details: raise RuntimeError('platform_login_required')
                if 'video unavailable' in details or 'has been removed' in details: raise RuntimeError('video_unavailable')
                raise RuntimeError('extractor_failed')
            files = [p for p in folder.iterdir() if p.suffix in ('.mp4','.webm','.mkv','.mov','.m4v') and p.is_file()]
            if len(files)!=1 or not 0 < files[0].stat().st_size <= 250*1024*1024: raise RuntimeError('no_file')
            job.update(state='ready',file=files[0].name,bytes=files[0].stat().st_size)
        except Exception as exc:
            print('Download job failed:', str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, flush=True)
            if proc and proc.returncode is None:
                proc.kill()
                await proc.communicate()
            reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            messages = {
                'platform_rate_limited': 'ভিডিও প্ল্যাটফর্ম এই সার্ভারের অনুরোধ সীমিত করেছে (429)। এখন ভিডিওটি আনা যাচ্ছে না। কিছু সময় পরে চেষ্টা করো।',
                'platform_access_denied': 'ভিডিও প্ল্যাটফর্ম এই সার্ভারের অনুরোধে অনুমতি দিচ্ছে না (403)। এই সার্ভার থেকে ভিডিওটি ডাউনলোড করা যাচ্ছে না।',
                'platform_bot_check': 'প্ল্যাটফর্ম সার্ভারের অনুরোধে যাচাই চাইছে। এখানে ওই ভিডিওটি ডাউনলোড করা যাচ্ছে না।',
                'video_unavailable': 'ভিডিওটি পাওয়া যাচ্ছে না। লিংকটি পাবলিক এবং এখনো চালু আছে কিনা যাচাই করো।',
                'platform_login_required': 'এই ভিডিও আনার জন্য প্ল্যাটফর্মে লগইন প্রয়োজন। এই সাইটে ব্যক্তিগত অ্যাকাউন্ট বা কুকি যুক্ত করা নেই, তাই ভিডিওটি ডাউনলোড করা যাচ্ছে না।',
                'TimeoutError': 'ভিডিও আনার সময় শেষ হয়েছে। ছোট ভিডিও দিয়ে আবার চেষ্টা করো।'
            }
            job.update(state='failed',code=reason,message=messages.get(reason,'ভিডিও আনা যায়নি। লিংকটি সমর্থিত ও পাবলিক কিনা যাচাই করো।'))
            shutil.rmtree(folder,ignore_errors=True)

@app.get('/auth', dependencies=[Depends(auth)])
def check_auth(): return {'ok':True}

@app.post('/jobs', dependencies=[Depends(auth)])
async def create_job(request: VideoRequest):
    url = validate_url(request.url)
    if sum(j['state'] in ('queued','working') for j in JOBS.values()) >= 4: raise HTTPException(429,'সার্ভার ব্যস্ত। কিছুক্ষণ পরে চেষ্টা করো।')
    ident = str(uuid.uuid4())
    JOBS[ident] = {'state':'queued','created':time.time()}
    asyncio.create_task(download(ident,url))
    return {'id':ident,'state':'queued'}

def get_job(ident):
    job = JOBS.get(ident)
    if not job: raise HTTPException(404,'ভিডিওর মেয়াদ শেষ হয়েছে। আবার লিংক দাও।')
    return job

@app.get('/jobs/{ident}', dependencies=[Depends(auth)])
def status(ident: str):
    job = get_job(ident)
    return {k:v for k,v in job.items() if k not in ('created','file')}

@app.get('/jobs/{ident}/file', dependencies=[Depends(auth)])
def file(ident: str):
    job = get_job(ident)
    if job['state'] != 'ready': raise HTTPException(409,'ভিডিও এখনো তৈরি হয়নি।')
    path = ROOT / ident / job['file']
    if not path.is_file(): raise HTTPException(404,'ভিডিওর মেয়াদ শেষ হয়েছে।')
    return FileResponse(path, filename='subha-video'+path.suffix, headers={'Cache-Control':'no-store'})
