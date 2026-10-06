import subprocess,json,sys,threading,queue
p=subprocess.Popen([r'C:\Users\ryant\AppData\Local\OpenAI\Codex\runtimes\cua_node\45309f9050f7314b\bin\node_repl.exe'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
p.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'acw-ui-acceptance','version':'1'}}})+'\n');p.stdin.flush()
print(p.stdout.readline())
p.stdin.write(json.dumps({'jsonrpc':'2.0','method':'notifications/initialized'})+'\n');p.stdin.write(json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})+'\n');p.stdin.flush()
print(p.stdout.readline())
p.stdin.close()
