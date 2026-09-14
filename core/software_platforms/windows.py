import os, platform, re, shutil, subprocess
from pathlib import Path
from core.software_workflow import (SoftwareEnvironment, SoftwareRequest, SoftwareSource,
    SoftwarePlan, SoftwareArtifact, SoftwareResolutionError, run_command)
from core.verified_download import download_verified

PACKAGES={"jq":("jqlang.jq","jq.exe"),"ripgrep":("BurntSushi.ripgrep.MSVC","rg.exe"),"git":("Git.Git","git.exe")}
ALIASES={"rg":"ripgrep", **{k.lower():n for n,(k,_) in PACKAGES.items()}}
JQ_URL="https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-windows-amd64.exe"
JQ_SHA256="a6fc67fedaf9128a3309a1e2ebb8b986aeccf70122ee46d2cb4849e423f0c627"
JQ_CHECKSUM_URL="https://github.com/jqlang/jq/releases/download/jq-1.8.2/sha256sum.txt"

class WindowsAdapter:
    def detect_environment(self):
        return SoftwareEnvironment("Windows","windows",platform.machine(),shell=shutil.which("pwsh") or shutil.which("powershell") or "",package_managers=[x for x in ("winget","choco") if shutil.which(x)],user=os.environ.get("USERNAME",""),home=str(Path.home()),privilege_capabilities=["user_scope"])
    def work_directory(self,environment,task_id): return Path(environment.home)/"AppData/Local/Vaelor/tasks"/task_id
    def canonicalize_program(self,request):
        text=str(request or "").strip(); match=re.search(r"\b(?:download|install|get|setup|set up|clone)\s+(?:the\s+)?([a-z0-9][a-z0-9+._-]*)\b",text.lower())
        token=match.group(1) if match else ""
        if not token: raise ValueError("Could not identify the software name in the request.")
        name=ALIASES.get(token,token); action="clone" if re.search(r"^\s*clone\b",text,re.I) else ("download_only" if re.search(r"\b(installer|zip)\b.*\b(only|downloads?)\b|\b(save|download)\b.*\bonly\b|\bdon['’]?t\s+(?:run|install)\b",text,re.I) else "install")
        return SoftwareRequest(request,token,name,action)
    @staticmethod
    def _normal(value): return re.sub(r"[^a-z0-9]+","",str(value or "").lower())
    def _search(self,name,provider,exe,args):
        if not exe: return [],{"provider":provider,"status":"unavailable","query":name}
        rc,out=run_command([exe]+args,30); rows=[]
        for line in out.splitlines():
            m=re.match(r"^\s*(.+?)\s{2,}([\w.-]+\.[\w.-]+)\s{2,}([\w.+-]+)(?:\s{2,}(\S+))?\s*$",line)
            if m:
                title,pkg,ver,source=m.groups(); source=source or provider; target=self._normal(name); score=100 if self._normal(title.strip())==target else 0
                rows.append({"name":title.strip(),"package":pkg,"version":ver,"source":source,"score":score})
        return rows,{"provider":provider,"status":"available","returncode":rc,"query":name,"output":out}
    def _discover(self,name):
        rows,winget=self._search(name,"winget",shutil.which("winget"),["search","--name",name,"--source","winget","--accept-source-agreements","--disable-interactivity"])
        attempts=[winget]
        if not rows:
            rows,choco=self._search(name,"chocolatey",shutil.which("choco"),["search",name,"--limit-output","--no-color"]); attempts.append(choco)
        return sorted(rows,key=lambda x:(-x["score"],x["package"])),attempts
    def resolve_source(self,request):
        package,exe=PACKAGES.get(request.canonical_name,(request.canonical_name,request.canonical_name)); installed=self.find_executable(request,SoftwareSource("",package=package,executable=exe))
        if installed: return SoftwareSource("already_installed",package=package,repository="local executable",executable=installed,confidence="high",evidence=[{"kind":"path","value":installed}],reason="Executable already present; verify without reinstalling.")
        if request.canonical_name in PACKAGES and shutil.which("winget"):
            rc,out=run_command([shutil.which("winget"),"show","--id",package,"--exact","--source","winget","--scope","user","--disable-interactivity"],30)
            version=re.search(r"(?m)^Version:\s*([\w.+-]+)\s*$",out)
            if rc==0 and package in out and version:
                return SoftwareSource("winget",package=package,repository="winget",version=version.group(1),helper=shutil.which("winget"),confidence="high",evidence=[{"provider":"winget","query":package,"output":out}],reason="Exact curated WinGet metadata fast path.")
        rows,attempts=self._discover(request.canonical_name)
        if attempts and rows: attempts[0]["candidates"]=rows
        if rows and rows[0]["score"]>=100 and (len(rows)==1 or rows[0]["score"]>rows[1]["score"]):
            item=rows[0]; method="winget" if item["source"].lower()=="winget" else "chocolatey"; return SoftwareSource(method,package=item["package"],repository=item["source"],version=item["version"],helper=shutil.which(method) or "",confidence="high",evidence=[item],discovery=attempts,reason="Deterministic exact-name package match.")
        if request.canonical_name=="jq" and platform.machine().lower() in {"amd64","x86_64"}: return SoftwareSource("official_upstream_artifact",package="jq.exe",repository="official upstream",version="1.8.2",url=JQ_URL,checksum_sha256=JQ_SHA256,checksum_url=JQ_CHECKSUM_URL,confidence="high",evidence=attempts,discovery=attempts,reason="Verified official portable jq binary.")
        raise SoftwareResolutionError("No trusted Windows source established for "+request.canonical_name+".",attempts)
    def install_command(self,source):
        if source.method not in {"winget","chocolatey"} or not source.package or not re.fullmatch(r"[\w.+-]+",source.version): raise ValueError("Unreviewed package or missing exact version.")
        exe=shutil.which(source.method)
        if not exe or source.helper!=exe: raise ValueError("Package manager unavailable or changed; prepare a fresh plan.")
        if source.method=="chocolatey": return [exe,"install",source.package,"--version",source.version,"--yes","--no-progress"]
        return [exe,"install","--id",source.package,"--exact","--version",source.version,"--source","winget","--scope","user","--silent","--disable-interactivity","--accept-package-agreements","--accept-source-agreements","--no-upgrade"]
    def create_install_plan(self,request,source,work_dir):
        if source.method=="already_installed": return SoftwarePlan(actions=["verify"],expected_changes="none")
        if source.method in {"winget","chocolatey"}: return SoftwarePlan(actions=["install"],commands=[subprocess.list2cmdline(self.install_command(source))],expected_changes="Install exact discovered package version for this user.",verification_strategy=["--version"])
        if source.method!="official_upstream_artifact": raise ValueError("Unsupported Windows software source.")
        return SoftwarePlan(actions=["download"],commands=[f"download {source.url} to {work_dir/source.package}"],expected_changes="Create a SHA-256 verified portable executable.")
    def execute_install(self,request,source,plan,work_dir):
        if plan.commands!=self.create_install_plan(request,source,work_dir).commands: raise ValueError("Saved command changed; prepare a fresh plan.")
        if source.method in {"winget","chocolatey"}: rc,out=run_command(self.install_command(source),120); return {"returncode":rc,"output":out,"commands":[{"command":plan.commands[0],"returncode":rc,"output":out}]}
        target=work_dir/source.package; size,digest=download_verified(source.url,target,source.checksum_sha256); return {"returncode":0,"output":"Verified portable executable","artifacts":[SoftwareArtifact(source=source.url,destination=str(target),filename=target.name,size=size,checksum=digest)]}
    def find_executable(self,request,source):
        exe=(PACKAGES.get(request.canonical_name) or (request.canonical_name,request.canonical_name))[1]; candidates=[source.executable,shutil.which(exe),str(Path.home()/"AppData/Local/Microsoft/WinGet/Links"/exe)]
        if request.canonical_name=="git": candidates.append(str(Path.home())+"/AppData/Local/Programs/Git/cmd/git.exe")
        return next((x for x in candidates if x and Path(x).is_file()),None)
    def verification_candidates(self,request): return ["--version"]
    def usage_instructions(self,request,executable): return f'PowerShell: & "{executable}" --help'
    def update_instructions(self,source): return f"Request a reviewed update for {source.package}."
    def removal_instructions(self,source): return f"Remove {source.package} using the selected trusted provider."
