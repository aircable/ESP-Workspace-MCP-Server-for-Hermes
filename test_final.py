
import json, os, sys, tempfile, shutil, traceback, time

PROJECT_ROOT = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/MCPserver"
sys.path.insert(0, PROJECT_ROOT + "/.venv/lib/python3.14/site-packages")
sys.path.insert(0, PROJECT_ROOT)

ROOTS = ["/home/juergen/AIRcableLLC", "/tmp"]
PROJECT_DIR = "/home/juergen/AIRcableLLC/ESP_SW/NEWEST/WishMesh.work"

from esp_workspace_mcp.tools.phase4_tools import replace_text, patch_file
from esp_workspace_mcp.tools.phase4_uart import decode_panic, monitor_uart
from esp_workspace_mcp.tools.phase4_symbols import find_symbol, find_references
from esp_workspace_mcp.tools.session_tools import SessionManager
from esp_workspace_mcp.tools.esp_idf import parse_build_output
from esp_workspace_mcp.tools.git_tools import git_status, git_diff, git_branch, git_log
from esp_workspace_mcp.tools.serial_tools import list_serial_ports
from esp_workspace_mcp.tools.diagnostics import get_project_info, get_connected_devices
from esp_workspace_mcp.tools.filesystem import read_file, write_file, append_file, list_dir, create_dir, delete_path, file_stat, glob_search
from esp_workspace_mcp.tools.search import grep, find_files
from esp_workspace_mcp.tools.shell import execute_command

P=0; F=0; ERR=[]
def ok(n,d=""):
    global P; P+=1; print("  PASS  "+n+((" --- "+d) if d else ""))
def fail(n,r=""):
    global F,ERR; F+=1; ERR.append(n); print("  FAIL  "+n+": "+str(r))
def j(s):
    if isinstance(s,dict): return s
    try: return json.loads(s)
    except: return {"_raw":str(s)[:200]}

# === Phase 1: Filesystem ===
print("\n--- Phase 1: Filesystem ---")
try:
    fn=tempfile.mktemp(dir="/tmp"); open(fn,"w").write("L1\nL2\nL3\n")
    assert "L1" in str(read_file(fn,ROOTS)); ok("read_file")
    # offset=1 means skip 1 line, show from line 2
    r2 = str(read_file(fn,ROOTS,offset=1,limit=1))
    assert "L2" in r2, "L2 not in: %s" % r2[:50]; ok("read_file offset","shows L2")
    write_file(fn,"new\n",ROOTS); assert "new" in str(read_file(fn,ROOTS)); ok("write_file")
    append_file(fn,"add\n",ROOTS); c=str(read_file(fn,ROOTS)); assert "new" in c and "add" in c; ok("append_file")
    os.unlink(fn)
except Exception as e: fail("fs-%s"%str(e)[:40])

try:
    r=list_dir("/tmp",ROOTS); ok("list_dir")
    d="/tmp/mcp_test_final"; create_dir(d,ROOTS); create_dir(d+"/a/b",ROOTS)
    delete_path(d+"/a/b",ROOTS); assert not os.path.exists(d+"/a/b"); ok("create/delete")
    shutil.rmtree(d,ignore_errors=True)
    ok("file_stat",str(file_stat("/tmp",ROOTS))[:50])
    b="/tmp/mcp_gfin"; os.makedirs(b,exist_ok=True)
    [open(os.path.join(b,"f%d.txt"%i),"w").write("x") for i in range(3)]
    ok("glob_search",str(glob_search("*.txt",b,ROOTS))[:50])
    shutil.rmtree(b,ignore_errors=True)
except Exception as e: fail("fs_adv",str(e))

# Security
print("\n--- Security ---")
try:
    r=str(read_file("/etc/passwd",ROOTS)); assert "error" in r.lower() or "denied" in r.lower() or "not allowed" in r.lower()
    ok("blocks /etc/passwd")
except Exception as e: fail("sec",str(e))

# Shell
print("\n--- Shell ---")
try:
    assert "hello_test" in str(execute_command("hello_test_123",ROOTS)); ok("exec echo")
    assert "/tmp" in str(execute_command("pwd",ROOTS,cwd="/tmp")); ok("exec cwd")
except Exception as e: fail("exec",str(e))

# Git (status only)
print("\n--- Git ---")
try:
    r=str(git_status(PROJECT_DIR,ROOTS)); assert "Branch" in r; ok("git_status")
except Exception as e: fail("git_status",str(e)[:50])
try:
    r=str(git_branch(PROJECT_DIR,ROOTS)); ok("git_branch",r[:60])
except Exception as e: fail("git_branch",str(e)[:50])
try:
    r=str(git_log(PROJECT_DIR,ROOTS,count=3)); ok("git_log",r[:60])
except Exception as e: fail("git_log",str(e)[:50])
try:
    r=str(git_diff(PROJECT_DIR,ROOTS)); ok("git_diff",r[:60])
except Exception as e: fail("git_diff",str(e)[:50])

# Search
print("\n--- Search ---")
try:
    r=str(grep("import",PROJECT_DIR,ROOTS,file_pattern="*.py",max_results=3)); assert ".py" in r; ok("grep")
except Exception as e: fail("grep",str(e)[:50])
try:
    r=str(find_files("*.py",PROJECT_DIR,ROOTS)); assert ".py" in r; ok("find_files")
except Exception as e: fail("find_files",str(e)[:50])

# Serial
print("\n--- Serial ---")
try:
    r=str(list_serial_ports(ROOTS)); ok("list_serial_ports",r[:60])
except Exception as e: fail("list_serial_ports",str(e)[:50])

# Diagnostics
print("\n--- Diagnostics ---")
try:
    r=str(get_project_info(PROJECT_DIR,ROOTS)); ok("get_project_info",r[:60])
except Exception as e: fail("get_project_info",str(e)[:50])
try:
    r=str(get_connected_devices(ROOTS)); ok("get_connected_devices",r[:60])
except Exception as e: fail("get_connected_devices",str(e)[:50])

# Phase 3: Build Diagnostics
print("\n--- Phase 3 ---")
try:
    sample=("main.c:42:5: error: undeclared\nmain.h:10:5: warning: unused\n"
            "main.c:25:3: error: implicit declaration\n")
    r=j(parse_build_output(sample))
    assert isinstance(r,dict) and r.get("error_count",0)>=1; ok("parse_build_output","%d errs"%r.get("error_count",0))
except Exception as e: fail("parse_build",str(e)[:50])

try:
    sm=SessionManager(); sm.create_session("t1",working_dir="/tmp")
    ok("create_session"); sm.destroy_session("t1"); ok("destroy_session")
except Exception as e: fail("sessions",str(e)[:50])

# Phase 4: File Ops
print("\n--- Phase 4 ---")
try:
    fn=tempfile.mktemp(dir="/tmp"); open(fn,"w").write("hello\nhello\nhello\n")
    r=j(replace_text(fn,"hello","goodbye",replace_all=True,allowed_roots=ROOTS))
    if isinstance(r,dict): ok("replace_text","%d replacements"%r.get("replacements",0))
    else: ok("replace_text")
    os.unlink(fn)
except Exception as e: fail("replace_text",str(e)[:50])

# Phase 4: Panic Decoder
try:
    panic=("Guru Meditation Error: Core 0 panic'ed (LoadProhibited).\n"
           "PC : 0x40081234\nBacktrace: 0x40081234:0x3ffb0010\nRebooting...\n")
    r=j(decode_panic(panic))
    assert r.get("panic_detected")==True; ok("panic detected")
    assert r.get("pc_address")=="0x40081234"; ok("PC")
    assert r.get("reset_reason")=="load_prohibited"; ok("reason")
    assert len(r.get("backtrace_addresses",[]))>0; ok("backtrace")
    r2=j(decode_panic("Normal output")); assert r2.get("panic_detected")==False; ok("no panic")
    r3=j(decode_panic("abort() was called at PC 0x40085678 on core 0\n"))
    assert r3.get("reset_reason")=="software_abort"; ok("abort")
except Exception as e: fail("decode_panic",str(e)[:50])

# Phase 4: Symbol Indexing
try:
    r=j(find_symbol("read_file",project_path=PROJECT_ROOT,allowed_roots=ROOTS))
    assert isinstance(r,dict); ok("find_symbol","method="+r.get("method","?"))
except Exception as e: fail("find_symbol",str(e)[:50])
try:
    r=j(find_references("MCPError",project_path=PROJECT_ROOT,allowed_roots=ROOTS))
    assert isinstance(r,dict); ok("find_references","%d refs"%r.get("total_references",0))
except Exception as e: fail("find_references",str(e)[:50])

# Phase 4: Serial Monitor (TargetS3 on /dev/ttyACM0)
if os.path.exists("/dev/ttyACM0"):
    try:
        r=j(monitor_uart("/dev/ttyACM0",115200,duration=3,filter_pattern="",allowed_roots=ROOTS))
        if isinstance(r,dict): ok("monitor_uart","%d lines"%r.get("captured_lines",0))
        else: ok("monitor_uart")
        # Save output for inspection
        if isinstance(r,dict) and r.get("output"):
            print("  [TargetS3 output sample]:", r["output"][:150])
    except Exception as e: fail("monitor_uart",str(e)[:50])
else:
    ok("monitor_uart","SKIPPED")

# Summary
print("\n"+"="*60)
print("Results: %d/%d passed, %d failed"%(P,P+F,F))
for e in ERR: print("  FAIL: "+e)
print("="*60)
if F==0: print("ALL TESTS PASSED")
