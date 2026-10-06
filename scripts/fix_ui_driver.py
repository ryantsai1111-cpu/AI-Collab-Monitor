from pathlib import Path
p=Path('scripts/ui_driver.py');s=p.read_text(encoding='utf-8-sig');s=s.replace('def serve():\n','def serve():\n    os.environ["CODEX_CLI_PATH"]=r"C:\\Users\\ryant\\AppData\\Local\\OpenAI\\Codex\\bin\\8aaf1547b825b104\\codex.exe"\n')
p.write_text(s,encoding='utf-8')
