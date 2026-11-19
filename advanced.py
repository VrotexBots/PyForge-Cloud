"""PyForge Vision AI Studio advanced engine.

Uses an OpenAI-compatible Chat Completions API. Credentials are read only from
process environment; never returned by status endpoints or written into builds.
"""
from __future__ import annotations
import base64, json, os, re, shutil, subprocess, tempfile, urllib.error, urllib.request, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from configuration.config import STORAGE_DIR
from .router import _design_path, _validate_project, _now, _identify_image, REFERENCE_DIR, DESIGN_DIR, MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/vision", tags=["Vision AI Studio Advanced"])
ENGINE_DIR = STORAGE_DIR / "vision_studio" / "engine"
BUILDS_DIR = ENGINE_DIR / "builds"
for _p in (ENGINE_DIR, BUILDS_DIR):
    _p.mkdir(parents=True, exist_ok=True)
    try: os.chmod(_p, 0o700)
    except OSError: pass

class AnalyzeRequest(BaseModel):
    design_id: str
    reference_id: str | None = None

class AudioRequest(BaseModel):
    design_id: str
    filename: str = "voice.webm"
    mime_type: str = "audio/webm"
    audio_base64: str = Field(..., min_length=20, max_length=18_000_000)

class EditRequest(BaseModel):
    design_id: str
    instruction: str = Field(..., min_length=1, max_length=4000)

class BuildRequest(BaseModel):
    design_id: str
    app_name: str = Field(default="PyForge Generated App", max_length=80)

class TestRequest(BaseModel):
    design_id: str

class CompareRequest(BaseModel):
    design_id: str
    screenshot_data_url: str = Field(..., min_length=30, max_length=12_000_000)

class ProviderConfig(BaseModel):
    api_key: str = Field(..., min_length=12, max_length=500)
    base_url: str = Field(default="https://api.openai.com/v1", min_length=12, max_length=300)
    vision_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=100)
    audio_model: str = Field(default="whisper-1", min_length=1, max_length=100)


def _cfg():
    config_path = ENGINE_DIR / "provider.json"
    saved = {}
    try:
        if config_path.is_file() and not config_path.is_symlink():
            saved = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    key = os.getenv("PYFORGE_VISION_API_KEY", "").strip() or str(saved.get("api_key", "")).strip()
    base = os.getenv("PYFORGE_VISION_BASE_URL", str(saved.get("base_url", "https://api.openai.com/v1"))).strip().rstrip("/")
    model = os.getenv("PYFORGE_VISION_MODEL", str(saved.get("vision_model", "gpt-4o-mini"))).strip()
    audio_model = os.getenv("PYFORGE_VISION_AUDIO_MODEL", str(saved.get("audio_model", "whisper-1"))).strip()
    return key, base, model, audio_model


def _provider_json(messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 5000):
    key, base, model, _ = _cfg()
    if not key:
        raise HTTPException(503, "AI provider is not configured. Set PYFORGE_VISION_API_KEY, then restart PyForge API.")
    payload = json.dumps({"model": model, "messages": messages, "temperature": temperature,
                          "max_tokens": max_tokens, "response_format": {"type": "json_object"}}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=payload,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(x.get("text", "") for x in content if isinstance(x, dict))
        return json.loads(content)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", "replace")
        raise HTTPException(502, f"AI provider returned HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(502, f"AI provider connection failed: {exc}")
    except (KeyError, ValueError, IndexError) as exc:
        raise HTTPException(502, f"AI provider returned an invalid response: {exc}")


def _reference(design: dict, reference_id: str | None = None):
    rid = reference_id or design.get("original_reference_id")
    if not rid or rid not in design.get("reference_ids", []):
        raise HTTPException(404, "No reference image is linked to this design.")
    meta = REFERENCE_DIR / f"{rid}.json"
    if meta.is_symlink() or not meta.is_file(): raise HTTPException(404, "Reference metadata not found.")
    record = json.loads(meta.read_text(encoding="utf-8"))
    image = REFERENCE_DIR / record.get("image_file", "")
    if image.is_symlink() or not image.is_file() or image.resolve().parent != REFERENCE_DIR.resolve():
        raise HTTPException(404, "Reference image is unavailable.")
    return rid, record, image


def _save_design(directory: Path, meta: Path, design: dict):
    design["updated_at"] = _now()
    tmp = meta.with_name(".design.json.tmp")
    tmp.write_text(json.dumps(design, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600); tmp.replace(meta)


def _build_dir(design_id: str):
    return BUILDS_DIR / design_id


@router.post("/ai/config")
def save_provider_config(data: ProviderConfig):
    base=data.base_url.strip().rstrip("/")
    if not base.startswith("https://"):
        raise HTTPException(400,"Provider base URL must use HTTPS.")
    if not re.fullmatch(r"[A-Za-z0-9._:/-]+", data.vision_model) or not re.fullmatch(r"[A-Za-z0-9._:/-]+", data.audio_model):
        raise HTTPException(400,"Model names contain unsupported characters.")
    path=ENGINE_DIR/"provider.json"
    temporary=ENGINE_DIR/".provider.json.tmp"
    temporary.write_text(json.dumps({"api_key":data.api_key.strip(),"base_url":base,"vision_model":data.vision_model,"audio_model":data.audio_model},indent=2),encoding="utf-8")
    os.chmod(temporary,0o600); temporary.replace(path); os.chmod(path,0o600)
    return {"success":True,"configured":True,"provider":"OpenAI-compatible HTTPS API","base_url":base,"vision_model":data.vision_model,"audio_model":data.audio_model,"key_saved":"The API key is stored locally with owner-only file permissions and is never returned."}


@router.get("/ai/status")
def ai_status():
    key, base, model, audio_model = _cfg()
    return {"configured": bool(key), "provider": "OpenAI-compatible API" if key else "not_configured",
            "base_url": base, "vision_model": model, "audio_model": audio_model,
            "features": {"image_analysis": bool(key), "voice_transcription": bool(key),
                         "targeted_editing": bool(key), "application_generation": bool(key),
                         "pwa_packaging": True, "android_project_packaging": True,
                         "apk_compilation": shutil.which("gradle") is not None and bool(os.getenv("ANDROID_HOME"))}}


@router.post("/analyze")
def analyze_design(data: AnalyzeRequest):
    directory, meta, design = _design_path(data.design_id); _validate_project(design["project_name"])
    rid, record, image = _reference(design, data.reference_id)
    mime = record["mime_type"]
    encoded = base64.b64encode(image.read_bytes()).decode("ascii")
    prompt = """You are a screenshot-to-application design analysis engine. Return JSON only with keys: summary, page_type, viewport, layout, navigation, palette, typography, components, spacing, imagery, responsive_rules, interactions, accessibility, fidelity_constraints, ambiguities. Describe only visible evidence; mark uncertain details as uncertain. Do not redesign. The uploaded screenshot is the immutable design master. Preserve exact hierarchy, approximate geometry, visible wording, colors and component relationships. Identify all visible elements and their positions in normalized 0..1 coordinates where possible."""
    result = _provider_json([{"role":"system","content":prompt}, {"role":"user","content":[
        {"type":"text","text":f"Analyze this original reference for project {design['project_name']}. Reference ID {rid}."},
        {"type":"image_url","image_url":{"url":f"data:{mime};base64,{encoded}"}}]}], max_tokens=6000)
    design["analysis"] = {"reference_id":rid,"created_at":_now(),"result":result}
    design["status"] = "analyzed"
    _save_design(directory, meta, design)
    return {"success":True,"analysis":result,"design_id":data.design_id}


@router.post("/compare")
def compare_reconstruction(data: CompareRequest):
    directory,meta,design=_design_path(data.design_id); _validate_project(design["project_name"])
    rid,original_record,original_path=_reference(design)
    try:
        header,encoded=data.screenshot_data_url.split(",",1)
        generated=base64.b64decode(encoded,validate=True)
    except Exception: raise HTTPException(400,"Generated screenshot must be a valid base64 image data URL.")
    if len(generated)>MAX_IMAGE_BYTES: raise HTTPException(413,"Generated screenshot exceeds 8 MB.")
    generated_mime,_=_identify_image(generated)
    original_b64=base64.b64encode(original_path.read_bytes()).decode("ascii")
    generated_b64=base64.b64encode(generated).decode("ascii")
    result=_provider_json([
        {"role":"system","content":"Compare two screenshots of the same intended interface. Image one is the immutable master reference; image two is the generated result. Return JSON only with keys fidelity_score_0_to_100, layout_differences, color_differences, typography_differences, component_differences, content_differences, responsive_observations, preserved_elements, prioritized_fixes. Be evidence-based. Do not claim pixel-perfect matching. Score is an estimate, not a guarantee."},
        {"role":"user","content":[{"type":"text","text":"Image 1 is the original master reference. Image 2 is the generated screenshot. Compare them and report differences without modifying either image."},{"type":"image_url","image_url":{"url":f"data:{original_record['mime_type']};base64,{original_b64}"}},{"type":"image_url","image_url":{"url":f"data:{generated_mime};base64,{generated_b64}"}}]}
    ],max_tokens=5000)
    report={"created_at":_now(),"reference_id":rid,"result":result}
    design.setdefault("visual_comparisons",[]).append(report); _save_design(directory,meta,design)
    return {"success":True,"comparison":report}


@router.post("/transcribe")
def transcribe_audio(data: AudioRequest):
    directory, meta, design = _design_path(data.design_id); _validate_project(design["project_name"])
    key, base, _, audio_model = _cfg()
    if not key: raise HTTPException(503,"Voice transcription needs PYFORGE_VISION_API_KEY configured.")
    try: raw = base64.b64decode(data.audio_base64, validate=True)
    except Exception: raise HTTPException(400,"Invalid audio encoding.")
    if not raw or len(raw) > 12*1024*1024: raise HTTPException(413,"Audio must be between 1 byte and 12 MB.")
    ext = ".webm" if "webm" in data.mime_type else ".mp4" if "mp4" in data.mime_type else ".wav" if "wav" in data.mime_type else ".m4a"
    boundary = "----PyForge" + uuid.uuid4().hex
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", data.filename)[:100] or "voice"+ext
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\n{audio_model}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {data.mime_type}\r\n\r\n".encode()+raw+b"\r\n",
        f"--{boundary}--\r\n".encode()]
    req=urllib.request.Request(base+"/audio/transcriptions",data=b"".join(parts),headers={"Authorization":"Bearer "+key,"Content-Type":"multipart/form-data; boundary="+boundary},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=120) as resp: result=json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc: raise HTTPException(502,f"Transcription provider HTTP {exc.code}: {exc.read(1000).decode('utf-8','replace')}")
    except Exception as exc: raise HTTPException(502,f"Transcription failed: {exc}")
    text=result.get("text","").strip()
    if not text: raise HTTPException(502,"Transcription returned no text.")
    audio_dir=directory/"voice_recordings"; audio_dir.mkdir(mode=0o700,exist_ok=True)
    audio_id=uuid.uuid4().hex; audio_path=audio_dir/(audio_id+ext)
    audio_path.write_bytes(raw); os.chmod(audio_path,0o600)
    entry={"id":uuid.uuid4().hex,"instruction":text,"source":"voice","created_at":_now(),"status":"transcribed_not_executed","audio_recording_id":audio_id}
    design.setdefault("instructions",[]).append(entry)
    design.setdefault("audio_recordings",[]).append({"id":audio_id,"mime_type":data.mime_type,"size_bytes":len(raw),"created_at":_now(),"transcription":text})
    _save_design(directory,meta,design)
    return {"success":True,"text":text,"instruction":entry,"audio_recording_id":audio_id}


@router.post("/edit")
def targeted_edit(data: EditRequest):
    directory, meta, design = _design_path(data.design_id); _validate_project(design["project_name"])
    analysis=design.get("analysis",{}).get("result")
    if not analysis: raise HTTPException(409,"Analyze the original reference before requesting AI edits.")
    instruction=data.instruction.strip()
    system="""You are a precision UI editor. Return JSON only: {"change_summary": string, "html": string, "css": string, "js": string, "changed_elements": [strings], "preserved_elements": [strings], "questions": [strings]}. Generate a complete self-contained page fragment in html, styles in css and optional behavior in js. The user's instruction is the only authorization to change design. Preserve every element not explicitly requested. Do not invent new visual features, copy unrelated brands, or remove content. If ambiguous, put a concise question in questions and leave the current design unchanged. Use semantic accessible HTML. The reference image and analysis are authoritative."""
    previous=design.get("editor",{})
    rid, ref_record, ref_image = _reference(design)
    encoded_image = base64.b64encode(ref_image.read_bytes()).decode("ascii")
    user_content = [
        {"type":"text","text":json.dumps({"reference_analysis":analysis,"previous_editor_state":previous,"explicit_user_instruction":instruction,"project":design["project_name"],"mode":"If no previous editor exists, reconstruct the initial page from the screenshot. Otherwise make only the requested targeted changes."},ensure_ascii=False)},
        {"type":"image_url","image_url":{"url":f"data:{ref_record['mime_type']};base64,{encoded_image}"}}
    ]
    result=_provider_json([{"role":"system","content":system},{"role":"user","content":user_content}],max_tokens=9000)
    if result.get("questions"):
        design.setdefault("edit_history",[]).append({"instruction":instruction,"created_at":_now(),"status":"needs_clarification","questions":result["questions"]})
        _save_design(directory,meta,design)
        return {"success":False,"needs_clarification":True,"questions":result["questions"],"change_summary":result.get("change_summary","")}
    for field in ("html","css","js"):
        if not isinstance(result.get(field,""),str): raise HTTPException(502,"AI edit response did not contain valid source strings.")
    version={"id":uuid.uuid4().hex,"created_at":_now(),"instruction":instruction,"result":result}
    design.setdefault("versions",[]).append(version); design["editor"]={"html":result.get("html",""),"css":result.get("css",""),"js":result.get("js",""),"version_id":version["id"]}
    design.setdefault("edit_history",[]).append({"instruction":instruction,"created_at":_now(),"status":"applied_to_draft","version_id":version["id"]})
    design["status"]="edited_draft"; _save_design(directory,meta,design)
    return {"success":True,"version":version,"editor":design["editor"],"change_summary":result.get("change_summary",""),"changed_elements":result.get("changed_elements",[]),"preserved_elements":result.get("preserved_elements",[])}


@router.post("/build")
def build_application(data: BuildRequest):
    directory, meta, design = _design_path(data.design_id); project_path=_validate_project(design["project_name"])
    analysis=design.get("analysis",{}).get("result")
    editor=design.get("editor")
    if not analysis or not editor: raise HTTPException(409,"Complete image analysis and at least one AI reconstruction/edit before building.")
    build=_build_dir(data.design_id); build.mkdir(parents=True,exist_ok=True)
    app_name=re.sub(r"[^A-Za-z0-9 _-]","",data.app_name).strip()[:80] or "PyForge App"
    html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#101827"><link rel="manifest" href="manifest.webmanifest"><link rel="stylesheet" href="assets/app.css"><title>'''+app_name.replace("<","&lt;")+'''</title></head><body><main id="app">'''+editor["html"]+'''</main><script src="assets/app.js"></script><script>if('serviceWorker' in navigator)navigator.serviceWorker.register('./sw.js').catch(()=>{});</script></body></html>'''
    assets=build/"assets"; assets.mkdir(exist_ok=True)
    (build/"index.html").write_text(html,encoding="utf-8")
    css_text=editor.get("css", ""); js_text=editor.get("js", "")
    (build/"app.css").write_text(css_text,encoding="utf-8")
    (build/"app.js").write_text(js_text,encoding="utf-8")
    (assets/"app.css").write_text(css_text,encoding="utf-8")
    (assets/"app.js").write_text(js_text,encoding="utf-8")
    (assets/"manifest.webmanifest").write_text("{}",encoding="utf-8")
    (assets/"sw.js").write_text("",encoding="utf-8")
    icon_svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="100" fill="#101827"/><path d="M100 350 256 80l156 270H100Z" fill="#5278ff"/><circle cx="256" cy="300" r="65" fill="#a78bfa"/></svg>'
    (assets/"icon.svg").write_text(icon_svg,encoding="utf-8")
    manifest={"name":app_name,"short_name":app_name[:20],"start_url":"./","display":"standalone","background_color":"#101827","theme_color":"#101827","icons":[{"src":"assets/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}
    (build/"manifest.webmanifest").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    (build/"sw.js").write_text("const C='pyforge-"+data.design_id+"-v1';self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['./','./index.html','./assets/app.css','./assets/app.js','./manifest.webmanifest','./assets/icon.svg']))));self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));});",encoding="utf-8")
    # Generated Python backend starter, separate from the main PyForge server.
    backend_result = _provider_json([
        {"role":"system","content":"Generate a safe, minimal FastAPI backend source for the described UI. Return JSON only with key backend_py containing complete valid Python source. Include typed request models, useful API endpoints implied by the interface, input validation, no secrets, no wildcard credentialed CORS, no destructive file operations, and a health endpoint. Use in-memory placeholder data only where persistence requirements are unknown and clearly comment it. Do not import PyForge internals."},
        {"role":"user","content":json.dumps({"app_name":app_name,"reference_analysis":analysis,"generated_frontend_html":editor.get("html","")[:12000],"frontend_javascript":editor.get("js","")[:8000]},ensure_ascii=False)}
    ],max_tokens=6000)
    backend_code=backend_result.get("backend_py", "")
    if not isinstance(backend_code,str) or "FastAPI" not in backend_code or "def " not in backend_code:
        raise HTTPException(502,"AI provider did not return a valid FastAPI backend source. Build was not marked complete.")

    (build/"backend.py").write_text(backend_code,encoding="utf-8")
    (build/"requirements.txt").write_text("fastapi>=0.99\nuvicorn>=0.20\n",encoding="utf-8")
    readme=f"# {app_name}\n\nGenerated by PyForge Vision AI Studio.\n\nFrontend: serve this folder over HTTP. Backend: `uvicorn backend:app --host 127.0.0.1 --port 8100`. Review security and API permissions before public deployment.\n"
    (build/"README.md").write_text(readme,encoding="utf-8")
    # Keep generated work in isolated storage until explicit export.
    design["build_status"]="built"; design["build"]={"created_at":_now(),"path":str(build),"app_name":app_name,"project_name":design["project_name"]}; _save_design(directory,meta,design)
    return {"success":True,"build_status":"built","files":[p.name for p in build.iterdir()],"preview_url":f"/api/vision/builds/{data.design_id}/preview","design_id":data.design_id}


@router.get("/builds/{design_id}/preview")
def preview_build(design_id: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    path=_build_dir(design_id)/"index.html"
    if not path.is_file(): raise HTTPException(404,"Build not found.")
    from fastapi.responses import FileResponse
    return FileResponse(path,media_type="text/html",headers={"Cache-Control":"no-store"})


@router.get("/builds/{design_id}/assets/{filename}")
def preview_asset(design_id: str, filename: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    if filename not in {"app.css", "app.js", "manifest.webmanifest", "sw.js", "icon.svg"}:
        raise HTTPException(404, "Asset not found.")
    path=_build_dir(design_id)/"assets"/filename
    if not path.is_file(): raise HTTPException(404, "Asset not found.")
    from fastapi.responses import FileResponse
    media={"app.css":"text/css","app.js":"application/javascript","manifest.webmanifest":"application/manifest+json","sw.js":"application/javascript","icon.svg":"image/svg+xml"}[filename]
    return FileResponse(path,media_type=media,headers={"Cache-Control":"no-store"})


@router.get("/builds/{design_id}/{filename}")
def preview_root_asset(design_id: str, filename: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    if filename not in {"manifest.webmanifest", "sw.js"}: raise HTTPException(404, "Asset not found.")
    path=_build_dir(design_id)/filename
    if not path.is_file(): raise HTTPException(404, "Asset not found.")
    from fastapi.responses import FileResponse
    media="application/manifest+json" if filename.endswith("webmanifest") else "application/javascript"
    return FileResponse(path,media_type=media,headers={"Cache-Control":"no-store"})


@router.post("/test")
def test_build(data: TestRequest):
    _,_,design=_design_path(data.design_id); _validate_project(design["project_name"])
    build=_build_dir(data.design_id)
    if not build.is_dir(): raise HTTPException(409,"Build the application first.")
    required=["index.html","app.css","app.js","manifest.webmanifest","sw.js","backend.py","requirements.txt"]
    results=[]
    for name in required:
        p=build/name; results.append({"test":f"file:{name}","passed":p.is_file() and p.stat().st_size>=0})
    html=(build/"index.html").read_text(encoding="utf-8")
    results.extend([{"test":"html:doctype","passed":html.lower().startswith("<!doctype html>")},{"test":"pwa:manifest-link","passed":"manifest.webmanifest" in html},{"test":"pwa:service-worker","passed":"serviceWorker" in html}])
    for asset in (build/"assets"/"app.css", build/"assets"/"app.js", build/"assets"/"icon.svg"):
        results.append({"test":f"asset:{asset.name}","passed":asset.is_file()})
    try:
        import ast
        ast.parse((build/"backend.py").read_text(encoding="utf-8")); results.append({"test":"python-backend:syntax","passed":True})
    except SyntaxError as exc: results.append({"test":"python-backend:syntax","passed":False,"detail":str(exc)})
    node=shutil.which("node")
    if node:
        try:
            check=subprocess.run([node,"--check",str(build/"assets"/"app.js")],capture_output=True,text=True,timeout=30)
            results.append({"test":"javascript:syntax","passed":check.returncode==0,"detail":(check.stderr or "")[-1000:]})
        except Exception as exc: results.append({"test":"javascript:syntax","passed":False,"detail":str(exc)})
    else:
        results.append({"test":"javascript:syntax","passed":False,"skipped":True,"detail":"Node.js is not installed; JavaScript syntax test skipped."})
    summary={"passed":sum(1 for x in results if x["passed"]),"failed":sum(1 for x in results if not x["passed"] and not x.get("skipped")),"skipped":sum(1 for x in results if x.get("skipped")),"tests":results,"created_at":_now()}
    design["last_test_report"]=summary; design["build_status"]="tested" if summary["failed"]==0 else "test_failed"
    directory,meta,_=_design_path(data.design_id); _save_design(directory,meta,design)
    return summary


@router.post("/repair/{design_id}")
def repair_failed_build(design_id: str):
    directory,meta,design=_design_path(design_id); _validate_project(design["project_name"])
    report=design.get("last_test_report")
    if not report or not report.get("failed"): raise HTTPException(409,"There are no recorded failed tests to repair.")
    editor=design.get("editor")
    if not editor: raise HTTPException(409,"No generated editor source exists.")
    repaired=_provider_json([
        {"role":"system","content":"Repair the supplied generated application source based on its test failures. Return JSON only with complete keys html, css, js, backend_py and repair_summary. Preserve the design and all working behavior. Do not remove features merely to silence tests. Produce syntactically valid source."},
        {"role":"user","content":json.dumps({"test_report":report,"html":editor.get("html",""),"css":editor.get("css",""),"js":editor.get("js",""),"backend_py":(_build_dir(design_id)/"backend.py").read_text(encoding="utf-8") if (_build_dir(design_id)/"backend.py").is_file() else ""},ensure_ascii=False)}
    ],max_tokens=9000)
    for key in ("html","css","js"):
        if not isinstance(repaired.get(key),str): raise HTTPException(502,"AI repair did not return complete frontend source.")
    version={"id":uuid.uuid4().hex,"created_at":_now(),"instruction":"Automatic repair based on failed tests","result":{"html":repaired["html"],"css":repaired["css"],"js":repaired["js"],"change_summary":repaired.get("repair_summary","")}}
    design.setdefault("versions",[]).append(version); design["editor"]={"html":repaired["html"],"css":repaired["css"],"js":repaired["js"],"version_id":version["id"]}
    _save_design(directory,meta,design)
    built=build_application(BuildRequest(design_id=design_id,app_name=design.get("title") or "PyForge Generated App"))
    backend_code=repaired.get("backend_py")
    if isinstance(backend_code,str) and "FastAPI" in backend_code:
        import ast
        try:
            ast.parse(backend_code)
            (_build_dir(design_id)/"backend.py").write_text(backend_code,encoding="utf-8")
        except SyntaxError:
            pass
    return {"success":True,"repair_summary":repaired.get("repair_summary",""),"build":built,"message":"AI repair draft rebuilt. Run automatic tests again before export."}


@router.post("/publish/{design_id}")
def publish_build(design_id: str):
    _,_,design=_design_path(design_id); project_path=_validate_project(design["project_name"])
    build=_build_dir(design_id)
    if not build.is_dir(): raise HTTPException(409,"Build the application first.")
    report=design.get("last_test_report")
    if not report or report.get("failed",1): raise HTTPException(409,"Run and pass automatic tests before saving into the project.")
    destination=project_path/"pyforge_vision_apps"/design_id
    if destination.exists() or destination.is_symlink(): raise HTTPException(409,"This design already has a published project folder. Use a new design/version to avoid overwriting it.")
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(build,destination,symlinks=False)
    return {"success":True,"project_name":design["project_name"],"relative_path":str(destination.relative_to(project_path)),"message":f"Tested application saved into {design['project_name']}/{destination.relative_to(project_path)}. Existing project files were not overwritten."}


@router.get("/export/{design_id}")
def export_build(design_id: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    build=_build_dir(design_id)
    if not build.is_dir(): raise HTTPException(404,"Build not found.")
    report=design.get("last_test_report")
    if not report or report.get("failed",1): raise HTTPException(409,"Run and pass automatic tests before exporting.")
    out=ENGINE_DIR/f"{design_id}-pwa.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for f in build.rglob("*"):
            if f.is_file(): z.write(f,f.relative_to(build))
    from fastapi.responses import FileResponse
    return FileResponse(out,filename=f"{design_id}-pwa.zip",media_type="application/zip")


@router.post("/android/{design_id}")
def android_package(design_id: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    build=_build_dir(design_id)
    if not build.is_dir(): raise HTTPException(409,"Build the PWA before creating Android package source.")
    android=build/"android-wrapper"; (android/"app/src/main/assets/public").mkdir(parents=True,exist_ok=True)
    public_dir=android/"app/src/main/assets/public"
    for f in build.iterdir():
        if f.is_file(): shutil.copy2(f,public_dir/f.name)
        elif f.is_dir() and f.name != "android-wrapper": shutil.copytree(f,public_dir/f.name,dirs_exist_ok=True)
    (android/"settings.gradle").write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name='PyForgeVisionApp'\ninclude ':app'\n",encoding="utf-8")
    (android/"build.gradle").write_text("plugins { id 'com.android.application' version '8.5.2' apply false }\n",encoding="utf-8")
    (android/"app/build.gradle").write_text("plugins { id 'com.android.application' }\nandroid { namespace 'com.pyforge.generated'; compileSdk 35; defaultConfig { applicationId 'com.pyforge.generated'; minSdk 23; targetSdk 35; versionCode 1; versionName '1.0' } }\n",encoding="utf-8")
    manifest=android/"app/src/main/AndroidManifest.xml"; manifest.write_text('<?xml version="1.0" encoding="utf-8"?><manifest xmlns:android="http://schemas.android.com/apk/res/android"><uses-permission android:name="android.permission.INTERNET"/><application android:theme="@android:style/Theme.Material.Light.NoActionBar" android:label="PyForge App"><activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>',encoding="utf-8")
    java=android/"app/src/main/java/com/pyforge/generated/MainActivity.java"; java.parent.mkdir(parents=True,exist_ok=True)
    java.write_text('package com.pyforge.generated;\nimport android.app.Activity;import android.os.Bundle;import android.webkit.WebView;import android.webkit.WebSettings;\npublic class MainActivity extends Activity { public void onCreate(Bundle b){super.onCreate(b);WebView w=new WebView(this);WebSettings s=w.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);setContentView(w);w.loadUrl("file:///android_asset/public/index.html");}}',encoding="utf-8")
    out=ENGINE_DIR/f"{design_id}-android-source.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        for f in android.rglob("*"):
            if f.is_file(): z.write(f,f.relative_to(android))
    apk_path=android/"app/build/outputs/apk/debug/app-debug.apk"
    apk_compiled=False; compile_message="Android project source ZIP created. Android SDK/JDK/Gradle are required to compile an APK."
    if shutil.which("gradle") and os.getenv("ANDROID_HOME"):
        try:
            result=subprocess.run(["gradle","--no-daemon","assembleDebug"],cwd=str(android),capture_output=True,text=True,timeout=900)
            apk_compiled=result.returncode==0 and apk_path.is_file()
            compile_message="Debug APK compiled successfully." if apk_compiled else "Gradle was available but APK compilation failed: "+(result.stderr or result.stdout)[-1200:]
        except Exception as exc: compile_message="APK compilation could not complete: "+str(exc)
    return {"success":True,"message":compile_message,"apk_compiled":apk_compiled,"apk_compiler_available":bool(shutil.which("gradle") and os.getenv("ANDROID_HOME")),"download":"/api/vision/android-export/"+design_id}


@router.get("/android-apk/{design_id}")
def download_android_apk(design_id: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    path=_build_dir(design_id)/"android-wrapper/app/build/outputs/apk/debug/app-debug.apk"
    if not path.is_file(): raise HTTPException(404,"APK has not been compiled. Download the Android project source and build it with Android SDK/Gradle.")
    from fastapi.responses import FileResponse
    return FileResponse(path,filename="pyforge-app-debug.apk",media_type="application/vnd.android.package-archive")


@router.get("/android-export/{design_id}")
def download_android_source(design_id: str):
    _,_,design=_design_path(design_id); _validate_project(design["project_name"])
    path=ENGINE_DIR/f"{design_id}-android-source.zip"
    if not path.is_file(): raise HTTPException(404,"Create Android package source first.")
    from fastapi.responses import FileResponse
    return FileResponse(path,filename=f"{design_id}-android-source.zip",media_type="application/zip")
