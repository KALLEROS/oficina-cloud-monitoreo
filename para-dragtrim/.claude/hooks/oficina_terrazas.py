#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Avisa a la Oficina de Calleros qué hace Claude en la tableta Android de Alberto Terrazas.

Solo publica un archivito (oficina/estado-terrazas.json) en la rama aparte
`claude/oficina-estado`. NO toca la rama de trabajo, ni los archivos del proyecto, ni el
historial: arma el commit "por fuera" con un índice temporal.

No hace ningún trabajo. Si algo falla, se calla para no estorbar.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

RAMA = "claude/oficina-estado"
GUARDA = os.path.join(tempfile.gettempdir(), "oficina_terrazas.json")
CADA = 15                        # segundos mínimos entre envíos (salvo al terminar)
MAX_ARCHIVOS = 40

QUE = {
    "Read": ("biblioteca", "Leyendo {f}"), "Grep": ("biblioteca", "Buscando en el código"),
    "Glob": ("biblioteca", "Buscando archivos"), "Write": ("escritorio", "Creando {f}"),
    "Edit": ("escritorio", "Editando {f}"), "NotebookEdit": ("escritorio", "Editando {f}"),
    "WebSearch": ("internet", "Buscando en internet"), "WebFetch": ("internet", "Leyendo una página"),
    "Agent": ("sala de juntas", "Pidiendo ayuda a un ayudante"), "Task": ("sala de juntas", "Pidiendo ayuda a un ayudante"),
}


def ahora():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def corto(texto, palabras=10, letras=60):
    t = " ".join(str(texto or "").split()[:palabras])
    return t if len(t) <= letras else t[:letras - 1] + "…"


def git(*args, entrada=None, env=None):
    r = subprocess.run(["git", *args], capture_output=True, env=env, timeout=40,
                       input=entrada.encode("utf-8") if entrada is not None else None)   # bytes: sin \r\n de Windows
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:200])
    return r.stdout.decode("utf-8", "replace").strip()


def leer_guarda(ses):
    try:
        with open(GUARDA.replace(".json", f"_{ses}.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"archivos": [], "enviado": 0}


def guardar_guarda(ses, g):
    with open(GUARDA.replace(".json", f"_{ses}.json"), "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False)


def titulo_sesion(d):
    """El título que tiene la sesión en Claude (sale del transcript), p. ej. "UI" o "Drag Trim"."""
    ruta = d.get("transcript_path")
    if not ruta:
        return None
    try:
        with open(ruta, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 2_000_000))
            cola = f.read().decode("utf-8", "ignore")
        hallados = re.findall(r'"customTitle"\s*:\s*"((?:[^"\\]|\\.)*)"', cola)
        return json.loads('"' + hallados[-1] + '"').strip() or None if hallados else None
    except Exception:
        return None


def remoto():
    """Lo que ya publicaron las OTRAS sesiones de la tableta (para no borrarlas)."""
    try:
        git("fetch", "-q", "--depth=1", "origin", f"+refs/heads/{RAMA}:refs/oficina/t")
        return json.loads(git("show", "refs/oficina/t:oficina/estado-terrazas.json"))
    except Exception:
        return {}


def viejo(fecha, minutos=30):
    try:
        t = datetime.strptime(str(fecha), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() > minutos * 60
    except Exception:
        return True


def publicar(mio, mis_archivos):
    """Junta mi monito con los de las otras sesiones y publica un solo archivo."""
    r = remoto()
    otros = [a for a in (r.get("agentes") or ([r["agente"]] if r.get("agente") else []))
             if a.get("id") != mio["id"] and a.get("id") != "terrazas-tableta" and not viejo(a.get("actualizado"))]
    archivos, vistos = [], set()
    for f in sorted(mis_archivos + list(r.get("archivos_recientes") or []), key=lambda x: str(x.get("fecha")), reverse=True):
        if f.get("nombre") not in vistos:
            vistos.add(f.get("nombre"))
            archivos.append(f)
    datos = {"actualizado": ahora(), "agentes": otros + [mio], "archivos_recientes": archivos[:MAX_ARCHIVOS]}
    texto = json.dumps(datos, ensure_ascii=False, indent=2) + "\n"
    blob = git("hash-object", "-w", "--stdin", entrada=texto)
    sub = git("mktree", entrada=f"100644 blob {blob}\testado-terrazas.json\n")
    raiz = git("mktree", entrada=f"040000 tree {sub}\toficina\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="Oficina Terrazas", GIT_AUTHOR_EMAIL="oficina@localhost",
               GIT_COMMITTER_NAME="Oficina Terrazas", GIT_COMMITTER_EMAIL="oficina@localhost")
    commit = git("commit-tree", raiz, "-m", "estado de la tableta", env=env)
    git("push", "-q", "-f", "origin", f"{commit}:refs/heads/{RAMA}")


def main():
    d = json.loads(sys.stdin.buffer.read().decode("utf-8-sig", "replace") or "{}")
    if d.get("agent_id"):
        return                                           # los ayudantes no salen como monitos aparte
    ses = re.sub(r"[^A-Za-z0-9]", "", str(d.get("session_id") or "x"))[:8] or "x"
    ev = d.get("hook_event_name")
    tool = d.get("tool_name") or ""
    inp = d.get("tool_input") or {}
    g = leer_guarda(ses)
    area, actividad, estado, urgente = "terrazas", None, "trabajando", False

    if ev == "PreToolUse":
        ruta = inp.get("file_path") or inp.get("notebook_path") or ""
        nombre = os.path.basename(ruta) if ruta else ""
        if tool in QUE:
            actividad = QUE[tool][1].format(f=nombre or "un archivo")
        elif tool == "Bash":
            actividad = inp.get("description") or "Usando la terminal"
        elif tool == "Workflow":
            g["ultra"] = True
            actividad = "Trabajando en modo Ultra"
        else:
            actividad = "Trabajando"
        if tool in ("Write", "Edit", "NotebookEdit") and ruta:
            rel = os.path.relpath(ruta, d.get("cwd") or os.getcwd()).replace("\\", "/")
            if not rel.startswith("..") and "/.obsidian" not in "/" + rel:
                g["archivos"] = [f for f in g["archivos"] if f.get("nombre") != rel]
                g["archivos"].insert(0, {"nombre": rel, "origen": "tableta-android", "area": "terrazas",
                                         "fecha": ahora(), "tipo": "creado" if tool == "Write" else "editado",
                                         "sesion": ses})
                del g["archivos"][MAX_ARCHIVOS:]
    elif ev == "UserPromptSubmit":
        actividad = "Leyendo el mensaje de Terrazas"
        g["ultra"] = False
    elif ev in ("Stop", "SessionStart", "SessionEnd") or (ev == "Notification" and d.get("notification_type") == "idle_prompt"):
        actividad, estado, urgente = "Esperando instrucciones", "esperando", True
        g["ultra"] = False
    elif ev == "Notification":
        actividad, estado = "Esperando permiso", "esperando"
    else:
        return

    nombre = (titulo_sesion(d) or g.get("nombre") or f"DragTree {ses[:4]}")[:18]
    g["nombre"] = nombre
    mio = {"id": f"terrazas-{ses}", "nombre": nombre, "persona": "Alberto Terrazas", "area": area,
           "actividad": corto(actividad), "estado": estado,
           "modo": "ultra" if g.get("ultra") and estado == "trabajando" else "normal",
           "dispositivo": "tableta-android", "origen": "tableta-android", "actualizado": ahora()}
    if urgente or time.time() - g.get("enviado", 0) >= CADA:
        try:
            publicar(mio, g["archivos"])
        except Exception:
            time.sleep(2)
            publicar(mio, g["archivos"])         # otra sesión publicó al mismo tiempo: un reintento
        g["enviado"] = time.time()
    guardar_guarda(ses, g)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
