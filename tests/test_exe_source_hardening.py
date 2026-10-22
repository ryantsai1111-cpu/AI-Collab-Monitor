"""Offline policy/argv oracle/static source tests. NEVER compiler/installer/EXE."""
import copy,ctypes,hashlib,importlib.util,io,json,re,shutil,stat,subprocess,tempfile,types,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
policy=module('installer_policy');observation=module('launch_observation');context=module('package_context');reader=module('read_launch_snapshot')

def valid_snapshot():
    names=['run.py','acw/__init__.py','acw/core.py','acw/store.py','acw/ui/__init__.py','acw/ui/main_window.py','acw/ui/widgets.py','acw/ui/dialogs.py','scripts/dot_cli_entry.py','tools/dot-source-manifest.json',
           'tools/claude-session-sdk/session-helper.mjs','tools/claude-session-sdk/package.json',
           'vendor/PySide6/__init__.py','vendor/PySide6/QtCore.pyd','vendor/PySide6/QtGui.pyd','vendor/PySide6/QtWidgets.pyd',
           'vendor/shiboken6/__init__.py','vendor/shiboken6/Shiboken.pyd','vendor/pyside6-6.11.2.dist-info/METADATA','vendor/shiboken6-6.11.2.dist-info/METADATA',
           'tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/package.json',
           'tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs',
           'tools/claude-session-sdk/node_modules/mock-package/index.js',
           'tools/chatgpt-dot-cli-pinned/chatgpt_dot/__init__.py','tools/chatgpt-dot-cli-pinned/chatgpt_dot/api.py','AI Collaboration Workspace.exe']
    digest=hashlib.sha256(b'OFFLINE FIXTURE ONLY - NO EXECUTABLE CONTENT').hexdigest()
    inventories=[{'root':prefix,'entries':[name for name in names if name.startswith(prefix+'/')],
                  'entry_count':sum(name.startswith(prefix+'/') for name in names),'enumeration_complete':True,'reparse_checked':True} for prefix in policy.ROOTS]
    return dict(package_identity={'status':'UNPACKAGED','source':'MOCK'},alias_consistency='MATCH',excluded=[],source_inventory=inventories,
                sdk_package={'name':'@anthropic-ai/claude-agent-sdk','version':'0.3.289','entrypoints':['tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs']},
                destination_absolute=True,destination_name=policy.APP_NAME,app_exists=False,python_absolute=True,
                python_name='pythonw.exe',python_exists=True,console_python_exists=True,build_sources_match=True,
                build_manifest={'schema':1,'status':'BUILT','compiler':{'sha256':digest},'command':['MOCK ONLY - NEVER RUN'],
                                'output':{'sha256':digest}},files=[{'path':name,'sha256':digest} for name in names])

class ExeSourceHardening(unittest.TestCase):
    def test_valid_pure_plan_does_not_execute_or_write(self):
        with patch('subprocess.Popen',side_effect=AssertionError('NO EXECUTION')),patch.object(Path,'write_text',side_effect=AssertionError('NO WRITES')):
            plan=policy.validate(valid_snapshot())
        self.assertEqual(plan['state'],'PREFLIGHT_VERIFIED');self.assertIn('not a malware verdict',plan['warnings'][0])

    def test_quarantine_and_unverified_existing_app_never_resume(self):
        for existing,exe in [(None,False),({'schema':1,'app':policy.APP_NAME,'state':'COMPLETED'},False),
                             ({'schema':1,'app':policy.APP_NAME,'state':'INCOMPLETE'},False),
                             ({'schema':1,'app':policy.APP_NAME,'state':'COMPLETED'},True)]:
            data=valid_snapshot();data.update(app_exists=True,existing_manifest=existing,installed_exe_exists=exe,resume_partial=True)
            with self.subTest(existing=existing,exe=exe),self.assertRaises(ValueError):policy.validate(data)

    def test_all_preflight_failures_are_pure_zero_writes(self):
        changes=[{'packaged_context':True},{'destination_alias_mismatch':True},{'destination_absolute':False},
                 {'destination_name':'other-app'},{'shortcut_conflicts':['existing.lnk']},{'resume_partial':True},
                 {'python_absolute':False},{'python_name':'auth.json'},{'python_exists':False},{'console_python_exists':False},
                 {'build_manifest':{}},{'build_sources_match':False},{'files':[]}]
        with patch.object(Path,'write_bytes',side_effect=AssertionError('NO WRITES')),patch('subprocess.Popen',side_effect=AssertionError('NO EXECUTION')):
            for change in changes:
                data=valid_snapshot();data.update(change)
                with self.subTest(change=change),self.assertRaises(ValueError):policy.validate(data)

    def test_allowlist_secrets_history_and_path_escape_rejected(self):
        for name in ['tests/test.py','evidence/log.json','scripts/build_launcher.ps1','scripts/evil.py',
                     'acw/auth.json','tools/claude-session-sdk/node_modules/x/.npmrc',
                     'tools/claude-session-sdk/node_modules/x/.env.local','../run.py',r'C:\auth.json','acw/../run.py']:
            with self.subTest(name=name):self.assertFalse(policy.allowed(name))
        self.assertTrue(policy.allowed('scripts/dot_cli_entry.py'))
        data=valid_snapshot();data['files'].append({'path':'evidence/history.json','sha256':'a'*64})
        with self.assertRaises(ValueError):policy.validate(data)

    def test_hash_and_required_runtime_completeness(self):
        for field in ['invalid_hash','duplicate','missing_helper','missing_dependency','wrong_exe_hash']:
            data=valid_snapshot()
            if field=='invalid_hash':data['files'][0]['sha256']='z'*64
            elif field=='duplicate':data['files'].append(copy.deepcopy(data['files'][0]))
            elif field=='missing_helper':data['files']=[r for r in data['files'] if r['path']!='scripts/dot_cli_entry.py']
            elif field=='missing_dependency':data['files']=[r for r in data['files'] if not r['path'].startswith('vendor/PySide6/')]
            else:data['build_manifest']['output']['sha256']='f'*64
            with self.subTest(field=field),self.assertRaises(ValueError):policy.validate(data)

    def test_inspector_rejects_arbitrary_secret_paths_before_content_read(self):
        with tempfile.TemporaryDirectory(prefix='acw-exe-policy-') as tmp:
            root=Path(tmp);auth=root/'auth.json';auth.write_text('FAKE SECRET - MUST NOT READ')
            with patch.object(Path,'read_text',side_effect=AssertionError('NO CONTENT READ')):
                with self.assertRaisesRegex(ValueError,'provenance'):
                    policy.inspect(root,root/policy.APP_NAME,root/'python.exe',auth,[],root/policy.APP_NAME)

    def test_absolute_path_policy_drive_relative_rejected(self):
        for value in ['relative','C:relative',r'\root-relative','']:
            self.assertFalse(policy.absolute_windows_path(value))
        for value in [r'C:\repo','D:'+chr(92),r'\\server\share\repo']:
            self.assertTrue(policy.absolute_windows_path(value))

    def test_launcher_guard_order_static_not_runtime_certification(self):
        code=(ROOT/'scripts/Launcher.cs').read_text()
        main=code[code.index('static int Main'):]
        self.assertLess(main.index('try {'),main.index('File.ReadAllText'))
        self.assertLess(main.index('return 2;'),main.index('Process.Start'))
        self.assertIn('args.Length != 2 || args[0] != "--data-dir"',main)
        self.assertIn('!File.Exists(script)',main);self.assertIn('UseShellExecute = false, CreateNoWindow = true',main)
        self.assertIn('NOT UI readiness/EXE acceptance',main);self.assertNotIn('Kill(',main)

    def test_manifest_is_as_invoker_not_elevation_or_trust_change(self):
        import xml.etree.ElementTree as ET
        root=ET.parse(ROOT/'scripts/launcher.manifest').getroot()
        level=root.find('.//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel')
        self.assertEqual(level.attrib,{'level':'asInvoker','uiAccess':'false'})

    def test_unknown_production_and_backend_evidence_stays_unknown(self):
        result=observation.assess({'window_visible':True,'normal_close_requested':True,'normal_exit':True,'target_matches_build':True})
        self.assertEqual(result['prod_data_used'],'UNKNOWN');self.assertEqual(result['backend_connected'],'UNKNOWN')
        self.assertEqual(result['status'],'UNKNOWN')

    def test_observed_scope_not_full_acceptance_and_refusal_no_retry(self):
        data={'observed_argv':['pythonw','run.py','--data-dir',r'C:\tests\isolated'],
              'isolated_data_dir':r'C:\tests\isolated','production_data_dir':r'C:\real\data',
              'window_visible':True,'normal_close_requested':True,'normal_exit':True,'target_matches_build':True}
        result=observation.assess(data);self.assertEqual(result['prod_data_used'],'UNKNOWN');self.assertTrue(result['data_dir_argument_isolated'])
        self.assertEqual(result['backend_connected'],'UNKNOWN');self.assertIn('scope',result['status'])
        data['failure']={'status':'BLOCKED','native_error_code':225,'retry_performed':False}
        self.assertEqual(observation.assess(data)['status'],'BLOCKED')

    def test_powershell_parser_and_exact_csharp_regex_with_windows_argv_oracle(self):
        # Invoke ONLY the existing trusted PowerShell parser and declared PURE
        # helpers. Never dot-source installer/build/launch entry scripts.
        code=(ROOT/'scripts/Launcher.cs').read_text()
        constants={key:value.replace('""','"') for key,value in re.findall(r'internal const string (\w+) = @"((?:[^"]|"")*)";',code)}
        self.assertEqual(set(constants),{'QuotePattern','QuoteReplacement','TrailingPattern','TrailingReplacement'})
        slash=chr(92)
        values=['','C:'+slash,'C:'+slash+'folder with spaces'+slash,'中文路徑'+slash,
                'a"b','a'+slash+'"b','line'+slash+chr(10),slash*2+'server'+slash+'share'+slash,
                'backslash'+slash*2,'-dash','x'*500]
        files=['install.ps1','scripts/build_launcher.ps1','scripts/verify_desktop_launch.ps1','scripts/launch_validation_helpers.ps1','scripts/ascii_json_helpers.ps1']
        files = [name for name in files if (ROOT / name).is_file()]
        if 'install.ps1' not in files:
            print('根目錄 install.ps1 已移除，PowerShell 解析 oracle 只對現存檔案執行', flush=True)
        with tempfile.TemporaryDirectory(prefix='acw-ps-pure-') as tmp:
            root=Path(tmp);fixture=root/'input.json';fixture.write_text(json.dumps({'constants':constants,'values':values,'files':[str(ROOT/p) for p in files]}),encoding='utf-8')
            harness=root/'pure-parser.ps1'
            harness.write_text("param([string]$Fixture,[string]$Helpers)\n. $Helpers\n$data=Get-Content -LiteralPath $Fixture -Raw | ConvertFrom-Json\n$constants=@{};foreach($property in $data.constants.PSObject.Properties){$constants[$property.Name]=[string]$property.Value}\n$parse=@();foreach($file in $data.files){$tokens=$null;$errors=$null;$ast=[System.Management.Automation.Language.Parser]::ParseFile($file,[ref]$tokens,[ref]$errors);$parse+=@{file=$file;errors=@($errors | ForEach-Object {$_.Message})}}\n$quoted=@();foreach($value in $data.values){$quoted+=ConvertTo-LauncherQuotedArgument -Value $value -Constants $constants}\n$failure=Get-NativeLaunchFailure -Exception ([Exception]::new('wrapped mock',[ComponentModel.Win32Exception]::new(225,'mock security refusal')))\n@{parse=$parse;quoted=$quoted;failure=$failure}|ConvertTo-Json -Depth 8\n",encoding='utf-8')
            ps=shutil.which('pwsh') or shutil.which('powershell')
            self.assertTrue(ps,'Existing trusted PowerShell required; never install a toolchain')
            # PowerShell console output can use the user's ACP. Preserve bytes
            # then decode explicitly; never silently replace Unicode evidence.
            result=subprocess.run([str(ps),'-NoProfile','-NonInteractive','-File',str(harness),str(fixture),str(ROOT/'scripts/launch_validation_helpers.ps1')],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,repr(result.stderr))
            try:stdout=result.stdout.decode('utf-8')
            except UnicodeDecodeError:stdout=result.stdout.decode('cp950')
            parsed=json.loads(stdout);self.assertTrue(all(not row['errors'] for row in parsed['parse']),parsed['parse'])
            self.assertEqual(parsed['failure']['status'],'BLOCKED');self.assertEqual(parsed['failure']['native_error_code'],225)
            shell=ctypes.WinDLL('shell32');kernel=ctypes.WinDLL('kernel32')
            shell.CommandLineToArgvW.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int)]
            shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
            kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
            for value,quoted in zip(values,parsed['quoted']):
                count=ctypes.c_int();pointer=shell.CommandLineToArgvW('oracle '+quoted,ctypes.byref(count))
                self.assertTrue(pointer)
                try:self.assertEqual([pointer[i] for i in range(count.value)],['oracle',value],repr(value))
                finally:kernel.LocalFree(pointer)

    def test_reparse_and_symlink_mock_rejected_before_any_traversal(self):
        for mode,attributes in [(stat.S_IFDIR,0x400),(stat.S_IFLNK,0),(stat.S_IFREG,0x400)]:
            with self.subTest(mode=mode,attributes=attributes),patch.object(Path,'lstat',return_value=types.SimpleNamespace(st_mode=mode,st_file_attributes=attributes)),patch('os.scandir',side_effect=AssertionError('NO TRAVERSAL')):
                with self.assertRaisesRegex(ValueError,'reparse'):policy.require_unlinked(Path('mock-dependency'))

    def test_inventory_excluded_resources_and_metadata_are_explicit(self):
        with tempfile.TemporaryDirectory(prefix='pure-inventory-') as tmp:
            root=Path(tmp);vendor=root/'vendor';(vendor/'PySide6').mkdir(parents=True)
            (vendor/'pyside6-6.11.2.dist-info').mkdir();(vendor/'bin').mkdir()
            (vendor/'PySide6/__init__.py').write_text('# MOCK')
            (vendor/'pyside6-6.11.2.dist-info/METADATA').write_text('MOCK METADATA')
            (vendor/'bin/unknown-resource.dat').write_text('MOCK ONLY')
            rows,excluded,inventory=policy.collect_root(root,'vendor')
            self.assertEqual(inventory['entry_count'],3)
            self.assertIn('vendor/pyside6-6.11.2.dist-info/METADATA',[row['path'] for row in rows])
            self.assertEqual(excluded,[{'path':'vendor/bin/unknown-resource.dat','reason':'unreviewed_resource_or_package','necessity':'UNKNOWN','kind':'file','content_read':False}])
            data=valid_snapshot();data['excluded']=excluded
            with self.assertRaisesRegex(ValueError,'necessity UNKNOWN'):policy.validate(data)

    def test_secret_named_dependency_excluded_without_reading_and_cache_documented(self):
        with tempfile.TemporaryDirectory(prefix='pure-exclusions-') as tmp:
            root=Path(tmp);prefix='tools/claude-session-sdk/node_modules';package=root/prefix/'fixture';package.mkdir(parents=True)
            (package/'credentials.json').write_text('ARTIFICIAL NAME FIXTURE ONLY')
            (package/'__pycache__').mkdir();(package/'__pycache__/generated.pyc').write_text('MOCK CACHE')
            with patch.object(Path,'read_bytes',side_effect=AssertionError('NO EXCLUDED CONTENT READ')):
                rows,excluded,inventory=policy.collect_root(root,prefix)
            self.assertEqual(rows,[])
            self.assertEqual({row['necessity'] for row in excluded},{'GENERATED','UNKNOWN'})
            self.assertTrue(all(row['content_read'] is False for row in excluded))

    def test_full_inventory_cannot_be_replaced_with_prefix_presence(self):
        for mutation in ('missing_inventory','missing_entry','incomplete_enumeration','unchecked_reparse','missing_entrypoint'):
            data=valid_snapshot()
            if mutation=='missing_inventory':data['source_inventory']=[]
            elif mutation=='missing_entry':data['source_inventory'][0]['entries'].append('acw/unrecorded.py');data['source_inventory'][0]['entry_count']+=1
            elif mutation=='incomplete_enumeration':data['source_inventory'][0]['enumeration_complete']=False
            elif mutation=='unchecked_reparse':data['source_inventory'][0]['reparse_checked']=False
            else:
                name='acw/store.py';data['files']=[r for r in data['files'] if r['path']!=name]
                data['source_inventory'][0]['entries'].remove(name);data['source_inventory'][0]['entry_count']-=1
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):policy.validate(data)

    def test_package_identity_return_codes_and_unknown_alias_fail_closed(self):
        self.assertEqual(context.interpret_identity(15700)['status'],'UNPACKAGED')
        self.assertEqual(context.interpret_identity(122,20,0,'MOCK_PACKAGE')['status'],'PACKAGED')
        for record in (context.interpret_identity(5),context.interpret_identity(122,0),context.interpret_identity(122,20,5),context.interpret_identity(122,20,0,''),context.interpret_identity(122,50000,0,'MOCK')):
            self.assertEqual(record['status'],'UNKNOWN')
            data=valid_snapshot();data['package_identity']=record
            with self.assertRaisesRegex(ValueError,'UNKNOWN'):policy.validate(data)
        data=valid_snapshot();data['alias_consistency']='UNKNOWN'
        with self.assertRaisesRegex(ValueError,'alias'):policy.validate(data)

    def test_ascii_plan_round_trip_and_size_limit(self):
        text=policy.encode_plan({'path':'中文路徑','quotes':'a"b'})
        self.assertTrue(text.isascii());self.assertEqual(json.loads(text)['path'],'中文路徑')
        with self.assertRaisesRegex(ValueError,'limit'):policy.encode_plan({'large':'x'*1000001})

    def test_required_runtime_and_sdk_metadata_not_just_present_prefixes(self):
        for name in ('vendor/PySide6/QtWidgets.pyd','vendor/shiboken6/Shiboken.pyd','tools/claude-session-sdk/node_modules/@anthropic-ai/claude-agent-sdk/sdk.mjs'):
            data=valid_snapshot();data['files']=[row for row in data['files'] if row['path']!=name]
            for inventory in data['source_inventory']:
                if name in inventory['entries']:inventory['entries'].remove(name);inventory['entry_count']-=1
            with self.subTest(name=name),self.assertRaises(ValueError):policy.validate(data)
        for metadata in ({},{'exports':{'import':'./sdk.mjs','types':'./sdk.d.ts'}},{'main':'../escape.js'},{'exports':'./wildcard/*.js'}):
            if metadata.get('exports')=={'import':'./sdk.mjs','types':'./sdk.d.ts'}:
                self.assertEqual(len(policy.sdk_entrypoints(metadata)['entrypoints']),2)
            else:
                with self.subTest(metadata=metadata),self.assertRaises(ValueError):policy.sdk_entrypoints(metadata)

    def test_json_stdin_preserves_quoted_command_line_and_rejects_bad_requests(self):
        command='"pythonw.exe" "C:\\folder with spaces\\run.py" --data-dir "C:\\tests\\中文"'
        request={'command_line':command,'data_dir':'C:\\tests\\中文','expected_script':'C:\\folder with spaces\\run.py'}
        self.assertEqual(reader.read_request(io.StringIO(json.dumps(request,ensure_ascii=True))),request)
        for value in ('{bad','[]',json.dumps({'command_line':command}),'x'*1000001):
            with self.subTest(value=value[:20]),self.assertRaises(ValueError):reader.read_request(io.StringIO(value))

    def test_sqlite_and_payload_errors_remain_unknown_with_original_error(self):
        data=ROOT/'tests/mock-observation';script=ROOT/'run.py';argv=['pythonw',str(script),'--data-dir',str(data)]
        for error in (sqlite3.OperationalError('MOCK SQL ERROR'),json.JSONDecodeError('MOCK JSON ERROR','x',0)):
            connection=types.SimpleNamespace(execute=lambda query:(_ for _ in ()).throw(error),close=lambda:None)
            with self.subTest(error=type(error).__name__),patch.object(Path,'is_file',return_value=True),patch.object(reader.sqlite3,'connect',return_value=connection):
                result=reader.snapshot('MOCK COMMAND',data,str(script),decoder=lambda command:argv)
            self.assertEqual(result['status'],'UNKNOWN');self.assertEqual(result['prod_data_used'],'UNKNOWN')
            self.assertEqual(result['backend_connected'],'UNKNOWN');self.assertTrue(result['data_dir_argument_isolated'])
            self.assertTrue(result['entrypoint_argument_matches']);self.assertIn('MOCK',result['observation_errors'][0]['message'])

    def test_launch_and_build_guards_static_not_runtime_certification(self):
        launch=(ROOT/'scripts/verify_desktop_launch.ps1').read_text()
        self.assertIn('$request | & $Python',launch);self.assertNotIn('--command-line $ownedMeta.CommandLine',launch)
        self.assertIn('} finally {',launch);self.assertIn('Test-OwnedLaunchMetadata',launch);self.assertNotIn('Kill(',launch)
        self.assertIn("'BLOCKED_PREFLIGHT'",launch)
        build=(ROOT/'scripts/build_launcher.ps1').read_text()
        self.assertIn("'/noconfig'",build);self.assertLess(build.index('$record.invocation_attempted=$true'),build.index('[Diagnostics.Process]::Start'))
        self.assertIn('ReadToEndAsync',build);self.assertNotIn('& $compiler',build)

    def test_pure_powershell_ascii_bounds_and_owned_metadata(self):
        with tempfile.TemporaryDirectory(prefix='pure-ps-helpers-') as tmp:
            harness=Path(tmp)/'helpers.ps1'
            harness.write_text("param([string]$Ascii,[string]$Launch)\n. $Ascii\n. $Launch\n$text=ConvertTo-StableAsciiJson -Value @{path=[string][char]0x4e2d}\n$round=ConvertFrom-BoundedPlanJson -Text $text\n$limited=$false;try{ConvertFrom-BoundedPlanJson -Text ('x'*11) -MaxCharacters 10}catch{$limited=$true}\n$first=[pscustomobject]@{ProcessId=2;CreationDate='mock-birth';CommandLine='mock command'}\n$same=[pscustomobject]@{ProcessId=2;CreationDate='mock-birth';CommandLine='mock command'}\n$reuse=[pscustomobject]@{ProcessId=2;CreationDate='different-birth';CommandLine='mock command'}\nConvertTo-StableAsciiJson -Value @{ascii=($text -notmatch '[^\\x00-\\x7f]');roundtrip=([int][char]$round.path -eq 0x4e2d);limit=$limited;same=(Test-OwnedLaunchMetadata $first $same);reuse=(Test-OwnedLaunchMetadata $first $reuse);missing=(Test-OwnedLaunchMetadata $first $null)}\n",encoding='utf-8')
            ps=shutil.which('pwsh') or shutil.which('powershell');self.assertTrue(ps)
            done=subprocess.run([ps,'-NoProfile','-NonInteractive','-File',str(harness),str(ROOT/'scripts/ascii_json_helpers.ps1'),str(ROOT/'scripts/launch_validation_helpers.ps1')],capture_output=True,timeout=30)
            self.assertEqual(done.returncode,0,repr(done.stderr));result=json.loads(done.stdout.decode('ascii'))
            self.assertTrue(result['ascii'] and result['roundtrip'] and result['limit'] and result['same'])
            self.assertFalse(result['reuse']);self.assertFalse(result['missing'])

if __name__=='__main__':unittest.main()
