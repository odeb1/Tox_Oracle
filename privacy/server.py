"""Standalone loopback gateway. No provider clients or remote inference paths."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
from pathlib import Path
import secrets
import time
import threading
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from privacy.engine import LocalDetector, PrivacyError, scan, toxicity_request

STATIC = Path(__file__).parent/'static'
TTL = 1800
ORIGIN = 'http://127.0.0.1:8765'


def create_app(detector=None, token=None, clock=time.monotonic, *, origin=ORIGIN, static_dir=STATIC):
    # Trusted factory configuration only. No public bind, DNS name or browser override.
    parsed=urlsplit(origin)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username is not None or parsed.password is not None:
        raise ValueError('loopback_origin_required')
    static_dir=Path(static_dir)
    detector = detector or LocalDetector()
    token = token or secrets.token_urlsafe(32)
    sessions = {}
    mutex = threading.Lock()

    def expire():
        with mutex:
            for sid in list(sessions):
                if clock()-sessions[sid]['last']>TTL:
                    del sessions[sid]

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(30)
                expire()
        task=asyncio.create_task(cleanup())
        yield
        task.cancel(); sessions.clear()

    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.launch_token=token

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if request.headers.get('host')!=parsed.netloc:
            return JSONResponse({'error':'invalid_host'},status_code=403)
        request_origin=request.headers.get('origin')
        if request_origin and request_origin!=origin:
            return JSONResponse({'error':'invalid_origin'},status_code=403)
        if request.url.path.startswith('/api/'):
            if not hmac.compare_digest(request.headers.get('x-session-token',''),token):
                return JSONResponse({'error':'invalid_session_token'},status_code=403)
            if request_origin!=origin:
                return JSONResponse({'error':'origin_required'},status_code=403)
        # Stream-limit the entire body before parsing (including chunked requests).
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2_000_000:
                return JSONResponse({'error':'request_too_large'},status_code=413)
        request._body=bytes(body)
        try:
            response=await call_next(request)
        except Exception:
            response=JSONResponse({'error':'local_request_failed'},status_code=500)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; connect-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})
        return response

    @app.exception_handler(PrivacyError)
    async def privacy_error(request, exc):
        return JSONResponse({'error':str(exc)},status_code=400)

    @app.get('/')
    async def index():
        return HTMLResponse((static_dir/'index.html').read_text().replace('__LAUNCH_TOKEN__',token))

    app.mount('/static',StaticFiles(directory=static_dir),name='static')

    async def payload(request):
        try:
            result=await request.json()
            if not isinstance(result,dict):
                raise ValueError()
            return result
        except Exception:
            raise PrivacyError('invalid_request') from None

    def session(data):
        expire()
        sid=data.get('session_id')
        if not isinstance(sid,str) or sid not in sessions:
            raise PrivacyError('session_expired')
        state=sessions[sid]; state['last']=clock()
        return state

    @app.post('/api/session')
    async def new_session():
        expire()
        if len(sessions)>=32:
            raise PrivacyError('too_many_sessions')
        sid=secrets.token_urlsafe(32)
        sessions[sid]=dict(last=clock(),version=0,snapshot=None,approved=None)
        return {'session_id':sid}

    @app.post('/api/invalidate')
    async def invalidate(request:Request):
        state=session(await payload(request))
        state.update(version=state['version']+1,snapshot=None,approved=None)
        return {'status':'cleared'}

    @app.post('/api/reset')
    async def reset(request:Request):
        data=await payload(request)
        session(data)
        del sessions[data['session_id']]
        return {'status':'cleared'}

    @app.post('/api/scan')
    async def scan_input(request:Request):
        return await scan_payload(await payload(request))

    async def scan_payload(data):
        state=session(data)
        state.update(version=state['version']+1,snapshot=None,approved=None)
        version=state['version']
        if data.get('enabled') is not True:
            raise PrivacyError('preview_only_export_disabled')
        result=await run_in_threadpool(scan,data.get('content'),data.get('format'),detector)
        if state['version']!=version or sessions.get(data['session_id']) is not state or clock()-state['last']>TTL:
            raise PrivacyError('scan_invalidated')
        result['scan_id']=secrets.token_urlsafe(24)
        state['snapshot']=result; state['last']=clock()
        return result

    def reviewed(data, require_approval=True):
        state=session(data); snapshot=state['snapshot']
        if snapshot is None or snapshot['blocked']:
            raise PrivacyError('review_required')
        if data.get('scan_id')!=snapshot['scan_id']:
            raise PrivacyError('stale_scan')
        if require_approval and state['approved']!=snapshot['scan_id']:
            raise PrivacyError('approval_required')
        return state,snapshot

    @app.post('/api/approve')
    async def approve(request:Request):
        data=await payload(request)
        if data.get('approve') is not True:
            raise PrivacyError('approval_required')
        state,snapshot=reviewed(data,False)
        required={f['field_id'] for f in snapshot['review_fields']}
        supplied=data.get('retain_fields',[])
        if not isinstance(supplied,list) or any(not isinstance(v,str) for v in supplied) or set(supplied)!=required:
            raise PrivacyError('scientific_field_review_required')
        snapshot['audit']['reviewed_scientific_fields_retained']=len(required)
        state['approved']=snapshot['scan_id']
        return {'approved':True,'audit':dict(snapshot['audit'],decision='approved')}

    @app.post('/api/export')
    async def export(request:Request):
        data=await payload(request); _,snapshot=reviewed(data)
        kind=data.get('kind','sanitized')
        if kind=='sanitized':
            return {'content':snapshot['sanitized'],'format':snapshot['format'],
                    'audit':dict(snapshot['audit'],decision='approved')}
        if kind=='toxicity':
            return toxicity_request(snapshot)
        raise PrivacyError('invalid_export_kind')

    @app.post('/api/predict')
    async def predict_local(request:Request):
        data=await payload(request); state,snapshot=reviewed(data)
        from toxicity.src.baseline import predict
        try:
            result=await run_in_threadpool(predict,toxicity_request(snapshot))
        except PrivacyError:
            raise
        except Exception:
            raise PrivacyError('local_prediction_failed') from None
        if state['snapshot'] is not snapshot or state['approved']!=snapshot['scan_id']:
            raise PrivacyError('prediction_invalidated')
        return result

    # Trusted in-process extensions use the same session and approval boundary.
    # These capabilities are never exposed to JavaScript or through generic RPC.
    app.state.privacy_payload=payload
    app.state.privacy_session=session
    app.state.privacy_reviewed=reviewed
    app.state.privacy_scan=scan_payload
    return app


def main():
    import uvicorn
    print('Open http://127.0.0.1:8765 — local privacy gateway. No external agents are connected.')
    uvicorn.run(create_app(),host='127.0.0.1',port=8765,access_log=False,log_level='critical')


if __name__=='__main__':
    main()
