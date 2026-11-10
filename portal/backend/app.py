"""Isolated Education HTTP application. Run with python -m uvicorn backend.app:app."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from .db import ROOT, migrate
from .ai_migrations import migrate_ai
from . import auth, robots, learning, workspace, relationships, curriculum, roles, robot_workflow, self_hosted, managed_robots

@asynccontextmanager
async def lifespan(app):
    migrate()
    relationships.migrate_relationships()
    curriculum.migrate_curriculum()
    learning.seed_library()
    migrate_ai()
    self_hosted.migrate_self_hosted()
    managed_robots.migrate_managed()
    yield

app=FastAPI(title='WeWIN Education Portal',version='0.2.0',lifespan=lifespan)
for router in (auth.router,robots.router,learning.router,workspace.router,relationships.router,curriculum.router,roles.router,robot_workflow.router,self_hosted.router,managed_robots.router):
    app.include_router(router)

@app.middleware('http')
async def headers(request: Request,call_next):
    size=request.headers.get('content-length','0')
    if size.isdigit() and int(size)>9*1024*1024:
        return JSONResponse({'detail':'Yêu cầu vượt quá 9 MB'},status_code=413)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    return response

@app.get('/api/health')
def health():
    return {'status':'ok','service':'wewin-education','cloud_writes':False,'firmware_writes':False,'self_hosted_ai':'opt_in_staging'}

DIST=ROOT/'frontend/dist'

@app.get('/{path:path}',include_in_schema=False)
def static(path: str):
    target=(DIST/path).resolve()
    if path and target.is_file() and target.is_relative_to(DIST.resolve()):
        return FileResponse(target)
    if path.startswith('api/') or '.' in Path(path).name or not (DIST/'index.html').is_file():
        raise HTTPException(404)
    return FileResponse(DIST/'index.html')
