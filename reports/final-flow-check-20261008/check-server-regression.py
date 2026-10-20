"""Run existing server regression plus the reviewed new continuation cases."""
import json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
folder = Path(__file__).parent
backup = json.loads((folder/'final-audit-deployment.json').read_text(encoding='utf-8'))['backup']
script = r'''
import contextlib,importlib.util,io,json,os,sys,unittest
os.chdir('/opt/gongwei/releases/20261007-120338-maintenance');sys.path.insert(0,os.getcwd())
stream=io.StringIO()
with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
 suite=unittest.defaultTestLoader.discover('.')
 def leaves(s):
  for test in s:
   if isinstance(test,unittest.TestSuite):yield from leaves(test)
   else:yield test
 tests=[t for t in leaves(suite) if type(t).__module__!='test_homepage_continuation']
 spec=importlib.util.spec_from_file_location('reviewed_homepage_tests',staged+'/next/test_homepage_continuation.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 tests.extend(leaves(unittest.defaultTestLoader.loadTestsFromModule(m)))
 result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestSuite(tests))
print(json.dumps({'total':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful(),'log':stream.getvalue()},ensure_ascii=False))
'''
ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ServerAliveInterval=10','-i',str(ROOT.parent/'gongwei.pem'),'ubuntu@43.156.60.222']
run=subprocess.run(ssh+['sudo /opt/gongwei/.venv/bin/python -'],input=('staged='+repr(backup)+'\n'+script).encode(),capture_output=True,timeout=180)
if run.returncode:raise RuntimeError(run.stderr.decode(errors='replace'))
result=json.loads(run.stdout)
(folder/'server-regression.log').write_text(result.pop('log'),encoding='utf-8')
(folder/'server-regression.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result));assert result['passed']
