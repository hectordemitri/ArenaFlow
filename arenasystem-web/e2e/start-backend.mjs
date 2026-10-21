import { spawn } from 'node:child_process';
import path from 'node:path';

const child = spawn(process.env.E2E_PYTHON_BIN || 'python', [
  '-c', "import os,sys,runpy; p=os.environ.get('E2E_EXTRA_PACKAGES'); sys.path.append(p) if p else None; sys.argv=['manage.py','serve_e2e','--settings=arenasystem.settings_e2e']; runpy.run_path('manage.py',run_name='__main__')",
], { cwd: path.resolve('../arenasystem'), env: process.env, stdio: 'inherit', windowsHide: true });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code) => { process.exitCode = code || 0; });
