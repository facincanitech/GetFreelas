"""
GetFreelas Scraper
Busca vagas em RemoteOK e Remotive, pontua com Ollama e publica no GitHub.
Rode manualmente ou agende no Task Scheduler do Windows.
"""

import json
import re
import time
import hashlib
import base64
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CFG_FILE = BASE_DIR / "config.json"

with open(CFG_FILE, encoding="utf-8") as f:
    CFG = json.load(f)

GH_TOKEN   = CFG["github_token"]
GH_REPO    = CFG["github_repo"]
GH_BRANCH  = CFG["github_branch"]
OLLAMA_URL = CFG["ollama_url"]
MODEL      = CFG["ollama_model"]
MAX_JOBS   = CFG["max_jobs"]
SCORE_MIN  = CFG["score_minimo"]
BOOST      = [w.lower() for w in CFG["palavras_boost"]]
BLOCK      = [w.lower() for w in CFG["palavras_block"]]

AVATAR_COLORS = ["#0f6cbd","#8764b8","#107c10","#d13438","#ca5010","#038387"]

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def fetch_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "GetFreelas-Scraper/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def ago(date_str):
    try:
        if isinstance(date_str, (int, float)):
            dt = datetime.fromtimestamp(date_str, tz=timezone.utc)
        else:
            date_str = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(date_str)
        diff = datetime.now(timezone.utc) - dt
        h = int(diff.total_seconds() / 3600)
        if h < 1:   return "há menos de 1h"
        if h < 24:  return f"há {h}h"
        d = h // 24
        if d == 1:  return "há 1 dia"
        return f"há {d} dias"
    except:
        return "recente"

def job_id(source, raw_id):
    return int(hashlib.md5(f"{source}{raw_id}".encode()).hexdigest()[:8], 16)

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()

def categorize(tags, title, desc):
    text = " ".join(tags + [title, desc]).lower()
    if any(w in text for w in ["python","javascript","typescript","react","vue","node","flutter","backend","frontend","devops","software","developer","engineer","data","ml","ai","cloud"]):
        return "tech"
    if any(w in text for w in ["design","figma","ui","ux","graphic","illustrator","photoshop","brand","logo","motion"]):
        return "design"
    if any(w in text for w in ["write","writing","writer","content","copywriter","editor","seo","blog","article"]):
        return "texto"
    if any(w in text for w in ["video","audio","podcast","youtube","editing","animation","3d"]):
        return "audio"
    if any(w in text for w in ["marketing","social media","ads","campaign","growth","email"]):
        return "design"
    return "tech"

def urgency_from_date(date_str):
    try:
        if isinstance(date_str, (int, float)):
            dt = datetime.fromtimestamp(date_str, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(date_str.replace("Z","+00:00"))
        diff = datetime.now(timezone.utc) - dt
        h = int(diff.total_seconds() / 3600)
        if h < 12:  return "hot"
        if h < 48:  return "new"
        return "normal"
    except:
        return "normal"

def pay_str(salary_min, salary_max):
    if salary_min and salary_max:
        return f"${salary_min:,}–${salary_max:,}/ano"
    if salary_min:
        return f"A partir de ${salary_min:,}/ano"
    return "A combinar"

def pay_num(salary_min, salary_max):
    if salary_min: return salary_min
    if salary_max: return salary_max
    return 0

def quick_score(job):
    text = (job.get("title","") + " " + " ".join(job.get("tags",[])) + " " + job.get("desc","")).lower()
    score = 5
    for w in BOOST:
        if w in text: score += 1
    for w in BLOCK:
        if w in text: score -= 3
    return max(0, min(10, score))

# ─────────────────────────────────────────
# SOURCES
# ─────────────────────────────────────────
def fetch_remoteok():
    print("🔍 Buscando RemoteOK...")
    try:
        data = fetch_json("https://remoteok.com/api", headers={
            "User-Agent": "GetFreelas-Scraper/1.0",
            "Accept": "application/json"
        })
        jobs = []
        for item in data:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            tags = item.get("tags", []) or []
            title = item.get("position", "")
            desc  = strip_html(item.get("description", ""))[:500]
            cat   = categorize(tags, title, desc)
            sal_min = item.get("salary_min") or 0
            sal_max = item.get("salary_max") or 0
            jobs.append({
                "id":        job_id("remoteok", item.get("id","")),
                "title":     title,
                "company":   item.get("company", "—"),
                "category":  cat,
                "type":      "freela",
                "desc":      desc,
                "req":       ", ".join(tags[:6]) if tags else "Ver descrição",
                "details":   f"Vaga remota global · Fonte: RemoteOK",
                "contact":   item.get("url", ""),
                "pay":       pay_str(sal_min, sal_max),
                "payNum":    pay_num(sal_min, sal_max),
                "payPeriod": "ano",
                "tags":      tags[:5],
                "location":  "Remoto",
                "urgency":   urgency_from_date(item.get("epoch", 0)),
                "avatar":    hash(item.get("company","")) % len(AVATAR_COLORS),
                "posted":    ago(item.get("epoch", 0)),
                "source":    "RemoteOK",
                "_raw_date": item.get("epoch", 0)
            })
        print(f"   ✓ {len(jobs)} vagas encontradas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro RemoteOK: {e}")
        return []

def fetch_remotive():
    print("🔍 Buscando Remotive...")
    try:
        data = fetch_json("https://remotive.com/api/remote-jobs?limit=100")
        jobs = []
        for item in data.get("jobs", []):
            tags  = item.get("tags", []) or []
            title = item.get("title", "")
            desc  = strip_html(item.get("description", ""))[:500]
            cat   = categorize(tags, title, desc)
            salary = item.get("salary", "") or ""
            jobs.append({
                "id":        job_id("remotive", item.get("id","")),
                "title":     title,
                "company":   item.get("company_name", "—"),
                "category":  cat,
                "type":      "freela",
                "desc":      desc,
                "req":       ", ".join(tags[:6]) if tags else "Ver descrição",
                "details":   f"Vaga remota · {item.get('candidate_required_location','Global')} · Fonte: Remotive",
                "contact":   item.get("url", ""),
                "pay":       salary if salary else "A combinar",
                "payNum":    0,
                "payPeriod": "combinado",
                "tags":      tags[:5],
                "location":  "Remoto",
                "urgency":   urgency_from_date(item.get("publication_date","")),
                "avatar":    hash(item.get("company_name","")) % len(AVATAR_COLORS),
                "posted":    ago(item.get("publication_date","")),
                "source":    "Remotive",
                "_raw_date": item.get("publication_date","")
            })
        print(f"   ✓ {len(jobs)} vagas encontradas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro Remotive: {e}")
        return []

# ─────────────────────────────────────────
# OLLAMA SCORING
# ─────────────────────────────────────────
def ollama_score(jobs):
    print(f"🤖 Pontuando {len(jobs)} vagas com Ollama ({MODEL})...")
    batch_size = 10
    for i in range(0, len(jobs), batch_size):
        batch = jobs[i:i+batch_size]
        lista = "\n".join([f"{j}: {b['title']} @ {b['company']} | tags: {','.join(b['tags'])}" for j,b in enumerate(batch)])
        prompt = f"""Você é um curador de vagas de freela para profissionais brasileiros.
Avalie cada vaga abaixo com uma nota de 0 a 10 baseada em:
- Relevância para freelancers brasileiros (remoto = bom)
- Qualidade da oportunidade
- Clareza e atratividade

Responda APENAS com JSON no formato: [{{"i":0,"score":7}},{{"i":1,"score":4}}...]

Vagas:
{lista}

JSON:"""
        try:
            payload = json.dumps({"model": MODEL, "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text = resp.get("response", "")
            match = re.search(r'\[.*?\]', text, re.DOTALL)
            if match:
                scores = json.loads(match.group())
                for s in scores:
                    idx = i + s.get("i", 0)
                    if idx < len(jobs):
                        jobs[idx]["score_ia"] = s.get("score", 5)
        except Exception as e:
            print(f"   ⚠ Ollama batch {i//batch_size+1} falhou ({e}), usando score rápido")
            for j in batch:
                if "score_ia" not in j:
                    j["score_ia"] = quick_score(j)
        time.sleep(0.5)
    print("   ✓ Pontuação concluída")
    return jobs

# ─────────────────────────────────────────
# GITHUB PUSH
# ─────────────────────────────────────────
def push_to_github(freelas_json):
    if not GH_TOKEN or GH_TOKEN == "SEU_TOKEN_AQUI":
        print("⚠ Token GitHub não configurado — salvando só localmente.")
        return False

    path    = "freelas.json"
    content = base64.b64encode(json.dumps(freelas_json, ensure_ascii=False, indent=2).encode("utf-8")).decode()
    api     = f"https://api.github.com/repos/{GH_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }

    # Busca SHA atual (necessário para update)
    sha = None
    try:
        req = urllib.request.Request(f"{api}?ref={GH_BRANCH}", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            sha = json.loads(r.read()).get("sha")
    except:
        pass

    body = {
        "message": f"chore: atualiza freelas.json — {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "content": content,
        "branch":  GH_BRANCH
    }
    if sha:
        body["sha"] = sha

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(api, data=payload, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print(f"   ✓ Push realizado → github.com/{GH_REPO}/blob/{GH_BRANCH}/{path}")
        return True
    except Exception as e:
        print(f"   ✗ Erro no push: {e}")
        return False

# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────
def main():
    print("\n" + "="*50)
    print("  GetFreelas Scraper")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("="*50 + "\n")

    # 1. Busca vagas
    all_jobs = fetch_remoteok() + fetch_remotive()
    print(f"\n📦 Total bruto: {len(all_jobs)} vagas\n")

    # 2. Deduplicação por ID
    seen = set()
    unique = []
    for j in all_jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            unique.append(j)

    # 3. Filtro rápido (remove bloqueadas)
    filtered = []
    for j in unique:
        text = (j["title"] + " " + j["desc"]).lower()
        if any(w in text for w in BLOCK):
            continue
        filtered.append(j)

    print(f"🔎 Após filtro: {len(filtered)} vagas\n")

    # 4. Score rápido pré-Ollama
    for j in filtered:
        j["score_ia"] = quick_score(j)

    # 5. Pega top candidatos pro Ollama (economiza tempo)
    filtered.sort(key=lambda x: x["score_ia"], reverse=True)
    top = filtered[:MAX_JOBS * 2]

    # 6. Ollama scoring
    try:
        top = ollama_score(top)
    except Exception as e:
        print(f"⚠ Ollama indisponível ({e}), usando score rápido para todos")

    # 7. Ordena e pega os melhores
    top.sort(key=lambda x: x.get("score_ia", 0), reverse=True)
    final = [j for j in top if j.get("score_ia", 0) >= SCORE_MIN][:MAX_JOBS]

    # 8. Remove campos internos
    for j in final:
        j.pop("_raw_date", None)
        j.pop("source", None)
        j["avatar"] = abs(j["avatar"]) % len(AVATAR_COLORS)

    print(f"\n✅ {len(final)} vagas selecionadas (score ≥ {SCORE_MIN})\n")

    # 9. Monta JSON final
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(final),
        "freelas": final
    }

    # 10. Salva localmente
    out_file = BASE_DIR.parent / "data" / "freelas.json"
    out_file.parent.mkdir(exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 Salvo em {out_file}")

    # 11. Push GitHub
    print("\n🚀 Enviando para GitHub...")
    push_to_github(output)

    print(f"\n🎉 Concluído — {len(final)} vagas publicadas\n")

if __name__ == "__main__":
    main()
