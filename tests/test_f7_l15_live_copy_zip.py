"""F7-L15 real copy2 + ZipFile.write isolation regression in fresh Python process."""
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

ROOT=Path(__file__).resolve().parents[1]

class LiveObserverTest(unittest.TestCase):
    def test_two_real_operations_isolated(self):
        child=textwrap.dedent("""
            import importlib.util, pathlib, tempfile, shutil, zipfile, json
            root=pathlib.Path(__import__('sys').argv[1])
            def load(name,file):
                sp=importlib.util.spec_from_file_location(name,root/'scripts'/file)
                m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m
            c=load('copy_observer','f7_auditwheel_python_trace.py')
            z=load('zip_observer','f7_l14_zip_api_observer.py')
            with tempfile.TemporaryDirectory() as d:
                d=pathlib.Path(d)
                c.LOG=str(d/'copy.jsonl');z.LOG=str(d/'zip.jsonl')
                c.PASS='first';z.PASS='first'
                c._wrap(shutil,'copyfile')
                c._wrap(shutil,'copy2')
                z._trace('write')
                src=d/'source.bin';dst=d/'copied.bin';src.write_bytes(b'ELF-TEST-BYTES')
                result=shutil.copy2(src,dst)
                assert pathlib.Path(result).read_bytes()==src.read_bytes()
                with zipfile.ZipFile(d/'a.whl','w') as wheel:
                    wheel.write(dst,arcname='lib/test.so')
                with zipfile.ZipFile(d/'a.whl','r') as wheel:
                    assert wheel.read('lib/test.so')==src.read_bytes()
                co=[json.loads(x) for x in (d/'copy.jsonl').read_text().splitlines()]
                zi=[json.loads(x) for x in (d/'zip.jsonl').read_text().splitlines()]
                assert len(co)==1 and co[0]['operation']=='shutil.copy2',co
                assert len(zi)==1 and zi[0]['operation']=='ZipFile.write',zi
                assert all(x['repair_pass']=='first' for x in co+zi)
                assert not any('zip_api' in x['operation'] for x in co)
                assert co[0]['source_sha256_before']==co[0]['destination_sha256_after']
                assert zi[0]['file_sha256_before']==co[0]['destination_sha256_after']
        """)
        for passage in ('first','second'):
            r=subprocess.run([sys.executable,'-c',child.replace("c.PASS='first';z.PASS='first'",f"c.PASS='{passage}';z.PASS='{passage}'").replace("=='first' ",f"=='{passage}' "),str(ROOT)],capture_output=True,text=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stderr)
if __name__=='__main__':unittest.main()
