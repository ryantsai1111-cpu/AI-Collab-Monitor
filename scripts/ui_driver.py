"""Local standard MCP client for the bundled node_repl tool (no custom sky protocol)."""
import sys, json, subprocess, time, base64, pathlib, os
ROOT=pathlib.Path(__file__).resolve().parents[1]
STATE=ROOT/'evidence'/'ui-driver'
STATE.mkdir(parents=True,exist_ok=True)
REPL=r'C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\45309f9050f7314b\bin\node_repl.exe'
MODULES=str(pathlib.Path(REPL).parent/'node_modules')

def serve():
    os.environ["CODEX_CLI_PATH"]=r"C:\Users\ryant\AppData\Local\OpenAI\Codex\bin\8aaf1547b825b104\codex.exe"
    p=subprocess.Popen([REPL],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(STATE/'server-stderr.log').open('w'),text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    seq=0
    def rpc(method,params):
        nonlocal seq
        seq+=1
        p.stdin.write(json.dumps({'jsonrpc':'2.0','id':seq,'method':method,'params':params})+'\n');p.stdin.flush()
        while True:
            line=p.stdout.readline()
            if not line: raise RuntimeError('node_repl stopped')
            value=json.loads(line)
            if value.get('id')==seq:return value
    rpc('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'acw-ui-acceptance','version':'1'}})
    p.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');p.stdin.flush()
    rpc('tools/call',{'name':'js_add_node_module_dir','arguments':{'path':MODULES}})
    init=rpc('tools/call',{'name':'js','arguments':{'code':'if (!globalThis.sky) { const { sky } = await import("@oai/sky"); globalThis.sky = sky; } nodeRepl.write("Computer Use initialized");'}})
    (STATE/'ready.json').write_text(json.dumps(init),encoding='utf-8')
    while not (STATE/'stop').exists():
        for req in sorted(STATE.glob('*.request.json')):
            answer=req.with_name(req.name.replace('.request.json','.response.json'))
            if answer.exists():continue
            data=json.loads(req.read_text(encoding='utf-8-sig'))
            result=rpc('tools/call',{'name':'js','arguments':{'code':data['code'],'timeout_ms':45000,'title':data.get('title','Workspace UI acceptance')}})
            for i,content in enumerate(result.get('result',{}).get('content',[])):
                if content.get('type')=='image':
                    img=answer.with_suffix('.'+str(i)+'.png')
                    img.write_bytes(base64.b64decode(content.pop('data')))
                    content['saved_image']=str(img)
            answer.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        time.sleep(.15)
    p.stdin.close()
if __name__=='__main__':serve()
