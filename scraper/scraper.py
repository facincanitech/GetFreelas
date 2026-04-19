"""
GetFreelas Scraper — Multi-source, sem IA
Busca vagas em RemoteOK, Remotive, Jooble e Adzuna.
Filtra, pontua por relevância e publica no GitHub.
"""

import json
import re
import hashlib
import base64
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

# Fix encoding no Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ─────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CFG_FILE = BASE_DIR / "config.json"

with open(CFG_FILE, encoding="utf-8") as f:
    CFG = json.load(f)

GH_TOKEN  = CFG.get("github_token", "")
GH_REPO   = CFG.get("github_repo", "")
GH_BRANCH = CFG.get("github_branch", "main")
MAX_JOBS  = CFG.get("max_jobs", 80)
SCORE_MIN = CFG.get("score_minimo", 3)

JOOBLE_KEY        = CFG.get("jooble_api_key", "")
JOOBLE_KEY_BACKUP = CFG.get("jooble_api_key_backup", "")
ADZUNA_ID   = CFG.get("adzuna_app_id", "")
ADZUNA_KEY  = CFG.get("adzuna_app_key", "")

BOOST = [w.lower() for w in CFG.get("palavras_boost", [])]
BLOCK = [w.lower() for w in CFG.get("palavras_block", [])]

AVATAR_COLORS = ["#0f6cbd","#8764b8","#107c10","#d13438","#ca5010","#038387"]

# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────
def fetch_json(url, headers=None, data=None, method="GET"):
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {"User-Agent": "GetFreelas-Scraper/1.0"},
        method=method
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))

def strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()

_BR = ['brasil','brazil','sao paulo','são paulo','rio de janeiro','curitiba','belo horizonte',
       'porto alegre','florianopolis','florianópolis','salvador','brasilia','brasília',
       'fortaleza','recife','manaus','goiania','goiânia','campinas','r$ ','brl']
_US = ['united states','usa',' us ','new york','los angeles','san francisco','chicago',
       'miami','seattle','boston','austin','texas','california','silicon valley','usd']
_CA = ['canada','toronto','vancouver','montreal','calgary','ottawa','edmonton']
_EU = ['europe','uk ','london','paris','berlin','amsterdam','lisbon','madrid','rome',
       'dublin','germany','france','spain','italy','netherlands','ireland','eur ']
_CN = ['china','shanghai','beijing','shenzhen','guangzhou','chengdu','hong kong']
_AU = ['australia','sydney','melbourne','brisbane','perth','adelaide']

def detect_country(location=''):
    loc = (location or '').lower().strip()
    if not loc or loc in ('worldwide','global','anywhere','remote','remoto',''):
        return 'global'
    for kw in _BR:
        if kw in loc: return 'BR'
    for kw in _US:
        if kw in loc: return 'US'
    for kw in _CA:
        if kw in loc: return 'CA'
    for kw in _EU:
        if kw in loc: return 'EU'
    for kw in _CN:
        if kw in loc: return 'CN'
    for kw in _AU:
        if kw in loc: return 'AU'
    return 'global'

def ago(date_val):
    try:
        if isinstance(date_val, (int, float)):
            dt = datetime.fromtimestamp(date_val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        h = int(diff.total_seconds() / 3600)
        if h < 1:  return "há menos de 1h"
        if h < 24: return f"há {h}h"
        d = h // 24
        return f"há {d} dia{'s' if d > 1 else ''}"
    except:
        return "recente"

def urgency(date_val):
    try:
        if isinstance(date_val, (int, float)):
            dt = datetime.fromtimestamp(date_val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
        h = int((datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        if h < 12:  return "hot"
        if h < 48:  return "new"
        return "normal"
    except:
        return "normal"

def job_id(source, raw_id):
    return int(hashlib.md5(f"{source}{raw_id}".encode()).hexdigest()[:8], 16)

def avatar(company):
    return abs(hash(str(company))) % len(AVATAR_COLORS)

def categorize(tags, title, desc=""):
    text = " ".join(list(tags) + [title, desc]).lower()
    if any(w in text for w in ["python","javascript","typescript","react","vue","angular","node","flutter","backend","frontend","devops","software","developer","engineer","data","ml","ai","cloud","aws","docker","api","fullstack","mobile","ios","android"]):
        return "tech"
    if any(w in text for w in ["design","figma","ui","ux","graphic","illustrator","photoshop","brand","logo","motion","sketch","canva","creative"]):
        return "design"
    if any(w in text for w in ["write","writing","writer","content","copywriter","editor","seo","blog","article","translation","redator","conteúdo"]):
        return "texto"
    if any(w in text for w in ["video","audio","podcast","youtube","editing","animation","3d","motion","after effects","premiere","filming"]):
        return "audio"
    if any(w in text for w in ["marketing","social media","ads","campaign","growth","email","analytics","ppc","sem"]):
        return "design"
    return "tech"

def score(job):
    text = (job.get("title","") + " " + " ".join(job.get("tags",[])) + " " + job.get("desc","")).lower()
    pts = 5
    for w in BOOST:
        if w in text: pts += 1
    for w in BLOCK:
        if w in text: pts -= 3
    # bônus por ter salário informado
    if job.get("payNum", 0) > 0: pts += 1
    # bônus por ser recente
    if job.get("urgency") == "hot": pts += 2
    elif job.get("urgency") == "new": pts += 1
    return max(0, min(10, pts))

# ─────────────────────────────────────────
# SOURCE 1 — RemoteOK (grátis, sem auth)
# ─────────────────────────────────────────
def fetch_remoteok():
    print("🔍 RemoteOK...")
    try:
        data = fetch_json("https://remoteok.com/api", headers={
            "User-Agent": "GetFreelas-Scraper/1.0",
            "Accept": "application/json"
        })
        jobs = []
        for item in data:
            if not isinstance(item, dict) or not item.get("position"):
                continue
            tags     = item.get("tags") or []
            title    = item.get("position", "")
            desc     = strip_html(item.get("description", ""))[:600]
            sal_min  = item.get("salary_min") or 0
            sal_max  = item.get("salary_max") or 0
            pay_txt  = f"${sal_min:,}–${sal_max:,}/ano" if sal_min and sal_max else ("A combinar")
            date_val = item.get("epoch", 0)
            jobs.append({
                "id":        job_id("remoteok", item.get("id","")),
                "title":     title,
                "company":   item.get("company", "—"),
                "category":  categorize(tags, title, desc),
                "type":      "freela",
                "desc":      desc,
                "req":       ", ".join(tags[:6]) if tags else "Ver descrição",
                "details":   "Vaga remota global · Fonte: RemoteOK",
                "contact":   item.get("url", ""),
                "pay":       pay_txt,
                "payNum":    sal_min or sal_max,
                "payPeriod": "ano",
                "tags":      [t for t in tags[:5] if t],
                "location":  "Remoto",
                "country":   "US",
                "urgency":   urgency(date_val),
                "avatar":    avatar(item.get("company","")),
                "posted":    ago(date_val),
                "source":    "RemoteOK"
            })
        print(f"   ✓ {len(jobs)} vagas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return []

# ─────────────────────────────────────────
# SOURCE 2 — Remotive (grátis, sem auth)
# ─────────────────────────────────────────
def fetch_remotive():
    print("🔍 Remotive...")
    try:
        data = fetch_json("https://remotive.com/api/remote-jobs?limit=100")
        jobs = []
        for item in data.get("jobs", []):
            tags     = item.get("tags") or []
            title    = item.get("title", "")
            desc     = strip_html(item.get("description", ""))[:600]
            salary   = item.get("salary", "") or ""
            date_val = item.get("publication_date", "")
            location = item.get("candidate_required_location", "Global") or "Global"
            jobs.append({
                "id":        job_id("remotive", item.get("id","")),
                "title":     title,
                "company":   item.get("company_name", "—"),
                "category":  categorize(tags, title, desc),
                "type":      "freela",
                "desc":      desc,
                "req":       ", ".join(tags[:6]) if tags else "Ver descrição",
                "details":   f"Remoto · {location} · Fonte: Remotive",
                "contact":   item.get("url", ""),
                "pay":       salary if salary else "A combinar",
                "payNum":    0,
                "payPeriod": "combinado",
                "tags":      [t for t in tags[:5] if t],
                "location":  "Remoto",
                "country":   detect_country(location),
                "urgency":   urgency(date_val),
                "avatar":    avatar(item.get("company_name","")),
                "posted":    ago(date_val),
                "source":    "Remotive"
            })
        print(f"   ✓ {len(jobs)} vagas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return []

# ─────────────────────────────────────────
# SOURCE 3 — Jooble (grátis com API key)
# ─────────────────────────────────────────
def _jooble_request(key, params):
    payload = json.dumps({**params, "page": 1}).encode()
    return fetch_json(
        f"https://jooble.org/api/{key}",
        headers={"Content-Type": "application/json"},
        data=payload,
        method="POST"
    )

def fetch_jooble():
    if not JOOBLE_KEY and not JOOBLE_KEY_BACKUP:
        print("⏭  Jooble — sem API key, pulando")
        return []
    print("🔍 Jooble...")
    try:
        searches = [
            {"keywords": "freelance remote", "location": ""},
            {"keywords": "freelancer remoto", "location": "Brasil"},
            {"keywords": "desenvolvedor freelancer", "location": "Brasil"},
        ]
        jobs = []
        seen = set()
        for params in searches:
            try:
                # Tenta key principal; cai na backup se der erro
                try:
                    data = _jooble_request(JOOBLE_KEY, params)
                except Exception as e1:
                    if JOOBLE_KEY_BACKUP:
                        print(f"   ⚠ Key principal falhou ({e1}), usando backup...")
                        data = _jooble_request(JOOBLE_KEY_BACKUP, params)
                    else:
                        raise
                for item in data.get("jobs", []):
                    jid = item.get("id", "")
                    if jid in seen: continue
                    seen.add(jid)
                    title    = item.get("title", "")
                    desc     = strip_html(item.get("snippet", ""))[:600]
                    company  = item.get("company", "—")
                    date_val = item.get("updated", "")
                    salary   = item.get("salary", "") or ""
                    tags     = [t.strip() for t in title.split() if len(t) > 3][:5]
                    jobs.append({
                        "id":        job_id("jooble", jid),
                        "title":     title,
                        "company":   company,
                        "category":  categorize([], title, desc),
                        "type":      "freela",
                        "desc":      desc,
                        "req":       "Ver descrição completa",
                        "details":   f"Fonte: Jooble · {item.get('location','Global')}",
                        "contact":   item.get("link", ""),
                        "pay":       salary if salary else "A combinar",
                        "payNum":    0,
                        "payPeriod": "combinado",
                        "tags":      tags,
                        "location":  item.get("location", "Remoto") or "Remoto",
                        "country":   detect_country(item.get("location", "")),
                        "urgency":   urgency(date_val),
                        "avatar":    avatar(company),
                        "posted":    ago(date_val),
                        "source":    "Jooble"
                    })
            except Exception as e:
                print(f"   ⚠ Jooble query '{params['keywords']}': {e}")
        print(f"   ✓ {len(jobs)} vagas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return []

# ─────────────────────────────────────────
# SOURCE 4 — Adzuna (grátis com cadastro)
# ─────────────────────────────────────────
def fetch_adzuna():
    if not ADZUNA_ID or not ADZUNA_KEY:
        print("⏭  Adzuna — sem API key, pulando")
        return []
    print("🔍 Adzuna...")
    try:
        countries = ["br", "us", "gb"]
        jobs = []
        for country in countries:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
                f"?app_id={ADZUNA_ID}&app_key={ADZUNA_KEY}"
                f"&results_per_page=20&what=freelance+remote&content-type=application/json"
            )
            try:
                data = fetch_json(url)
                for item in data.get("results", []):
                    title    = item.get("title", "")
                    desc     = strip_html(item.get("description", ""))[:600]
                    company  = item.get("company", {}).get("display_name", "—")
                    date_val = item.get("created", "")
                    sal_min  = item.get("salary_min", 0) or 0
                    sal_max  = item.get("salary_max", 0) or 0
                    pay_txt  = f"${sal_min:,.0f}–${sal_max:,.0f}" if sal_min else "A combinar"
                    tags     = item.get("category", {}).get("label", "").split("/")
                    tags     = [t.strip() for t in tags if t.strip()]
                    jobs.append({
                        "id":        job_id("adzuna", item.get("id","")),
                        "title":     title,
                        "company":   company,
                        "category":  categorize(tags, title, desc),
                        "type":      "freela",
                        "desc":      desc,
                        "req":       "Ver descrição completa",
                        "details":   f"Fonte: Adzuna · {country.upper()}",
                        "contact":   item.get("redirect_url", ""),
                        "pay":       pay_txt,
                        "payNum":    sal_min,
                        "payPeriod": "combinado",
                        "tags":      tags[:5],
                        "location":  item.get("location", {}).get("display_name", "Remoto") or "Remoto",
                        "country":   "BR" if country == "br" else "US" if country == "us" else "EU" if country == "gb" else "global",
                        "urgency":   urgency(date_val),
                        "avatar":    avatar(company),
                        "posted":    ago(date_val),
                        "source":    "Adzuna"
                    })
            except Exception as e:
                print(f"   ⚠ Adzuna/{country}: {e}")
        print(f"   ✓ {len(jobs)} vagas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return []

# ─────────────────────────────────────────
# SOURCE 5 — Freelancer.com (grátis, sem auth, global + BR)
# ─────────────────────────────────────────
def fetch_freelancer():
    print("🔍 Freelancer.com...")
    try:
        # Busca projetos ativos em português e inglês
        urls = [
            "https://www.freelancer.com/api/projects/0.1/projects/active/?limit=50&job_details=true&languages[]=pt",
            "https://www.freelancer.com/api/projects/0.1/projects/active/?limit=50&job_details=true&languages[]=en",
        ]
        jobs = []
        seen = set()
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                projects = data.get("result", {}).get("projects", [])
                for item in projects:
                    pid = item.get("id", "")
                    if pid in seen: continue
                    seen.add(pid)
                    title     = item.get("title", "")
                    desc      = strip_html(item.get("preview_description", ""))[:600]
                    budget    = item.get("budget", {}) or {}
                    pay_min   = budget.get("minimum", 0) or 0
                    pay_max   = budget.get("maximum", 0) or 0
                    currency  = item.get("currency", {}).get("sign", "$") or "$"
                    pay_txt   = f"{currency}{pay_min:,.0f}–{currency}{pay_max:,.0f}" if pay_min else "A combinar"
                    jobs_list = item.get("jobs", []) or []
                    tags      = [j.get("name","") for j in jobs_list if j.get("name")][:5]
                    date_val  = item.get("time_submitted", "")
                    country   = item.get("language", "").upper() or "Global"
                    jobs.append({
                        "id":        job_id("freelancer", pid),
                        "title":     title,
                        "company":   "Freelancer.com",
                        "category":  categorize(tags, title, desc),
                        "type":      "freela",
                        "desc":      desc or "Ver descrição completa no link.",
                        "req":       ", ".join(tags) if tags else "Ver descrição",
                        "details":   f"Fonte: Freelancer.com · {country}",
                        "contact":   f"https://www.freelancer.com/projects/{item.get('seo_url','')}",
                        "pay":       pay_txt,
                        "payNum":    pay_min,
                        "payPeriod": "projeto",
                        "tags":      tags,
                        "location":  "Remoto",
                        "country":   "BR" if "languages[]=pt" in url else "global",
                        "urgency":   urgency(date_val),
                        "avatar":    avatar("Freelancer"),
                        "posted":    ago(date_val),
                        "source":    "Freelancer"
                    })
            except Exception as e:
                print(f"   ⚠ {e}")
        print(f"   ✓ {len(jobs)} vagas")
        return jobs
    except Exception as e:
        print(f"   ✗ Erro: {e}")
        return []

# ─────────────────────────────────────────
# GITHUB PUSH
# ─────────────────────────────────────────
def push_to_github(payload):
    if not GH_TOKEN or GH_TOKEN == "SEU_TOKEN_AQUI":
        print("⚠  Token GitHub não configurado — JSON salvo só localmente.")
        return False
    path    = "data/freelas.json"
    content = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode()
    api     = f"https://api.github.com/repos/{GH_REPO}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept":        "application/vnd.github+json",
        "Content-Type":  "application/json",
        "User-Agent":    "GetFreelas-Scraper/1.0"
    }
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
        "branch":  GH_BRANCH,
        **({"sha": sha} if sha else {})
    }
    req = urllib.request.Request(
        api, data=json.dumps(body).encode(), headers=headers, method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        print(f"   ✓ github.com/{GH_REPO}/blob/{GH_BRANCH}/{path}")
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

    # 1. Busca todas as fontes
    all_jobs = (
        fetch_remoteok()   +
        fetch_remotive()   +
        fetch_freelancer() +
        fetch_jooble()     +
        fetch_adzuna()
    )
    print(f"\n📦 Total bruto: {len(all_jobs)} vagas")

    # 2. Deduplicação por ID
    seen, unique = set(), []
    for j in all_jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            unique.append(j)
    print(f"🔎 Únicos: {len(unique)}")

    # 3. Filtra bloqueadas
    filtered = []
    for j in unique:
        text = (j["title"] + " " + j["desc"]).lower()
        if not any(w in text for w in BLOCK):
            filtered.append(j)

    # 4. Score por relevância
    for j in filtered:
        j["score_ia"] = score(j)

    # 5. Ordena: score desc, depois recência
    order = {"hot": 0, "new": 1, "normal": 2}
    filtered.sort(key=lambda x: (-x["score_ia"], order.get(x["urgency"], 2)))

    # 6. Seleciona os melhores
    final = [j for j in filtered if j["score_ia"] >= SCORE_MIN][:MAX_JOBS]

    # 7. Remove campos internos
    for j in final:
        j.pop("source", None)
        j["avatar"] = abs(j["avatar"]) % len(AVATAR_COLORS)

    print(f"✅ {len(final)} vagas selecionadas (score ≥ {SCORE_MIN})\n")

    # 8. Monta JSON
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(final),
        "freelas":    final
    }

    # 9. Salva local
    out_file = BASE_DIR.parent / "data" / "freelas.json"
    out_file.parent.mkdir(exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 Salvo em {out_file}")

    # 10. Push GitHub
    print("🚀 Enviando para GitHub...")
    push_to_github(output)

    print(f"\n🎉 Concluído — {len(final)} vagas publicadas\n")

if __name__ == "__main__":
    main()
