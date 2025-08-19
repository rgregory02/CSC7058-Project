import os
import json
import shutil  
import time 
import re
import math
import uuid

from collections import defaultdict
from flask import Flask, Response, jsonify, request, url_for, redirect, render_template, flash, get_flashed_messages, send_from_directory, render_template_string, session
from markupsafe import Markup, escape
from urllib.parse import quote, unquote
from datetime import datetime, timezone, timedelta
from openai import OpenAI
from dotenv import load_dotenv
from requests import get
from typing import Optional, Dict, Any, List

load_dotenv()
oai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def safe_date(x):
    try:
        dt = datetime.fromisoformat(x[2])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

try:
    from zoneinfo import ZoneInfo  # type: ignore[import]  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8 fallback
from utils import (
    load_grouped_biographies,
    load_json_as_dict,
    save_dict_as_json,
    get_readable_time,
    printButton,
    prettify,
    get_label_description,
    enrich_label_data,
    get_icon,
    uk_datetime,
    display_dob_uk,
    resolve_entities,
    LIFE_STAGE_ORDER,
    collect_label_groups,
    load_labels_from_folder,
    suggest_labels_from_text,
    map_existing_bio_selections,
    build_suggested_biographies,
    list_biographies,
    expand_child_groups,
    list_types_live,
    scan_cross_references,
    archive_type,
    restore_type,
    archive_root,
    resolve_property_options,
    list_types,
    sanitise_key,
    checkbox_on,
    list_label_groups_for_type,
    build_label_groups_by_type,
    _ensure_property_self_labels,
    _import_labels_from_api,
    _import_labels_from_sqlite,
    _write_label_json,
    now_iso_utc,
    _score_label,
    _collect_all_labels,
    build_label_catalog_for_type
)

from time_utils import normalise_time_for_bio_entry

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'the_random_string')  # Use environment variable if available

app.jinja_env.filters['uk_datetime'] = uk_datetime
app.jinja_env.filters['display_dob_uk'] = display_dob_uk

@app.context_processor
def inject_utilities():
    return dict(get_icon=get_icon)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@app.route('/types/<path:filename>')
def serve_type_images(filename):
    return send_from_directory('types', filename)


def _copytree_safe(src: str, dst: str):
    """Copy a directory tree into an existing (or new) destination, without blowing up if files exist."""
    os.makedirs(dst, exist_ok=True)
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        tgt = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(tgt, exist_ok=True)
        for d in dirs:
            os.makedirs(os.path.join(tgt, d), exist_ok=True)
        for f in files:
            s = os.path.join(root, f)
            t = os.path.join(tgt, f)
            if not os.path.exists(t):
                shutil.copy2(s, t)

@app.template_filter("uk_date")
def uk_date(value):
    from datetime import datetime
    if not value:
        return ""
    try:
        if len(value) == 4:  # year only
            return value
        if len(value) == 7:  # YYYY-MM
            dt = datetime.strptime(value, "%Y-%m")
            return dt.strftime("%m/%Y")
        if len(value) == 10:  # YYYY-MM-DD
            dt = datetime.strptime(value, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
    except:
        pass
    return value


@app.template_filter("uk_datetime")
def uk_datetime(value):
    try:
        dt = datetime.fromisoformat(value)
        return dt.strftime("%d %B %Y, %H:%M")
    except Exception:
        return value

@app.template_filter("short_timestamp")
def short_timestamp(value):
    return value.replace("T", " ")[:16] if value else ""


def list_types(base="./types"):
    return sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])

def list_biographies(type_name, base="./types", include_archived=False):
    bios_dir = os.path.join(base, type_name, "biographies")
    if not os.path.isdir(bios_dir):
        return []

    out = []
    for f in os.listdir(bios_dir):
        if not f.endswith(".json"):
            continue
        bio_id = os.path.splitext(f)[0]
        try:
            with open(os.path.join(bios_dir, f), "r", encoding="utf-8") as fp:
                data = json.load(fp)

            # Skip archived unless explicitly included
            if not include_archived and data.get("archived", False):
                continue

            out.append({
                "id": bio_id,
                "name": data.get("name", bio_id),
                "description": data.get("description", ""),
                "archived": bool(data.get("archived", False)),
                "archived_at": data.get("archived_at", None),
                "updated": data.get("updated", None)
            })
        except Exception:
            out.append({
                "id": bio_id,
                "name": bio_id,
                "description": "",
                "archived": False,
                "archived_at": None,
                "updated": None
            })

    # Sort: active first, then archived; within each group, newest updated first
    return sorted(
        out,
        key=lambda x: (x["archived"], x["updated"] or ""),
        reverse=True
    )



@app.route("/")
def dashboard():
    types = list_types()
    preview = {t: list_biographies(t)[:6] for t in types}
    return render_template("dashboard.html", types=types, preview=preview)

@app.route("/people")
def index_page():
    person_bios = []
    types = []

    for file in os.listdir("./types"):
        if file.endswith(".json") and os.path.splitext(file)[0].lower() != "time":
            types.append(os.path.splitext(file)[0])

    person_dir = "./types/person/biographies"
    if os.path.exists(person_dir):
        for af in os.listdir(person_dir):
            if af.endswith(".json"):
                agg_id = af[:-5]
                data = load_json_as_dict(os.path.join(person_dir, af))
                name = data.get("name", agg_id.replace("_", " "))
                created = data.get("created", "")
                person_bios.append((agg_id, name, created))

    person_bios.sort(key=safe_date, reverse=True)
    return render_template("index.html", types=types, person_bios=person_bios)



@app.route("/wizard/begin", methods=["POST"])
def wizard_begin():
    type_name = request.form.get("type_name", "").strip()
    bio_id = request.form.get("bio_id", "").strip()
    if not type_name:
        flash("Please choose a type.", "warning")
        return redirect(url_for("general_step_start"))
    if not bio_id:
        # Push them into your existing search/create UI, then return here:
        return redirect(url_for("search_or_add_biography", type_name=type_name, return_url=url_for("general_step_start")))
    # If you want time first, redirect to your time step (generalised), else go to label_step step 0
    return redirect(url_for("label_step", type_name=type_name, bio_id=bio_id, step=0))

@app.route("/add_type_prompt", methods=["GET", "POST"])
def add_type_prompt():
    def _slugify(s: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_") or "untitled"

    if request.method == "POST":
        new_type_name = (request.form.get("new_type_name") or "").strip()
        base_type     = (request.form.get("base_type") or "").strip()
        mk_labels     = bool(request.form.get("mk_labels"))
        mk_time       = bool(request.form.get("mk_time_labels"))
        mk_bios       = bool(request.form.get("mk_biographies"))

        if not new_type_name:
            flash("Please enter a type name.", "error")
            return redirect(url_for("add_type_prompt"))

        slug = _slugify(new_type_name)
        type_root = os.path.join("types", slug)
        labels_dir = os.path.join(type_root, "labels")
        bios_dir   = os.path.join(type_root, "biographies")
        time_labels_dir = os.path.join(type_root, "time", "labels")

        try:
            os.makedirs(type_root, exist_ok=True)
            if mk_labels:
                os.makedirs(labels_dir, exist_ok=True)
            if mk_time:
                os.makedirs(time_labels_dir, exist_ok=True)
            if mk_bios:
                os.makedirs(bios_dir, exist_ok=True)

            # If basing off an existing type, copy label folders
            if base_type:
                base_root = os.path.join("types", base_type)
                # copy labels/
                if mk_labels and os.path.isdir(os.path.join(base_root, "labels")):
                    _copytree_safe(os.path.join(base_root, "labels"), labels_dir)
                # copy time/labels/
                if mk_time and os.path.isdir(os.path.join(base_root, "time", "labels")):
                    _copytree_safe(os.path.join(base_root, "time", "labels"), time_labels_dir)

            # Write a minimal type_info.json
            info_path = os.path.join(type_root, "type_info.json")
            if not os.path.exists(info_path):
                info = {
                    "type": slug,
                    "name": new_type_name,
                    "created": now_iso_utc(),
                    "updated": now_iso_utc(),
                    "schema_version": 1
                }
                save_dict_as_json(info_path, info)

            flash(f"Type '{new_type_name}' created.", "success")
            return redirect(url_for("dashboard"))

        except Exception as e:
            print("[add_type_prompt] error:", e)
            flash("Failed to create type. Check server logs.", "error")
            return redirect(url_for("add_type_prompt"))

    # GET
    try:
        existing_types = list_types()
    except Exception:
        existing_types = []
    return render_template("add_type_prompt.html", existing_types=existing_types)


@app.route("/type/<type_name>")
def type_browse(type_name):
    show = (request.args.get("show") or "").lower()   # "", "archived", "all"
    include_archived = show in ("archived", "all")
    bios = list_biographies(type_name, include_archived=include_archived)
    active = [b for b in bios if not b["archived"]]
    archived = [b for b in bios if b["archived"]]
    return render_template("type_browse.html",
                           type_name=type_name,
                           active_bios=active,
                           archived_bios=archived,
                           show=show)



@app.route("/global_search")
def global_search():
    query = request.args.get("q", "").lower()
    page = int(request.args.get("page", 1))
    per_page = 10

    results = []
    person_dir = "./types/person/biographies"

    if query and os.path.exists(person_dir):
        for file in os.listdir(person_dir):
            if not file.endswith(".json"):
                continue

            try:
                full_path = os.path.join(person_dir, file)
                data = load_json_as_dict(full_path)
                name = data.get("name", "").lower()
                matched = False

                # Check name
                if query in name:
                    matched = True

                # Check entries in all known sections
                for section in ["time", "people", "organisations", "buildings"]:
                    for entry in data.get(section, []):
                        # Only try .values() if it's a dictionary
                        if isinstance(entry, dict):
                            searchable = [str(v).lower() for v in entry.values()]
                            if any(query in val for val in searchable if isinstance(val, str)):
                                matched = True
                                break
                        elif isinstance(entry, str) and query in entry.lower():
                            matched = True
                            break

                if matched:
                    results.append((file[:-5], data.get("name", file[:-5])))

            except Exception as e:
                print(f"Error searching {file}: {e}")
                continue

    # Remove duplicates
    results = list(dict(results).items())

    # Paginate
    start = (page - 1) * per_page
    end = start + per_page
    paginated = results[start:end]
    total_pages = (len(results) + per_page - 1) // per_page

    return render_template(
        "global_search.html",
        query=query,
        results=paginated,
        page=page,
        total_pages=total_pages
    )

@app.route("/api/search_person_bios")
def api_search_person_bios():
    query = request.args.get("q", "").lower()
    person_dir = "./types/person/biographies"
    matches = []

    if query and os.path.exists(person_dir):
        for file in os.listdir(person_dir):
            if not file.endswith(".json"):
                continue
            try:
                data = load_json_as_dict(os.path.join(person_dir, file))
                name = data.get("name", "").lower()
                if query in name:
                    matches.append({
                        "person_id": file[:-5],
                        "name": data.get("name", file[:-5])
                    })
            except:
                continue

    return jsonify(matches[:10])  # Return only first 10 matches for speed

def _read_json_safe(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _tokenize(text: str):
    text = (text or "").lower()
    text = re.sub(r"[^a-z0-9_ ]+", " ", text)
    parts = [w for w in text.split() if w]
    return parts

def _kw_score(prompt_terms, haystack_terms):
    # simple IR scoring: sum of sqrt(freq) for terms that overlap
    if not prompt_terms or not haystack_terms:
        return 0.0
    freq = defaultdict(int)
    for t in haystack_terms:
        freq[t] += 1
    s = 0.0
    for t in prompt_terms:
        if t in freq:
            s += math.sqrt(freq[t])
    return s

def _iter_all_label_files():
    """Yield (type_name, group_key, label_id, path, meta). 
       group_key is the folder path under labels (e.g. 'work_building')."""
    root = "types"
    if not os.path.isdir(root):
        return
    for type_name in os.listdir(root):
        tdir = os.path.join(root, type_name)
        if not os.path.isdir(tdir):
            continue
        labels_dir = os.path.join(tdir, "labels")
        if not os.path.isdir(labels_dir):
            continue
        # walk labels dir
        for dirpath, _, files in os.walk(labels_dir):
            rel_dir = os.path.relpath(dirpath, labels_dir).replace("\\", "/")
            for f in files:
                if not f.endswith(".json"):
                    continue
                if f == "_group.json":
                    continue
                # treat top-level property jsons as groups, but they aren’t options themselves
                if rel_dir == "." and "/" not in f and f.endswith(".json") and os.path.isfile(os.path.join(dirpath, f)):
                    # property json; skip as an option
                    continue
                label_id = os.path.splitext(f)[0]
                path = os.path.join(dirpath, f)
                meta = _read_json_safe(path)
                group_key = "" if rel_dir == "." else rel_dir
                yield type_name, group_key, label_id, path, meta

def _build_candidate_pool(user_text: str, current_type: str, max_pool: int = 120):
    """
    Build a pool of candidate labels from:
      - this type's labels/*
      - any other type's labels/*  (so cross-type 'hospital' appears)
    Rank by a quick keyword score using label id + name + description.
    """
    prompt_terms = _tokenize(user_text)
    scored = []

    for tname, group_key, lid, p, meta in _iter_all_label_files():
        # features to match against
        name = (meta.get("properties", {}) or {}).get("name") or meta.get("name") or lid
        desc = meta.get("description") or (meta.get("properties", {}) or {}).get("description", "")
        hay = _tokenize(f"{lid} {name} {desc} {group_key} {tname}")
        score = _kw_score(prompt_terms, hay)

        # small boost if this is the same type
        if tname == current_type:
            score *= 1.15

        if score > 0:
            # label_type = last segment of group_key if present, else group_key itself, else use tname
            label_type = (group_key.split("/")[-1] if group_key else tname)
            scored.append({
                "type_name": tname,
                "group_key": group_key,    # e.g. 'work_building'
                "id": lid,
                "display": name,
                "description": desc,
                "label_type": label_type,
                "score": score
            })

    # keep a diverse, high-quality subset
    scored.sort(key=lambda x: (-x["score"], x["type_name"], x["group_key"], x["id"]))
    return scored[:max_pool]

def _gpt_pick_labels(prompt_text: str, candidates: list, max_return: int = 8):
    """
    Ask GPT to select the most relevant candidate label ids.
    We pass candidates (already filtered & ranked) to keep GPT on the rails.
    """
    if not candidates:
        return []

    # compact candidate list for the model
    cand_summary = [
        {
            "id": c["id"],
            "label_type": c["label_type"],
            "group_key": c["group_key"],
            "type": c["type_name"],
            "display": c["display"],
        } for c in candidates
    ]

    system = (
        "You help map a short description to label IDs from a fixed catalog. "
        "Only choose from the provided candidates. Prefer the few best matches. "
        f"Return at most {max_return} items as a JSON list of objects with keys: "
        "id, label_type, (optional) confidence (0-100)."
    )
    user = (
        f"User description: {prompt_text}\n\n"
        "Candidate labels (id, label_type, group_key, type, display):\n"
        f"{json.dumps(cand_summary, ensure_ascii=False)}\n\n"
        "Pick the most relevant few."
    )

    try:
        resp = oai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            temperature=0.2,
            max_tokens=600,
        )
        content = resp.choices[0].message.content.strip()
        # Try to parse a JSON array out of the content
        # Be permissive: allow the model to wrap in text
        m = re.search(r"\[.*\]", content, re.S)
        raw = m.group(0) if m else content
        data = json.loads(raw)
        out = []
        for x in data:
            if not isinstance(x, dict):
                continue
            if "id" not in x:
                continue
            # Find the candidate to copy display/desc/type info
            ref = next((c for c in candidates if c["id"] == x["id"]), None)
            if not ref:
                continue
            out.append({
                "id": x["id"],
                "label_type": x.get("label_type") or ref["label_type"],
                "display": ref["display"],
                "description": ref["description"],
                "confidence": int(x.get("confidence", 100)),
                "group_key": ref["group_key"],
                "type": ref["type_name"],
            })
        return out[:max_return]
    except Exception as e:
        print("[gpt_pick_labels] error:", e)
        return []

@app.post("/api/suggest_labels")
def api_suggest_labels():
    """
    Body: { "type": "<current_type>", "prompt": "<free text>", "context": { selections: [...] } }
    Returns: { "labels": [ {id, label_type, display, description, confidence} ... ] }
    """
    try:
        payload = request.get_json(force=True) or {}
        current_type = (payload.get("type") or "").strip()
        user_text    = (payload.get("prompt") or "").strip()
        if not current_type or not user_text:
            return jsonify({"labels": []})

        # 1) Build a strong candidate pool across all types (with a small bias to current_type)
        pool = _build_candidate_pool(user_text, current_type, max_pool=120)

        # 2) Hand the short list to GPT to pick ~5–8
        picked = _gpt_pick_labels(user_text, pool, max_return=8)

        # 3) Final sanity check: only return ids that exist in the pool
        pool_ids = {c["id"] for c in pool}
        result = [p for p in picked if p["id"] in pool_ids]

        return jsonify({"labels": result})
    except Exception as e:
        print("[/api/suggest_labels] fatal:", e)
        return jsonify({"labels": []}), 500

# ---------- Bootstrap for UI dropdowns ----------
@app.get("/api/labels/admin/bootstrap")
def api_labels_admin_bootstrap():
    type_name = (request.args.get("type") or "").strip()
    if not type_name:
        return {"ok": False, "error": "missing_type"}, 400

    base = os.path.join("types", type_name, "labels")
    os.makedirs(base, exist_ok=True)

    # Collect groups using your existing helper
    try:
        groups = collect_label_groups(base, type_name) or []
    except Exception:
        groups = []

    # Flatten all group keys; top-level keys for "parent" dropdown
    all_group_keys = [g.get("key") for g in groups if g.get("key")]
    top_level = sorted({k.split("/")[0] for k in all_group_keys})

    # Try to read property templates from a schema (optional)
    props = []
    schema_path = os.path.join("types", type_name, "type.json")
    try:
        schema = load_json_as_dict(schema_path) or {}
        # support either {"properties": {...}} or {"properties": [{"key":...}]}
        raw = schema.get("properties") or {}
        if isinstance(raw, dict):
            props = sorted(list(raw.keys()))
        elif isinstance(raw, list):
            props = sorted([p.get("key") for p in raw if isinstance(p, dict) and p.get("key")])
    except Exception:
        props = []

    # List all type folders for cross-type refer_to
    try:
        type_folders = [d for d in os.listdir("types") if os.path.isdir(os.path.join("types", d))]
    except Exception:
        type_folders = []

    return {
        "ok": True,
        "type": type_name,
        "types": sorted(type_folders),
        "groups": all_group_keys,
        "top_level_groups": top_level,
        "property_templates": props,
    }

# ---------- Create a NEW property (group) with optional refer_to ----------
@app.post("/api/labels/admin/create_group")
def api_labels_admin_create_group():
    p = request.get_json(silent=True) or {}
    type_name = _slugify(p.get("type_name"))
    key       = _slugify(p.get("key"))                 # e.g. "hair_color"
    label     = (p.get("label") or "").strip()
    desc      = (p.get("description") or "").strip()
    refer_to  = p.get("refer_to")                      # e.g. {"source": "biographies", "type": "person"}
    try:
        order = int(p.get("order", 999))
    except Exception:
        order = 999

    if not type_name or not key:
        return {"ok": False, "error": "missing_fields"}, 400

    base_desc = os.path.join("types", type_name, "labels", key + ".json")
    if os.path.exists(base_desc):
        return {"ok": False, "error": "group_exists"}, 409

    data = {"label": label or key.replace("_"," ").title(), "description": desc, "order": order}
    # allow linking a property to other biographies
    if isinstance(refer_to, dict):
        src = (refer_to.get("source") or "").strip().lower()
        rtype = _slugify(refer_to.get("type") or "")
        if src == "biographies" and rtype:
            data["refer_to"] = {"source": "biographies", "type": rtype}

    _safe_json_write(base_desc, data)
    os.makedirs(os.path.join("types", type_name, "labels", key), exist_ok=True)
    return {"ok": True, "group_key": key}

# ---------- Create a CHILD group under existing parent (supports refer_to) ----------
@app.post("/api/labels/admin/create_child_group")
def api_labels_admin_create_child_group():
    p = request.get_json(silent=True) or {}
    type_name  = _slugify(p.get("type_name"))
    parent_key = _slugify(p.get("parent_key"))
    child_key  = _slugify(p.get("child_key"))
    label      = (p.get("label") or "").strip()
    desc       = (p.get("description") or "").strip()
    refer_to   = p.get("refer_to")
    try:
        order = int(p.get("order", 999))
    except Exception:
        order = 999

    if not type_name or not parent_key or not child_key:
        return {"ok": False, "error": "missing_fields"}, 400

    parent_folder = os.path.join("types", type_name, "labels", parent_key)
    if not os.path.isdir(parent_folder):
        return {"ok": False, "error": "parent_missing"}, 404

    child_desc = os.path.join(parent_folder, f"{child_key}.json")
    if os.path.exists(child_desc):
        return {"ok": False, "error": "child_exists"}, 409

    data = {"label": label or child_key.replace("_"," ").title(), "description": desc, "order": order}
    if isinstance(refer_to, dict):
        src = (refer_to.get("source") or "").strip().lower()
        rtype = _slugify(refer_to.get("type") or "")
        if src == "biographies" and rtype:
            data["refer_to"] = {"source": "biographies", "type": rtype}

    _safe_json_write(child_desc, data)
    os.makedirs(os.path.join(parent_folder, child_key), exist_ok=True)
    return {"ok": True, "child_key": f"{parent_key}/{child_key}"}


@app.post("/api/labels/resolve_option")
def api_resolve_option():
    """
    Resolve a suggested option id (e.g. "hospital") to the UI group that can select it.

    Returns JSON:
      {
        "ok": true/false,
        # If option is directly in a top-level group:
        "group_key": "<group_key>"
        # If option is a child under a parent option:
        "group_key": "<parent group key>/<parent_id>",
        "parent_id": "<parent_id>",
        "child_key": "<parent group key>/<parent_id>",
        "child_id": "<option_id>"
      }
    """
    data = request.get_json(force=True) or {}
    type_name = (data.get("type_name") or "").strip()
    option_id = (data.get("option_id") or "").strip()
    if not type_name or not option_id:
        return jsonify(ok=False, error="Missing type_name/option_id")

    # Build current groups (property-first, with refer_to hints)
    label_base = os.path.join("types", type_name, "labels")
    groups = collect_label_groups(label_base_path=label_base, current_type=type_name)

    oid = option_id.strip()
    oid_l = oid.lower()

    # Helper: list json basenames in a folder (lowercased)
    def json_names_lower(folder):
        try:
            return {os.path.splitext(f)[0].lower() for f in os.listdir(folder) if f.endswith(".json")}
        except Exception:
            return set()

    # ---------- 1) Direct match inside any top-level group ----------
    for g in groups:
        for opt in g.get("options", []):
            if (opt.get("id") or "").lower() == oid_l:
                return jsonify(ok=True, group_key=g["key"])

    # ---------- 2) Search for child under SAME-TYPE label tree ----------
    # e.g. types/<current>/labels/<g.key>/<parent_id>/<oid>.json
    for g in groups:
        base_path = g.get("key", "").strip("/")
        if not base_path:
            continue
        for parent in g.get("options", []):
            parent_id = (parent.get("id") or "").strip()
            if not parent_id:
                continue
            child_dir = os.path.join(label_base, *base_path.split("/"), parent_id)
            if os.path.isdir(child_dir) and oid_l in json_names_lower(child_dir):
                child_key = f"{g['key']}/{parent_id}"
                return jsonify(
                    ok=True,
                    group_key=child_key,
                    parent_id=parent_id,
                    child_key=child_key,
                    child_id=oid
                )

    # ---------- 3) Cross-type children via refer_to: {source:'labels', type, path} ----------
    for g in groups:
        src = g.get("refer_to") or {}
        if (src.get("source") or "") != "labels":
            continue

        search_type = (src.get("type") or type_name).strip()
        base_path   = (src.get("path") or g["key"]).strip("/")

        # Root where the parent options live
        cross_root = os.path.join("types", search_type, "labels", *base_path.split("/"))

        for parent in g.get("options", []):
            parent_id = (parent.get("id") or "").strip()
            if not parent_id:
                continue
            child_dir = os.path.join(cross_root, parent_id)
            if os.path.isdir(child_dir) and oid_l in json_names_lower(child_dir):
                # Present to the UI as a child under this parent group
                child_key = f"{g['key']}/{parent_id}"
                return jsonify(
                    ok=True,
                    group_key=child_key,
                    parent_id=parent_id,
                    child_key=child_key,
                    child_id=oid
                )

    # ---------- 4) Fallback: scan all types to find a folder that contains <oid>.json,
    # then try to map it back to a current group with a matching refer_to root ----------
    try:
        types_root = "types"
        for tname in os.listdir(types_root):
            tdir = os.path.join(types_root, tname)
            if not os.path.isdir(tdir):
                continue
            labels_root = os.path.join(tdir, "labels")
            if not os.path.isdir(labels_root):
                continue

            for dirpath, _, files in os.walk(labels_root):
                basenames = {os.path.splitext(f)[0].lower() for f in files if f.endswith(".json")}
                if oid_l not in basenames:
                    continue

                # dirpath looks like: types/<tname>/labels/<some/base>/<maybe parent>
                rel_from_labels = os.path.relpath(dirpath, labels_root).replace("\\", "/")
                parts = rel_from_labels.split("/") if rel_from_labels != "." else []
                # if there is a parent folder, parts[-1] is parent_id and parts[:-1] is base_path
                if parts:
                    parent_id = parts[-1]
                    base_path = "/".join(parts[:-1])

                    # Find a group in current type whose refer_to matches (tname, base_path)
                    for g in groups:
                        src = g.get("refer_to") or {}
                        if (src.get("source") == "labels" and
                            (src.get("type") or type_name) == tname and
                            (src.get("path") or g["key"]).strip("/") == base_path):
                            child_key = f"{g['key']}/{parent_id}"
                            return jsonify(
                                ok=True,
                                group_key=child_key,
                                parent_id=parent_id,
                                child_key=child_key,
                                child_id=oid
                            )
    except Exception as e:
        print("[resolve_option fallback] error:", e)

    return jsonify(ok=False)


@app.route("/api/labels/children", methods=["POST"])
def api_labels_children():
    """
    Body: { "type_name": "person", "group_key": "work_place", "selected_id": "hospital" }
    Returns: { "ok": true, "child_key": "work_place/hospital", "options": [ {id,display,description?,image?}, ... ] }
             or { "ok": false, "reason": "..." }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        type_name   = (data.get("type_name") or "").strip()
        group_key   = (data.get("group_key") or "").strip()
        selected_id = (data.get("selected_id") or "").strip()
        if not (type_name and group_key and selected_id):
            return jsonify({"ok": False, "reason": "Missing type_name/group_key/selected_id"}), 400

        label_base_path = os.path.join("types", type_name, "labels")

        # Where are the child options located on disk?
        # Mirrors expand_child_groups() logic (self or cross-type when allowed).
        # First, figure out whether this group uses cross-type labels.
        base_groups = collect_label_groups(label_base_path, type_name)
        parent = next((g for g in base_groups if g.get("key") == group_key), None)
        if not parent:
            return jsonify({"ok": False, "reason": f"Unknown group '{group_key}'"}), 404

        src = parent.get("refer_to") or parent.get("source") or {}
        kind = src.get("source") or src.get("kind") or ""  # "labels"|"biographies"|"" (self)
        allow_children = bool(src.get("allow_children"))

        # default: same type
        search_type = type_name
        base_path   = group_key

        if kind == "labels":
            # cross-type labels
            search_type = src.get("type") or type_name
            base_path   = (src.get("path") or group_key).strip("/")
            if search_type != type_name and not allow_children:
                return jsonify({"ok": False, "reason": "Children not allowed for this cross-type source"}), 200

        if kind == "biographies":
            # bios don’t yield child label folders
            return jsonify({"ok": True, "child_key": None, "options": []}), 200

        # Resolve absolute folder
        if search_type == type_name:
            folder = os.path.join(label_base_path, *base_path.split("/"), selected_id)
        else:
            folder = os.path.join("types", search_type, "labels", *base_path.split("/"), selected_id)

        if not os.path.isdir(folder):
            return jsonify({"ok": True, "child_key": None, "options": []}), 200

        # Load options from that folder
        def _collect_opts(folder_abs):
            out = []
            for f in sorted(os.listdir(folder_abs)):
                if not f.endswith(".json") or f == "_group.json":
                    continue
                p = os.path.join(folder_abs, f)
                j = load_json_as_dict(p)
                lid = os.path.splitext(f)[0]
                disp = (j.get("properties", {}) or {}).get("name") or j.get("name") or lid
                desc = j.get("description", (j.get("properties", {}) or {}).get("description", ""))
                opt = {"id": lid, "display": disp, "description": desc}
                # try sibling image
                for ext in (".png", ".jpg", ".jpeg", ".webp"):
                    imgp = os.path.join(folder_abs, lid + ext)
                    if os.path.exists(imgp):
                        rel = os.path.relpath(imgp, ".").replace("\\", "/")
                        opt["image"] = "/" + rel if not rel.startswith("types/") else f"/{rel}"
                        break
                out.append(opt)
            return out

        options = _collect_opts(folder)
        child_key = f"{base_path}/{selected_id}"
        return jsonify({"ok": True, "child_key": child_key, "options": options}), 200

    except Exception as e:
        print("[/api/labels/children] ERROR:", e)
        return jsonify({"ok": False, "reason": "Server error"}), 500


@app.route("/api/labels/suggest_biographies", methods=["POST"])
def api_suggest_biographies():
    """
    Body: {
      "type_name": "person",
      "group_key": "work_place/hospital",   # usually a child key
      "selections": { "work_place": "hospital", "work_place/hospital": "royal_victoria" }
    }
    Returns: { "ok": true, "bios": [ {id, display, description?}, ... ] }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        type_name  = (data.get("type_name") or "").strip()
        group_key  = (data.get("group_key") or "").strip()
        selections = data.get("selections") or {}
        if not (type_name and group_key):
            return jsonify({"ok": False, "reason": "Missing type_name/group_key"}), 400

        label_base_path = os.path.join("types", type_name, "labels")
        base_groups = collect_label_groups(label_base_path, type_name)

        # We only need to compute suggestions for the relevant groups; pass selections as existing_labels.
        # Make sure we feed a list of groups that includes this group (and possibly siblings).
        # Easiest: reuse expand_child_groups to ensure any children exist, then run build_suggested_biographies.
        expanded = expand_child_groups(
            base_groups=base_groups,
            current_type=type_name,
            label_base_path=label_base_path,
            existing_labels=selections,   # accepts {"key": "id"} or {"key": {"label": "id"}}
        )

        suggested = build_suggested_biographies(
            current_type=type_name,
            label_groups_list=expanded,
            label_base_path=label_base_path,
            existing_labels=selections
        )

        safe = group_key.replace("/", "__")
        bios = suggested.get(safe, [])
        return jsonify({"ok": True, "bios": bios}), 200

    except Exception as e:
        print("[/api/labels/suggest_biographies] ERROR:", e)
        return jsonify({"ok": False, "reason": "Server error"}), 500


# --- Helpers ---------------------------------------------------------------

def _group_storage(type_name: str, group_key: str):
    """
    Return ('folder', dir_path) if options live as files in a folder,
           ('file',   json_path) if options live inside a single <group>.json,
           or (None, None) if neither exists.
    """
    base = os.path.join("types", type_name, "labels")
    dir_path  = os.path.join(base, group_key)
    json_path = os.path.join(base, f"{group_key}.json")
    if os.path.isdir(dir_path):
        return "folder", dir_path
    if os.path.isfile(json_path):
        return "file", json_path
    return None, None


def _write_json_safely(path: str, payload: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print("ERROR writing", path, "->", e)
        return False


def _archive_in_folder(dir_path: str, option_id: str, child_id: str, archive: bool) -> bool:
    """
    Edit types/<T>/labels/<group>/<option_id>.json
    If child_id provided, toggle that child entry's 'archived'.
    """
    jf = os.path.join(dir_path, f"{option_id}.json")
    if not os.path.isfile(jf):
        return False
    data = load_json_as_dict(jf) or {}
    changed = False

    if child_id:
        kids = data.get("children") or []
        for k in kids:
            if (k.get("id") or "").strip() == child_id:
                if archive and not k.get("archived"):
                    k["archived"] = True; changed = True
                elif not archive and k.get("archived"):
                    k.pop("archived", None); changed = True
                break
    else:
        if archive and not data.get("archived"):
            data["archived"] = True; changed = True
        elif not archive and data.get("archived"):
            data.pop("archived", None); changed = True

    return _write_json_safely(jf, data) if changed else False


def _archive_in_file(json_path: str, option_id: str, child_id: str, archive: bool) -> bool:
    """
    Edit types/<T>/labels/<group>.json within {"options":[...]}.
    Supports children inside an option dict.
    """
    if not os.path.isfile(json_path):
        return False
    doc = load_json_as_dict(json_path) or {}
    opts = doc.get("options") or []
    changed = False

    for o in opts:
        if (o.get("id") or "").strip() == option_id:
            if child_id:
                kids = o.get("children") or []
                for k in kids:
                    if (k.get("id") or "").strip() == child_id:
                        if archive and not k.get("archived"):
                            k["archived"] = True; changed = True
                        elif not archive and k.get("archived"):
                            k.pop("archived", None); changed = True
                        break
            else:
                if archive and not o.get("archived"):
                    o["archived"] = True; changed = True
                elif not archive and o.get("archived"):
                    o.pop("archived", None); changed = True
            break

    return _write_json_safely(json_path, {"options": opts}) if changed else False


def _do_archive_label(*, target_type: str, group_key: str, option_id: str, child_id: str, archive: bool) -> bool:
    """
    Locate the storage for the (target_type, group_key) and archive/unarchive
    the option (or its child) regardless of folder/file storage.
    """
    storage, path = _group_storage(target_type, group_key)
    if storage == "folder":
        return _archive_in_folder(path, option_id, child_id, archive)
    if storage == "file":
        return _archive_in_file(path, option_id, child_id, archive)
    return False


# --- API endpoints ---------------------------------------------------------

@app.post("/api/archive_label/<type_name>")
def api_archive_label(type_name):
    # From the form in type_labels.html
    group_key   = (request.form.get("group_key") or "").strip()
    option_id   = (request.form.get("option_id") or "").strip()
    child_id    = (request.form.get("child_id") or "").strip()
    # For property-link groups, these override where we write:
    target_type = (request.form.get("target_type") or type_name).strip()
    target_path = (request.form.get("target_path") or group_key).strip()

    ok = _do_archive_label(
        target_type=target_type,
        group_key=target_path,
        option_id=option_id,
        child_id=child_id,
        archive=True,
    )
    flash("Label archived." if ok else "Couldn’t archive label (not found?).", "success" if ok else "error")
    return redirect(request.form.get("next") or request.referrer or url_for("type_labels", type_name=type_name))


@app.post("/api/unarchive_label/<type_name>")
def api_unarchive_label(type_name):
    group_key   = (request.form.get("group_key") or "").strip()
    option_id   = (request.form.get("option_id") or "").strip()
    child_id    = (request.form.get("child_id") or "").strip()
    target_type = (request.form.get("target_type") or type_name).strip()
    target_path = (request.form.get("target_path") or group_key).strip()

    ok = _do_archive_label(
        target_type=target_type,
        group_key=target_path,
        option_id=option_id,
        child_id=child_id,
        archive=False,
    )
    flash("Label unarchived." if ok else "Couldn’t unarchive label (not found?).", "success" if ok else "error")
    return redirect(request.form.get("next") or request.referrer or url_for("type_labels", type_name=type_name))


def _group_storage(type_name: str, group_key: str):
    base = os.path.join("types", type_name, "labels")
    dir_path  = os.path.join(base, group_key)
    json_path = os.path.join(base, f"{group_key}.json")
    if os.path.isdir(dir_path):
        return "folder", dir_path
    if os.path.isfile(json_path):
        return "file", json_path
    return None, None


def _read_json(path: str) -> dict:
    try:
        return load_json_as_dict(path) or {}
    except Exception:
        return {}


def _write_json(path: str, payload: dict) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print("Write error:", path, e)
        return False


def _set_group_archived(type_name: str, group_key: str, archive: bool, cascade: bool = False) -> bool:
    """
    For folder groups -> write types/<T>/labels/<GROUP>/_group.json with {"archived": true/false}
    For file groups   -> set {"archived": true/false} at top of types/<T>/labels/<GROUP>.json
    If cascade=True, also toggle every option's archived flag.
    """
    storage, path = _group_storage(type_name, group_key)
    if storage is None:
        return False

    changed = False

    if storage == "folder":
        meta_path = os.path.join(path, "_group.json")
        meta = _read_json(meta_path)
        if archive and not meta.get("archived"):
            meta["archived"] = True; changed = True
        elif not archive and meta.get("archived"):
            meta.pop("archived", None); changed = True
        if changed:
            if not _write_json(meta_path, meta):
                return False

        if cascade:
            for fn in sorted(os.listdir(path)):
                if not fn.endswith(".json") or fn == "_group.json":
                    continue
                jf = os.path.join(path, fn)
                data = _read_json(jf)
                # option itself
                if archive and not data.get("archived"):
                    data["archived"] = True; changed = True
                elif not archive and data.get("archived"):
                    data.pop("archived", None); changed = True
                # children
                kids = data.get("children") or []
                for k in kids:
                    if archive and not k.get("archived"):
                        k["archived"] = True; changed = True
                    elif not archive and k.get("archived"):
                        k.pop("archived", None); changed = True
                _write_json(jf, data)

        return True

    # storage == "file"
    doc = _read_json(path)
    if archive and not doc.get("archived"):
        doc["archived"] = True; changed = True
    elif not archive and doc.get("archived"):
        doc.pop("archived", None); changed = True

    if cascade:
        opts = doc.get("options") or []
        for o in opts:
            if archive and not o.get("archived"):
                o["archived"] = True; changed = True
            elif not archive and o.get("archived"):
                o.pop("archived", None); changed = True
            for k in (o.get("children") or []):
                if archive and not k.get("archived"):
                    k["archived"] = True; changed = True
                elif not archive and k.get("archived"):
                    k.pop("archived", None); changed = True
        doc["options"] = opts

    return _write_json(path, doc)

@app.route("/api/bio/<type_name>/<bio_id>/archive", methods=["POST"])
def api_archive_bio(type_name, bio_id):
    nxt = request.form.get("next") or request.args.get("next") or request.referrer \
          or url_for("type_browse", type_name=type_name)
    if set_bio_archived(type_name, bio_id, True):
        flash("Biography archived.", "success")
        return redirect(nxt)
    return ("Not found", 404)

@app.route("/api/bio/<type_name>/<bio_id>/unarchive", methods=["POST"])
def api_unarchive_bio(type_name, bio_id):
    nxt = request.form.get("next") or request.args.get("next") or request.referrer \
          or url_for("type_browse", type_name=type_name, show="archived")
    if set_bio_archived(type_name, bio_id, False):
        flash("Biography unarchived.", "success")
        return redirect(nxt)
    return ("Not found", 404)



@app.route("/<type_name>_step/time/<bio_id>", methods=["GET", "POST"])
def time_step(type_name, bio_id):
    labels_folder = "./types/time/labels"
    bio_folder = f"./types/{type_name}/biographies"
    os.makedirs(labels_folder, exist_ok=True)
    os.makedirs(bio_folder, exist_ok=True)

    bio_file = os.path.join(bio_folder, f"{bio_id}.json")
    if not os.path.exists(bio_file):
        return f"Biography {bio_id} not found for type {type_name}.", 404

    bio_data = load_json_as_dict(bio_file)
    name = bio_data.get("name", "[Unknown]")

    # Initial defaults
    selected_label_type = ""
    selected_subvalue = ""
    selected_date = ""
    selected_confidence = ""

    # Editing via GET
    edit_index = request.args.get("edit_entry_index")
    if request.method == "GET" and edit_index is not None:
        try:
            edit_index = int(edit_index)
            session["edit_entry_index"] = edit_index
            entries = bio_data.get("entries", [])
            if 0 <= edit_index < len(entries):
                time_data = entries[edit_index].get("time", {})
                selected_label_type = time_data.get("label_type", "")
                selected_subvalue = time_data.get("subvalue", "")
                selected_date = time_data.get("date_value", "")
                selected_confidence = time_data.get("confidence", "")
        except Exception:
            session.pop("edit_entry_index", None)

    # Post values
    if request.method == "POST":
        selected_label_type = request.form.get("label_type") or selected_label_type
        selected_subvalue = request.form.get("subvalue") or selected_subvalue
        selected_date = request.form.get("date_value") or selected_date
        selected_confidence = request.form.get("confidence") or selected_confidence

    # Default to last entry if available
    if (
        request.method == "GET"
        and not selected_label_type
        and "edit_entry_index" not in session
        and bio_data.get("entries")
    ):
        latest_entry = bio_data["entries"][-1]
        time_data = latest_entry.get("time", {})
        selected_label_type = time_data.get("label_type", "")
        selected_subvalue = time_data.get("subvalue", "")
        selected_date = time_data.get("date_value", "")
        selected_confidence = time_data.get("confidence", "")

    # Cancel edit
    if request.method == "POST" and request.form.get("cancel_edit") == "true":
        session.pop("edit_entry_index", None)
        return redirect(url_for("view_biography", type_name=type_name, bio_id=bio_id))

    # Handle form submission
    if request.method == "POST":
        try:
            confidence_value = int(selected_confidence)
        except (TypeError, ValueError):
            confidence_value = None

        valid_entry = (
            confidence_value is not None and (
                (selected_label_type == "date" and selected_date) or
                (selected_label_type != "date" and selected_subvalue)
            )
        )

        if valid_entry:
            time_entry = {
                "label_type": selected_label_type,
                "confidence": confidence_value
            }
            if selected_label_type == "date":
                time_entry["date_value"] = selected_date
                label_value = selected_date
            else:
                time_entry["subvalue"] = selected_subvalue
                label_value = selected_subvalue

            session["time_selection"] = {
                "label": label_value,
                "confidence": confidence_value,
                "label_type": selected_label_type,
                "date_value": selected_date if selected_label_type == "date" else "",
                "subvalue": selected_subvalue if selected_label_type != "date" else ""
            }
            session["bio_id"] = bio_id
            session["bio_name"] = name
            session["time_step_in_progress"] = True

            edit_index = session.pop("edit_entry_index", None)
            if edit_index is None:
                edit_index = session.get("entry_index")

            if edit_index is not None and 0 <= edit_index < len(bio_data["entries"]):
                bio_data["entries"][edit_index]["time"] = session["time_selection"]
                bio_data["entries"][edit_index]["created"] = datetime.now().isoformat()
                session["entry_index"] = edit_index
            else:
                new_entry = {
                    "time": session["time_selection"],
                    "created": datetime.now().isoformat()
                }
                bio_data.setdefault("entries", []).append(new_entry)
                session["entry_index"] = len(bio_data["entries"]) - 1

            save_dict_as_json(bio_file, bio_data)
            return redirect(url_for("general_step_labels", type_name=type_name, bio_id=bio_id))

    # Load time label types (e.g. date.json, life_stage.json)
    label_files = []
    if os.path.exists(labels_folder):
        for file in os.listdir(labels_folder):
            full_path = os.path.join(labels_folder, file)
            if file.endswith(".json") and os.path.isfile(full_path):
                try:
                    with open(full_path) as f:
                        data = json.load(f)
                        label = os.path.splitext(file)[0]
                        desc = data.get("description", "")
                        label_files.append((label, desc))
                except Exception as e:
                    print(f"[ERROR] Failed to load label {file}: {e}")

    # Load sublabels if applicable
    subfolder_labels = []
    if selected_label_type and selected_label_type != "date":
        subfolder_path = os.path.join(labels_folder, selected_label_type)
        if os.path.isdir(subfolder_path):
            for f in os.listdir(subfolder_path):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(subfolder_path, f)) as sf:
                            data = json.load(sf)
                            subfolder_labels.append({
                                "name": os.path.splitext(f)[0],
                                "description": data.get("description", ""),
                                "order": data.get("order", 999)
                            })
                    except Exception as e:
                        print(f"[ERROR] Failed to load sublabel {f}: {e}")
            subfolder_labels.sort(key=lambda x: (x.get("order", 999), x["name"]))

    # Format existing entries
    display_list = []
    for entry in bio_data.get("entries", []):
        time_info = entry.get("time", {})
        tag = time_info.get("subvalue") or time_info.get("date_value") or "[unspecified]"
        conf = time_info.get("confidence", "unknown")
        display_list.append((tag, conf))

    return render_template(
        "time_step.html",
        type_name=type_name,
        bio_id=bio_id,
        name=name,
        label_files=label_files,
        selected_label_type=selected_label_type,
        selected_subvalue=selected_subvalue,
        selected_date=selected_date,
        selected_confidence=selected_confidence,
        subfolder_labels=subfolder_labels,
        existing_entries=display_list,
        edit_entry_index=session.get("edit_entry_index")
    )

# /type/<type_name>/labels – folder-first label browser
from flask import request, redirect, url_for, flash

@app.route("/type/<type_name>/labels")
def type_labels(type_name):
    label_dir = os.path.join("types", type_name, "labels")
    if not os.path.isdir(label_dir):
        return f"No labels folder for type '{type_name}'. Expected {label_dir}", 404

    IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

    def _is_mapping(x): return isinstance(x, dict)

    def _load_json(p):
        try:
            return load_json_as_dict(p) or {}
        except Exception as e:
            print(f"[labels view] bad json {p}: {e}")
            return {}

    def _save_json(p, data: dict):
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            save_dict_as_json(p, data)
            return True
        except Exception as e:
            print(f"[labels view] save error {p}: {e}")
            return False

    def _sibling_image(folder, base):
        for ext in IMAGE_EXTS:
            cand = os.path.join(folder, base + ext)
            if os.path.exists(cand):
                rel = os.path.relpath(cand, ".").replace("\\", "/")
                return "/" + rel
        return None

    def _folder_options_for(type_key, rel_path):
        """
        Return 1-level options for types/<type_key>/labels/<rel_path>/*.json
        (ignores _group.json)
        """
        out = []
        base = os.path.join("types", type_key, "labels", *rel_path.split("/")) if rel_path else os.path.join("types", type_key, "labels")
        if not os.path.isdir(base):
            return out
        for f in sorted(os.listdir(base)):
            if not f.endswith(".json") or f == "_group.json":
                continue
            lid = os.path.splitext(f)[0]
            jp = os.path.join(base, f)
            data = _load_json(jp)
            name = (data.get("properties", {}) or {}).get("name") or data.get("display") or data.get("name") or lid
            desc = data.get("description") or (data.get("properties", {}) or {}).get("description", "") or ""
            img = _sibling_image(os.path.dirname(jp), lid)
            opt = {
                "id": lid,
                "display": name,
                "description": desc,
                "image_url": img,
                "archived": bool(data.get("archived")),
            }
            # attach children if present in file format (optional)
            kids = []
            for k in (data.get("children") or []):
                cid = (k.get("id") or "").strip()
                if not cid:
                    continue
                kids.append({
                    "id": cid,
                    "display": (k.get("display") or k.get("label") or cid.replace("_", " ").title()),
                    "description": k.get("description", ""),
                    "image_url": k.get("image_url", ""),
                    "archived": bool(k.get("archived")),
                })
            if kids:
                opt["children"] = kids
                opt["child_count"] = len(kids)
            out.append(opt)
        return out

    def _child_options_here(group_key, option_id):
        # types/<this>/labels/<group_key>/<option_id>/*.json
        child_dir = os.path.join(label_dir, *group_key.split("/"), option_id)
        rel = os.path.relpath(child_dir, os.path.join("types", type_name, "labels")).replace("\\", "/")
        return _folder_options_for(type_name, rel) if os.path.isdir(child_dir) else []

    groups = []

    # Cache list of top-level jsons
    top_level_jsons = {
        f for f in os.listdir(label_dir)
        if f.endswith(".json") and os.path.isfile(os.path.join(label_dir, f))
    }

    # ---------- 1) FOLDER GROUPS ----------
    for entry in sorted(os.listdir(label_dir)):
        full = os.path.join(label_dir, entry)
        if not os.path.isdir(full):
            continue

        # metadata from _group.json
        meta_path = os.path.join(full, "_group.json")
        meta = _load_json(meta_path) if os.path.exists(meta_path) else {}
        gname = meta.get("name") or (meta.get("properties", {}) or {}).get("name") or entry.replace("_", " ").title()
        gdesc = meta.get("description") or (meta.get("properties", {}) or {}).get("description", "") or ""
        garch = bool(meta.get("archived"))

        # options directly under this folder
        options = _folder_options_for(type_name, entry)

        # attach children one level deeper for each option (folder style)
        enhanced = []
        for opt in options:
            kids = _child_options_here(entry, opt["id"])
            if kids:
                opt = dict(opt)
                opt["children"] = kids
                opt["child_count"] = len(kids)
            enhanced.append(opt)

        groups.append({
            "key": entry,
            "label": gname,
            "description": gdesc,
            "archived": garch,
            "options": enhanced,
            "count": len(enhanced),
            "kind": "folder"
        })

    # ---------- 2) PROPERTY/FILE GROUPS ----------
    for jf in sorted(top_level_jsons):
        prop_key = os.path.splitext(jf)[0]
        prop_path = os.path.join(label_dir, jf)
        meta = _load_json(prop_path)
        if not _is_mapping(meta):
            continue

        src = meta.get("source") or (meta.get("properties", {}) or {}).get("source") or {}
        is_mapping_source = _is_mapping(src)
        kind = src.get("kind") if is_mapping_source else None

        # Only label sources here (ignore biographies)
        if is_mapping_source and kind not in ("self_labels", "type_labels") and src.get("source") != "labels":
            continue

        # Resolve target for property links
        target_type, target_path = None, None
        if is_mapping_source and kind in ("self_labels", "type_labels"):
            if kind == "self_labels":
                target_type = type_name
                target_path = src.get("path") or prop_key
            else:
                target_type = src.get("type")
                target_path = src.get("path") or prop_key
                if not target_type:
                    continue
        elif is_mapping_source and src.get("source") == "labels":
            target_type = src.get("type") or ""
            target_path = src.get("path") or prop_key

        prop_name = meta.get("name") or (meta.get("properties", {}) or {}).get("name") or prop_key.replace("_", " ").title()
        prop_desc = meta.get("description") or (meta.get("properties", {}) or {}).get("description", "") or ""
        parch = bool(meta.get("archived"))

        options = []
        if target_path:
            options = _folder_options_for(target_type or type_name, target_path)

        groups.append({
            "key": prop_key,
            "label": prop_name,
            "description": prop_desc if (not target_type or target_type == type_name) else f"{prop_desc} (from {target_type} / {target_path})",
            "archived": parch,
            "options": options,
            "count": len(options),
            "kind": "property_link",
            "target_type": target_type,
            "target_path": target_path
        })

    # sort: folders first, then property links
    groups.sort(key=lambda g: (0 if g["kind"] == "folder" else 1, g["key"]))

    return render_template("type_labels.html", type_name=type_name, groups=groups)


def _set_group_archived(type_name: str, group_key: str, *, archived: bool) -> bool:
    """
    For a folder group: write types/<type>/labels/<group_key>/_group.json {archived: bool}
    For a file/property group: write types/<type>/labels/<group_key>.json {archived: bool}
    """
    label_dir = os.path.join("types", type_name, "labels")
    folder = os.path.join(label_dir, group_key)
    filep  = os.path.join(label_dir, f"{group_key}.json")

    if os.path.isdir(folder):
        meta_path = os.path.join(folder, "_group.json")
        meta = load_json_as_dict(meta_path) if os.path.exists(meta_path) else {}
        if not isinstance(meta, dict):
            meta = {}
        meta["archived"] = bool(archived)
        try:
            save_dict_as_json(meta_path, meta)
            return True
        except Exception as e:
            print("Archive folder group error:", e)
            return False

    if os.path.isfile(filep):
        doc = load_json_as_dict(filep) or {}
        if not isinstance(doc, dict):
            doc = {}
        doc["archived"] = bool(archived)
        try:
            save_dict_as_json(filep, doc)
            return True
        except Exception as e:
            print("Archive file group error:", e)
            return False

    return False


@app.post("/api/archive_label_group/<type_name>")
def api_archive_label_group(type_name):
    group_key = (request.form.get("group_key") or "").strip()
    next_url  = request.form.get("next") or url_for("type_labels", type_name=type_name, focus=group_key)
    ok = _set_group_archived(type_name, group_key, archived=True)
    if ok:
        flash(f"Archived group “{group_key}”.", "success")
    else:
        flash(f"Could not archive group “{group_key}”.", "error")
    # keep focus and reveal archived in UI
    return redirect(f"{next_url}{'&' if '?' in next_url else '?'}focus={group_key}&show_archived=1")


@app.post("/api/unarchive_label_group/<type_name>")
def api_unarchive_label_group(type_name):
    group_key = (request.form.get("group_key") or "").strip()
    next_url  = request.form.get("next") or url_for("type_labels", type_name=type_name, focus=group_key)
    ok = _set_group_archived(type_name, group_key, archived=False)
    if ok:
        flash(f"Unarchived group “{group_key}”.", "success")
    else:
        flash(f"Could not unarchive group “{group_key}”.", "error")
    return redirect(f"{next_url}{'&' if '?' in next_url else '?'}focus={group_key}&show_archived=1")


@app.route("/api/type/<type_name>/label_paths")
def api_label_paths(type_name):
    base = os.path.join("types", type_name, "labels")
    paths = set()
    if os.path.isdir(base):
        for root, dirs, files in os.walk(base):
            rel = os.path.relpath(root, base)
            if rel == ".":
                continue
            # Only folders that contain .jsons (options/groups)
            has_json = any(f.endswith(".json") for f in files)
            if has_json:
                # normalise slashes
                paths.add(rel.replace("\\", "/"))
    return jsonify(sorted(paths))

@app.route("/api/type/<type_name>/bio_paths")
def api_bio_paths(type_name):
    base = os.path.join("types", type_name, "biographies")
    paths = set()
    if os.path.isdir(base):
        for root, dirs, files in os.walk(base):
            rel = os.path.relpath(root, base)
            if rel == ".":
                continue
            has_json = any(f.endswith(".json") for f in files)
            if has_json:
                paths.add(rel.replace("\\", "/"))
    return jsonify(sorted(paths))

@app.post("/api/time/admin/create_group")
def api_time_admin_create_group():
    p = request.get_json(silent=True) or {}
    type_name = (p.get("type_name") or "").strip()
    key = _slugify(p.get("key"))
    if not type_name or not key:
        return {"ok": False, "error": "missing_fields"}, 400
    base = os.path.join(_time_labels_root_for(type_name))
    os.makedirs(base, exist_ok=True)
    desc_path = os.path.join(base, f"{key}.json")
    if os.path.exists(desc_path):
        return {"ok": False, "error": "group_exists"}, 409
    data = {"label": (p.get("label") or key.replace("_"," ").title()),
            "description": p.get("description",""), "order": int(p.get("order", 999))}
    _safe_json_write(desc_path, data)
    os.makedirs(os.path.join(base, key), exist_ok=True)
    return {"ok": True, "group_key": key}

@app.post("/api/time/admin/create_option")
def api_time_admin_create_option():
    p = request.get_json(silent=True) or {}
    type_name = (p.get("type_name") or "").strip()
    group_key = _slugify(p.get("group_key"))
    opt_id    = _slugify(p.get("id"))
    if not type_name or not group_key or not opt_id:
        return {"ok": False, "error": "missing_fields"}, 400
    base = _time_labels_root_for(type_name)
    folder = os.path.join(base, group_key)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "group_missing"}, 404
    path = os.path.join(folder, f"{opt_id}.json")
    if os.path.exists(path):
        return {"ok": False, "error": "option_exists"}, 409
    data = {
        "id": opt_id,
        "display": p.get("display") or opt_id.replace("_"," ").title(),
        "description": p.get("description",""),
        "order": int(p.get("order", 999)),
        "start_iso": p.get("start_iso"),
        "end_iso": p.get("end_iso")
    }
    if not data["start_iso"]: data.pop("start_iso")
    if not data["end_iso"]:   data.pop("end_iso")
    _safe_json_write(path, data)
    return {"ok": True, "id": opt_id}

@app.route("/api/type/<type_name>/labels.json")
def type_labels_api(type_name):
    base = os.path.join("types", type_name, "labels")
    if not os.path.isdir(base):
        return jsonify({"error": "not_found"}), 404
    groups = collect_label_groups(base, type_name)
    return jsonify({"type": type_name, "groups": groups})

@app.post("/api/labels/admin/create_option")
def api_labels_admin_create_option():
    p = request.get_json(silent=True) or {}
    type_name = _slugify(p.get("type_name"))
    group_key = _slugify(p.get("group_key"))             # e.g. "hair_color"
    opt_id    = _slugify(p.get("id"))                    # e.g. "brown_hair"
    display   = (p.get("display") or "").strip()
    desc      = (p.get("description") or "").strip()
    image     = (p.get("image") or p.get("image_url") or "").strip()
    try:
        order = int(p.get("order", 999))
    except Exception:
        order = 999

    if not type_name or not group_key or not opt_id:
        return {"ok": False, "error": "missing_fields"}, 400

    folder = os.path.join("types", type_name, "labels", group_key)
    if not os.path.isdir(folder):
        return {"ok": False, "error": "group_missing"}, 404

    path = os.path.join(folder, f"{opt_id}.json")
    if os.path.exists(path):
        return {"ok": False, "error": "option_exists"}, 409

    data = {
        "id": opt_id,
        "display": display or opt_id.replace("_"," "),
        "description": desc,
        "order": order
    }
    if image:
        data["image_url"] = image
    _safe_json_write(path, data)
    return {"ok": True, "id": opt_id}

@app.route("/general_iframe_wizard", methods=["GET", "POST"])
def general_iframe_wizard():
    """
    Unified entry to the wizard.
    POST on step=start:
      - creates a new biography OR selects existing, then redirects to step=time.
    """
    step   = (request.args.get("step") or "start").strip()
    q_type = (request.args.get("type") or "").strip()
    bio_id = (request.args.get("bio_id") or "").strip()

    # Try to infer type from a supplied bio_id
    type_name = q_type
    if not type_name and bio_id:
        try:
            for t in list_types():
                candidate = os.path.join("types", t, "biographies", f"{bio_id}.json")
                if os.path.exists(candidate):
                    data = load_json_as_dict(candidate) or {}
                    type_name = data.get("type") or t
                    break
        except Exception:
            pass

    # (Optional) edit flags
    edit_entry = request.args.get("edit_entry_index")
    edit_bio   = request.args.get("edit_bio")

    if bio_id and type_name:
        bio_file = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
        if os.path.exists(bio_file):
            bio = load_json_as_dict(bio_file) or {}
            entries = bio.get("entries") or []

            if edit_entry is not None:
                try:
                    idx = int(edit_entry)
                    if 0 <= idx < len(entries):
                        session["entry_index"] = idx
                        session["editing_entry"] = True
                except ValueError:
                    pass

            if edit_bio:
                session["editing_bio"] = True
        else:
            session.pop("entry_index", None)
            session.pop("editing_entry", None)
            session.pop("editing_bio", None)

    # --------------------- START ---------------------
    if step == "start":
        if request.method == "POST":
            type_name = (request.form.get("type_name") or type_name or "").strip()
            chosen_bio = (request.form.get("bio_id") or "").strip()
            new_name   = (request.form.get("new_bio_name") or "").strip()

            if not type_name:
                flash("Pick a type.", "error")
                return redirect(url_for("general_iframe_wizard", step="start"))

            # If both provided, prefer existing bio
            if chosen_bio and new_name:
                new_name = ""

            # Validate existing bio belongs to the chosen type
            if chosen_bio:
                path = os.path.join("types", type_name, "biographies", f"{chosen_bio}.json")
                if not os.path.exists(path):
                    flash("That biography doesn’t belong to the selected type.", "error")
                    return redirect(url_for("general_iframe_wizard", step="start", type=type_name))
                bio_id = chosen_bio

                if session.get("editing_bio"):
                    data = load_json_as_dict(path) or {}
                    if new_name:
                        data["name"] = new_name
                    data["updated"] = now_iso_utc()
                    save_dict_as_json(path, data)

                return redirect(url_for("general_iframe_wizard", type=type_name, bio_id=bio_id, step="time"))

            # Create new bio
            bio_dir = os.path.join("types", type_name, "biographies")
            os.makedirs(bio_dir, exist_ok=True)

            slug_base = re.sub(r"[^a-zA-Z0-9_]+", "_", new_name).strip("_").lower() or "untitled"
            slug = slug_base
            i = 2
            while os.path.exists(os.path.join(bio_dir, f"{slug}.json")):
                slug = f"{slug_base}_{i}"
                i += 1

            data = {
                "id": slug,
                "uid": uuid.uuid4().hex,
                "name": new_name or slug.replace("_", " ").title(),
                "type": type_name,
                "created": now_iso_utc(),
                "updated": now_iso_utc(),
                "entries": []
            }

            # ✅ write file correctly (no trailing comma)
            save_dict_as_json(os.path.join(bio_dir, f"{slug}.json"), data)

            bio_id = slug
            session.pop("entry_index", None)
            session["editing_entry"] = False

            return redirect(url_for("general_iframe_wizard", type=type_name, bio_id=bio_id, step="time"))

        # GET start: render the picker/creator form
        types = list_types()
        # If a type is preselected, only load those bios (faster page)
        filtered_bios = list_biographies(type_name) if type_name else []
        return render_template(
            "general_step_start.html",
            types=types,
            preselected_type=type_name or "",
            filtered_bios=filtered_bios
        )

    # ------------------- other steps -------------------
    if not type_name:
        flash("Type is missing for this wizard session.", "error")
        return redirect(url_for("general_iframe_wizard", step="start"))

    return render_template(
        "general_iframe_wizard.html",
        type_name=type_name,
        bio_id=bio_id,
        step=step
    )


# ---- Small JSON endpoint used by the start page to fetch bios for a type ----
@app.route("/api/bios/list")
def api_bios_list():
    t = (request.args.get("type") or "").strip()
    if not t:
        return jsonify({"ok": False, "error": "type required"}), 400
    try:
        bios = list_biographies(t)  # expect list of dicts with id & name
        # keep payload tiny
        return jsonify({"ok": True, "items": [{"id": b["id"], "name": b.get("name", b["id"])} for b in bios]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _time_labels_root_for(type_name: str) -> str:
    # 1) per-type override, else 2) global
    p1 = os.path.join("types", type_name, "time", "labels")
    if os.path.isdir(p1):
        return p1
    return os.path.join("types", "time", "labels")

def _read_json(path: str) -> dict:
    try:
        return load_json_as_dict(path) or {}
    except Exception:
        return {}

def load_time_catalog(type_name: str) -> dict:
    """
    Returns a dict:
    {
      "categories": [ {"key":"date","description":...}, {"key":"decade",...}, ... ],
      "options": { "life_stage":[ {...}, ... ], "decade":[ {...}, ... ], "era":[ {...}, ... ] }
    }
    """
    root = _time_labels_root_for(type_name)
    os.makedirs(root, exist_ok=True)

    cats = []
    opts = {}

    # categories = all *.json at root
    for f in os.listdir(root):
        if not f.endswith(".json"):
            continue
        key = os.path.splitext(f)[0]
        meta = _read_json(os.path.join(root, f))
        cats.append({
            "key": key,
            "description": meta.get("description", ""),
            "order": meta.get("order", 999)
        })

    # options by subfolder
    for cat in [c["key"] for c in cats]:
        subdir = os.path.join(root, cat)
        if os.path.isdir(subdir):
            arr = []
            for g in os.listdir(subdir):
                if g.endswith(".json"):
                    j = _read_json(os.path.join(subdir, g))
                    arr.append({
                        "id": os.path.splitext(g)[0],
                        "display": j.get("display") or os.path.splitext(g)[0].replace("_"," ").title(),
                        "description": j.get("description", ""),
                        "order": j.get("order", 999),
                        # pass through optional bounds for normaliser
                        "start_iso": j.get("start_iso"),
                        "end_iso": j.get("end_iso"),
                        "image": j.get("image") or j.get("image_url")
                    })
            arr.sort(key=lambda x: (x.get("order", 999), x["display"]))
            opts[cat] = arr

    cats.sort(key=lambda x: (x.get("order", 999), x["key"]))
    return {"categories": cats, "options": opts}


@app.route("/general_step/time/<type_name>/<bio_id>", methods=["GET", "POST"])
def general_step_time(type_name, bio_id):
    labels_root = _time_labels_root_for(type_name)
    bio_file = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    os.makedirs(labels_root, exist_ok=True)
    if not os.path.exists(bio_file):
        return f"Biography {bio_id} not found.", 404

    bio_data = load_json_as_dict(bio_file) or {}
    bio_data.setdefault("entries", [])

    def _as_int(x, default=None):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    # ---------- edit/add mode detection (FINAL) ----------
    # Rules:
    #   • If ?edit_entry_index=i is present and valid -> EDIT that entry (overwrite).
    #   • Else -> ADD mode (append a new entry on save).
    #   • A POST with force_new=1 ALWAYS adds (even if editing).
    edit_idx_qs = request.args.get("edit_entry_index")
    editing_entry = False
    edit_index = None
    if edit_idx_qs is not None:
        maybe = _as_int(edit_idx_qs)
        if maybe is not None and 0 <= maybe < len(bio_data["entries"]):
            editing_entry = True
            edit_index = maybe

    # Optional preset (e.g., ?preset=dob)
    preset_kind = (request.args.get("preset") or "").strip()

    # ---------- read form values ----------
    selected_label_type = (request.form.get("label_type") or preset_kind or "").strip()
    selected_subvalue   = (request.form.get("subvalue") or "").strip()
    selected_date       = (request.form.get("date_value") or "").strip()
    selected_start      = (request.form.get("start_date") or "").strip()
    selected_end        = (request.form.get("end_date") or "").strip()
    selected_confidence = (request.form.get("confidence") or "").strip()
    do_save             = (request.form.get("do_save") == "1")
    force_new           = (request.form.get("force_new") == "1")  # <-- NEW

    conf_val = _as_int(selected_confidence, 100) if selected_confidence else 100

    # ---------- prefill form if editing ----------
    if not do_save and request.method in ("GET", "POST") and editing_entry:
        cur = bio_data["entries"][edit_index] or {}
        t = cur.get("time") or {}
        if not selected_label_type:
            selected_label_type = (t.get("label_type") or "").strip()
        if not selected_subvalue:
            selected_subvalue = (t.get("subvalue") or "").strip()
        if not selected_date:
            selected_date = (t.get("date_value") or "").strip()
        if not selected_start:
            selected_start = (t.get("start_date") or "").strip()
        if not selected_end:
            selected_end = (t.get("end_date") or "").strip()
        if not selected_confidence:
            selected_confidence = str(t.get("confidence", 100))
            conf_val = _as_int(selected_confidence, 100)

    # ---------- validation & save ----------
    error_message = ""
    if request.method == "POST" and do_save:
        valid = (
            (selected_label_type in ("date", "dob") and bool(selected_date)) or
            (selected_label_type == "range" and bool(selected_start or selected_end)) or
            (selected_label_type not in ("date", "dob", "range") and bool(selected_subvalue))
        )
        if not valid:
            error_message = "Please complete the selected time fields before continuing."
        else:
            raw = {"label_type": selected_label_type, "confidence": conf_val}
            label_value = ""
            if selected_label_type in ("date", "dob"):
                raw["date_value"] = selected_date
                label_value = selected_date
            elif selected_label_type == "range":
                raw["start_date"] = selected_start
                raw["end_date"]   = selected_end
                label_value = f"{selected_start or '?'}..{selected_end or ''}".strip(".")
            else:
                raw["subvalue"] = selected_subvalue
                label_value = selected_subvalue

            # Option metadata for normaliser
            catalog = load_time_catalog(type_name)
            opt_meta = None
            if selected_label_type in catalog.get("options", {}):
                for o in catalog["options"][selected_label_type]:
                    if o["id"] == selected_subvalue:
                        opt_meta = o
                        break

            try:
                from time_utils import normalise_time_for_bio_entry
            except Exception:
                normalise_time_for_bio_entry = None

            normalised = {}
            if normalise_time_for_bio_entry:
                try:
                    normalised = normalise_time_for_bio_entry(raw, biography=bio_data, option_meta=opt_meta)
                except Exception:
                    normalised = {}

            now_iso = datetime.now(timezone.utc).isoformat()

            # === decisive save target ===
            if force_new or not editing_entry:
                # APPEND a fresh entry
                entry = {"created": now_iso, "updated": now_iso}
                bio_data["entries"].append(entry)
                # update session pointer to this new entry so labels step picks it up
                session["entry_index"] = len(bio_data["entries"]) - 1
            else:
                # OVERWRITE the specific entry in explicit edit mode
                entry = bio_data["entries"][edit_index]
                entry["updated"] = now_iso

            # Save time block
            entry["time"] = raw
            if normalised:
                entry["time_normalised"] = normalised
            bio_data["updated"] = now_iso

            # convenience copy for DOB
            if selected_label_type == "dob" and selected_date:
                bio_data["dob"] = selected_date

            # compact selection for Labels header
            session["time_selection"] = {
                "label": label_value,
                "confidence": conf_val,
                "label_type": selected_label_type,
                "date_value": selected_date if selected_label_type in ("date", "dob") else "",
                "subvalue":   selected_subvalue if selected_label_type not in ("date", "dob", "range") else "",
                "start_date": selected_start if selected_label_type == "range" else "",
                "end_date":   selected_end if selected_label_type == "range" else "",
            }

            save_dict_as_json(bio_file, bio_data)
            return redirect(url_for("general_iframe_wizard", type=type_name, bio_id=bio_id, step="labels"))

    # ---------- build template data ----------
    catalog = load_time_catalog(type_name)
    label_files = [{"key": c["key"], "desc": c.get("description", "")} for c in catalog["categories"]]

    subfolder_labels = []
    if selected_label_type and selected_label_type not in ("date", "dob", "range"):
        for o in catalog.get("options", {}).get(selected_label_type, []):
            subfolder_labels.append({
                "name": o["id"],
                "description": o.get("description", ""),
                "order": o.get("order", 999)
            })
        subfolder_labels.sort(key=lambda x: (x.get("order", 999), x["name"]))

    display_list = []
    for ent in bio_data.get("entries", []):
        t = ent.get("time", {}) or {}
        tag = (
            ("DOB: " + t.get("date_value")) if (t.get("label_type") == "dob" and t.get("date_value"))
            else t.get("subvalue")
            or t.get("date_value")
            or (t.get("start_date", "") + ".." + t.get("end_date", "")).strip(".")
        )
        conf = t.get("confidence", "unknown")
        display_list.append((tag or "[unspecified]", conf))

    selected_confidence = selected_confidence or "100"

    return render_template(
        "time_step.html",
        type_name=type_name,
        bio_id=bio_id,
        name=bio_data.get("name", bio_id),
        label_files=label_files,
        selected_label_type=selected_label_type,
        selected_subvalue=selected_subvalue,
        selected_date=selected_date,
        selected_range_start=selected_start,
        selected_range_end=selected_end,
        selected_confidence=selected_confidence,
        subfolder_labels=subfolder_labels,
        existing_entries=display_list,
        error_message=error_message,
        # helpful for the template if you want to switch button labels when editing
        editing_entry=editing_entry,
        edit_index=edit_index if editing_entry else None,
    )

@app.route("/general_step/labels/<type_name>/<bio_id>", methods=["GET", "POST"])
def general_step_labels(type_name, bio_id):
    """
    Type-agnostic labels step with:
      - property-first groups (including input groups: text/textarea/date/number/select)
      - nested child expansion (saved + preview)
      - biography suggestions
      - GPT label ingestion (works even if GPT returns only an {id})
    """
    # -------- paths / load bio --------
    label_base_path = os.path.join("types", type_name, "labels")
    bio_file_path   = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    os.makedirs(label_base_path, exist_ok=True)
    if not os.path.exists(bio_file_path):
        return f"Biography file {bio_id} not found for type {type_name}.", 404

    bio_data = load_json_as_dict(bio_file_path) or {}
    bio_data.setdefault("entries", [])

    # --- helper: cast to int safely ---
    def _as_int(x, default=None):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    # --- helper: build id -> group_key index for option groups
    def _build_option_index(groups: List[Dict]) -> Dict[str, str]:
        idx: Dict[str, str] = {}
        for g in groups or []:
            gkey = g.get("key")
            for opt in g.get("options", []) or []:
                oid = opt.get("id")
                if oid and gkey:
                    idx[str(oid)] = gkey
        return idx

    # --- helper: validate an input-group value according to its meta (all optional)
    def _validate_input_group(g: dict, value: str) -> Optional[str]:
        """
        Return None if ok; otherwise return an error message string.
        Uses g.get('required') and g['input'] constraints if present:
          - min_length, max_length, pattern (regex)
        """
        inp = (g or {}).get("input") or {}
        val = (value or "").strip()

        if g.get("required") and not val:
            return f"'{g.get('label') or g.get('key')}' is required."

        # Length checks
        try:
            mn = int(inp.get("min_length")) if inp.get("min_length") is not None else None
            mx = int(inp.get("max_length")) if inp.get("max_length") is not None else None
        except Exception:
            mn = mx = None

        if mn is not None and len(val) < mn:
            return f"Must be at least {mn} characters."
        if mx is not None and len(val) > mx:
            return f"Must be at most {mx} characters."

        # Pattern check (full match)
        patt = (inp.get("pattern") or "").strip()
        if patt:
            try:
                import re
                if not re.fullmatch(patt, val or ""):
                    return "Format is invalid."
            except re.error:
                pass

        return None

    # ===== current entry (create if needed, bring across time selection) =====
    entry_index = _as_int(session.get("entry_index"))
    if entry_index is None or not (0 <= entry_index < len(bio_data["entries"])):
        now = datetime.now(timezone.utc).isoformat()
        new_entry = {"created": now, "updated": now}
        if session.get("time_selection"):
            new_entry["time"] = session["time_selection"]
        new_entry[type_name] = []
        bio_data["entries"].append(new_entry)
        entry_index = len(bio_data["entries"]) - 1
        session["entry_index"] = entry_index
        save_dict_as_json(bio_file_path, bio_data)

    bio_data["entries"][entry_index].setdefault(type_name, [])

    # -------- build base groups --------
    base_groups = collect_label_groups(label_base_path, type_name)
    base_index = _build_option_index(base_groups)

    # -------- map saved selections -> existing_labels (initial, using base index) --------
    existing_labels: Dict[str, dict] = {}
    saved_items = bio_data["entries"][entry_index].get(type_name, [])
    for it in saved_items:
        lt  = (it.get("label_type") or "").strip()
        lid = (it.get("id") or "").strip()
        payload = {"confidence": it.get("confidence", 100), "source": it.get("source", "")}
        if lid:
            payload["label"] = lid
            payload["id"]    = lid
        key = base_index.get(lid) or lt
        if key:
            existing_labels[key] = payload

    # -------- preview overlay (so a click can reveal children without saving) --------
    preview_key = (request.args.get("preview_key") or "").strip()
    preview_val = (request.args.get("preview_val") or "").strip()
    display_labels = dict(existing_labels)
    if preview_key and preview_val:
        display_labels[preview_key] = {
            "label": preview_val, "id": preview_val, "confidence": 100, "source": "preview"
        }

    # -------- expand nested groups based on current display selections --------
    selected_map = {}
    for k, v in display_labels.items():
        if isinstance(v, dict):
            sel = v.get("label") or v.get("id")
            if sel:
                selected_map[k] = sel

    try:
        expanded_groups = expand_child_groups(
            base_groups=base_groups,
            current_type=type_name,
            label_base_path=label_base_path,
            existing_labels=selected_map,
        )
    except Exception as e:
        print(f"[WARN] expand_child_groups failed: {e}")
        expanded_groups = base_groups

    # ---- REBUILD existing_labels using expanded index so child groups preselect correctly
    expanded_index = _build_option_index(expanded_groups)
    rebuilt_existing: Dict[str, dict] = {}
    for it in saved_items:
        lt  = (it.get("label_type") or "").strip()
        lid = (it.get("id") or "").strip()
        payload = {"confidence": it.get("confidence", 100), "source": it.get("source", "")}
        if lid:
            payload["label"] = lid
            payload["id"]    = lid
        key = expanded_index.get(lid) or lt
        if key:
            rebuilt_existing[key] = payload

    if preview_key and preview_val:
        rebuilt_existing[preview_key] = {
            "label": preview_val, "id": preview_val, "confidence": 100, "source": "preview"
        }

    display_labels = rebuilt_existing

    # -------- helper: find a group for a raw option id (used by GPT ingestion) --------
    def find_group_key_for_id(opt_id: str) -> Optional[str]:
        return expanded_index.get(opt_id or "")

    # ======================= POST (save) =======================
    if request.method == "POST":
        new_entries: List[dict] = []

        # ---- (A) GPT suggestions ----
        gpt_raw = (request.form.get("gpt_selected_labels_json") or "").strip()
        if gpt_raw:
            try:
                gpt_items = json.loads(gpt_raw)
                if isinstance(gpt_items, list):
                    for lab in gpt_items:
                        if not isinstance(lab, dict):
                            continue
                        lid = (lab.get("id") or "").strip()
                        if not lid:
                            continue
                        lt  = (lab.get("label_type") or "").strip()
                        if not lt:
                            maybe = find_group_key_for_id(lid)
                            if maybe:
                                lt = maybe.split("/")[-1]
                            else:
                                lt = type_name
                        try:
                            conf = int(lab.get("confidence", 100))
                        except Exception:
                            conf = 100
                        new_entries.append({
                            "id": lid,
                            "label_type": lt.split("/")[-1],
                            "confidence": conf,
                            "source": lab.get("source", "gpt"),
                        })
                else:
                    print("[GPT] Expected list, got:", type(gpt_items))
            except Exception as e:
                print("[GPT] parse error:", e)

        # ---- (B) Manual groups (inputs first, then option/bio groups) ----
        for g in expanded_groups:
            key = g.get("key", "").strip()
            if not key:
                continue

            conf_raw = (request.form.get(f"confidence_{key}") or "").strip()
            conf = int(conf_raw) if conf_raw.isdigit() else 100

            # (B1) Input groups
            if g.get("input"):
                val = (request.form.get(f"input_{key}") or "").strip()
                err = _validate_input_group(g, val)
                if err:
                    try:
                        flash(err, "error")
                    except Exception:
                        print("[WARN] flash not available:", err)
                    return redirect(request.url)

                if val:
                    new_entries.append({
                        "label_type": key.split("/")[-1],
                        "id": val,
                        "confidence": conf,
                        "source": "input",
                    })
                continue

            # (B2) Option / biography groups
            sel_id   = (request.form.get(f"selected_id_{key}") or "").strip()
            sel_bio  = (request.form.get(f"selected_id_{key}_bio") or "").strip()
            bio_conf_raw = (request.form.get(f"confidence_{key}_bio") or "").strip()
            bio_conf = int(bio_conf_raw) if bio_conf_raw.isdigit() else 100

            if sel_id or sel_bio:
                entry = {"label_type": key.split("/")[-1], "confidence": conf}
                if sel_id:
                    entry["id"] = sel_id
                if sel_bio:
                    entry["biography"] = sel_bio
                    entry["biography_confidence"] = bio_conf
                new_entries.append(entry)

        # Overwrite this entry’s labels for the current type and bump updated timestamp
        bio_data["entries"][entry_index][type_name] = new_entries
        bio_data["entries"][entry_index]["updated"] = datetime.now(timezone.utc).isoformat()
        bio_data["updated"] = bio_data["entries"][entry_index]["updated"]
        save_dict_as_json(bio_file_path, bio_data)

        # 👇 NEW: honour caller's desired next step; default to 'events'
        next_step = (request.form.get("next_step")
                    or request.args.get("next")
                    or "events").strip().lower()
        if next_step not in {"start", "time", "labels", "events", "review"}:
            next_step = "events"

        return redirect(url_for("general_iframe_wizard",
                                type=type_name, bio_id=bio_id, step=next_step))
    
        # ======================= GET (suggest bios + render) =======================
    try:
        suggested_biographies = build_suggested_biographies(
            current_type=type_name,
            label_groups_list=expanded_groups,
            label_base_path=label_base_path,
            existing_labels=display_labels,
        )
    except Exception as e:
        print(f"[WARN] build_suggested_biographies failed: {e}")
        suggested_biographies = {}

    # Map existing biography picks for preselects
    try:
        existing_bio_selections = map_existing_bio_selections(
            expanded_groups,
            bio_data["entries"][entry_index].get(type_name, [])
        )
    except Exception:
        existing_bio_selections = {}

    # -------- NEW: build fallback lists of bios for any group that links to biographies
    refer_types = set()
    for g in expanded_groups:
        ref = (g.get("refer_to") or {})
        if isinstance(ref, dict) and (ref.get("source") == "biographies"):
            rtype = (ref.get("type") or type_name).strip()
            if rtype:
                refer_types.add(rtype)

    linkable_bios = {}
    for rtype in sorted(refer_types):
        try:
            linkable_bios[rtype] = list_biographies(rtype) or []
        except Exception:
            linkable_bios[rtype] = []

    return render_template(
        "label_step.html",
        current_type=type_name,
        label_groups_list=expanded_groups,
        existing_labels=display_labels,             # saved + preview
        existing_bio_selections=existing_bio_selections,
        suggested_biographies=suggested_biographies,
        linkable_bios=linkable_bios,                # <-- NEW
        step=0,
        next_step=1,
        prev_step=None,
        bio_id=bio_id,
        time_selection=session.get("time_selection"),
        bio_name=bio_data.get("name", bio_id),
        skip_allowed=(len(expanded_groups) == 0)
    )

def _load_time_kinds_and_options():
    """
    Build:
      - time_kinds: list[{key, desc, has_folder}] from types/time/labels/*.json
      - time_options_by_key: { key: [ {id,display}, ... ] } from child files in same-named folders
    """
    base = os.path.join("types", "time", "labels")
    time_kinds, options_by_key = [], {}

    if not os.path.isdir(base):
        return time_kinds, options_by_key

    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".json"):
            continue

        key = os.path.splitext(fn)[0]  # e.g. "life_stage", "date", "range"
        data = load_json_as_dict(os.path.join(base, fn)) or {}
        desc = (data.get("description") or data.get("label") or key.replace("_", " ").title()).strip()

        has_folder = os.path.isdir(os.path.join(base, key))
        time_kinds.append({"key": key, "desc": desc, "has_folder": has_folder})

        if has_folder:
            folder = os.path.join(base, key)
            opts = []
            for cf in sorted(os.listdir(folder)):
                if not cf.endswith(".json"):
                    continue
                item = load_json_as_dict(os.path.join(folder, cf)) or {}
                oid  = (item.get("id") or os.path.splitext(cf)[0]).strip()
                disp = (item.get("display") or item.get("label") or oid.replace("_"," ").title()).strip()
                if oid:
                    opts.append({"id": oid, "display": disp})
            options_by_key[key] = opts

    return time_kinds, options_by_key


def _list_event_groups() -> list:
    base = os.path.join("types", "events", "labels")
    if not os.path.isdir(base):
        return []
    out = []
    for fn in os.listdir(base):
        if not fn.endswith(".json"):
            continue
        data = load_json_as_dict(os.path.join(base, fn)) or {}
        key = data.get("key") or os.path.splitext(fn)[0]
        label = data.get("label") or key.replace("_", " ").title()
        out.append({
            "key": key,
            "label": label,
            "description": data.get("description", ""),
            "meta": data,
        })
    out.sort(key=lambda x: x["label"].lower())
    return out


def _options_from_dir(t: str, k: str) -> list:
    base = os.path.join("types", t, "labels", k)
    if not os.path.isdir(base):
        return []
    out = []
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".json") or fn == "_group.json":
            continue
        data = load_json_as_dict(os.path.join(base, fn)) or {}
        opt_id = (data.get("id") or os.path.splitext(fn)[0]).strip()
        label = (data.get("display") or data.get("label") or data.get("name") or opt_id.replace("_", " ").title())
        opt = {"id": opt_id, "display": label}
        if isinstance(data.get("children"), list):
            opt["children"] = data["children"]
        if isinstance(data.get("refer_to"), dict):
            opt["refer_to"] = data["refer_to"]
        out.append(opt)
    return out


def _options_from_file(t: str, k: str) -> list:
    jf = os.path.join("types", t, "labels", f"{k}.json")
    if not os.path.isfile(jf):
        return []
    data = load_json_as_dict(jf) or {}
    return data.get("options", []) or []


def _merge_option_lists(*lists: list) -> list:
    """
    Merge multiple lists of options:
      [ {id, display, children?, refer_to?, description?}, ... ]

    - De‑dupes by id.
    - Prefers richer records (with children / refer_to / description / display).
    - Merges children arrays (unique by child.id) when present in either.
    - Returns list sorted by display then id (case‑insensitive).
    """
    out = {}

    def better(a: dict, b: dict) -> dict:
        if not a:
            return dict(b)
        c = dict(a)
        # Prefer richer text
        if not c.get("display") and b.get("display"):
            c["display"] = b["display"]
        if not c.get("description") and b.get("description"):
            c["description"] = b["description"]
        # Prefer refer_to when missing
        if not c.get("refer_to") and b.get("refer_to"):
            c["refer_to"] = b["refer_to"]
        # Merge children
        ach = a.get("children") or []
        bch = b.get("children") or []
        if ach or bch:
            seen = set()
            merged = []
            for src in (ach, bch):
                for ch in src:
                    cid = ch.get("id") or ch.get("key")
                    if cid and cid not in seen:
                        seen.add(cid)
                        merged.append(ch)
            c["children"] = merged
        return c

    for lst in lists:
        if not isinstance(lst, list):
            continue
        for o in lst:
            oid = o.get("id") or o.get("key")
            if not oid:
                continue
            out[oid] = better(out.get(oid), o)

    items = list(out.values())
    items.sort(key=lambda x: ((x.get("display") or x.get("id") or "").lower(),
                              (x.get("id") or "").lower()))
    return items


def _options_from_both(t: str, k: str) -> list:
    """Merge directory + file options for a (type, key) pair."""
    if not t or not k:
        return []
    return _merge_option_lists(_options_from_dir(t, k), _options_from_file(t, k))


def _resolve_group_options(scope_t: str, meta: dict, *, group_key: str, collection_type: str = "events") -> list:
    """
    Resolve options for a group by MERGING all applicable sources:

      • meta["options"] (literal list)
      • meta["source"] (kind: 'type_labels' | 'self_labels' | {source:'labels'})
      • meta["refer_to"] / meta["link_biography"] when they point to labels
      • SAFETY NET A: types/<collection_type>/labels/<group_key>/
      • SAFETY NET B: types/<scope_t>/labels/<group_key>/

    Returns one merged list, preserving 'children' (so the UI can show the Child dropdown).
    """
    if not isinstance(meta, dict):
        meta = {}

    candidate_lists = []

    # 1) literal
    lit = meta.get("options")
    if isinstance(lit, list) and lit:
        candidate_lists.append(lit)

    # 2) explicit source
    src = meta.get("source") or {}
    if isinstance(src, dict):
        kind = (src.get("kind") or "").strip()
        plain = (src.get("source") or "").strip()

        if kind in ("type_labels", "self_labels"):
            t = (src.get("type") or (scope_t if kind == "self_labels" else "")).strip()
            k = (src.get("path") or "").strip()
            candidate_lists.append(_options_from_both(t, k))

        if plain == "labels":
            t = (src.get("type") or "").strip()
            k = (src.get("path") or "").strip()
            candidate_lists.append(_options_from_both(t, k))

    # 3) labels hinted under refer_to / link_biography
    ref = meta.get("refer_to") or meta.get("link_biography") or {}
    if isinstance(ref, dict) and (ref.get("source") == "labels"):
        t = (ref.get("type") or "").strip()
        k = (ref.get("path") or "").strip()
        candidate_lists.append(_options_from_both(t, k))

    # 4) SAFETY NET A — this collection’s own labels/<group_key>
    if group_key:
        candidate_lists.append(_options_from_both(collection_type, group_key))

    # 5) SAFETY NET B — the biography scope type’s labels/<group_key>
    if group_key:
        candidate_lists.append(_options_from_both(scope_t, group_key))

    return _merge_option_lists(*candidate_lists)

@app.route("/general_step/events/<type_name>/<bio_id>", methods=["GET", "POST"])
def general_step_events(type_name, bio_id):
    bio_path = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    if not os.path.exists(bio_path):
        return f"Biography {bio_id} not found for {type_name}.", 404

    bio = load_json_as_dict(bio_path) or {}
    bio.setdefault("entries", [])

    idx = session.get("entry_index")
    if not isinstance(idx, int) or not (0 <= idx < len(bio["entries"])):
        bio["entries"].append({"created": now_iso_utc(), "updated": now_iso_utc()})
        idx = len(bio["entries"]) - 1
        session["entry_index"] = idx

    scope_type = (request.form.get("scope_type") or request.args.get("scope_type") or type_name).strip()

    groups = _list_event_groups()
    incoming_group = (request.values.get("group_key") or "").strip()
    if not incoming_group and groups:
        incoming_group = groups[0]["key"]

    group_key  = incoming_group
    group_meta = next((g["meta"] for g in groups if g["key"] == group_key), {}) if group_key else {}

    # ---- Build options_raw EARLY (merged from all sources) ----
    options_raw = _resolve_group_options(
        scope_t=scope_type,
        meta=group_meta,
        group_key=group_key,
        collection_type="events",
    )

    # ---- Default link target type (from chosen option or group) ----
    chosen_option_id = (request.form.get("option_id") or "").strip()
    refer_to_type = ""
    if chosen_option_id:
        opt = next((o for o in options_raw if o.get("id") == chosen_option_id), None)
        if opt and (opt.get("refer_to") or {}).get("source") == "biographies":
            refer_to_type = (opt["refer_to"].get("type") or "").strip()
    if not refer_to_type:
        lb = (group_meta or {}).get("link_biography") or {}
        refer_to_type = (lb.get("type") or "").strip()

    # Time kinds/options BEFORE save
    time_kinds, time_options_by_key = _load_time_kinds_and_options()

    # ---------- Save ----------
    is_save = (request.method == "POST" and (request.form.get("do_save") == "1"))
    if is_save:
        row_option_ids       = request.form.getlist("row_option_id[]")
        row_option_displays  = request.form.getlist("row_option_display[]")
        row_child_ids        = request.form.getlist("row_child_option_id[]")
        row_link_types       = request.form.getlist("row_link_type[]")
        row_link_bios        = request.form.getlist("row_link_bio[]")
        row_confidences      = request.form.getlist("row_confidence[]")

        row_time_kinds       = request.form.getlist("row_time_kind[]")
        row_time_conf        = request.form.getlist("row_time_confidence[]")
        row_date_values      = request.form.getlist("row_date_value[]")
        row_start_dates      = request.form.getlist("row_start_date[]")
        row_end_dates        = request.form.getlist("row_end_date[]")
        row_time_subvalues   = request.form.getlist("row_time_subvalue[]")
        row_time_labels      = request.form.getlist("row_time_label[]")
        row_time_label_free  = request.form.getlist("row_time_label_free[]")

        added = 0
        entry = bio["entries"][idx]
        entry.setdefault("events", [])

        n = len(row_option_ids)
        for i in range(n):
            option_id   = (row_option_ids[i] or "").strip()
            option_disp = (row_option_displays[i] or "").strip()
            child_id    = (row_child_ids[i] or "").strip() if i < len(row_child_ids) else ""
            link_type   = (row_link_types[i] or "").strip() if i < len(row_link_types) else ""
            link_bio    = (row_link_bios[i] or "").strip() if i < len(row_link_bios) else ""

            try:    conf_val = int(row_confidences[i]) if i < len(row_confidences) else 100
            except: conf_val = 100

            t_kind = (row_time_kinds[i] or "").strip() if i < len(row_time_kinds) else ""
            try:    t_conf = int(row_time_conf[i]) if i < len(row_time_conf) else 100
            except: t_conf = 100

            raw_time = None
            if t_kind:
                raw_time = {"label_type": t_kind, "confidence": t_conf}
                if t_kind == "date":
                    raw_time["date_value"] = (row_date_values[i] or "").strip() if i < len(row_date_values) else ""
                elif t_kind == "range":
                    raw_time["start_date"] = (row_start_dates[i] or "").strip() if i < len(row_start_dates) else ""
                    raw_time["end_date"]   = (row_end_dates[i] or "").strip() if i < len(row_end_dates) else ""
                else:
                    if t_kind in time_options_by_key:
                        raw_time["label_id"]   = (row_time_labels[i] or "").strip() if i < len(row_time_labels) else ""
                        raw_time["label_free"] = (row_time_label_free[i] or "").strip() if i < len(row_time_label_free) else ""
                    else:
                        raw_time["subvalue"]   = (row_time_subvalues[i] or "").strip() if i < len(row_time_subvalues) else ""

            normalised = {}
            if raw_time:
                try:
                    from time_utils import normalise_time_for_bio_entry
                    normalised = normalise_time_for_bio_entry(raw_time, biography=bio, option_meta=None) or {}
                except Exception:
                    normalised = {}

            event = {
                "group_key": group_key,
                "option_id": option_id or None,
                "child_option_id": child_id or None,
                "option_display": (option_disp or child_id or option_id) or None,
                "link_type": link_type or (refer_to_type or None),
                "linked_bio": link_bio or None,
                "confidence": conf_val,
                "time": raw_time or None,
                "time_normalised": normalised or None,
                "created": now_iso_utc(),
            }
            event = {k: v for k, v in event.items() if v not in (None, "")}
            if not event.get("option_id") and not event.get("option_display"):
                continue

            entry["events"].append(event)
            added += 1

        if added:
            entry["updated"] = now_iso_utc(); bio["updated"] = entry["updated"]
            save_dict_as_json(bio_path, bio)
            flash(f"Added {added} event{'s' if added != 1 else ''}.", "success")
        else:
            flash("No events to add.", "error")

        next_action = (request.form.get("next_action") or "stay").strip().lower()
        if next_action == "review":
            return redirect(url_for("general_iframe_wizard", type=type_name, bio_id=bio_id, step="review"))
        return redirect(url_for("general_step_events", type_name=type_name, bio_id=bio_id, group_key=group_key, start=1))

    # ---------- render ----------
    options = options_raw

    try:    type_list = list_types()
    except Exception: type_list = []

    linkable = {t: list_biographies(t) for t in type_list}
    current_events = (bio["entries"][idx] or {}).get("events", [])
    show_builder   = bool(request.args.get("start") == "1" or current_events)

    return render_template(
        "events_step.html",
        type_name=type_name,
        bio_id=bio_id,
        bio_name=bio.get("name", bio_id),
        scope_type=scope_type,
        types=type_list,
        groups=groups,
        chosen_group=group_key,
        group_doc=group_meta,
        options=options,
        allowed_types=type_list,
        linkable=linkable,
        target_bios=list_biographies(refer_to_type) if refer_to_type else [],
        time_kinds=time_kinds,
        time_options_by_key=time_options_by_key,
        current_events=current_events,
        show_builder=show_builder,
    )



# ---------- 6) Step: Review ----------
@app.route("/general_step/review/<type_name>/<bio_id>", methods=["GET"])
def general_step_review(type_name, bio_id):
    """
    Review screen for the active entry. Supports a 'new_time=1' flag that
    clears the current edit index and forwards to the Time step so a *new*
    entry will be created (instead of overwriting the existing one).
    """
    # --- guard / load biography ---
    bio_path = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    if not os.path.exists(bio_path):
        return f"Biography {bio_id} not found for {type_name}.", 404

    bio = load_json_as_dict(bio_path) or {}
    bio.setdefault("entries", [])

    # --- NEW: intercept "Add Another Time Period" intent ---
    if request.args.get("new_time") == "1":
        # Clear any edit context so the Time step appends a NEW entry.
        session.pop("entry_index", None)
        session["editing_entry"] = False  # explicit for safety
        # Also set a hint the Time step already understands (your current time route
        # checks ?new=1 to force add mode).
        return redirect(url_for("general_iframe_wizard",
                                type=type_name, bio_id=bio_id, step="time", new=1))

    # --- pick the entry to show (keep existing behaviour) ---
    entry_index = session.get("entry_index")
    entries = bio.get("entries", [])
    if isinstance(entry_index, int) and 0 <= entry_index < len(entries):
        entry = entries[entry_index]
    else:
        entry = entries[-1] if entries else {}

    # --- light derived values (keep simple / non-breaking) ---
    dob_iso = (bio.get("dob") or "").strip() or None
    # If you had a custom util for ages, keep using it; otherwise leave None
    age_now = None
    age_at_entry = None

    # Events (if any) for this entry
    events = entry.get("events", []) if isinstance(entry, dict) else []

    # Render unchanged template (below)
    return render_template(
        "general_step_review.html",
        type_name=type_name,
        bio_id=bio_id,
        bio=bio,
        events=events,
        dob_iso=dob_iso,
        age_now=age_now,
        age_at_entry=age_at_entry,
    )



@app.route("/type/<type_name>/archive", methods=["GET", "POST"])
def archive_type_confirm(type_name):
    if request.method == "POST":
        force = request.form.get("force") == "on"
        refs = scan_cross_references(type_name)
        if refs and not force:
            flash("This type is referenced by others. Tick 'Force archive' to proceed.", "error")
            return render_template("archive_type_confirm.html", type_name=type_name, refs=refs)

        try:
            dst = archive_type(type_name)
            flash(f"Archived '{type_name}' to {dst}.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            flash(str(e), "error")
            return render_template("archive_type_confirm.html", type_name=type_name, refs=refs)

    # GET: show refs & confirm
    refs = scan_cross_references(type_name)
    return render_template("archive_type_confirm.html", type_name=type_name, refs=refs)

@app.route("/type/archive")
def archived_types_list():
    root = archive_root()
    items = sorted(os.listdir(root)) if os.path.isdir(root) else []
    return render_template("archived_types.html", archived=items)

@app.route("/type/archive/restore/<archived_folder>", methods=["POST"])
def restore_archived_type(archived_folder):
    try:
        dst = restore_type(archived_folder)
        flash(f"Restored to {dst}.", "success")
    except Exception as e:
        flash(str(e), "error")
    return redirect(url_for("archived_types_list"))

@app.route("/type/<type_name>/bio/<bio_id>")
def biography_view(type_name, bio_id):
    bio_path = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    if not os.path.isfile(bio_path):
        return f"Biography '{bio_id}' not found for type '{type_name}'.", 404

    bio = load_json_as_dict(bio_path) or {}
    bio.setdefault("entries", [])

    # Optional: build a compact, display-ready view of events per entry
    def _time_text(t: dict) -> str:
        if not isinstance(t, dict):
            return ""
        kind = (t.get("label_type") or "").strip()
        if kind in ("date", "dob") and t.get("date_value"):
            return t["date_value"]
        if kind == "range" and (t.get("start_date") or t.get("end_date")):
            s = t.get("start_date") or ""
            e = t.get("end_date") or ""
            return f"{s} – {e}".strip()
        if t.get("label_id") or t.get("label_free"):
            base = t.get("label_id") or ""
            if t.get("label_free"):
                base = (base + f" ({t['label_free']})").strip()
            return base
        return (t.get("subvalue") or "").strip()

    def _linked_bio_name(link_type: str, linked_bio: str) -> str:
        if not link_type or not linked_bio:
            return ""
        try:
            bios = list_biographies(link_type)
        except Exception:
            bios = []
        hit = next((b for b in bios if b.get("id") == linked_bio), None)
        return (hit or {}).get("name", "") or linked_bio

    def _pretty_events(ev_list):
        out = []
        if isinstance(ev_list, list):
            for ev in ev_list:
                if not isinstance(ev, dict):
                    continue
                title = ev.get("option_display") or ev.get("option_id") or "Event"
                tt = _time_text(ev.get("time") or {})
                conf = ev.get("confidence")
                link_type = ev.get("link_type") or ev.get("link_kind")
                linked_bio = ev.get("linked_bio")
                out.append({
                    "title": title,
                    "time_text": tt,
                    "confidence": conf,
                    "link_type": link_type,
                    "linked_bio": linked_bio,
                    "linked_bio_name": _linked_bio_name(link_type, linked_bio) if (link_type and linked_bio) else "",
                    "group_key": ev.get("group_key"),
                })
        return out

    events_by_entry = [_pretty_events(e.get("events", [])) for e in bio["entries"]]

    return render_template(
        "biography_view.html",
        type_name=type_name,
        bio_id=bio_id,
        bio=bio,
        events_by_entry=events_by_entry,  # optional if you want to render them
    )


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9/_-]+", "_", s)  # allow _, -, /
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def _slugify_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9/_-]+", "_", s)  # allow _, -, /
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _safe_json_write(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- Properties: list ----------
@app.route("/type/<type_name>/properties")
def type_properties(type_name):
    base = os.path.join("types", type_name, "labels")
    props = []
    if os.path.isdir(base):
        for f in sorted(os.listdir(base)):
            p = os.path.join(base, f)
            if f.endswith(".json") and os.path.isfile(p):
                key = os.path.splitext(f)[0]
                try:
                    data = load_json_as_dict(p)
                except Exception:
                    data = {}
                # tolerant read
                name = (isinstance(data, dict) and (
                    data.get("name") or data.get("properties", {}).get("name")
                )) or key.replace("_"," ").title()
                desc = (isinstance(data, dict) and (
                    data.get("description") or data.get("properties", {}).get("description", "")
                )) or ""
                props.append({"key": key, "name": name, "description": desc})
    # Show subfolders too, for context (not editable here)
    subfolders = [d for d in sorted(os.listdir(base)) if os.path.isdir(os.path.join(base, d))] if os.path.isdir(base) else []
    return render_template("type_properties.html", type_name=type_name, properties=props, subfolders=subfolders)

# ---------- Properties: add ----------
@app.route("/type/<type_name>/properties/new", methods=["GET", "POST"])
def new_property(type_name):
    base = os.path.join("types", type_name, "labels")
    os.makedirs(base, exist_ok=True)

    if request.method == "POST":
        # Name -> key (auto if key blank)
        name = (request.form.get("name") or "").strip()
        raw_key = (request.form.get("key") or "").strip().lower()
        key = _slugify_key(raw_key or name)
        if not key:
            flash("Please provide a Name (the key will be auto‑generated) or a valid Key.", "error")
            return redirect(request.url)

        path = os.path.join(base, f"{key}.json")
        if os.path.exists(path):
            flash("A property with that key already exists.", "error")
            return redirect(request.url)

        payload = {
            "name": name or key.replace("_", " ").title(),
            "description": (request.form.get("description") or "").strip()
        }

        # ----- Source block -----
        source_kind = (request.form.get("source_kind") or "").strip()
        source_type = (request.form.get("source_type") or "").strip()
        source_path = (request.form.get("source_path") or "").strip()
        allow_children = checkbox_on(request, "source_allow_children")

        if source_kind == "self_labels":
            # normalize to a type_labels that points to the current type
            payload["source"] = {
                "kind": "type_labels",
                "type": type_name,
                "path": source_path or key,   # default to the property key
                "allow_children": bool(allow_children),
            }
        elif source_kind in ("type_labels", "type_biographies") and source_type:
            src = {"kind": source_kind, "type": source_type}
            if source_kind == "type_labels":
                src["path"] = source_path
                src["allow_children"] = bool(allow_children)
            payload["source"] = src
        else:
            payload.pop("source", None)


        # ----- Link biography block (optional) -----
        link_bio_type = (request.form.get("link_bio_type") or "").strip()
        if link_bio_type:
            payload["link_biography"] = {
                "type": link_bio_type,
                "path": (request.form.get("link_bio_path") or "").strip(),
                "mode": (request.form.get("link_bio_mode") or "child_or_parent").strip()
            }

        save_dict_as_json(path, payload)
        flash("Property created.", "success")
        return redirect(url_for("type_properties", type_name=type_name))

    return render_template(
        "property_edit.html",
        type_name=type_name,
        mode="new",
        prop=None,
        available_types=list_types(),
        label_groups_by_type=build_label_groups_by_type(),
    )


# ---------- Properties: edit ----------
@app.route("/type/<type_name>/properties/<prop_key>", methods=["GET", "POST"])
def edit_property(type_name, prop_key):
    base = os.path.join("types", type_name, "labels")
    path = os.path.join(base, f"{prop_key}.json")
    if not os.path.exists(path):
        return f"Property {prop_key} not found for {type_name}.", 404

    prop = load_json_as_dict(path)

    if request.method == "POST":
        # Allow rename of key (auto‑slug if blank)
        name = (request.form.get("name") or "").strip() or prop.get("name") or prop_key.replace("_", " ").title()
        raw_new_key = (request.form.get("key") or prop_key).strip().lower()
        new_key = _slugify_key(raw_new_key or name) or prop_key

        # Start from existing to avoid losing unknown future fields
        payload = dict(prop)
        payload["name"] = name
        payload["description"] = (request.form.get("description") or "").strip()

        source_kind = (request.form.get("source_kind") or "").strip()
        source_type = (request.form.get("source_type") or "").strip()
        source_path = (request.form.get("source_path") or "").strip()
        allow_children = checkbox_on(request, "source_allow_children")

        if source_kind == "self_labels":
            # normalize to a type_labels that points to the current type
            payload["source"] = {
                "kind": "type_labels",
                "type": type_name,
                "path": source_path or new_key,   # default to the property key
                "allow_children": bool(allow_children),
            }
        elif source_kind in ("type_labels", "type_biographies") and source_type:
            src = {"kind": source_kind, "type": source_type}
            if source_kind == "type_labels":
                src["path"] = source_path
                src["allow_children"] = bool(allow_children)
            payload["source"] = src
        else:
            payload.pop("source", None)


        # Link biography (optional)
        link_bio_type = (request.form.get("link_bio_type") or "").strip()
        if link_bio_type:
            payload["link_biography"] = {
                "type": link_bio_type,
                "path": (request.form.get("link_bio_path") or "").strip(),
                "mode": (request.form.get("link_bio_mode") or "child_or_parent").strip()
            }
        else:
            payload.pop("link_biography", None)

        # Save (handle rename)
        new_path = os.path.join(base, f"{new_key}.json")
        save_dict_as_json(new_path, payload)
        if new_path != path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception as e:
                print(f"[WARN] Failed to remove old property file {path}: {e}")

        flash("Property saved.", "success")
        return redirect(url_for("type_properties", type_name=type_name))

    return render_template(
        "property_edit.html",
        type_name=type_name,
        mode="edit",
        prop_key=prop_key,
        prop=prop,
        available_types=list_types(),
        label_groups_by_type=build_label_groups_by_type(),
    )


# ---------- Properties: delete ----------
@app.route("/type/<type_name>/properties/<prop_key>/delete", methods=["POST"])
def delete_property(type_name, prop_key):
    path = os.path.join("types", type_name, "labels", f"{prop_key}.json")
    if os.path.exists(path):
        os.remove(path)
        flash("Property deleted.", "success")
    else:
        flash("Nothing to delete.", "info")
    return redirect(url_for("type_properties", type_name=type_name))


def _bio_path(type_name: str, bio_id: str) -> str:
    return os.path.join("types", type_name, "biographies", f"{bio_id}.json")

def set_bio_archived(type_name: str, bio_id: str, archived: bool) -> bool:
    p = _bio_path(type_name, bio_id)
    if not os.path.exists(p):
        return False
    data = load_json_as_dict(p) or {}
    data["archived"] = bool(archived)
    if archived:
        data["archived_at"] = now_iso_utc()
    else:
        data.pop("archived_at", None)
    data["updated"] = now_iso_utc()
    save_dict_as_json(p, data)
    return True


@app.route("/suggest_labels", methods=["POST"])
def suggest_labels():
    data = request.get_json()
    user_text = data.get("text")
    type_name = data.get("type")  # e.g. 'person', 'buildings', 'organisation'

    if not user_text or not type_name:
        return jsonify({"error": "Missing input"}), 400

    try:
        suggestions = suggest_labels_from_text(user_text, type_name)
        print(f"[SUGGEST] Input: {user_text} → Suggested IDs: {suggestions}")
        return jsonify({"suggestions": suggestions or []})  # Always return list

    except Exception as e:
        print(f"[OpenAI ERROR] {e}")
        return jsonify({
            "suggestions": [],
            "error": str(e)
        }), 500

@app.route("/most_like/<type_name>/<bio_id>")
def most_like_type(type_name, bio_id):
    """
    Compare one biography against all others of the same type using an MSE-like
    score over confidence vectors, grouped by time period.

    - Vectors use confidence (0..100) per item (labels + events) per time bucket.
    - Keys are normalized to maximize intersections.
    - "Differences by time" are also recorded to explain non-overlap.
    - No time decay. Missing items are 0.
    """

    import math

    # -------------------- helpers --------------------

    def _norm(s: str) -> str:
        """Looser match: lower-case + strip. None-safe."""
        return (s or "").strip().lower()

    def _safe_name(x: dict, fallback: str) -> str:
        return (x or {}).get("name") or fallback

    def _uk_dob(meta):
        # Keep whatever you already use; prevent KeyErrors
        return meta.get("dob") or meta.get("date_of_birth") or ""

    def _time_key(entry: dict) -> str:
        """
        Stable, normalized time bucket key.
        Priority: subvalue (e.g. 'teens'), else date_value (YYYY[-MM[-DD]]),
        else "start..end", else 'unknown'.
        """
        t = (entry or {}).get("time") or {}
        if t.get("subvalue"):
            return _norm(str(t["subvalue"]))
        if t.get("date_value"):
            return _norm(str(t["date_value"]))
        if t.get("start_date") or t.get("end_date"):
            s = _norm(t.get("start_date"))
            e = _norm(t.get("end_date"))
            return f"{s}..{e}".strip(".")
        return "unknown"

    def _label_vkey(label_type: str, label_id: str) -> str:
        """Normalized vector key for a label."""
        return f"L::{_norm(label_type)}::{_norm(label_id)}"

    def _event_vkey(ev: dict) -> str:
        """
        Normalized vector key for an event.
        Uses: group_key / option_id / child_option_id / link_type / linked_bio
        (drop empties at the end).
        """
        gk   = _norm(ev.get("group_key") or "event")
        oid  = _norm(ev.get("option_id") or ev.get("option_display"))
        cid  = _norm(ev.get("child_option_id"))
        ltyp = _norm(ev.get("link_type"))
        lbio = _norm(ev.get("linked_bio"))
        parts = [p for p in (gk, oid, cid, ltyp, lbio) if p]
        return "E::" + "/".join(parts) if parts else "E::" + gk

    def _extract_vectors_by_time(bio_json: dict) -> dict:
        """
        Return:
          { "<time_key>": { "<vkey>": {confidence, kind, display, meta}, ... }, ... }
        Capture both labels (any list field that's not reserved) and events.
        """
        out = {}
        for entry in (bio_json.get("entries") or []):
            tk = _time_key(entry)
            slot = out.setdefault(tk, {})

            # Labels: any list under entry except reserved keys
            for bucket_key, values in (entry or {}).items():
                if bucket_key in ("time", "time_normalised", "events", "created", "updated", "status"):
                    continue
                if not isinstance(values, list):
                    continue
                for lab in values:
                    if not isinstance(lab, dict):
                        continue
                    lid  = (lab.get("id") or "").strip()
                    ltyp = (lab.get("label_type") or bucket_key or "").strip()
                    if not lid or not ltyp:
                        continue
                    vkey = _label_vkey(ltyp, lid)
                    slot[vkey] = {
                        "confidence": int(lab.get("confidence", 100)),
                        "kind": "label",
                        "display": lab.get("display") or lid.replace("_", " ").title(),
                        "meta": {"label_type": ltyp, "id": lid}
                    }

            # Events
            for ev in (entry.get("events") or []):
                if not isinstance(ev, dict):
                    continue
                vkey = _event_vkey(ev)
                if not vkey:
                    continue

                disp = ev.get("option_display") or ev.get("option_id") or (ev.get("group_key") or "Event")
                if ev.get("child_option_id"):
                    disp += f" → {ev.get('child_option_id')}"
                extra = []
                if ev.get("link_type"):
                    extra.append(ev["link_type"])
                if ev.get("linked_bio"):
                    extra.append(ev["linked_bio"])
                if extra:
                    disp += f" ({' → '.join(extra)})"

                slot[vkey] = {
                    "confidence": int(ev.get("confidence", 100)),
                    "kind": "event",
                    "display": disp,
                    "meta": {
                        "group_key": ev.get("group_key"),
                        "option_id": ev.get("option_id") or ev.get("option_display"),
                        "child_id": ev.get("child_option_id"),
                        "link_type": ev.get("link_type"),
                        "linked_bio": ev.get("linked_bio"),
                    },
                }
        return out

    # -------------------- load target --------------------
    target_path = os.path.join("types", type_name, "biographies", f"{bio_id}.json")
    if not os.path.exists(target_path):
        return f"{type_name} biography '{bio_id}' not found.", 404

    target = load_json_as_dict(target_path) or {}
    target_name = _safe_name(target, bio_id)
    target_vecs = _extract_vectors_by_time(target)

    # -------------------- compare with others --------------------
    bio_folder = os.path.join("types", type_name, "biographies")
    candidates = []

    for fn in sorted(os.listdir(bio_folder)):
        if not fn.endswith(".json"):
            continue
        other_id = fn[:-5]
        if other_id == bio_id:
            continue

        other = load_json_as_dict(os.path.join(bio_folder, fn)) or {}
        other_vecs = _extract_vectors_by_time(other)

        # Compare only on overlapping time buckets
        shared_times = set(target_vecs.keys()) & set(other_vecs.keys())
        if not shared_times:
            continue

        total_err = 0.0
        count = 0

        shared_labels_by_time = {}
        shared_events_by_time = {}
        diffs_by_time = {}  # present in one, missing in the other (per time bucket)

        for tk in shared_times:
            tv = target_vecs[tk]
            ov = other_vecs[tk]
            all_keys = set(tv.keys()) | set(ov.keys())

            for k in all_keys:
                t_item = tv.get(k)
                o_item = ov.get(k)
                t_conf = (t_item or {}).get("confidence", 0)
                o_conf = (o_item or {}).get("confidence", 0)

                # pure 0..100 difference → normalised to 0..1 for MSE term
                err = ((t_conf - o_conf) / 100.0) ** 2
                total_err += err
                count += 1

                if t_item and o_item:
                    row = {
                        "display": t_item["display"],
                        "confidence_1": t_conf,
                        "confidence_2": o_conf,
                    }
                    if t_item["kind"] == "event":
                        shared_events_by_time.setdefault(tk, []).append(row)
                    else:
                        row["label_type"] = t_item["meta"].get("label_type", "")
                        shared_labels_by_time.setdefault(tk, []).append(row)
                else:
                    present = t_item or o_item
                    diffs_by_time.setdefault(tk, []).append({
                        "who": "you" if t_item else "them",
                        "display": (present.get("display") if present else k),
                        "kind": (present.get("kind") if present else "label"),
                        "confidence": t_conf if t_item else o_conf,
                    })

        if count == 0:
            continue

        mse = total_err / count

        candidates.append({
            "id": other_id,
            "name": _safe_name(other, other_id),
            "dob": _uk_dob(other),
            "mse": mse,
            "shared_labels_by_time": shared_labels_by_time,
            "shared_events_by_time": shared_events_by_time,
            "diffs_by_time": diffs_by_time,              # NEW: explain non-overlap
            "time_bucket_count": len(shared_times),      # NEW: pill in UI
            "comparison_count": count,                   # NEW: pill in UI
        })

    candidates.sort(key=lambda x: x["mse"])
    top_matches = candidates[:5]

    return render_template(
        "most_like_results_generic.html",
        type_name=type_name,
        bio_id=bio_id,
        base_name=target_name,
        matches=top_matches
    )



@app.route('/add_label/<type_name>/<path:subfolder_name>', methods=['GET', 'POST'])
def add_label(type_name, subfolder_name):
    labels_dir = os.path.join('types', type_name, 'labels', subfolder_name)
    os.makedirs(labels_dir, exist_ok=True)

    def _slug(s: str) -> str:
        try:
            from utils import _slugify_key  # if you already have it
            return _slugify_key(s)
        except Exception:
            import re
            return re.sub(r'[^a-z0-9_]+', '_', (s or '').lower()).strip('_')

    if request.method == 'POST':
        # round-trip target
        return_url = request.form.get("return_url") or request.referrer or url_for('type_browse', type_name=type_name)

        # required
        raw_label_name = (request.form.get('label_name') or '').strip()
        if not raw_label_name:
            flash("❌ Please provide a label name.", "error")
            return redirect(request.url)

        # key can be overridden, else slug from name
        submitted_key = (request.form.get('label_id') or '').strip()
        label_id = _slug(submitted_key or raw_label_name)
        if not label_id:
            flash("❌ Could not derive a valid key from the name.", "error")
            return redirect(request.url)

        display_name = raw_label_name.strip()
        label_type = subfolder_name.split('/')[-1] if '/' in subfolder_name else subfolder_name

        description = (request.form.get('description') or '').strip()
        image_val   = (request.form.get('image') or '').strip()
        confidence  = int((request.form.get('confidence') or '100').strip() or 100)
        source      = (request.form.get('source') or '').strip() or 'user'
        make_children = bool(request.form.get('make_children'))
        make_stub_bio = bool(request.form.get('make_stub_bio'))
        timestamp   = datetime.now(timezone.utc).isoformat()

        # extra properties JSON
        extra_raw = (request.form.get('extra_properties') or '').strip()
        try:
            extra_properties = json.loads(extra_raw) if extra_raw else {}
            if not isinstance(extra_properties, dict):
                raise ValueError("Extra properties must be a JSON object.")
        except Exception as e:
            flash(f"❌ Invalid JSON in extra properties: {e}", "error")
            return redirect(request.url)

        # guard duplicate (case-insensitive)
        label_filename = f"{label_id}.json"
        existing = {f.lower() for f in os.listdir(labels_dir) if f.endswith('.json')}
        if label_filename.lower() in existing:
            flash("❌ A label with this key already exists in this folder.", "error")
            return redirect(request.url)

        # construct canonical label JSON
        label_path = os.path.join(labels_dir, label_filename)
        label_data = {
            "id": label_id,
            "name": display_name,           # <- for loaders that read 'name'
            "display": display_name,        # <- for UIs that read 'display'
            "label_type": label_type,
            "description": description,
            "confidence": confidence,
            "image": image_val or None,     # both keys for compatibility
            "image_url": image_val or None,
            "source": source,
            "created": timestamp,
            "properties": extra_properties or {}
        }
        # strip Nones/empties
        label_data = {k: v for k, v in label_data.items() if v not in (None, "", {}) or k == "properties"}

        # save label
        with open(label_path, 'w') as f:
            json.dump(label_data, f, indent=2)

        # optionally create nested folders
        if make_children:
            child_label_dir = os.path.join('types', type_name, 'labels', subfolder_name, label_id)
            child_bio_dir   = os.path.join('types', type_name, 'biographies', subfolder_name, label_id)
            os.makedirs(child_label_dir, exist_ok=True)
            os.makedirs(child_bio_dir, exist_ok=True)

            # optional stub biography
            if make_stub_bio:
                stub_path = os.path.join(child_bio_dir, f"{label_id}.json")
                if not os.path.exists(stub_path):
                    stub_data = {
                        "id": label_id,
                        "name": display_name,
                        "description": f"Auto-generated biography stub for label: {display_name}",
                        "source": "auto-generated from label",
                        "entries": []
                    }
                    with open(stub_path, 'w') as f:
                        json.dump(stub_data, f, indent=2)

        flash(f"✅ Label “{display_name}” added.", "success")
        if make_children:
            flash("📂 Child folders created (labels & biographies).", "success")
            if make_stub_bio:
                flash("📄 Stub biography created.", "success")

        return redirect(return_url)

    # GET
    return_url = request.args.get("return_url") or request.referrer or url_for('type_browse', type_name=type_name)
    return render_template(
        'add_label.html',
        type_name=type_name,
        subfolder_name=subfolder_name,
        return_url=return_url
    )


@app.route("/create_subfolder/<type_name>", methods=["GET", "POST"])
def create_subfolder(type_name):
    labels_root = os.path.join("types", type_name, "labels")
    bios_root   = os.path.join("types", type_name, "biographies")
    os.makedirs(labels_root, exist_ok=True)
    os.makedirs(bios_root, exist_ok=True)

    return_url = request.values.get("return_url") or request.referrer or url_for("dashboard")

    if request.method == "POST":
        display_label = (request.form.get("subfolder_label") or "").strip()
        group_desc    = (request.form.get("subfolder_desc") or "").strip()
        internal_name = (request.form.get("subfolder_name") or "").strip()
        if not internal_name and display_label:
            internal_name = _slugify_key(display_label)

        if not display_label:
            flash("Display label is required.", "error")
            return redirect(request.url)
        if not internal_name:
            flash("Could not generate a valid internal name from display label.", "error")
            return redirect(request.url)

        subfolder_path       = os.path.join(labels_root, internal_name)
        subfolder_group_meta = os.path.join(subfolder_path, "_group.json")
        bios_base_path       = os.path.join(bios_root, internal_name)

        # Make group folder & meta (folder-only definition)
        os.makedirs(subfolder_path, exist_ok=True)
        if not os.path.exists(subfolder_group_meta):
            save_dict_as_json(subfolder_group_meta, {"name": display_label, "description": group_desc})

        # ---- NEW: property JSON is OPTIONAL ---------------------------------
        make_property = (request.form.get("make_property") in ("on", "1", "true", "True"))
        if make_property:
            # Ensure a top-level {key}.json that points to this folder (preferred 'property' definition)
            _ensure_property_self_labels(type_name, internal_name, display_label, group_desc)
        # ---------------------------------------------------------------------

        # Optionally make biographies root
        if request.form.get("also_make_bio_root") == "on":
            os.makedirs(bios_base_path, exist_ok=True)

        # --- Population mode ---
        populate_mode = request.form.get("populate_mode") or "manual"

        if populate_mode == "api":
            api_url     = (request.form.get("api_url") or "").strip()
            array_path  = (request.form.get("api_array_path") or "").strip()
            field_id    = (request.form.get("api_field_id") or "id").strip()
            field_name  = (request.form.get("api_field_display") or "name").strip()
            field_desc  = (request.form.get("api_field_desc") or "description").strip()
            field_img   = (request.form.get("api_field_image") or "image_url").strip()
            max_items   = int(request.form.get("api_max_items") or "200")

            if not api_url:
                flash("API URL is required for API population.", "error")
                return redirect(request.url)

            created = _import_labels_from_api(
                type_name, internal_name, display_label, group_desc,
                api_url=api_url,
                array_path=array_path,
                field_map={
                    "id": field_id, "display": field_name,
                    "description": field_desc, "image_url": field_img
                },
                headers=None, query=None, max_items=max_items
            )
            flash(f"✅ Imported {len(created)} labels from API.", "success")

        elif populate_mode == "db_sqlite":
            sqlite_path = (request.form.get("db_sqlite_path") or "").strip()
            sql         = (request.form.get("db_sql") or "").strip()
            col_id      = (request.form.get("db_col_id") or "id").strip()
            col_name    = (request.form.get("db_col_display") or "name").strip()
            col_desc    = (request.form.get("db_col_desc") or "description").strip()
            col_img     = (request.form.get("db_col_image") or "image_url").strip()
            max_items   = int(request.form.get("db_max_items") or "500")

            if not sqlite_path or not sql:
                flash("SQLite path and SQL are required for DB population.", "error")
                return redirect(request.url)

            created = _import_labels_from_sqlite(
                type_name, internal_name, display_label, group_desc,
                sqlite_path=sqlite_path, sql=sql,
                col_id=col_id, col_display=col_name, col_desc=col_desc, col_img=col_img,
                max_items=max_items
            )
            flash(f"✅ Imported {len(created)} labels from database.", "success")

        else:
            # manual path: optionally create first label as before
            if request.form.get("create_first_label") == "on":
                raw_label_name = (request.form.get("first_label_name") or "").strip()
                if raw_label_name:
                    item = {
                        "id": raw_label_name,
                        "display": raw_label_name.strip().title(),
                        "description": (request.form.get("first_label_desc") or "").strip(),
                        "image_url": (request.form.get("first_label_image") or "").strip(),
                        "confidence": int(request.form.get("first_label_conf") or "100"),
                        "source": "user"
                    }
                    _write_label_json(subfolder_path, internal_name, item)

                    if request.form.get("make_stub_bio") == "on":
                        child_bio_dir = os.path.join(bios_base_path, _slugify_key(raw_label_name))
                        os.makedirs(child_bio_dir, exist_ok=True)
                        stub = os.path.join(child_bio_dir, f"{_slugify_key(raw_label_name)}.json")
                        if not os.path.exists(stub):
                            save_dict_as_json(stub, {
                                "id": _slugify_key(raw_label_name),
                                "name": item["display"],
                                "description": f"Auto-generated biography stub for label: {item['display']}",
                                "source": "auto",
                                "entries": []
                            })
                    flash(f"✅ Created first label “{item['display']}”.", "success")

        # UX nudge: let the user know whether a property JSON was created
        if make_property:
            flash("🧩 Property JSON created (points to this folder).", "success")
        else:
            flash("📂 Folder created (no property JSON).", "success")

        return redirect(return_url)

    # GET
    return render_template("create_subfolder.html", type_name=type_name, return_url=return_url)

@app.route('/iframe_select/<string:type_name>')
def iframe_select_type(type_name):
    """
    Displays a selector inside an iframe with:
    - Biography options (with optional images),
    - Confidence slider,
    - Optional label input.
    """
    import os, json

    biographies_path = f"./types/{type_name}/biographies"
    label_path = f"./types/{type_name}/labels"

    bios = []
    if os.path.exists(biographies_path):
        for file in os.listdir(biographies_path):
            if file.endswith(".json"):
                path = os.path.join(biographies_path, file)
                bio = load_json_as_dict(path)
                bios.append({
                    "id": bio.get("id", file[:-5]),
                    "name": bio.get("name", file[:-5]),
                    "image": bio.get("image", "")  # optional
                })

    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Select Item</title>
      <style>
        body { font-family: sans-serif; padding: 20px; }
        .bio-card {
          display: flex;
          align-items: center;
          gap: 16px;
          margin-bottom: 15px;
          padding: 10px;
          border: 1px solid #ccc;
          border-radius: 8px;
        }
        img {
          width: 64px; height: 64px;
          object-fit: cover;
          border-radius: 8px;
          background-color: #f0f0f0;
        }
        select, input[type='text'], input[type='range'] {
          margin-top: 8px;
          width: 100%;
          max-width: 300px;
        }
        .confidence-display {
          font-weight: bold;
          margin-top: 5px;
        }
      </style>
    </head>
    <body>
      <h2>Select from {type_name}</h2>
      <form method="post" action="/iframe_add_to_person">
        <input type="hidden" name="type" value="{type_name}">
        <label>Select an item:</label><br>
        <select name="item_id" required>
    """.replace("{type_name}", type_name.capitalize())

    for bio in bios:
        img_path = f"/serve_label_image/{type_name}/{bio['id']}/{bio['image']}" if bio['image'] else "/static/placeholder.png"
        html += f'<option value="{bio["id"]}">{bio["name"]}</option>'

    html += """
        </select><br><br>

        <label>Label (optional):</label><br>
        <input type="text" name="label" placeholder="e.g. inspired_by, mentor"><br><br>

        <label>Confidence:</label><br>
        <input type="range" id="confidence" name="confidence" min="0" max="100" value="80" oninput="document.getElementById('confVal').innerText = this.value + '%'">
        <div class="confidence-display">Confidence: <span id="confVal">80%</span></div>

        <br><br><button type="submit">Save & Return</button>
      </form>
    </body>
    </html>
    """

    return html

@app.route('/iframe_select_mostlike')
def iframe_select_mostlike():
    people_path = "./types/people/biographies"
    bios = []

    if os.path.exists(people_path):
        for file in os.listdir(people_path):
            if file.endswith(".json"):
                path = os.path.join(people_path, file)
                bio = load_json_as_dict(path)
                bios.append({
                    "id": bio.get("id", file[:-5]),
                    "name": bio.get("name", file[:-5]),
                    "image": bio.get("image", "")  # optional
                })

    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Most Like</title>
      <style>
        body { font-family: sans-serif; padding: 20px; }
        .card { display: flex; align-items: center; margin-bottom: 12px; border: 1px solid #ccc; padding: 10px; border-radius: 8px; }
        img { width: 60px; height: 60px; object-fit: cover; border-radius: 50%; margin-right: 15px; }
        select, input[type='range'] { width: 100%; max-width: 300px; }
        .confidence-display { font-weight: bold; margin-top: 5px; }
      </style>
    </head>
    <body>
      <h2>Choose the person you're most like</h2>
      <form method="post" action="/save_mostlike">
        <label>Person:</label><br>
        <select name="mostlike_id" required>
    """

    for bio in bios:
        html += f'<option value="{bio["id"]}">{bio["name"]}</option>'

    html += """
        </select><br><br>

        <label>Confidence:</label><br>
        <input type="range" name="confidence" min="0" max="100" value="75" oninput="document.getElementById('confShow').innerText = this.value + '%'">
        <div class="confidence-display">Confidence: <span id="confShow">75%</span></div>

        <br><button type="submit">Save and Continue</button>
      </form>
    </body>
    </html>
    """
    return html

@app.route('/save_mostlike', methods=['POST'])
def save_mostlike():
    mostlike_id = request.form.get("mostlike_id")
    confidence = request.form.get("confidence", "75")
    person_id = session.get("person_id")

    if not person_id:
        flash("No active person biography session", "danger")
        return redirect("/")

    person_file = f"./types/person/biographies/{person_id}.json"
    person_data = {}
    if os.path.exists(person_file):
        person_data = load_json_as_dict(person_file)

    person_data["mostlike"] = {
        "id": mostlike_id,
        "confidence": confidence
    }

    save_dict_as_json(person_file, person_data)

    return redirect("/person_iframe_wizard?step=2")

@app.route('/iframe_add_to_person', methods=['POST'])
def iframe_add_to_person():
    item = {
        "type": request.form["type"],
        "id": request.form["item_id"],
        "label": request.form.get("label", ""),
        "confidence": int(request.form.get("confidence", "80")) / 100.0
    }

    if "person_aggregator" not in session:
        session["person_aggregator"] = {"items": []}

    session["person_aggregator"]["items"].append(item)
    session.modified = True
    return "<script>window.top.location.href='/person_iframe_wizard';</script>"


@app.route('/finalise_person_bio')
def finalise_person_bio():
    person_id = session.get("person_id")
    if not person_id:
        return "<p>Error: No active person biography session.</p>"

    file_path = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(file_path):
        return "<p>Error: Draft biography file not found.</p>"

    # Load, mark as finalised, and save
    person = load_json_as_dict(file_path)
    person["finalised"] = True
    save_dict_as_json(file_path, person)

    person_name = person.get("name", "Unnamed Person")
    entries = person.get("entries", [])
    entry = entries[-1] if entries else {}

    # ✅ Enrich all labels in the latest entry while keeping original metadata (like 'display', 'relationship')
    for type_key, label_group in entry.items():
        if isinstance(label_group, list) and all(isinstance(l, dict) for l in label_group):
            enriched = []
            for label in label_group:
                try:
                    full = enrich_label_data(label["label_type"], label["id"])
                    merged = {**label, **full}  # merge original + enriched
                    merged["confidence"] = label.get("confidence", 100)
                    enriched.append(merged)
                except Exception as e:
                    print(f"Error enriching label: {label} - {e}")
                    enriched.append(label)
            entry[type_key] = enriched

    # Clear session variables
    session.pop("person_id", None)
    session.pop("person_name", None)
    session.pop("time_selection", None)
    session.pop("entry_index", None)
    session.pop("edit_entry_index", None)

    return render_template(
        "finalise_person_bio.html",
        person_id=person_id,
        person_name=person_name,
        entry=entry,
        dob=session.get('dob'),
        display_dob_uk=display_dob_uk
    )

@app.route('/person_summary/<person_id>')
def person_summary(person_id):
    path = f"./types/person/biographies/{person_id}.json"
    person = load_json_as_dict(path)
    entry = person.get("entries", [])[-1] if person.get("entries") else {}

    # ✅ Enrich labels
    for type_key, label_group in entry.items():
        if isinstance(label_group, list):
            enriched = []
            for label in label_group:
                if isinstance(label, dict) and "id" in label and "label_type" in label:
                    full = enrich_label_data(label["label_type"], label["id"])
                    full["confidence"] = label.get("confidence", 100)
                    enriched.append(full)
                else:
                    enriched.append(label)
            entry[type_key] = enriched

    return render_template(
        "finalise_person_bio.html",
        person_id=person_id,
        person_name=person.get("name", "Unnamed Person"),
        entry=entry,
        dob=session.get('dob'),
        display_dob_uk=display_dob_uk,
    )

@app.route('/person_view/<person_id>')
def person_view(person_id):

    def entry_summary(entry):
        """
        Generates a comma-separated summary string from a given biography entry.
        Prioritises 'display' > 'label' > 'id' and prettifies the output.
        """
        summary = []
        for key, values in entry.items():
            if key not in ["time", "created", "status"] and isinstance(values, list):
                for v in values:
                    if isinstance(v, dict):
                        label = v.get("display") or v.get("label") or v.get("id")
                        if label:
                            summary.append(label.replace("_", " ").title())
        return ", ".join(summary)

    def format_uk_date(datestr):
        """Formats YYYY-MM-DD string as DD Month YYYY (UK style)."""
        try:
            return datetime.strptime(datestr.strip(), "%Y-%m-%d").strftime("%d %B %Y")
        except:
            return datestr

    type_name = "person"
    person_file = f"./types/{type_name}/biographies/{person_id}.json"

    if not os.path.exists(person_file):
        return f"<h1>Person {person_id} Not Found</h1>", 404

    person_data = load_json_as_dict(person_file)
    person_name = person_data.get("name", f"Person {person_id}")
    show_archived = request.args.get("show_archived", "false").lower() == "true"

    # ✅ Parse DOB
    dob_str = person_data.get("dob")
    dob = None
    if dob_str:
        try:
            dob = datetime.strptime(dob_str.strip(), "%Y-%m-%d")
        except Exception as e:
            print(f"[WARNING] Could not parse DOB '{dob_str}': {e}")

    def get_sort_order(entry):
        time_info = entry.get("time", {})
        label_type = time_info.get("label_type")
        subvalue = time_info.get("subvalue", "").lower()
        date_value = time_info.get("date_value")

        # 1️⃣ Use date_value if valid
        if date_value:
            try:
                ts = datetime.strptime(date_value.strip(), "%Y-%m-%d").timestamp()
                print(f"[DEBUG] Parsed date_value '{date_value}' → {ts}")
                return ts
            except Exception as e:
                print(f"[ERROR] Invalid date_value '{date_value}': {e}")

        # 2️⃣ Estimate using LIFE_STAGE_ORDER if available
        if dob and label_type == "life_stage" and subvalue:
            order = LIFE_STAGE_ORDER.get(subvalue)
            if isinstance(order, (int, float)):
                estimated_date = dob + timedelta(days=order * 365.25)
                ts = estimated_date.timestamp()
                print(f"[DEBUG] Estimated '{subvalue}' using LIFE_STAGE_ORDER={order} → {ts}")
                return ts
            else:
                print(f"[WARNING] No valid LIFE_STAGE_ORDER for '{subvalue}'")

        # 3️⃣ Fallback
        print(f"[DEBUG] No valid sort key for entry '{subvalue or date_value}'")
        return float('inf')

    all_entries = person_data.get("entries", [])
    entries, archived_entries = [], []

    for i, raw_entry in enumerate(all_entries):
        entry_obj = {
            "time": raw_entry.get("time", {}),
            "created": raw_entry.get("created"),
            "status": raw_entry.get("status", None),
            "original_index": i
        }

        for key, value in raw_entry.items():
            if key in ["time", "created", "status"] or not isinstance(value, list):
                continue
            entry_obj[key] = resolve_entities(key, value)

        if raw_entry.get("status") == "archived":
            archived_entries.append(entry_obj)
        else:
            entries.append(entry_obj)

    # ✅ Sort by estimated timestamps
    entries.sort(key=get_sort_order)
    archived_entries.sort(key=get_sort_order)

    # 🧪 Debug: show final entry order
    print("\n=== FINAL SORTED ORDER ===")
    for e in entries:
        t = e.get("time", {})
        label = t.get("subvalue") or t.get("date_value") or "[unspecified]"
        print(f"- {label}")

    return render_template(
        "person_view.html",
        person_id=person_id,
        person_name=person_name,
        entries=entries,
        archived_entries=archived_entries,
        show_archived=show_archived,
        entry_summary=entry_summary,
        get_icon=get_icon,
        dob=person_data.get("dob"),
        display_dob_uk=display_dob_uk,
        format_uk_date=format_uk_date  
    )

@app.route('/cancel_person_creation')
def cancel_person_creation():
    person_id = session.pop('person_id', None)
    session.pop('person_name', None)

    if person_id:
        file_path = f"./types/person/biographies/{person_id}.json"
        if os.path.exists(file_path):
            os.remove(file_path)

    return redirect('/')


def printLabel(label):
    prefix = label['label']+"="  
    if "value" in label:
        return prefix+label["value"]
    else:
        return prefix+label["category"]

#In case we want to print time in a special way
def printTime(timeLabel):
    if "value" in timeLabel:
        return timeLabel["value"]
    else:
        return timeLabel["category"]


from flask import request, redirect, flash
import os, time

@app.route('/person_biography_add', methods=['GET', 'POST'])
def person_biography_add():
    """
    Allows user to create a rich 'person biography' by selecting entries from
    people, buildings, orgs, etc. Each entry includes time, optional label and notes.
    """
    save_dir = "./types/person/biographies"
    os.makedirs(save_dir, exist_ok=True)

    if request.method == "POST":
        person_name = request.form.get("person_name", "Unnamed_Person").strip()
        entry_blocks = []
        
        index = 0
        while True:
            type_ = request.form.get(f"entry_{index}_type")
            biography = request.form.get(f"entry_{index}_biography")
            entry_idx = request.form.get(f"entry_{index}_entry")
            date = request.form.get(f"entry_{index}_date")
            label = request.form.get(f"entry_{index}_label")
            notes = request.form.get(f"entry_{index}_notes")

            if not type_:
                break

            entry_blocks.append({
                "type": type_,
                "biography": biography,
                "entry_index": int(entry_idx),
                "date": date,
                "label": label,
                "notes": notes
            })
            index += 1

        person_id = f"Person_{int(time.time())}"
        save_path = os.path.join(save_dir, f"{person_id}.json")
        save_dict_as_json(save_path, {
            "id": person_id,
            "name": person_name,
            "entries": entry_blocks
        })

        flash(f"Person biography '{person_name}' saved.", "success")
        return redirect(f"/person_biography_view/{person_id}")

    # ---- GET method ----
    # Build selector form
    html = """
    <h1>Create Person Biography</h1>
    <form method='post'>
      <label>Person Name:</label>
      <input type='text' name='person_name' required><br><br>

      <div id="entry-container">
        <!-- JS will populate multiple entry blocks here -->
      </div>

      <button type='submit'>Save Person Biography</button>
    </form>

    <script>
      let counter = 0;
      function addEntryBlock() {
        const container = document.getElementById("entry-container");
        const html = `
        <div class="entry-block">
          <h4>Entry \${counter + 1}</h4>
          Type: <input name='entry_\${counter}_type' required>
          Biography: <input name='entry_\${counter}_biography' required>
          Entry #: <input name='entry_\${counter}_entry' type='number' required>
          Date: <input name='entry_\${counter}_date'>
          Label: <input name='entry_\${counter}_label'>
          Notes: <input name='entry_\${counter}_notes'>
          <hr>
        </div>`;
        container.insertAdjacentHTML('beforeend', html);
        counter++;
      }

      // Add first block by default
      window.onload = () => addEntryBlock();

      // Add button
      const btn = document.createElement('button');
      btn.textContent = "Add Entry";
      btn.type = "button";
      btn.onclick = addEntryBlock;
      document.forms[0].insertBefore(btn, document.getElementById("entry-container").nextSibling);
    </script>
    """
    return html

@app.route('/person_biography_view/<person_id>')
def person_biography_view(person_id):
    """
    View a saved person biography made of multiple entries.
    """
    path = f"./types/person/biographies/{person_id}.json"
    if not os.path.exists(path):
        return f"<h1>Person {person_id} not found.</h1>", 404

    data = load_json_as_dict(path)
    name = data.get("name", person_id)
    entries = data.get("entries", [])

    html = f"""
    <h1>Person Biography: {name}</h1>
    <ul>
    """
    for e in entries:
        html += f"<li><strong>{e['type']}</strong> → {e['biography']} / Entry #{e['entry_index']}<br>"
        html += f"Date: {e.get('date','')} | Label: {e.get('label','')} | Notes: {e.get('notes','')}" 
        html += "</li><br>"
    html += """</ul>
    <a href='/person_biography_add'>← Back to Add</a>
    """
    return html


@app.route('/biography/<string:type_name>/<string:biography_name>')
def biography_page(type_name, biography_name):
    """
    Displays a single biography with entries, formatted times (date or subfolder), 
    subfolder-based or date-based approach, plus label images and confidence if present.
    """

    # 1. Validate the path
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"""
        <h1>Error: Biography Not Found</h1>
        <p>The file <code>{biography_path}</code> does not exist.</p>
        <a href='/type/{type_name}' class='back-link'>Back</a>
        """, 404

    # 2. Load the JSON data
    bio_data = load_json_as_dict(biography_path)
    display_name = bio_data.get("name", biography_name)
    readable_time = bio_data.get("readable_time", "Unknown Time")
    description = bio_data.get("description", "No description available.")
    entries = bio_data.get("entries", [])

    # 3. (Optional) Build an image dictionary for subfolder approaches & label images
    #    If you have multiple subfolder-based approach names (like "person_decade", "celebea_face_hq"), 
    #    gather them all. For brevity, we show a single scanning of `./types/<type_name>/labels/<some_subfolder>`.
    #    This is similar to what we do in 'editlabel' or 'addlabel'.
    image_dict = {}  # e.g. {"celebea_face_hq:1": "/serve_label_image/people/celebea_face_hq/1.jpg"}
    
    # Path for label definitions
    labels_base_path = f"./types/{type_name}/labels"
    if os.path.exists(labels_base_path) and os.path.isdir(labels_base_path):
        for lbl_folder in os.listdir(labels_base_path):
            # each lbl_folder might be "person_decade", "celebea_face_hq", etc.
            possible_folder = os.path.join(labels_base_path, lbl_folder)
            if os.path.isdir(possible_folder):
                # gather images
                image_files = [f for f in os.listdir(possible_folder) if f.endswith((".jpg",".png"))]
                for img in image_files:
                    base = os.path.splitext(img)[0]  # e.g. "1"
                    # store "lbl_folder:base" => serve path
                    image_key = f"{lbl_folder}:{base}"
                    image_dict[image_key] = f"/serve_label_image/{type_name}/{lbl_folder}/{img}"
            # (We ignore .json in these subfolders for this route, just images.)
    
    # # A small helper to prettify approach names (split underscores, capitalize words)
    # def prettify_name(raw: str) -> str:
    #     return " ".join(word.capitalize() for word in raw.split("_"))

    # 4. Start building the HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function removeBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to remove this biography? It will be archived.")) {{
                    fetch(`/biography_remove/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography archived successfully.");
                                window.location.href = "/type/" + typeName;
                            }} else {{
                                alert("Error archiving biography.");
                            }}
                        }});
                }}
            }}

            function removeEntry(typeName, biographyName, entryIndex) {{
                if (confirm("Are you sure you want to remove this entry?")) {{
                    fetch(`/biography_removeentry/${{typeName}}/${{biographyName}}/${{entryIndex}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Entry removed successfully.");
                                location.reload();
                            }} else {{
                                alert("Error removing entry.");
                            }}
                        }});
                }}
            }}

            function removeLabel(typeName, biographyName, entryIndex, labelIndex) {{
                if (confirm("Are you sure you want to remove this label?")) {{
                    fetch(`/biography_removelabel/${{typeName}}/${{biographyName}}/${{entryIndex}}/${{labelIndex}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Label removed successfully.");
                                location.reload();
                            }} else {{
                                alert("Error removing label.");
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/type/{type_name}" class="back-link">Back</a>
            <h1>{display_name.capitalize()}</h1>
            <p class="timestamp">Created: {readable_time}</p>
            <p class="description">{description}</p>

            <!-- Edit or Remove biography -->
            <button class="edit-biography-button" onclick="window.location.href='/biography_edit/{type_name}/{biography_name}'">
                Edit Biography
            </button>
            <button class="delete-button" onclick="removeBiography('{type_name}', '{biography_name}')">Remove Biography</button>
            
            <h2>Entries</h2>
            <a href="/biography_addentry/{type_name}/{biography_name}" class="button add-entry-button">Add New Entry</a>

            <div class="entries-container">
    """

    # 5. Loop through each entry
    for entry_index, entry in enumerate(entries):
        time_period = entry.get("time_period", {})
        start_info = time_period.get("start", {})
        end_info   = time_period.get("end", {})

        # Format the start
        start_str, start_img_html = format_time_approach(start_info, image_dict, prettify)
        end_str, end_img_html     = format_time_approach(end_info, image_dict, prettify)

        # Now build the HTML for the entry
        entry_html = f"""
        <div class="entry">
            <p><strong>From:</strong> {start_str}</p>
            {start_img_html}
            <p><strong>To:</strong> {end_str}</p>
            {end_img_html}

            <div class="entry-actions">
                <a href="/biography_editentry/{type_name}/{biography_name}/{entry_index}" class="edit-entry-button">Edit Entry</a>
                <button class="remove-entry-button" onclick="removeEntry('{type_name}', '{biography_name}', {entry_index})">Remove Entry</button>
                <a href="/biography_addlabel/{type_name}/{biography_name}/{entry_index}" class="add-label-button">Add Label</a>
            </div>
            <h3>Labels:</h3>
            <div class="labels-container">
        """

        # Display each label
        labels_list = entry.get("labels", [])
        if labels_list:
            for label_index, label_item in enumerate(labels_list):
                lbl_name = label_item.get("label","Unknown")
                lbl_val  = label_item.get("value","Unknown")
                lbl_conf = label_item.get("confidence", None)

                # Prettify label name
                pretty_label_name = prettify(lbl_name)  # e.g. "Celebea Face Hq"
                # Build label text 
                conf_str = f"(Confidence: {lbl_conf})" if lbl_conf is not None else ""
                label_str = f"{pretty_label_name}: {lbl_val} {conf_str}"

                # Check if there's an image for this label
                # e.g. "celebea_face_hq:1"
                image_key = f"{lbl_name}:{lbl_val}"
                if image_key in image_dict and image_dict[image_key] is not None:
                    label_img = f"<img src='{image_dict[image_key]}' alt='Label Image' style='max-width:100px;'>"
                else:
                    label_img = ""

                entry_html += f"""
                <div class="label-box">
                    <span><strong>{label_str}</strong></span>
                    {label_img}
                    <div class="label-actions">
                        <a href="/biography_editlabel/{type_name}/{biography_name}/{entry_index}/{label_index}" class="edit-label-button">Edit</a>
                        <button class="remove-label-button" onclick="removeLabel('{type_name}', '{biography_name}', {entry_index}, {label_index})">Remove</button>
                    </div>
                </div>
                """
        else:
            entry_html += "<p>No labels added yet.</p>"

        entry_html += "</div></div>"  # close .labels-container, .entry
        html_template += entry_html

    html_template += """
            </div> <!-- end .entries-container -->
        </div> <!-- end .container -->
    </body>
    </html>
    """

    return html_template


def format_time_approach(time_dict, image_dict, prettify_func):
    """
    Helper function to format a single 'start' or 'end' dictionary 
    from new_entry["time_period"]["start"] or ["end"].
    Returns (text, optional_image_html).
    """
    if not time_dict:
        return ("<em>Unknown</em>", "")

    approach = time_dict.get("approach", None)
    if approach == "date":
        # partial year vs. exact date
        mode = time_dict.get("mode","exact")
        val  = time_dict.get("value","")
        is_partial = time_dict.get("is_partial", False)
        if is_partial:
            display_str = f"(Year Only) {val}"
        else:
            display_str = val if val else "<em>No date</em>"
        # no subfolder image in date approach, presumably
        return (display_str, "")
    elif approach in (None, "time"): 
        # Maybe you used the older logic or no approach?
        # We can attempt to display subfolder_type + subfolder_value
        sub_type = time_dict.get("subfolder_type","").lower()
        sub_val  = time_dict.get("subfolder_value","")
        if sub_type and sub_val:
            # Prettify name
            pretty_sub_type = prettify_func(sub_type)
            # Possibly see if there's an image
            image_key = f"{sub_type}:{sub_val}"
            if image_key in image_dict and image_dict[image_key] is not None:
                return (f"{pretty_sub_type} => {sub_val}", 
                        f"<img src='{image_dict[image_key]}' style='max-width:100px;' alt='Time Image'>")
            else:
                return (f"{pretty_sub_type} => {sub_val}", "")
        else:
            return ("<em>Unknown</em>", "")
    else:
        # approach might be e.g. "person_decade", "celebea_face_hq", etc.
        # or from your code: { 'approach': 'person_decade', 'label': 'person_decade', 'value': '1920s'}
        # We'll try to show approach + value, plus image
        approach_label = prettify_func(approach)
        val = time_dict.get("value","")
        image_key = f"{approach}:{val}"
        if image_key in image_dict and image_dict[image_key] is not None:
            return (f"{approach_label}: {val}", 
                    f"<img src='{image_dict[image_key]}' style='max-width:100px;' alt='Time Image'>")
        else:
            return (f"{approach_label}: {val}", "")



@app.route('/biography_removeentry/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_removeentry(type_name, biography_name, entry_index):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    asDict = load_json_as_dict(biography_path)

    # Remove entry
    try:
        del asDict["entries"][entry_index]
    except IndexError:
        return "Entry not found", 404

    # Save updated JSON
    save_dict_as_json(biography_path, asDict)

    return "Success", 200

@app.route('/biography_removelabel/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['POST'])
def biography_removelabel(type_name, biography_name, entry_index, label_index):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"

    # Load biography data
    asDict = load_json_as_dict(biography_path)

    # Ensure the entry exists
    if entry_index >= len(asDict.get("entries", [])):
        flash("Error: Entry not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    entry = asDict["entries"][entry_index]

    # Ensure labels exist for this entry
    if "labels" not in entry or not entry["labels"]:
        flash("Error: No labels to remove.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Ensure the label index is within range
    if label_index >= len(entry["labels"]):
        flash("Error: Label not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Remove the label
    removed_label = entry["labels"].pop(label_index)

    # Save updated JSON
    save_dict_as_json(biography_path, asDict)

    flash(f"Label '{removed_label['label']}' removed successfully.", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")



@app.route('/biography_addentry/<string:type_name>/<string:biography_name>', methods=['GET','POST'])
def biography_addentry_page(type_name, biography_name):
    """
    Displays a combined approach for adding a new entry:
      - If user chooses "date", we show exact/partial date fields for start & end.
      - If user chooses a label folder with a subfolder (e.g. 'person_decade'),
        we show subfolder-based dropdown for start & end (like 'twenties','thirties'),
        with prettified names.

    All folder names (e.g. 'person_decade') and subfolder values (e.g. 'thirties') 
    are displayed in a prettified form ('Person Decade','Thirties'). 
    However, we store the raw string in the JSON to keep consistency.

    Under the hood, if approach == 'date', no subfolder. 
    If approach == 'person_decade', we read the subfolder /types/time/labels/person_decade/*.json 
    and build a dropdown (plus a custom option).
    """

    import os, json

    # ----------- 1) Load the biography data -----------
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    display_name = bio_data.get("name", biography_name)
    if "entries" not in bio_data:
        bio_data["entries"] = []

    # A helper to load the subfolder-based approach
    # We'll unify them in one dictionary: { "date": { "raw":"date","pretty":"Date","has_subfolder":False,"values":[] } ... }

    # We'll define a function to prettify underscores, e.g. 'person_decade' => 'Person Decade'
    def prettify_label(s: str) -> str:
        return " ".join(part.capitalize() for part in s.split("_"))

    # ----------- 2) Build the approach dictionary -----------
    # By default, we have "date" approach => no subfolder => partial or exact date
    approach_dict = {
        "date": {
            "raw": "date",
            "pretty": "Date",
            "has_subfolder": False,
            "values": []  # no subfolder-based values
        }
    }

    # We'll also parse the /types/time/labels/ directory to find subfolder-based approaches.
    times_path = "./types/time/labels"
    if os.path.exists(times_path) and os.path.isdir(times_path):
        for file in os.listdir(times_path):
            if not file.endswith(".json"):
                continue
            folder_name = os.path.splitext(file)[0]  # e.g. 'person_decade'
            if folder_name == "date":
                # skip if there's an actual date.json, because we handle 'date' above
                continue

            subfolder_path = os.path.join(times_path, folder_name)
            if os.path.isdir(subfolder_path):
                # gather .json => sub-values
                sub_files = [f for f in os.listdir(subfolder_path) if f.endswith(".json")]
                # We'll store them as { 'raw':'thirties','pretty':'Thirties' }
                sub_values_list = []
                for sf in sub_files:
                    raw_val = os.path.splitext(sf)[0]  # e.g. 'thirties'
                    sub_values_list.append({
                        "raw": raw_val,
                        "pretty": prettify_label(raw_val)
                    })

                approach_dict[folder_name] = {
                    "raw": folder_name,  # e.g. 'person_decade'
                    "pretty": prettify_label(folder_name),  # e.g. 'Person Decade'
                    "has_subfolder": True,
                    "values": sub_values_list
                }
            else:
                # a .json with no subfolder => skip or handle differently
                pass

    # Example approach_dict might be:
    # {
    #   "date": { "raw":"date","pretty":"Date","has_subfolder":False,"values":[] },
    #   "person_decade": {
    #       "raw":"person_decade","pretty":"Person Decade","has_subfolder":True,
    #       "values":[ {"raw":"twenties","pretty":"Twenties"}, ... ]
    #   }
    # }

    # -------------- POST LOGIC --------------
    from flask import request, redirect, flash
    if request.method == 'POST':
        chosen_approach = request.form.get("start_approach","date").strip()
        if chosen_approach not in approach_dict:
            chosen_approach = "date"  # fallback

        # parse START time
        if approach_dict[chosen_approach]["has_subfolder"]:
            # subfolder approach
            start_val_raw = request.form.get("start_sub_val","").strip()
            if start_val_raw == "custom":
                start_val_raw = request.form.get("start_custom_val","").strip() or "Custom"
            start_time = {
                "approach": chosen_approach,  # e.g. 'person_decade'
                "value": start_val_raw  # store the raw string
            }
        else:
            # 'date' approach
            start_mode = request.form.get("start_date_mode","exact")
            if start_mode == "exact":
                s_date = request.form.get("start_full_date","").strip()
                if not s_date: s_date = "No Date"
                start_time = {
                    "approach": "date",
                    "mode": "exact",
                    "value": s_date,
                    "is_partial": False
                }
            else:
                s_year = request.form.get("start_partial_year","").strip()
                if not s_year: s_year = "Unknown Year"
                start_time = {
                    "approach": "date",
                    "mode": "partial",
                    "value": s_year,
                    "is_partial": True
                }

        # parse END time (same approach)
        if approach_dict[chosen_approach]["has_subfolder"]:
            end_val_raw = request.form.get("end_sub_val","").strip()
            if end_val_raw == "custom":
                end_val_raw = request.form.get("end_custom_val","").strip() or "Custom"
            end_time = {
                "approach": chosen_approach,
                "value": end_val_raw
            }
        else:
            end_mode = request.form.get("end_date_mode","exact")
            if end_mode == "exact":
                e_date = request.form.get("end_full_date","").strip()
                if not e_date: e_date = "No Date"
                end_time = {
                    "approach": "date",
                    "mode": "exact",
                    "value": e_date,
                    "is_partial": False
                }
            else:
                e_year = request.form.get("end_partial_year","").strip()
                if not e_year: e_year = "Unknown Year"
                end_time = {
                    "approach": "date",
                    "mode": "partial",
                    "value": e_year,
                    "is_partial": True
                }

        # build new entry
        new_entry = {
            "time_period": {
                "start": start_time,
                "end":   end_time
            },
            "labels": []
        }
        bio_data["entries"].append(new_entry)
        save_dict_as_json(json_file_path, bio_data)
        flash("Entry added successfully!", "success")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # -------- GET => build the form -----------
    # build an approach <option> list from approach_dict
    approach_html = ""
    for key, meta in approach_dict.items():
        # e.g. key='person_decade', meta['pretty'] = 'Person Decade'
        approach_html += f'<option value="{key}">{meta["pretty"]}</option>'

    # We'll build a JS object: { "person_decade": [ {raw:"twenties",pretty:"Twenties"}, ... ], "date":[] }
    # so we can populate start_sub_val, end_sub_val with prettified text
    subfolder_obj = {}
    for a_name, data in approach_dict.items():
        if data["has_subfolder"]:
            # data["values"] is a list of dicts like { raw:"thirties", pretty:"Thirties" }
            subfolder_obj[a_name] = data["values"]
        else:
            subfolder_obj[a_name] = []  # no subfolder

    subfolder_json = json.dumps(subfolder_obj)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Add Entry - {display_name}</title>
      <link rel="stylesheet" href="/static/styles.css">
      <script>
        let subfoldersMap = {subfolder_json};

        function onApproachChange() {{
          let approachSel = document.getElementById("start_approach").value;
          document.getElementById("end_approach").value = approachSel;

          // If this approach has subfolder => show subfolder approach
          if (subfoldersMap[approachSel] && subfoldersMap[approachSel].length > 0) {{
             document.getElementById("start_date_section").style.display = "none";
             document.getElementById("end_date_section").style.display   = "none";

             document.getElementById("start_subfolder_section").style.display = "block";
             document.getElementById("end_subfolder_section").style.display   = "block";

             // populate start_sub_val
             let startSel = document.getElementById("start_sub_val");
             startSel.innerHTML = "";
             subfoldersMap[approachSel].forEach(obj => {{
                let opt = document.createElement("option");
                opt.value = obj.raw;           // store raw in 'value'
                opt.textContent = obj.pretty;  // display prettified
                startSel.appendChild(opt);
             }});
             // add 'custom'
             let custOpt = document.createElement("option");
             custOpt.value = "custom";
             custOpt.textContent = "Enter Custom Value";
             startSel.appendChild(custOpt);

             // do same for end_sub_val
             let endSel = document.getElementById("end_sub_val");
             endSel.innerHTML = "";
             subfoldersMap[approachSel].forEach(obj => {{
                let opt = document.createElement("option");
                opt.value = obj.raw;
                opt.textContent = obj.pretty;
                endSel.appendChild(opt);
             }});
             let cust2 = document.createElement("option");
             cust2.value = "custom";
             cust2.textContent = "Enter Custom Value";
             endSel.appendChild(cust2);

          }} else {{
             // approachSel = 'date' or no subfolder => show date approach
             document.getElementById("start_subfolder_section").style.display = "none";
             document.getElementById("end_subfolder_section").style.display   = "none";

             document.getElementById("start_date_section").style.display = "block";
             document.getElementById("end_date_section").style.display   = "block";
          }}
        }}

        function toggleDateMode(prefix) {{
          let mode = document.querySelector('input[name="' + prefix + '_date_mode"]:checked').value;
          let fullDate = document.getElementById(prefix + '_full_date');
          let partialY = document.getElementById(prefix + '_partial_year');
          if (mode === "exact") {{
            fullDate.style.display = "inline-block";
            partialY.style.display = "none";
          }} else {{
            fullDate.style.display = "none";
            partialY.style.display = "inline-block";
          }}
        }}

        function checkCustomSub(prefix) {{
          let valSel = document.getElementById(prefix + '_sub_val');
          let customInput = document.getElementById(prefix + '_custom_val');
          if (valSel.value === 'custom') {{
            valSel.style.display = 'none';
            customInput.style.display = 'inline-block';
          }} else {{
            customInput.style.display = 'none';
            valSel.style.display = 'inline-block';
          }}
        }}

        window.onload = function() {{
          onApproachChange();
          toggleDateMode('start');
          toggleDateMode('end');
        }}
      </script>
    </head>

    <body>
      <div class="container">
        <a href="/biography/{type_name}/{biography_name}" class="back-link">Back</a>
        <h1>Add Entry to {display_name}</h1>

        <form method="post">
          <!-- Approach: e.g. "date" or "person_decade" -->
          <label>Approach:</label>
          <select id="start_approach" name="start_approach" onchange="onApproachChange()">
            {approach_html}
          </select>
          <input type="hidden" id="end_approach" name="end_approach" value="date">

          <hr>

          <!-- START: date approach -->
          <div id="start_date_section" style="display:none;">
            <h3>Start Date Approach</h3>
            <label>
              <input type="radio" name="start_date_mode" value="exact" checked
                     onclick="toggleDateMode('start')">
              Exact
            </label>
            <label>
              <input type="radio" name="start_date_mode" value="year"
                     onclick="toggleDateMode('start')">
              Year Only
            </label>
            <br>
            <label>Exact Start Date:</label>
            <input type="date" id="start_full_date" name="start_full_date" style="display:inline-block;">

            <label>Partial Start Year:</label>
            <input type="number" id="start_partial_year" name="start_partial_year"
                   min="1" max="9999" style="display:none;" placeholder="1952">
          </div>

          <!-- START: subfolder approach -->
          <div id="start_subfolder_section" style="display:none;">
            <h3>Start Subfolder Approach</h3>
            <label>Pick Value:</label>
            <select id="start_sub_val" name="start_sub_val" onchange="checkCustomSub('start')">
              <!-- JS populates with prettified items -->
            </select>
            <input type="text" id="start_custom_val" name="start_custom_val"
                   placeholder="Custom" style="display:none;">
          </div>

          <hr>

          <!-- END: date approach -->
          <div id="end_date_section" style="display:none;">
            <h3>End Date Approach</h3>
            <label>
              <input type="radio" name="end_date_mode" value="exact" checked
                     onclick="toggleDateMode('end')">
              Exact
            </label>
            <label>
              <input type="radio" name="end_date_mode" value="year"
                     onclick="toggleDateMode('end')">
              Year Only
            </label>
            <br>
            <label>Exact End Date:</label>
            <input type="date" id="end_full_date" name="end_full_date" style="display:inline-block;">
            <label>Partial End Year:</label>
            <input type="number" id="end_partial_year" name="end_partial_year"
                   min="1" max="9999" style="display:none;" placeholder="1980">
          </div>

          <!-- END: subfolder approach -->
          <div id="end_subfolder_section" style="display:none;">
            <h3>End Subfolder Approach</h3>
            <label>Pick Value:</label>
            <select id="end_sub_val" name="end_sub_val" onchange="checkCustomSub('end')">
              <!-- JS populates -->
            </select>
            <input type="text" id="end_custom_val" name="end_custom_val"
                   placeholder="Custom" style="display:none;">
          </div>

          <hr>
          <button type="submit">Add Entry</button>
        </form>
      </div>
    </body>
    </html>
    """




@app.route('/biography_addentry_submit/<string:type_name>/<string:biography_name>', methods=['POST'])
def biography_addentry_submit(type_name, biography_name):
    """
    POST to create a new entry. Checks if user picked 'date' or 'person_decade'.
    If 'date', parse exact/partial date fields.
    If 'person_decade', parse subfolder fields.
    """
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    if "entries" not in bio_data:
        bio_data["entries"] = []

    # 1. Grab approach for start & end
    start_approach = request.form.get("start_approach", "date")   # e.g. 'date' or 'person_decade'
    end_approach   = request.form.get("end_approach", "date")

    # We'll build a dictionary for start_time, end_time

    # -------- START --------
    if start_approach == "date":
        # parse radio => exact or year
        start_date_mode = request.form.get("start_date_mode", "exact")
        if start_date_mode == "exact":
            start_date_val = request.form.get("start_full_date", "").strip()  # "2025-03-25"
            start_is_partial = False
        else:
            start_date_val = request.form.get("start_partial_year", "").strip()  # e.g. "1952"
            start_is_partial = True

        start_data = {
            "approach": "date",
            "mode": start_date_mode,
            "value": start_date_val,
            "is_partial": start_is_partial
        }

    else:
        # approach = 'person_decade' or any subfolder-based
        start_label = request.form.get("start_time_label", "").strip()
        start_value = request.form.get("start_time_value", "").strip()
        if start_value == "custom":
            start_custom = request.form.get("start_custom_time_value", "").strip()
            if start_custom:
                start_value = start_custom

        start_data = {
            "approach": "person_decade",  # or subfolder approach
            "label": start_label,
            "value": start_value
        }

    # -------- END --------
    if end_approach == "date":
        end_date_mode = request.form.get("end_date_mode", "exact")
        if end_date_mode == "exact":
            end_date_val = request.form.get("end_full_date", "").strip()
            end_is_partial = False
        else:
            end_date_val = request.form.get("end_partial_year", "").strip()
            end_is_partial = True

        end_data = {
            "approach": "date",
            "mode": end_date_mode,
            "value": end_date_val,
            "is_partial": end_is_partial
        }
    else:
        end_label = request.form.get("end_time_label", "").strip()
        end_value = request.form.get("end_time_value", "").strip()
        if end_value == "custom":
            end_custom = request.form.get("end_custom_time_value", "").strip()
            if end_custom:
                end_value = end_custom

        end_data = {
            "approach": "person_decade",
            "label": end_label,
            "value": end_value
        }

    # 2. Build the new entry
    new_entry = {
        "time_period": {
            "start": start_data,
            "end": end_data
        },
        "labels": []
    }

    # 3. Save
    bio_data["entries"].append(new_entry)
    save_dict_as_json(json_file_path, bio_data)

    flash("Entry added successfully!", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")



@app.route('/biography_editentry/<string:type_name>/<string:biography_name>/<int:entry_index>')
def biography_editentry_page(type_name, biography_name, entry_index):
    """
    A fully updated Edit Entry route that:
      1) Lets the user pick 'date' approach or a subfolder approach (e.g. 'person_decade').
      2) If 'date' is chosen, user must pick 'exact' or 'partial' for start/end.
         - 'exact' => <input type="date">
         - 'partial' => a <select> of years 1900..2100, with type-ahead logic.
      3) Ensures End date/year >= Start date/year if both are 'date' approach.
      4) Hides partial-year field when 'exact' is selected, hides exact-date field if 'partial' is selected.
      5) Syncs approach: changing Start approach => End approach is forced to match.
         Similarly, if user picks Start 'exact' => End is forced 'exact', etc.
    """

    import os, json

    # 1) Load the biography & specific entry
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    # Helper to load JSON
    def load_json_as_dict(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    bio_data = load_json_as_dict(biography_path)
    entries_list = bio_data.get("entries", [])
    if entry_index >= len(entries_list):
        return "<h1>Error: Entry Index Out of Range</h1>", 404

    entry = entries_list[entry_index]
    time_period = entry.setdefault("time_period", {})
    start_block = time_period.setdefault("start", {})
    end_block   = time_period.setdefault("end",   {})

    # 2) We'll define a dictionary of possible approaches:
    #    "date" => no subfolder, plus any subfolders in /types/time/labels/<folder_name>
    times_path = f"./types/time/labels"
    approach_dict = {
        "date": {
            "raw": "date",
            "pretty": "Date",
            "has_subfolder": False,
            "values": []
        }
    }

    def prettify_label(s):
        return " ".join(part.capitalize() for part in s.split("_"))

    # If there's a 'person_decade' or other subfolder, include it
    if os.path.exists(times_path) and os.path.isdir(times_path):
        for file in os.listdir(times_path):
            if file.endswith(".json"):
                folder_name = os.path.splitext(file)[0]
                if folder_name == "date":
                    continue  # skip if there's date.json
                subfolder_dir = os.path.join(times_path, folder_name)
                if os.path.isdir(subfolder_dir):
                    # gather sub-values
                    sub_vals_list = []
                    for sf in os.listdir(subfolder_dir):
                        if sf.endswith(".json"):
                            raw_val = os.path.splitext(sf)[0]
                            sub_vals_list.append({
                                "raw": raw_val,
                                "pretty": prettify_label(raw_val)
                            })
                    approach_dict[folder_name] = {
                        "raw": folder_name,
                        "pretty": prettify_label(folder_name),
                        "has_subfolder": True,
                        "values": sub_vals_list
                    }

    # 3) Extract the user's existing approach & data
    start_approach = start_block.get("approach","date")  # e.g. 'date' or 'person_decade'
    start_mode     = start_block.get("mode","exact") if start_approach=="date" else ""
    start_value    = start_block.get("value","")

    end_approach = end_block.get("approach","date")
    end_mode     = end_block.get("mode","exact") if end_approach=="date" else ""
    end_value    = end_block.get("value","")

    # 4) Build a subfolder map for JS
    approach_obj = {}
    for a_key, meta in approach_dict.items():
        if meta["has_subfolder"]:
            approach_obj[a_key] = meta["values"]
        else:
            approach_obj[a_key] = []

    approach_obj_json = json.dumps(approach_obj)

    def build_approach_options(selected):
        # e.g. <option value="date" selected>Date</option>
        out = []
        for key, data in approach_dict.items():
            sel = "selected" if key == selected else ""
            out.append(f'<option value="{key}" {sel}>{data["pretty"]}</option>')
        return "".join(out)

    start_approach_options = build_approach_options(start_approach)
    end_approach_options   = build_approach_options(end_approach)

    # 5) Return the HTML with all logic
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Edit Entry - {bio_data.get("name", biography_name)}</title>
      <link rel="stylesheet" href="/static/styles.css">
      <style>
        .hidden {{ display: none; }}
      </style>
      <script>
        let approachData = {approach_obj_json};

        // build year list 1900..2100
        function buildYearOptions(selectEl, minYear=1900) {{
          selectEl.innerHTML = "";
          for (let y = minYear; y <= 2100; y++) {{
            let opt = document.createElement("option");
            opt.value = ""+y;
            opt.textContent = ""+y;
            selectEl.appendChild(opt);
          }}
        }}

        // attach a type-ahead so user can type e.g. 1 9 5 2 => jump to 1952
        function attachTypeAhead(selectEl) {{
          let typed = "";
          let lastTime = 0;

          selectEl.addEventListener("keydown", function(e) {{
            let now = Date.now();
            if (now - lastTime > 800) {{
              typed = "";
            }}
            lastTime = now;

            if (e.key === "Backspace") {{
              typed = typed.slice(0,-1);
              e.preventDefault();
            }} else if (/\\d/.test(e.key)) {{
              typed += e.key;
              e.preventDefault();
            }} else {{
              return;
            }}

            for (let i=0; i<selectEl.options.length; i++) {{
              if (selectEl.options[i].value.startsWith(typed)) {{
                selectEl.selectedIndex = i;
                break;
              }}
            }}
          }});
        }}

        function onApproachChange(prefix) {{
          // 1) first update the block for 'prefix'
          let approachSel = document.getElementById(prefix + '_approach').value;
          let dateSec = document.getElementById(prefix + '_date_section');
          let subfSec = document.getElementById(prefix + '_subfolder_section');

          if (approachData[approachSel] && approachData[approachSel].length > 0) {{
            // subfolder approach
            dateSec.classList.add("hidden");
            subfSec.classList.remove("hidden");

            let dd = document.getElementById(prefix + '_sub_val');
            dd.innerHTML = "";
            approachData[approachSel].forEach(obj => {{
              let opt = document.createElement("option");
              opt.value = obj.raw;
              opt.textContent = obj.pretty;
              dd.appendChild(opt);
            }});
            let customOpt = document.createElement("option");
            customOpt.value = "custom";
            customOpt.textContent = "Enter Custom Value";
            dd.appendChild(customOpt);

          }} else {{
            // date approach
            subfSec.classList.add("hidden");
            dateSec.classList.remove("hidden");
          }}

          // 2) If prefix='start', force end approach to match
          if (prefix === 'start') {{
            document.getElementById('end_approach').value = approachSel;
            onApproachChange('end');
          }}

          // enforce constraints after approach changes
          enforceEndConstraints();
        }}

        function onToggleDateMode(prefix) {{
          let exactRadio   = document.getElementById(prefix + '_date_mode_exact');
          let partialRadio = document.getElementById(prefix + '_date_mode_partial');
          let exactDiv     = document.getElementById(prefix + '_exactDiv');
          let partialDiv   = document.getElementById(prefix + '_partialDiv');

          if (exactRadio.checked) {{
            exactDiv.classList.remove("hidden");
            partialDiv.classList.add("hidden");
          }} else if (partialRadio.checked) {{
            exactDiv.classList.add("hidden");
            partialDiv.classList.remove("hidden");
            // build year list if empty
            let sel = document.getElementById(prefix + '_partial_year_select');
            if (sel.options.length < 1) {{
              buildYearOptions(sel, 1900);
              attachTypeAhead(sel);
            }}
          }}

          // If user toggles start partial/exact => do same for end
          if (prefix==='start') {{
            if (exactRadio.checked) {{
              document.getElementById('end_date_mode_exact').checked = true;
            }} else {{
              document.getElementById('end_date_mode_partial').checked = true;
            }}
            onToggleDateMode('end');
          }}

          enforceEndConstraints();
        }}

        // ensure end≥start if approach='date'
        function enforceEndConstraints() {{
          let sAp = document.getElementById('start_approach').value;
          let eAp = document.getElementById('end_approach').value;

          if (sAp !== 'date' || eAp !== 'date') {{
            // subfolder => no constraints
            return;
          }}

          let sExact = document.getElementById('start_date_mode_exact').checked;
          let eExact = document.getElementById('end_date_mode_exact').checked;

          if (sExact) {{
            let sVal = document.getElementById('start_full_date').value;
            if (!sVal) return; // can't do anything if no start date
            if (eExact) {{
              document.getElementById('end_full_date').min = sVal;
            }} else {{
              // end partial
              let year = parseInt(sVal.split('-')[0])||1900;
              let endSel = document.getElementById('end_partial_year_select');
              rebuildYearDropdown(endSel, year);
            }}
          }} else {{
            // start partial
            let sYear = parseInt(document.getElementById('start_partial_year_select').value)||1900;
            if (eExact) {{
              document.getElementById('end_full_date').min = sYear + '-01-01';
            }} else {{
              // partial => partial
              let eSel = document.getElementById('end_partial_year_select');
              rebuildYearDropdown(eSel, sYear);
            }}
          }}
        }}

        function rebuildYearDropdown(selEl, startYear) {{
          selEl.innerHTML = "";
          for (let y = startYear; y<=2100; y++) {{
            let opt = document.createElement('option');
            opt.value = ""+y;
            opt.textContent = ""+y;
            selEl.appendChild(opt);
          }}
        }}

        function checkCustom(prefix) {{
          let dd = document.getElementById(prefix + '_sub_val');
          let cust = document.getElementById(prefix + '_custom_val');
          if (dd.value==='custom') {{
            dd.style.display='none';
            cust.style.display='inline-block';
          }} else {{
            cust.style.display='none';
            dd.style.display='inline-block';
          }}
        }}

        window.onload = function() {{
          // 1) We run onApproachChange('start') => sets start approach, updates end approach => onApproachChange('end')
          onApproachChange('start');
          // 2) Then set the date mode toggles
          onToggleDateMode('start');
          onToggleDateMode('end');
          // 3) Possibly fill partial year or date from old data in a DOMContentLoaded snippet
          //    Then call enforceEndConstraints() again
          enforceEndConstraints();
        }};
      </script>
    </head>
    <body>
      <div class="container">
        <a href="/biography/{type_name}/{biography_name}" class="back-link">Back</a>
        <h1>Edit Entry for {bio_data.get("name", biography_name)}</h1>

        <!-- We'll assume your POST route is /biography_editentry_submit/... -->
        <form action="/biography_editentry_submit/{type_name}/{biography_name}/{entry_index}" method="post">

          <!-- START BLOCK -->
          <h2>Start Time</h2>
          <label>Approach:</label>
          <select id="start_approach" name="start_approach" onchange="onApproachChange('start')">
            {start_approach_options}
          </select>

          <div id="start_date_section" class="">
            <label>
              <input type="radio" id="start_date_mode_exact" name="start_date_mode" value="exact"
                     onclick="onToggleDateMode('start')"> Exact
            </label>
            <label>
              <input type="radio" id="start_date_mode_partial" name="start_date_mode" value="partial"
                     onclick="onToggleDateMode('start')"> Partial
            </label>
            <br><br>

            <!-- EXACT sub-block -->
            <div id="start_exactDiv">
              <label>Exact Start Date:</label>
              <input type="date" id="start_full_date" name="start_full_date">
            </div>

            <!-- PARTIAL sub-block -->
            <div id="start_partialDiv" class="hidden">
              <label>Partial Start Year:</label>
              <select id="start_partial_year_select" name="start_partial_year_select"></select>
            </div>
          </div>

          <div id="start_subfolder_section" class="hidden">
            <label>Pick Value:</label>
            <select id="start_sub_val" name="start_sub_val" onchange="checkCustom('start')"></select>
            <input type="text" id="start_custom_val" name="start_custom_val" placeholder="Custom" class="hidden">
          </div>

          <hr>

          <!-- END BLOCK -->
          <h2>End Time</h2>
          <label>Approach:</label>
          <select id="end_approach" name="end_approach" onchange="onApproachChange('end')">
            {end_approach_options}
          </select>

          <div id="end_date_section" class="hidden">
            <label>
              <input type="radio" id="end_date_mode_exact" name="end_date_mode" value="exact"
                     onclick="onToggleDateMode('end')"> Exact
            </label>
            <label>
              <input type="radio" id="end_date_mode_partial" name="end_date_mode" value="partial"
                     onclick="onToggleDateMode('end')"> Partial
            </label>
            <br><br>

            <div id="end_exactDiv">
              <label>Exact End Date:</label>
              <input type="date" id="end_full_date" name="end_full_date">
            </div>

            <div id="end_partialDiv" class="hidden">
              <label>Partial End Year:</label>
              <select id="end_partial_year_select" name="end_partial_year_select"></select>
            </div>
          </div>

          <div id="end_subfolder_section" class="hidden">
            <label>Pick Value:</label>
            <select id="end_sub_val" name="end_sub_val" onchange="checkCustom('end')"></select>
            <input type="text" id="end_custom_val" name="end_custom_val" placeholder="Custom" class="hidden">
          </div>

          <hr>
          <button type="submit">Save Changes</button>
        </form>

        <!-- If you need to fill old data e.g. partial year or subfolder:
             We'll do that after the DOM loads, then enforce constraints again. -->
        <script>
          document.addEventListener('DOMContentLoaded', function() {{
            // e.g. if your stored 'start_mode' == 'partial', do:
            //   document.getElementById('start_date_mode_partial').checked = true;
            //   onToggleDateMode('start');
            //   document.getElementById('start_partial_year_select').value = '{start_value}';
            // same for end
            // Then run enforceEndConstraints() again
          }});
        </script>
      </div>
    </body>
    </html>
    """

    return html




@app.route('/biography_editentry_submit/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_editentry_submit(type_name, biography_name, entry_index):
    """
    POST route that saves user changes from the updated editentry page:
      - If start_approach == 'date', parse start_date_mode = 'exact' or 'partial', plus the relevant field.
      - If subfolder approach, parse start_sub_val or custom typed.
      - Same logic for end_approach => end_date_mode or subfolder.
    Then we store them in time_period["start"] and time_period["end"].
    """

    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(json_file_path):
        return "<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(json_file_path)
    entries = bio_data.get("entries", [])
    if entry_index >= len(entries):
        return "<h1>Error: Entry Not Found</h1>", 404

    entry = entries[entry_index]
    if "time_period" not in entry:
        entry["time_period"] = {}
    time_period = entry["time_period"]
    if "start" not in time_period:
        time_period["start"] = {}
    if "end" not in time_period:
        time_period["end"] = {}

    # ------------------ PARSE START BLOCK ------------------
    start_approach = request.form.get("start_approach","date").strip()  # e.g. 'date' or 'person_decade'
    if start_approach == "date":
        start_date_mode = request.form.get("start_date_mode","exact").strip()  # 'exact' or 'partial'
        if start_date_mode == "exact":
            # read <input type="date" id="start_full_date">
            s_val = request.form.get("start_full_date","").strip()
            if not s_val:
                s_val = "No Date"
            time_period["start"] = {
                "approach": "date",
                "mode": "exact",
                "value": s_val,
                "is_partial": False
            }
        else:
            # partial => read <select name="start_partial_year_select">
            s_val = request.form.get("start_partial_year_select","").strip()
            if not s_val:
                s_val = "Unknown Year"
            time_period["start"] = {
                "approach": "date",
                "mode": "partial",
                "value": s_val,
                "is_partial": True
            }
    else:
        # subfolder approach
        # e.g. start_sub_val = "thirties" or "custom"
        s_sub_val = request.form.get("start_sub_val","").strip()
        if s_sub_val == "custom":
            s_sub_val = request.form.get("start_custom_val","").strip() or "Custom"
        time_period["start"] = {
            "approach": start_approach,
            "value": s_sub_val
        }

    # ------------------ PARSE END BLOCK ------------------
    end_approach = request.form.get("end_approach","date").strip()
    if end_approach == "date":
        end_date_mode = request.form.get("end_date_mode","exact").strip()
        if end_date_mode == "exact":
            e_val = request.form.get("end_full_date","").strip()
            if not e_val:
                e_val = "No Date"
            time_period["end"] = {
                "approach": "date",
                "mode": "exact",
                "value": e_val,
                "is_partial": False
            }
        else:
            # partial
            e_val = request.form.get("end_partial_year_select","").strip()
            if not e_val:
                e_val = "Unknown Year"
            time_period["end"] = {
                "approach": "date",
                "mode": "partial",
                "value": e_val,
                "is_partial": True
            }
    else:
        # subfolder approach
        e_sub_val = request.form.get("end_sub_val","").strip()
        if e_sub_val == "custom":
            e_sub_val = request.form.get("end_custom_val","").strip() or "Custom"
        time_period["end"] = {
            "approach": end_approach,
            "value": e_sub_val
        }

    # ------------------ Save JSON & Redirect ------------------
    entry["time_period"] = time_period
    save_dict_as_json(json_file_path, bio_data)

    return redirect(f"/biography/{type_name}/{biography_name}")


@app.route('/type/<string:type_name>')
def type_page(type_name):
    """
    Displays the type page for biographies:
    - Search bar for partial matches by name or label values.
    - Live checkboxes that filter by label name.
    - View-only mode: no add/edit/delete options.
    - Link to label viewer.
    """

    type_metadata_path = f"./types/{type_name}.json"
    if not os.path.exists(type_metadata_path):
        return f"""
        <h1>Error: Type metadata not found</h1>
        <p>The file <code>{type_metadata_path}</code> does not exist.</p>
        """, 404
    type_meta = load_json_as_dict(type_metadata_path)

    biographies_path = f"./types/{type_name}/biographies"
    biography_list = []
    all_label_names = set()

    if os.path.exists(biographies_path):
        for file in os.listdir(biographies_path):
            if file.endswith(".json"):
                file_path = os.path.join(biographies_path, file)
                bio_data = load_json_as_dict(file_path)

                name = bio_data.get("name", "Unknown")
                label_names_in_this_bio = set()
                label_values_in_this_bio = []

                for entry in bio_data.get("entries", []):
                    for lbl in entry.get("labels", []):
                        if lbl["label"].lower() in ["time", "start", "end"]:
                            continue
                        label_name = lbl["label"].strip().lower()
                        label_value = lbl.get("value", "").strip().lower()
                        label_names_in_this_bio.add(label_name)
                        if label_value:
                            label_values_in_this_bio.append(label_value)

                all_label_names.update(label_names_in_this_bio)
                bio_label_names_str = ",".join(sorted(label_names_in_this_bio))
                bio_label_values_str = ",".join(label_values_in_this_bio)

                biography_list.append({
                    "file_basename": file[:-5],
                    "name": name.capitalize(),
                    "label_names_str": bio_label_names_str,
                    "label_values_str": bio_label_values_str
                })

    def prettify_label_name(raw_name):
        return " ".join(word.capitalize() for word in raw_name.split("_"))

    sorted_label_names = sorted(all_label_names)
    label_options_html = ""
    for lbl_name in sorted_label_names:
        display_name = prettify_label_name(lbl_name)
        label_options_html += f"""
        <label class='filter-label'>
            <input type='checkbox' value='{lbl_name}' class='filter-checkbox'> {display_name}
        </label>
        """

    biography_items_html = ""
    for bio in biography_list:
        biography_items_html += f"""
        <div class='biography-item'
             data-name='{bio["name"].lower()}'
             data-labelnames='{bio["label_names_str"]}'
             data-labelvalues='{bio["label_values_str"]}'>
            <a href="/biography/{type_name}/{bio['file_basename']}" class='biography-button'>
                <strong>{bio['name']}</strong>
            </a>
        </div>
        """

    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset='UTF-8' />
        <title>{type_name.capitalize()}</title>
        <link rel='stylesheet' href='/static/styles.css'>
    </head>
    <body>
        <div class='container'>
            <a href='/' class='back-link'>← Back</a>
            <h1>{type_name.capitalize()}</h1>
            <p class='description'>{type_meta.get("description", "No description available.")}</p>

            <div class='search-container'>
                <input type='text' id='searchBar' class='search-input' placeholder='Search by name or label value...'>
                <button id='resetSearch' class='reset-button'>Reset Search</button>
            </div>

            <div class='filter-container'>
                <label>Filter by Label Name:</label>
                <div class='filter-labels'>
                    {label_options_html}
                </div>
            </div>

            <h2>Biographies</h2>
            <div class='biography-container' id='biographyList'>
                {biography_items_html if biography_items_html else "<p class='no-data'>No biographies found.</p>"}
            </div>

            <div class="label-explorer-link">
                <a href="/view_labels/{type_name}" class="view-labels-button">View All Labels</a>
            </div>
        </div>

        <script>
            const searchBar = document.getElementById('searchBar');
            const resetButton = document.getElementById('resetSearch');
            const checkboxes = document.querySelectorAll('.filter-checkbox');
            const biographyItems = document.querySelectorAll('.biography-item');

            function applyFilters() {{
                const query = searchBar.value.toLowerCase().trim();
                const selectedLabelNames = Array.from(checkboxes)
                    .filter(ch => ch.checked)
                    .map(ch => ch.value.toLowerCase());

                biographyItems.forEach(item => {{
                    const bioName = item.dataset.name;
                    const labelNames = item.dataset.labelnames;
                    const labelValues = item.dataset.labelvalues;

                    let searchMatch = true;
                    if (query) {{
                        const nameMatch = bioName.includes(query);
                        const valueMatch = labelValues.includes(query);
                        searchMatch = (nameMatch || valueMatch);
                    }}

                    let labelNameMatch = true;
                    if (selectedLabelNames.length > 0) {{
                        const labelNamesArr = labelNames.split(",");
                        labelNameMatch = selectedLabelNames.every(lbl => labelNamesArr.includes(lbl));
                    }}

                    const shouldShow = (searchMatch && labelNameMatch);
                    item.style.display = shouldShow ? 'block' : 'none';
                }});
            }}

            searchBar.addEventListener('input', applyFilters);
            checkboxes.forEach(ch => ch.addEventListener('change', applyFilters));

            resetButton.addEventListener('click', () => {{
                searchBar.value = "";
                checkboxes.forEach(ch => (ch.checked = false));
                biographyItems.forEach(item => item.style.display = 'block');
            }});
        </script>
    </body>
    </html>
    """

    return html_template


@app.route('/view_labels/<string:type_name>')
def view_labels(type_name):
    import os
    import json

    labels_dir = f'./types/{type_name}/labels'
    if not os.path.exists(labels_dir):
        return f"<h1>Error: Label folder not found for {type_name}</h1>", 404

    label_types = []
    for entry in sorted(os.listdir(labels_dir)):
        full_path = os.path.join(labels_dir, entry)
        if os.path.isdir(full_path):
            images_and_metadata = []
            for f in os.listdir(full_path):
                if f.endswith('.json'):
                    json_path = os.path.join(full_path, f)
                    
                    # Prefer .jpg, fallback to .png
                    image_filename = f.replace('.json', '.jpg')
                    image_full_path = os.path.join(full_path, image_filename)
                    if not os.path.exists(image_full_path):
                        image_filename = f.replace('.json', '.png')
                        image_full_path = os.path.join(full_path, image_filename)
                    
                    # Construct image URL if it exists
                    image_url = f"/types/{type_name}/labels/{entry}/{image_filename}" if os.path.exists(image_full_path) else None
                    
                    with open(json_path, 'r') as jf:
                        try:
                            data = json.load(jf)
                            description = data.get("description", "")
                            properties = data.get("properties", {})

                            properties_list = []
                            for key, val in properties.items():
                                if isinstance(val, dict):
                                    properties_list.append((prettify(key), val.get("value", "")))

                            # Add JSON filename (without extension) to search text and display
                            file_display_name = prettify(f.replace('.json', ''))

                            search_text = " ".join([
                                file_display_name
                            ] + [
                                str(val.get("value", "")) for val in properties.values()
                                if isinstance(val, dict)
                            ]).lower()

                            images_and_metadata.append({
                                "file": file_display_name,
                                "img": image_url,
                                "description": description,
                                "properties_list": properties_list,
                                "search_text": search_text
                            })
                        except Exception:
                            continue

            label_types.append({
                "name": entry,
                "display_name": prettify(entry),
                "description": get_label_description(labels_dir, entry),
                "values": images_and_metadata
            })

    html_template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>View Labels</title>
        <link rel="stylesheet" href="/static/styles.css">
        <style>
            .label-img { max-width: 120px; display: block; margin: 4px 0; }
            .label-group { margin-bottom: 30px; }
            .label-values { display: flex; flex-wrap: wrap; gap: 20px; margin-top: 10px; }
            .label-box { border: 1px solid #ccc; padding: 8px; width: 150px; }
            .label-description { font-style: italic; font-size: 0.9em; margin-bottom: 5px; }
            .search-input { padding: 8px; width: 300px; margin-bottom: 20px; font-size: 1em; }
            .back-link { margin-bottom: 20px; display: inline-block; text-decoration: none; font-size: 1.1em; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/type/{{ type_name }}" class="back-link">← Back</a>
            <h1>View Labels for {{ type_name.capitalize() }}</h1>
            <input type="text" id="labelSearch" class="search-input" placeholder="Search label values...">

            {% for lbl in label_types %}
            <div class="label-group">
                <h2>{{ lbl.display_name }}</h2>
                {% if lbl.description %}
                <p class="label-description">{{ lbl.description }}</p>
                {% endif %}
                <div class="label-values">
                    {% for item in lbl["values"] %}
                    <div class="label-box" data-search="{{ item.search_text }}">
                        {% if item.img %}
                        <img src="{{ item.img }}" alt="Label Image" class="label-img">
                        {% endif %}
                        <strong>Name</strong>: {{ item.file }}<br>
                        {% for pair in item["properties_list"] %}
                            <strong>{{ pair[0] }}</strong>: {{ pair[1] }}<br>
                        {% endfor %}
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endfor %}
        </div>

        <script>
            const input = document.getElementById('labelSearch');
            input.addEventListener('input', () => {
                const val = input.value.toLowerCase();
                document.querySelectorAll('.label-box').forEach(box => {
                    const text = box.dataset.search;
                    box.style.display = text.includes(val) ? 'block' : 'none';
                });
            });
        </script>
    </body>
    </html>
    '''

    return render_template_string(html_template, type_name=type_name, label_types=label_types)


@app.route('/search/<string:type_name>')
def search_biographies(type_name):
    query = request.args.get("q", "").strip().lower()
    if not query:
        return jsonify([])

    biographies_path = f"./types/{type_name}/biographies"
    if not os.path.exists(biographies_path):
        return jsonify([])

    results = []
    for file in os.listdir(biographies_path):
        if file.endswith(".json"):
            bio_data = load_json_as_dict(os.path.join(biographies_path, file))
            biography_name = file[:-5]  # Remove ".json"
            display_name = bio_data.get("name", biography_name)

            # Search through labels
            for entry in bio_data.get("entries", []):
                for label in entry.get("labels", []):
                    label_value = str(label.get("value", "")).lower()
                    label_name = str(label.get("label", "")).lower()

                    if query in label_value or query in label_name:
                        results.append({
                            "name": biography_name,
                            "display_name": display_name,
                            "matched_label": f"{label_name}: {label_value}"
                        })
                        break  # Stop searching further in this biography

    return jsonify(results)


from flask import send_from_directory

@app.route('/serve_label_image/<string:type_name>/<string:label_name>/<string:image_name>')
def serve_label_image(type_name, label_name, image_name):
    """ Serve images from the `types` directory dynamically. """
    image_path = f"./types/{type_name}/labels/{label_name}/"  # Adjust if the structure is different
    return send_from_directory(image_path, image_name)




@app.route('/biography_addlabel/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['GET'])
def biography_addlabel_page(type_name, biography_name, entry_index):
    """
    Displays the Add Label form with:
      - A prettified label name dropdown (e.g. "celebea_face_hq" => "Celebea Face Hq").
      - Subfolder-based values, plus custom typed value.
      - Image preview if <folder>:<value>.jpg exists.
    """

    # 1. Load the biography & entry
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    bio_data = load_json_as_dict(json_file_path)

    if entry_index >= len(bio_data.get("entries", [])):
        return f"<h1>Error: Entry Not Found</h1>", 404

    entry = bio_data["entries"][entry_index]
    display_name = bio_data.get("name", biography_name)

    # 2. Gather all label folders in ./types/<type_name>/labels/
    labels_path = f"./types/{type_name}/labels"
    label_folders = [f for f in os.listdir(labels_path) if f.endswith(".json")]
    # We'll store "folder_name => { 'values': [...], 'images': {...} }"
    label_info_dict = {}

    def prettify_label_name(raw: str) -> str:
        return " ".join(word.capitalize() for word in raw.split("_"))

    for label_file in label_folders:
        lbl_name = os.path.splitext(label_file)[0]  # e.g. "celebea_face_hq"
        label_folder_path = os.path.join(labels_path, lbl_name)
        label_json_path   = os.path.join(labels_path, label_file)

        # Load label data
        label_json = load_json_as_dict(label_json_path)
        values_list = label_json.get("values", [])
        
        images_map = {}  # e.g. {"1": "/serve_label_image/.../1.jpg"}

        # If subfolder has .json or images
        if os.path.exists(label_folder_path) and os.path.isdir(label_folder_path):
            subfolder_files = [sf for sf in os.listdir(label_folder_path) if sf.endswith(".json")]
            sub_values = [os.path.splitext(sf)[0] for sf in subfolder_files]
            # unify the two sets
            combined_values = list(set(values_list + sub_values))
            # find images
            image_files = [img for img in os.listdir(label_folder_path) if img.endswith((".jpg",".png"))]
            for val in combined_values:
                matched_img = next((img for img in image_files if os.path.splitext(img)[0] == val), None)
                if matched_img:
                    images_map[val] = f"/serve_label_image/{type_name}/{lbl_name}/{matched_img}"
                else:
                    images_map[val] = None
        else:
            combined_values = values_list

        label_info_dict[lbl_name] = {
            "pretty_name": prettify_label_name(lbl_name),
            "values": combined_values,
            "images": images_map
        }

    # 3. Convert to JSON for the front-end JS
    label_info_json = json.dumps(label_info_dict)

    # 4. Build HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Add Label to {display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">

        <script>
            let labelInfo = {label_info_json};

            function prettifyLabelName(raw) {{
                // We can do the same in JS if needed, or rely on your Python logic
                let parts = raw.split("_");
                return parts.map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
            }}

            function updateLabelDetails() {{
                let lblSelect = document.getElementById("label_type");
                let selected = lblSelect.value; // e.g. "celebea_face_hq"

                let descContainer = document.getElementById("label_description");
                let valSelect     = document.getElementById("label_value");
                let customInput   = document.getElementById("custom_label_value");
                let imgContainer  = document.getElementById("label_image");
                let placeholder   = document.getElementById("image_placeholder");

                // Reset
                valSelect.innerHTML = "";
                customInput.style.display = "none";
                customInput.value = "";
                customInput.required = false;

                // Fill value dropdown
                if (labelInfo[selected]) {{
                    let vals = labelInfo[selected].values;
                    vals.forEach(v => {{
                        let opt = document.createElement("option");
                        opt.value = v;
                        opt.textContent = v;
                        valSelect.appendChild(opt);
                    }});
                    // add 'custom' option
                    let customOpt = document.createElement("option");
                    customOpt.value = "custom";
                    customOpt.textContent = "Enter Custom Value";
                    valSelect.appendChild(customOpt);
                }}

                // Clear images initially
                imgContainer.style.display = "none";
                placeholder.style.display  = "none";

                // We'll call checkCustomValue afterwards 
                // so the user can see if it's custom or not
            }}

            function checkCustomValue() {{
                let valSelect = document.getElementById("label_value");
                let customInput = document.getElementById("custom_label_value");
                let selectedLbl = document.getElementById("label_type").value;

                let imgContainer = document.getElementById("label_image");
                let placeholder  = document.getElementById("image_placeholder");

                if (valSelect.value === "custom") {{
                    valSelect.style.display = "none";
                    customInput.style.display = "block";
                    customInput.required = true;
                    // no specific image for custom unless we guess
                    imgContainer.style.display = "none";
                    placeholder.style.display  = "block";
                    placeholder.innerHTML      = "No image for custom value";
                }} else {{
                    customInput.style.display = "none";
                    customInput.required = false;
                    valSelect.style.display = "inline-block";

                    // Possibly show an image if labelInfo has images
                    let chosenVal = valSelect.value;
                    let imagesMap = labelInfo[selectedLbl].images || {{}};
                    if (imagesMap[chosenVal]) {{
                        imgContainer.src = imagesMap[chosenVal];
                        imgContainer.style.display = "block";
                        placeholder.style.display = "none";
                    }} else {{
                        placeholder.innerHTML = "Expected Image: " + chosenVal + ".jpg or .png";
                        placeholder.style.display = "block";
                        imgContainer.style.display = "none";
                    }}
                }}
            }}

            window.onload = function() {{
                updateLabelDetails();
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Add Label to {display_name.capitalize()}</h1>

            <div class="label-container">
                <p><strong>From:</strong> {printTime(entry["time_period"]["start"])}</p>
                <p><strong>To:</strong> {printTime(entry["time_period"]["end"])}</p>

                <form action='/biography_addlabel_submit/{type_name}/{biography_name}/{entry_index}' method='post'>
                    <label for='label_type'>Choose a label folder:</label>
                    <select name='label_type' id='label_type' onchange="updateLabelDetails()" required>
                        <option value="">Select a folder</option>
    """

    # 5. Build the <option> list for label_type, using prettified name
    for folder_name, info in label_info_dict.items():
        pretty_name = info["pretty_name"]
        html_template += f"<option value='{folder_name}'>{pretty_name}</option>"

    html_template += """
                    </select>

                    <p id="label_description" style="margin-top:5px; font-style:italic;">
                        Select a label to view details (if any).
                    </p>

                    <img id="label_image" style="display:none; max-width:150px; margin-top:5px;">
                    <p id="image_placeholder" style="color:#999; font-style:italic; display:none;"></p>

                    <br>

                    <label for='label_value'>Select a value:</label>
                    <select id="label_value" name="label_value" class="dropdown" required onchange="checkCustomValue()">
                        <option value="custom">Enter Custom Value</option>
                    </select>

                    <input type="text" id="custom_label_value" name="custom_label_value"
                           placeholder="Enter custom value" style="display:none;"><br><br>

                    <!-- Confidence slider if needed -->
                    <label for="confidence_slider">Confidence (0.0 - 1.0):</label>
                    <input type="range" id="confidence_slider" name="confidence_slider"
                           min="0" max="1" step="0.01" value="1.0"
                           oninput="sliderValueDisplay.value = confidence_slider.value">
                    <output id="sliderValueDisplay">1.0</output><br><br>

                    <button type='submit' class="add-label-button">Add Label</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """

    return html_template


@app.route('/fetch_subfolder_contents/<string:type_name>/<path:label_type>/<string:subfolder>')
def fetch_subfolder_contents(type_name, label_type, subfolder):
    """
    Fetches the contents (JSON description and image) of a subfolder.
    """
    subfolder_path = f"./types/{type_name}/labels/{label_type}/{subfolder}"
    description = None
    image = None

    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        for file in os.listdir(subfolder_path):
            if file.endswith(".json"):
                json_data = load_json_as_dict(os.path.join(subfolder_path, file))
                description = json_data.get("description", "No description available.")
            elif file.endswith((".jpg", ".png", ".jpeg")):
                image = f"{type_name}/labels/{label_type}/{subfolder}/{file}"  # Updated path

    return jsonify({"description": description, "image": image})


@app.route('/get_subfolder_contents/<string:type_name>/<path:label_type>/<string:subfolder>')
def get_subfolder_contents(type_name, label_type, subfolder):
    """
    Fetches the contents (JSON description and image) of a subfolder.
    """
    subfolder_path = f"./types/{type_name}/labels/{label_type}/{subfolder}"
    description = None
    image = None

    if os.path.exists(subfolder_path) and os.path.isdir(subfolder_path):
        for file in os.listdir(subfolder_path):
            if file.endswith(".json"):
                json_data = load_json_as_dict(os.path.join(subfolder_path, file))
                description = json_data.get("description", "No description available.")
            elif file.endswith((".jpg", ".png", ".jpeg")):
                image = f"{type_name}/labels/{label_type}/{subfolder}/{file}"  # Corrected image path

    return jsonify({"description": description, "image": image})


@app.route('/get_label_options/<string:type_name>/<path:label_type>')
def get_label_options(type_name, label_type):
    """
    Fetches options from a subfolder within the labels directory based on selection.
    """
    labels_path = f"./types/{type_name}/labels/{label_type}"
    options = []

    if os.path.exists(labels_path) and os.path.isdir(labels_path):
        for file in os.listdir(labels_path):
            if file.endswith(".json"):
                name = os.path.splitext(file)[0]
                options.append(name.capitalize())

    return jsonify({"options": options})



@app.route('/biography_addlabel_submit/<string:type_name>/<string:biography_name>/<int:entry_index>', methods=['POST'])
def biography_addlabel_submit(type_name, biography_name, entry_index):
    """
    Handles the submission of a new label, including custom string values and confidence.
    Ensures proper validation and prevents duplicate entries.
    """
    json_file_path = f"./types/{type_name}/biographies/{biography_name}.json"
    bio_data = load_json_as_dict(json_file_path)

    # Ensure entry exists
    if entry_index >= len(bio_data["entries"]):
        flash("Error: Entry not found.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    entry = bio_data["entries"][entry_index]

    # Ensure labels list exists
    if "labels" not in entry:
        entry["labels"] = []

    # Get label details from form
    label_name = request.form.get("label_type", "").strip()
    label_value = request.form.get("label_value", "").strip()
    custom_value = request.form.get("custom_label_value", "").strip()

    # Fetch the confidence from the slider (default to 1.0 if missing/invalid)
    confidence_str = request.form.get("confidence_slider", "1.0").strip()
    try:
        confidence_val = float(confidence_str)
    except ValueError:
        confidence_val = 1.0

    # Prevent empty label names
    if not label_name:
        flash("Error: Label name cannot be empty.", "error")
        return redirect(f"/biography_addlabel/{type_name}/{biography_name}/{entry_index}")

    # Determine if label allows free-text input (e.g., first_name.json)
    label_json_path = f"./types/{type_name}/labels/{label_name}.json"
    label_type = ""

    if os.path.exists(label_json_path):
        label_data = load_json_as_dict(label_json_path)
        label_type = label_data.get("type", "").lower()  # Ensure lowercase comparison

    # If label type is "string" or user selected "custom", enforce using custom input
    if label_type == "string" or label_value == "custom":
        if not custom_value:
            flash("Error: Custom label value cannot be empty.", "error")
            return redirect(f"/biography_addlabel/{type_name}/{biography_name}/{entry_index}")
        label_value = custom_value  # Save the manually entered value

    # Build the new label object (including confidence)
    new_label = {
        "label": label_name,
        "value": label_value,
        "confidence": confidence_val
    }

    # Prevent duplicate label entries (optional uniqueness check)
    if new_label not in entry["labels"]:
        entry["labels"].append(new_label)
        save_dict_as_json(json_file_path, bio_data)
        flash(f"Label '{label_name}' with value '{label_value}' added successfully!", "success")
    else:
        flash(f"The label '{label_name}' with value '{label_value}' already exists.", "warning")

    return redirect(f"/biography/{type_name}/{biography_name}")


@app.route('/archived_biographies/<string:type_name>')
def archived_biographies(type_name):
    archive_path = f"./types/{type_name}/archived_biographies"
    
    # Ensure the archive folder exists, but only if necessary
    if not os.path.exists(archive_path) or not any(file.endswith(".json") for file in os.listdir(archive_path)):
        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Archived Biographies - {type_name.capitalize()}</title>
            <link rel="stylesheet" href="/static/styles.css">
        </head>
        <body>
            <div class="container">
                <a href="/type/{type_name}" class="button">Back</a>
                <h1>Archived Biographies</h1>
                <p>No archived biographies found.</p>
            </div>
        </body>
        </html>
        """

    archived_list = ""
    for file in os.listdir(archive_path):
        if file.endswith(".json"):
            file_path = os.path.join(archive_path, file)
            bio_data = load_json_as_dict(file_path)

            # Extract original name and archived timestamp
            name = bio_data.get("name", file[:-5]).capitalize()  # Default to filename if name missing
            archived_date = bio_data.get("archived_on", "Unknown Time")

            archived_list += f"""
                <div class="archived-item">
                    <p><strong>{name}</strong></p>
                    <p class="timestamp">Archived: {archived_date}</p>
                    <button class="restore-button" onclick="restoreBiography('{type_name}', '{file[:-5]}')">Restore</button>
                </div>
            """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Archived Biographies - {type_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function restoreBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to restore this biography?")) {{
                    fetch(`/biography_restore/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography restored successfully.");
                                location.reload();
                            }} else {{
                                alert("Failed to restore biography.");
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/type/{type_name}" class="button">Back</a>
            <h1>Archived Biographies</h1>
            <div class="archived-container">
                {archived_list if archived_list else "<p>No archived biographies found.</p>"}
            </div>
        </div>
    </body>
    </html>
    """


@app.route('/biography_restore/<string:type_name>/<string:biography_name>', methods=['POST'])
def biography_restore(type_name, biography_name):
    archive_path = f"./types/{type_name}/archived_biographies"
    biographies_path = f"./types/{type_name}/biographies"

    # Ensure active biography directory exists
    os.makedirs(biographies_path, exist_ok=True)

    # Paths to move
    archived_json = os.path.join(archive_path, f"{biography_name}.json")
    biography_json = os.path.join(biographies_path, f"{biography_name}.json")
    archived_folder = os.path.join(archive_path, biography_name)
    biography_folder = os.path.join(biographies_path, biography_name)

    # Check if archive exists before proceeding
    if not os.path.exists(archived_json):
        return jsonify({"error": "Archived biography not found"}), 404

    try:
        # Restore JSON file (remove "archived_on" key)
        restored_data = load_json_as_dict(archived_json)
        restored_data.pop("archived_on", None)  # Remove archive timestamp

        # Save updated JSON in biographies folder
        save_dict_as_json(biography_json, restored_data)

        # Remove from archive
        os.remove(archived_json)

        # Restore subfolder if it exists
        if os.path.exists(archived_folder):
            shutil.move(archived_folder, biography_folder)

        return jsonify({"message": "Biography restored successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to restore biography: {str(e)}"}), 500

@app.route('/archived_biography/<string:type_name>/<string:biography_name>')
def archived_biography_page(type_name, biography_name):
    archive_path = f"./types/{type_name}/archived_biographies/{biography_name}.json"

    if not os.path.exists(archive_path):
        return f"""
        <h1>Error: Archived Biography Not Found</h1>
        <p>The file <code>{archive_path}</code> does not exist.</p>
        <a href='/archived_biographies/{type_name}' class='back-link'>Back</a>
        """, 404

    # Load biography data
    asDict = load_json_as_dict(archive_path)

    # Extract correct name and timestamp
    display_name = asDict.get("name", biography_name)  # Show actual name if present
    readable_time = asDict.get("archived_on", "Unknown Time")  # Show when archived
    description = asDict.get("description", "No description available.")

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{display_name.capitalize()}</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            function restoreBiography(typeName, biographyName) {{
                if (confirm("Are you sure you want to restore this biography?")) {{
                    fetch(`/biography_restore/${{typeName}}/${{biographyName}}`, {{ method: 'POST' }})
                        .then(response => {{
                            if (response.ok) {{
                                alert("Biography restored successfully.");
                                window.location.href = "/type/" + typeName;
                            }}
                        }});
                }}
            }}
        </script>
    </head>
    <body>
        <div class="container">
            <a href="/archived_biographies/{type_name}" class="button">Back</a>
            <h1>{display_name.capitalize()}</h1>
            <p class="timestamp">Archived: {readable_time}</p>
            <p class="description">{description}</p>

            <!-- Restore Biography Button -->
            <button class="restore-button" onclick="restoreBiography('{type_name}', '{biography_name}')">Restore Biography</button>
        </div>
    </body>
    </html>
    """


@app.route('/biography_edit/<string:type_name>/<string:biography_name>', methods=['GET', 'POST'])
def biography_edit(type_name, biography_name):
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    biography_folder_path = f"./types/{type_name}/biographies/{biography_name}"

    if not os.path.exists(biography_path):
        return f"""
        <h1>Error: Biography Not Found</h1>
        <p>The file <code>{biography_path}</code> does not exist.</p>
        <a href='/type/{type_name}' class='back-link'>Back</a>
        """, 404

    # Load biography data
    bio_data = load_json_as_dict(biography_path)

    # Ensure timestamp exists; if missing, create one
    if "timestamp" not in bio_data:
        new_timestamp = str(int(time.time()))  # Generate a new timestamp
        bio_data["timestamp"] = new_timestamp
        bio_data["readable_time"] = datetime.fromtimestamp(int(new_timestamp)).strftime('%Y-%m-%d %H:%M:%S')

        # Save the updated JSON with the timestamp
        save_dict_as_json(biography_path, bio_data)

    if request.method == 'POST':
        new_name = request.form['biography_name'].strip().replace(" ", "_")
        new_description = request.form['description']

        # Use the existing timestamp
        timestamp = bio_data["timestamp"]
        new_biography_name = f"{new_name}_{timestamp}"  # Keep same timestamp
        new_biography_path = f"./types/{type_name}/biographies/{new_biography_name}.json"
        new_folder_path = f"./types/{type_name}/biographies/{new_biography_name}"

        # Update the JSON data
        bio_data["name"] = new_name
        bio_data["description"] = new_description

        # Rename JSON file and folder if the name has changed
        if new_biography_name != biography_name:
            os.rename(biography_path, new_biography_path)  # Rename JSON file
            if os.path.exists(biography_folder_path):
                os.rename(biography_folder_path, new_folder_path)  # Rename folder

        # Save updated JSON
        save_dict_as_json(new_biography_path, bio_data)

        flash(f"Biography '{new_name}' updated successfully!", "success")
        return redirect(f"/biography/{type_name}/{new_biography_name}")  # Redirect to new page

    # Get current values
    display_name = bio_data.get("name", "Unknown Name")
    description = bio_data.get("description", "No description available.")

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Edit Biography</title>
        <link rel="stylesheet" href="/static/styles.css">
    </head>
    <body>
        <div class="edit-biography-container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Edit Biography</h1>

            <form method="post">
                <label for="biography_name">Biography Name:</label>
                <input type="text" name="biography_name" value="{display_name}" required>

                <label for="description">Description:</label>
                <textarea name="description" required>{description}</textarea>

                <button type="submit">Save Changes</button>
            </form>
        </div>
    </body>
    </html>
    """


@app.route('/biography_editlabel/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['GET','POST'])
def biography_editlabel(type_name, biography_name, entry_index, label_index):
    """
    Displays the Edit Label page, letting us pick from subfolder-based label folders,
    show images, and preserve confidence & custom typed values.
    """

    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return f"<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(biography_path)
    entries = bio_data.get("entries", [])
    if entry_index >= len(entries):
        return f"<h1>Error: Entry Not Found</h1>", 404

    labels_list = entries[entry_index].get("labels", [])
    if label_index >= len(labels_list):
        return f"<h1>Error: Label Not Found</h1>", 404

    label_data = labels_list[label_index]
    label_name   = label_data.get("label","")
    label_value  = label_data.get("value","")
    confidence   = label_data.get("confidence", 1.0)

    display_name = bio_data.get("name", biography_name)

    # ----------------- POST: Save Changes -----------------
    if request.method == 'POST':
        updated_label_name = request.form.get("label_name", "").strip()
        updated_label_value = request.form.get("label_value", "").strip()
        if updated_label_value == "custom":
            updated_label_value = request.form.get("custom_label_value","").strip()
        
        conf_str = request.form.get("confidence_slider","1.0")
        try:
            updated_conf = float(conf_str)
        except ValueError:
            updated_conf = 1.0

        # Update the JSON
        labels_list[label_index] = {
            "label": updated_label_name,
            "value": updated_label_value,
            "confidence": updated_conf
        }
        save_dict_as_json(biography_path, bio_data)
        flash("Label updated successfully!", "success")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # ----------------- GET: Show Form -----------------
    labels_path = f"./types/{type_name}/labels"
    label_folders = [f for f in os.listdir(labels_path) if f.endswith(".json")]

    def prettify_label_name(raw: str) -> str:
        return " ".join(w.capitalize() for w in raw.split("_"))

    # Build a data structure: { "folder_name": { "pretty_name":..., "values": [...], "images": {...} } }
    label_info_dict = {}
    for label_file in label_folders:
        folder_name = os.path.splitext(label_file)[0]
        label_folder_path = os.path.join(labels_path, folder_name)
        label_json_path   = os.path.join(labels_path, label_file)
        data_json = load_json_as_dict(label_json_path)

        base_values = data_json.get("values", [])
        images_map  = {}

        if os.path.exists(label_folder_path) and os.path.isdir(label_folder_path):
            subfolder_files = [sf for sf in os.listdir(label_folder_path) if sf.endswith(".json")]
            sub_vals = [os.path.splitext(sf)[0] for sf in subfolder_files]
            combined = list(set(base_values + sub_vals))

            # Gather matching images
            image_files = [im for im in os.listdir(label_folder_path) if im.endswith((".jpg",".png"))]
            for val in combined:
                matched_img = next((im for im in image_files if os.path.splitext(im)[0] == val), None)
                if matched_img:
                    images_map[val] = f"/serve_label_image/{type_name}/{folder_name}/{matched_img}"
                else:
                    images_map[val] = None
        else:
            combined = base_values

        label_info_dict[folder_name] = {
            "pretty_name": prettify_label_name(folder_name),
            "values": combined,
            "images": images_map
        }

    # Convert to JSON for front-end
    import json
    label_info_json = json.dumps(label_info_dict)

    # 1) The top portion of our HTML
    html_top = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Edit Label</title>
        <link rel="stylesheet" href="/static/styles.css">
        <script>
            let labelInfo = {label_info_json};

            function updateLabelValues() {{
                let selectedFolder = document.getElementById("label_name").value;
                let valSelect      = document.getElementById("label_value");
                let customInput    = document.getElementById("custom_label_value");
                let imgContainer   = document.getElementById("label_image");
                let placeholder    = document.getElementById("image_placeholder");

                // Reset
                valSelect.innerHTML = "";
                customInput.style.display = "none";
                customInput.value = "";

                if (labelInfo[selectedFolder]) {{
                    let vals = labelInfo[selectedFolder].values;
                    vals.forEach(v => {{
                        let opt = document.createElement("option");
                        opt.value = v;
                        opt.textContent = v;
                        valSelect.appendChild(opt);
                    }});

                    // always add 'custom'
                    let customOpt = document.createElement("option");
                    customOpt.value = "custom";
                    customOpt.textContent = "Enter Custom Value";
                    valSelect.appendChild(customOpt);
                }} else {{
                    // no known folder => only 'custom'
                    let onlyCust = document.createElement("option");
                    onlyCust.value = "custom";
                    onlyCust.textContent = "Enter Custom Value";
                    valSelect.appendChild(onlyCust);
                }}

                // Hide or reset the image placeholder
                imgContainer.style.display = "none";
                placeholder.style.display  = "none";
            }}

            function checkCustomValue() {{
                let folderSel   = document.getElementById("label_name").value;
                let valSelect   = document.getElementById("label_value");
                let customInput = document.getElementById("custom_label_value");

                let imgContainer = document.getElementById("label_image");
                let placeholder  = document.getElementById("image_placeholder");

                if (valSelect.value === "custom") {{
                    valSelect.style.display = "none";
                    customInput.style.display = "block";
                    customInput.required = true;

                    imgContainer.style.display = "none";
                    placeholder.style.display  = "block";
                    placeholder.innerHTML = "No image for custom value";
                }} else {{
                    customInput.style.display = "none";
                    customInput.required = false;
                    valSelect.style.display = "inline-block";

                    let chosenVal = valSelect.value;
                    let imagesMap = labelInfo[folderSel].images;
                    if (imagesMap[chosenVal]) {{
                        imgContainer.src = imagesMap[chosenVal];
                        imgContainer.style.display = "block";
                        placeholder.style.display  = "none";
                    }} else {{
                        placeholder.style.display = "block";
                        placeholder.innerHTML = "Expected Image: " + chosenVal + ".jpg or .png";
                        imgContainer.style.display = "none";
                    }}
                }}
            }}

            window.onload = function() {{
                updateLabelValues();

                let existingVal = "{label_value}";
                let valSelect   = document.getElementById("label_value");

                let found = false;
                for (let i = 0; i < valSelect.options.length; i++) {{
                    if (valSelect.options[i].value === existingVal) {{
                        valSelect.selectedIndex = i;
                        found = true;
                        break;
                    }}
                }}

                if (!found) {{
                    for (let i = 0; i < valSelect.options.length; i++) {{
                        if (valSelect.options[i].value === "custom") {{
                            valSelect.selectedIndex = i;
                            break;
                        }}
                    }}
                    document.getElementById("custom_label_value").value = existingVal;
                }}

                checkCustomValue();
            }};
        </script>
    </head>
    <body>
        <div class="edit-label-container">
            <a href='/biography/{type_name}/{biography_name}' class="back-link">Back</a>
            <h1>Edit Label for {display_name}</h1>

            <form method="post">
                <!-- Label Folder -->
                <label for="label_name">Label Folder:</label>
                <select name="label_name" id="label_name"
                        onchange="updateLabelValues(); checkCustomValue();" required>
    """

    # 2) We build the <option> list in Python
    html_options = ""
    for folder, info in label_info_dict.items():
        selected = "selected" if folder == label_name else ""
        html_options += f'<option value="{folder}" {selected}>{info["pretty_name"]}</option>'

    # 3) The bottom portion of the HTML
    html_bottom = f"""
                </select>

                <!-- Image or placeholder -->
                <p id="image_placeholder" style="color: #888; font-style: italic; display: none;"></p>
                <img id="label_image" style="display: none; max-width: 150px; margin-top: 5px;"><br><br>

                <!-- Label Value -->
                <label for="label_value">Label Value:</label>
                <select name="label_value" id="label_value" onchange="checkCustomValue()" required>
                    <!-- Populated dynamically -->
                </select>
                <input type="text" id="custom_label_value" name="custom_label_value"
                       placeholder="Enter custom value" style="display:none;"><br><br>

                <!-- Confidence Slider -->
                <label for="confidence_slider">Confidence (0.0 - 1.0):</label>
                <input type="range" id="confidence_slider" name="confidence_slider"
                       min="0" max="1" step="0.01" value="{confidence}"
                       oninput="sliderValueDisplay.value = confidence_slider.value">
                <output id="sliderValueDisplay">{confidence}</output><br><br>

                <button type="submit">Save Changes</button>
            </form>
        </div>
    </body>
    </html>
    """

    # Finally, combine all parts into one string
    final_html = html_top + html_options + html_bottom
    return final_html




@app.route('/biography_editlabel_submit/<string:type_name>/<string:biography_name>/<int:entry_index>/<int:label_index>', methods=['POST'])
def biography_editlabel_submit(type_name, biography_name, entry_index, label_index):
    """
    POST route for saving changes to an existing label (name, value, confidence).
    This is separate from the GET-based `biography_editlabel` route.
    """

    # 1. Load the biography JSON
    biography_path = f"./types/{type_name}/biographies/{biography_name}.json"
    if not os.path.exists(biography_path):
        return "<h1>Error: Biography Not Found</h1>", 404

    bio_data = load_json_as_dict(biography_path)
    entries = bio_data.get("entries", [])

    # Ensure the entry index is valid
    if entry_index >= len(entries):
        flash("Error: Entry index out of range.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # Labels in that entry
    labels_list = entries[entry_index].get("labels", [])
    if label_index >= len(labels_list):
        flash("Error: Label index out of range.", "error")
        return redirect(f"/biography/{type_name}/{biography_name}")

    # 2. Parse form fields
    updated_label_name = request.form.get("label_name", "").strip()
    updated_label_value = request.form.get("label_value", "").strip()

    # If the user chose "custom", use the typed text
    if updated_label_value == "custom":
        custom_input = request.form.get("custom_label_value", "").strip()
        if custom_input:
            updated_label_value = custom_input
        else:
            flash("Error: Custom label value cannot be empty.", "error")
            return redirect(f"/biography/{type_name}/{biography_name}")

    # Parse confidence slider
    confidence_str = request.form.get("confidence_slider", "1.0").strip()
    try:
        updated_confidence = float(confidence_str)
    except ValueError:
        updated_confidence = 1.0

    # 3. Update the JSON
    labels_list[label_index] = {
        "label": updated_label_name,   # raw folder name or label name
        "value": updated_label_value,  # chosen or typed value
        "confidence": updated_confidence
    }

    # 4. Save
    save_dict_as_json(biography_path, bio_data)

    flash("Label updated successfully!", "success")
    return redirect(f"/biography/{type_name}/{biography_name}")


@app.route("/events/add", methods=["GET", "POST"])
def events_add():
    """
    Create a new 'event' biography that:
      - reuses your time catalog + normalisation
      - lets you pick a relationship label (from events/labels/relationship.json if present)
      - lets you attach multiple participants across types (person, organisation, building, …)
    """
    events_dir = os.path.join("types", "events", "biographies")
    os.makedirs(events_dir, exist_ok=True)

    # ---- load selectable things ----
    # Relationship options are data-driven if you add labels under types/events/labels/relationship.json
    def _load_relationship_options():
        labels_path = os.path.join("types", "events", "labels", "relationship.json")
        try:
            data = load_json_as_dict(labels_path) or {}
            return [ {"id": o.get("id"), "display": o.get("display") or o.get("id")} for o in data.get("options", []) ]
        except Exception:
            # Fallback hard-coded
            return [{"id":"employed_by","display":"Employed By"},
                    {"id":"lived_in","display":"Lived In"},
                    {"id":"founded","display":"Founded"},
                    {"id":"collaborated","display":"Collaborated"},
                    {"id":"visited","display":"Visited"}]

    relationship_opts = _load_relationship_options()

    # Participants: allow picking from any known type folders you care about
    selectable_types = ["person", "organisations", "buildings"]  # extend freely
    per_type_bios = { t: list_biographies(t) for t in selectable_types }

    # Time catalog for events (you can put decade/era etc. under types/events/labels/_time/*)
    def _time_catalog_for_events():
        try:
            return load_time_catalog("events")
        except Exception:
            return {"categories":[{"key":"date","description":"A date in time"},
                                  {"key":"life_stage","description":"A period"}],
                    "options":{}}

    time_catalog = _time_catalog_for_events()

    if request.method == "POST":
        # ---- gather form ----
        name         = (request.form.get("name") or "").strip()
        relationship = (request.form.get("relationship") or "").strip()
        notes        = (request.form.get("notes") or "").strip()

        # Participants come as rows: participant_type[i], participant_bio[i], role[i], confidence[i]
        participants = []
        idx = 0
        while True:
            tkey = request.form.get(f"participant_type[{idx}]")
            bid  = request.form.get(f"participant_bio[{idx}]")
            role = (request.form.get(f"participant_role[{idx}]") or "").strip()
            conf = request.form.get(f"participant_conf[{idx}]")
            if tkey is None and bid is None:
                break
            if (tkey or "").strip() and (bid or "").strip():
                try:
                    confv = int(conf) if conf is not None else 100
                except Exception:
                    confv = 100
                participants.append({
                    "type": tkey.strip(),
                    "bio_id": bid.strip(),
                    "role": role,
                    "confidence": confv
                })
            idx += 1

        # Time selection (same shape your time_step uses)
        lt = (request.form.get("label_type") or "").strip()
        sub = (request.form.get("subvalue") or "").strip()
        dv  = (request.form.get("date_value") or "").strip()
        sd  = (request.form.get("start_date") or "").strip()
        ed  = (request.form.get("end_date") or "").strip()
        try:
            tconf = int(request.form.get("time_confidence") or "100")
        except Exception:
            tconf = 100

        raw_time = {"label_type": lt, "confidence": tconf}
        if lt == "date":
            raw_time["date_value"] = dv
        elif lt == "range":
            raw_time["start_date"] = sd
            raw_time["end_date"]   = ed
        else:
            raw_time["subvalue"] = sub

        # Option meta for time (if decade/era etc.)
        opt_meta = None
        for o in time_catalog.get("options", {}).get(lt, []):
            if o.get("id") == sub:
                opt_meta = o
                break

        try:
            from time_utils import normalise_time_for_bio_entry
            time_norm = normalise_time_for_bio_entry(raw_time, biography={}, option_meta=opt_meta)
        except Exception:
            time_norm = {}

        # Event entry label bucket (relationship)
        rel_label = []
        if relationship:
            rel_label = [{
                "label_type": "relationship",
                "id": relationship,
                "confidence": 100
            }]

        # ---- write file ----
        now_iso = now_iso_utc()
        new_id  = f"evt_{uuid.uuid4().hex[:12]}"
        payload = {
            "id": new_id,
            "uid": uuid.uuid4().hex,
            "name": name or new_id.replace("_"," ").title(),
            "type": "events",
            "created": now_iso,
            "updated": now_iso,
            "archived": False,
            "entries": [{
                "created": now_iso,
                "updated": now_iso,
                "time": raw_time,
                "time_normalised": time_norm,
                "events": rel_label,
                "participants": participants,
                "notes": notes
            }]
        }
        save_dict_as_json(os.path.join(events_dir, f"{new_id}.json"), payload)
        flash("Event created.", "success")
        return redirect(url_for("biography_view", type_name="events", bio_id=new_id))

    # ---- GET: render a template ----
    # (Make a simple template 'event_add.html' with fields for: name, relationship,
    #  dynamic participant rows, and the same time widget layout you use in time_step.html.)
    return render_template(
        "event_add.html",
        relationship_opts=relationship_opts,
        per_type_bios=per_type_bios,
        time_catalog=time_catalog
    )



if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

