import subprocess, shutil, os, tempfile
VENV = r"H:\vs_code_file\git-clone-file\agent_leaning\.venv\Scripts\python.exe"
BASE = r"H:\vs_code_file\git-clone-file\ez-interview\code\tests\eval\coding_tasks"
for t in ["task1_off_by_one","task2_reverse_words"]:
    d = os.path.join(BASE, t)
    r = subprocess.run([VENV,"-m","pytest",os.path.join(d,"test_source.py"),"-q"],capture_output=True,text=True,cwd=d)
    print(t, "bug:", "FAIL(ok)" if r.returncode else "PASS(bug没fail!)")
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(d,"solution.py"), os.path.join(tmp,"source.py"))
    shutil.copy(os.path.join(d,"test_source.py"), os.path.join(tmp,"test_source.py"))
    r2 = subprocess.run([VENV,"-m","pytest",os.path.join(tmp,"test_source.py"),"-q"],capture_output=True,text=True,cwd=tmp)
    print(t, "sol:", "PASS(ok)" if r2.returncode==0 else "FAIL(solution错!)")
    shutil.rmtree(tmp, ignore_errors=True)
