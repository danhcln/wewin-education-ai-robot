from fastapi import APIRouter, HTTPException, Request, Response
from .security import is_valid_admin_token
from .browser_sessions import COOKIE, get_store, same_origin, set_cookie

router=APIRouter(prefix='/api/browser')

@router.post('/login')
def login(request:Request,response:Response):
    same_origin(request)
    scheme,_,token=request.headers.get('authorization','').partition(' ')
    if scheme.lower()!='bearer' or not is_valid_admin_token(token):raise HTTPException(401,'Invalid admin credential.')
    store=get_store();value=store.create(request.cookies.get(COOKIE));set_cookie(response,request,value)
    return {'authenticated':True,'role':'admin','csrf':store.csrf(value),'expires_in':604800}

@router.get('/session')
def session(request:Request):
    store=get_store();owner=store.authorize(request)
    return {'authenticated':True,'role':'admin','owner':owner,'csrf':store.csrf(request.cookies[COOKIE])}

@router.post('/renew')
def renew(request:Request,response:Response):
    store=get_store();store.authorize(request,True);token=request.cookies[COOKIE]
    expires=store.renew(token);set_cookie(response,request,token,max_age=max(0,int(expires-store.clock())))
    return {'authenticated':True,'role':'admin','csrf':store.csrf(token)}

@router.post('/logout')
def logout(request:Request,response:Response):
    store=get_store();store.authorize(request,True);store.revoke(request.cookies[COOKIE]);response.delete_cookie(COOKIE,path='/')
    return {'status':'ok'}
