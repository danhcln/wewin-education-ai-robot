import asyncio
import json
import os
import sys
from .settings import ROOT


class MCPClient:
    def __init__(self,settings):
        self.settings=settings;self.process=None;self.sequence=0

    async def __aenter__(self):
        env={**os.environ,'PYTHONIOENCODING':'utf-8','WEWIN_AI_CONNECTOR_DB':str(self.settings.connector_db)}
        self.process=await asyncio.create_subprocess_exec(sys.executable,'-m','ai_server.mcp_server',cwd=ROOT,env=env,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:
            await self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'wewin-ai','version':'1'}})
            self.process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            await self.process.stdin.drain()
        except BaseException:
            # __aexit__ is not called when initialization is cancelled/fails.
            await self.__aexit__()
            raise
        return self

    async def request(self,method,params=None):
        self.sequence+=1
        data={'jsonrpc':'2.0','id':self.sequence,'method':method,'params':params or {}}
        self.process.stdin.write((json.dumps(data,ensure_ascii=False)+'\n').encode())
        await self.process.stdin.drain()
        line=await asyncio.wait_for(self.process.stdout.readline(),8)
        result=json.loads(line)
        if result.get('id')!=self.sequence or 'error' in result:raise RuntimeError('MCP request rejected or unavailable')
        return result['result']

    async def __aexit__(self,*args):
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
                try:await self.process.stdin.wait_closed()
                except (BrokenPipeError,ConnectionResetError):pass
            try:await asyncio.wait_for(self.process.wait(),2)
            except asyncio.TimeoutError:self.process.kill();await self.process.wait()
