import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import py_compile, os
    
    path = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/analyze_and_render.py"
    with open(path) as f:
        lines = f.readlines()
    
    # The shebang (line 0) is fine. Every subsequent non-empty line is uniformly
    # prefixed with 4 extra spaces. Strip exactly the first 4 leading spaces from
    # each line after the shebang, preserving all internal relative indentation.
    out = []
    for i, ln in enumerate(lines):
        if i == 0:
            out.append(ln)  # shebang
            continue
        if ln.strip() == "":
            out.append(ln)  # keep blank lines as-is
            continue
        if ln.startswith("    "):
            out.append(ln[4:])
        else:
            out.append(ln)
    
    with open(path, "w") as f:
        f.writelines(out)
    
    # Verify it compiles
    try:
        py_compile.compile(path, doraise=True)
        print("COMPILE_OK")
    except py_compile.PyCompileError as e:
        print("COMPILE_FAILED")
        print(e)
    
    # Show first 20 lines to confirm indent fixed
    with open(path) as f:
        head = f.readlines()[:20]
    print("---- HEAD ----")
    print("".join(head))
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
