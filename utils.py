import re, math, os, json, requests
from datetime import datetime, timezone
from difflib import SequenceMatcher
from openai import OpenAI
import glob
from typing import List, Dict, Any, Optional  

from secrets_utils import get_secret

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")

def _sibling_image(folder: str, lid: str) -> str:
    """Return '/types/.../<lid>.<ext>' if a sibling image exists, else ''."""
    for ext in IMAGE_EXTS:
        cand = os.path.join(folder, lid + ext)
        if os.path.exists(cand):
            rel = os.path.relpath(cand, ".").replace("\\", "/")
            return rel if rel.startswith("/") else f"/{rel}"
    return ""

def load_json_safe(path):
    try:
        return load_json_as_dict(path)
    except Exception:
        return {}


def uk_datetime(iso_dt):
    """
    Converts ISO datetime string to UK-friendly format: 'DD Month YYYY, HH:MM'.
    """
    try:
        return datetime.fromisoformat(iso_dt).strftime("%d %B %Y, %H:%M")
    except (ValueError, TypeError):
        return iso_dt

def display_dob_uk(iso_date):
    """
    Converts a date string from 'YYYY-MM-DD' to 'DD/MM/YYYY' format.
    Returns original input if parsing fails.
    """
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso_date

def get_readable_time(timestamp):
    """
    Convert a Unix timestamp to a human-readable date.
    Returns 'Invalid Timestamp' if an error occurs.
    """
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return "Invalid Timestamp"
    
def now_iso_utc():
    return datetime.now(timezone.utc).isoformat()


def printButton(button_label,url):
    return "<a href='"+url+"'><button>"+button_label+"</button></a>"

def prettify(name):
    """
    Converts snake_case or kebab-case to Title Case and strips extensions if present.
    E.g., 'santa_claus.json' → 'Santa Claus'
    """
    import os
    base = os.path.splitext(name)[0]  # Remove .json, .jpg etc.
    return base.replace('_', ' ').replace('-', ' ').strip().title()

# ---------------------- bio selection mapping ----------------------

def map_existing_bio_selections(all_groups, entry_list):
    """
    Map previously selected biographies to their full group keys.

    Returns e.g.:
      {
        "work_building/hospital_bio": "royal_victoria_hospital",
        "work_building/hospital_bio_conf": 100
      }
    """
    # leaf -> [full_keys...]
    leaf_to_keys = {}
    for g in all_groups or []:
        key = g.get("key") or ""
        if not key:
            continue
        leaf = key.split("/")[-1]
        leaf_to_keys.setdefault(leaf, []).append(key)

    selections = {}
    for entry in entry_list or []:
        lt = (entry.get("label_type") or "").strip()
        bio_id = (entry.get("biography") or "").strip()
        if not lt or not bio_id:
            continue
        for full_key in leaf_to_keys.get(lt, []):
            selections[f"{full_key}_bio"] = bio_id
            selections[f"{full_key}_bio_conf"] = int(entry.get("biography_confidence", 100))
    return selections


def _map_existing_bio_selections(groups, saved_items):
    """Alias to map_existing_bio_selections for route code that expects the underscore name."""
    return map_existing_bio_selections(groups, saved_items)


# ---------------------- JSON utilities ----------------------

def save_dict_as_json(file_path, dictionary):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(dictionary, f, ensure_ascii=False, indent=4)
        return True
    except IOError as e:
        print(f"Error saving JSON file {file_path}: {e}")
        return False


def load_json_as_dict(file_path):
    """
    Load the JSON file at file_path into a dictionary.
    Returns an empty dict if the file does not exist or cannot be read.
    """
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            return json.load(json_file)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading JSON file {file_path}: {e}")
        return {}


# ---------------------- child group expansion ----------------------

def expand_child_groups(*, base_groups, current_type, label_base_path, existing_labels):
    """
    Expand nested child groups when a parent option is selected.

    - Supports self labels (current type) and cross-type labels (via source.kind=type_labels/self_labels
      or source.source='labels') with allow_children.
    - Recurses so work_place -> hospital -> royal_victoria_hospital -> ... will appear as you select deeper.
    - existing_labels may contain either raw strings or dicts with {label|id}.
    - Child groups inherit parent's `refer_to` and `link_biography` so biography suggestions
      render on the child group (not the parent).
    """
    # Start with a copy and a queue so we can recurse without deep recursion
    expanded = [dict(g) for g in (base_groups or [])]
    seen_keys = {g.get("key") for g in expanded if g.get("key")}
    queue = list(expanded)  # process newly-added groups as well

    def _selected_id_for(key: str):
        sel = (existing_labels or {}).get(key)
        if isinstance(sel, str):
            return sel
        if isinstance(sel, dict):
            return sel.get("label") or sel.get("id")
        return None

    def _collect_folder_options(folder_abs: str):
        """Lightweight loader used for child folders, including sibling images."""
        if not folder_abs or not os.path.isdir(folder_abs):
            return []

        opts = []
        for f in sorted(os.listdir(folder_abs)):
            if not f.endswith(".json") or f == "_group.json":
                continue

            path = os.path.join(folder_abs, f)
            data = load_json_as_dict(path) or {}

            oid = (data.get("id") or os.path.splitext(f)[0]).strip()
            if not oid:
                continue

            disp = (
                data.get("display")
                or data.get("label")
                or data.get("name")
                or data.get("properties", {}).get("name")
                or oid.replace("_", " ").title()
            )

            opt = {"id": oid, "display": disp}

            # description (prefer top-level, then properties.description)
            desc = data.get("description") or data.get("properties", {}).get("description")
            if desc:
                opt["description"] = desc

            # existing image fields (if present in JSON)
            if data.get("image"):
                opt["image"] = data["image"]
            if data.get("image_url"):
                opt["image_url"] = data["image_url"]

            # NEW: attach sibling image file (oid + extension) if no image already set
            if "image" not in opt and "image_url" not in opt:
                for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                    img_path = os.path.join(folder_abs, oid + ext)
                    if os.path.exists(img_path):
                        rel = os.path.relpath(img_path, ".").replace("\\", "/")
                        # ensure it’s a web path starting with '/'
                        opt["image"] = "/" + rel if not rel.startswith("/") else rel
                        break

            opts.append(opt)

        # nice stable ordering
        opts.sort(key=lambda o: ((o.get("display") or o.get("id") or "").lower(),
                                (o.get("id") or "").lower()))
        return opts

    while queue:
        g = queue.pop(0)
        parent_key = (g.get("key") or "").strip()
        if not parent_key:
            continue

        # Need a selection for THIS group to consider a child
        parent_id = _selected_id_for(parent_key)
        if not parent_id:
            continue

        # Determine the label-source for the parent group
        # Accept any of: source.kind in {type_labels, self_labels}, source.source == 'labels'
        src = (g.get("source") or {})
        refer = (g.get("refer_to") or g.get("link_biography") or {})  # used only for inheritance
        kind = (src.get("kind") or "").strip()
        src_source = (src.get("source") or "").strip()  # 'labels' | 'biographies' | ''
        allow_children = bool(src.get("allow_children"))

        # Work out which type/path to look under for the CHILD labels
        search_type = None
        base_path = None

        if kind in ("type_labels", "self_labels") or src_source == "labels":
            # explicit labels source
            if kind == "self_labels":  # refers to current type implicitly
                search_type = current_type
            else:
                search_type = (src.get("type") or current_type).strip()
            base_path = (src.get("path") or parent_key).strip("/")

            # If cross-type (different from current), require allow_children to expand
            if search_type != current_type and not allow_children:
                continue

        else:
            # no hint -> treat as this type's label tree
            search_type = current_type
            base_path = parent_key

        # Resolve absolute folder for the child options
        if search_type == current_type:
            child_folder = os.path.join(label_base_path, *base_path.split("/"), parent_id)
        else:
            child_folder = os.path.join("types", search_type, "labels", *base_path.split("/"), parent_id)

        if not os.path.isdir(child_folder):
            continue

        child_key = f"{base_path}/{parent_id}"
        if child_key in seen_keys:
            continue

        child_options = _collect_folder_options(child_folder)
        if not child_options:
            continue

        # Build the child group
        child_group = {
            "key": child_key,
            "label": f"{(g.get('label') or parent_key).replace('_', ' ').title()} / {parent_id.replace('_', ' ').title()}",
            "options": child_options,
            # inherit hints so deeper children expand and bios render here
            "source": dict(src) if isinstance(src, dict) else {},
        }
        if refer:
            # inherit for biography suggestion logic
            if g.get("refer_to"):
                child_group["refer_to"] = dict(g["refer_to"])
            if g.get("link_biography"):
                child_group["link_biography"] = dict(g["link_biography"])

        expanded.append(child_group)
        seen_keys.add(child_key)
        queue.append(child_group)  # allow deeper nesting if the child is already selected

    # Sort by depth then key for a stable UI
    expanded.sort(key=lambda gg: (len((gg.get("key") or "").split("/")), gg.get("key") or ""))
    return expanded

def _normalise_input_meta(meta: dict):
    """Return {"kind": ..., "name": "value", "placeholder": ..., "help": ...} or None."""
    if not isinstance(meta, dict):
        return None

    # Explicit "input" block wins
    if isinstance(meta.get("input"), dict):
        inp = dict(meta["input"])  # shallow copy
        if "name" not in inp:
            inp["name"] = "value"
        return inp

    # Fallback to simple "type" mapping
    t = (meta.get("type") or "").strip().lower()
    if not t:
        return None
    mapping = {
        "string": "text",
        "text": "textarea",
        "date": "date",
        "number": "number",
        "email": "email",
        "tel": "tel",
        "month": "month",
        "datetime-local": "datetime-local",
    }
    kind = mapping.get(t)
    if not kind:
        return None
    return {"kind": kind, "name": "value"}

def get_label_description(labels_dir, label_name):
    """Attempts to load a label description from a .txt file"""
    desc_path = os.path.join(labels_dir, f"{label_name}.txt")
    if os.path.exists(desc_path):
        with open(desc_path, 'r') as f:
            return f.read().strip()
    return ""

def resolve_entities(entry_type, entity_list):
    resolved = []
    for item in entity_list:
        if isinstance(item, str):
            item = {"id": item, "label_type": entry_type}

        eid = item.get("id")
        if not eid:
            continue

        label_type = item.get("label_type", entry_type)
        entry = {
            "id": eid,
            "confidence": item.get("confidence"),
            "label": item.get("label", ""),
            "label_type": label_type
        }

        entry["display"] = eid.capitalize()
        entry["link"] = None

        bio_path = f"./types/{entry_type}/biographies/{eid}.json"
        if os.path.exists(bio_path):
            bio_data = load_json_as_dict(bio_path)
            entry["display"] = bio_data.get("name", eid)
            entry["link"] = f"/biography/{entry_type}/{eid}"

        label_json_path = f"./types/{entry_type}/labels/{label_type}/{eid}.json"
        image_file_path = f"./types/{entry_type}/labels/{label_type}/{eid}.jpg"
        image_web_path = f"/serve_label_image/{entry_type}/{label_type}/{eid}.jpg"

        if os.path.exists(label_json_path):
            label_data = load_json_as_dict(label_json_path)
            entry["display"] = label_data.get("title") or label_data.get("name", eid.capitalize())
            entry["description"] = label_data.get("description", "")
            entry["properties"] = label_data.get("properties", {})

            if os.path.exists(image_file_path):
                entry["image_url"] = image_web_path

        resolved.append(entry)
    return resolved

def enrich_label_data(label_type: str, label_id: str, base_type: str = "person"):
    """
    Attempts to enrich a label by checking both:
    1. Subfolder-style: types/<base_type>/labels/<label_type>/<label_id>.json
    2. List-style: types/<base_type>/labels/<label_type>.json
    """

    # 1. Try subfolder-style
    subfolder_path = f"./types/{base_type}/labels/{label_type}/{label_id}.json"
    if os.path.exists(subfolder_path):
        with open(subfolder_path, "r") as f:
            label = json.load(f)
        return {
            "id": label_id,
            "label_type": label_type,
            "label": label.get("label", label_id),
            "display": label.get("display", label.get("label", label_id)),
            "description": label.get("description"),
            "image_url": label.get("image_url"),
            "properties": label.get("properties"),
        }

    # 2. Try list-style
    list_path = f"./types/{base_type}/labels/{label_type}.json"
    if os.path.exists(list_path):
        with open(list_path, "r") as f:
            label_list = json.load(f)

        for label in label_list:
            if label.get("id") == label_id:
                return {
                    "id": label_id,
                    "label_type": label_type,
                    "label": label.get("label", label_id),
                    "display": label.get("display", label.get("label", label_id)),
                    "description": label.get("description"),
                    "image_url": label.get("image_url"),
                    "properties": label.get("properties"),
                }

    # 3. Fallback
    return {
        "id": label_id,
        "label_type": label_type,
        "label": label_id,
    }

def get_icon(label_type):
    """
    Returns a small emoji or icon string based on label type or subfolder name.
    """
    if not label_type:
        return "🔖"
    label_type = label_type.lower()
    return {
        "house": "🏠",
        "school": "🏫",
        "university": "🎓",
        "job": "💼",
        "onet_occupation": "💼",
        "location": "📍",
        "event": "📅",
        "face": "🧑",
        "celebea_face_hq": "🧑‍🎤",
        "vehicle": "🚗",
        "organisation": "🏢",
        "friend": "🧑‍🤝‍🧑",
    }.get(label_type, "🔖")

LIFE_STAGE_ORDER = {
    "infant": 0.5,
    "toddler": 1.5,
    "childhood": 6.5,
    "preteen": 11.5,
    "teens": 15,
    "twenties": 25,
    "thirties": 35,
    "forties": 45,
    "fifties": 55,
    "sixties": 65,
    "seventies": 75,
    "eighties": 85,
    "nineties": 95,
    "hundreds": 105
}

def list_types():
    root = "types"
    if not os.path.isdir(root):
        return []
    return sorted([d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))])

def sanitise_key(raw: str, fallback: str = "") -> str:
    key = (raw or "").strip().lower()
    key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
    return key or fallback

def checkbox_on(req, name: str) -> bool:
    return (req.form.get(name) or "").lower() in ("on", "true", "1", "yes")

def collect_label_options_from_folder(folder_abs: str):
    """
    Return [{id, display, description?, image?|image_url?}] for *.json files in a folder.
    - Uses explicit `image` / `image_url` from the JSON if present.
    - Otherwise falls back to a sibling file <id>.(png|jpg|jpeg|webp) (case-insensitive).
    """
    if not folder_abs or not os.path.isdir(folder_abs):
        return []

    exts = (".png", ".jpg", ".jpeg", ".webp")
    out = []

    # Pre-list files once for case-insensitive sibling lookup
    try:
        dir_listing = os.listdir(folder_abs)
    except Exception:
        dir_listing = []
    lower_map = {fn.lower(): fn for fn in dir_listing}

    for fname in sorted(dir_listing):
        if not fname.endswith(".json") or fname == "_group.json":
            continue

        lid = os.path.splitext(fname)[0]
        data = load_json_safe(os.path.join(folder_abs, fname)) or {}

        display = (
            (data.get("properties") or {}).get("name")
            or data.get("display")
            or data.get("label")
            or data.get("name")
            or lid
        )
        desc = (
            data.get("description")
            or (data.get("properties") or {}).get("description", "")
        )

        item = {"id": lid, "display": display}
        if desc:
            item["description"] = desc

        # 1) Prefer explicit image fields from JSON, if present
        if data.get("image"):
            item["image"] = data["image"]
        if data.get("image_url"):
            item["image_url"] = data["image_url"]

        # 2) Fallback to sibling file <id>.<ext> (case-insensitive) if no image set
        if "image" not in item and "image_url" not in item:
            for ext in exts:
                cand_name = lid + ext
                # case-insensitive match in the folder
                real_name = lower_map.get(cand_name.lower())
                if real_name:
                    ipath = os.path.join(folder_abs, real_name)
                    if os.path.exists(ipath):
                        rel = os.path.relpath(ipath, ".").replace("\\", "/")
                        item["image"] = rel if rel.startswith("/") else f"/{rel}"
                        break

        out.append(item)

    out.sort(key=lambda o: ((o.get("display") or o.get("id") or "").lower(),
                            (o.get("id") or "").lower()))
    return out

def normalise_source_meta(meta: dict, prop_key: str, current_type: str):
    """
    Map self_labels -> type_labels(current_type), defaulting path to prop_key.
    This keeps the rest of the code path simple (only type_labels/type_biographies).
    """
    if not isinstance(meta, dict):
        return meta
    src = (meta.get("source") or meta.get("properties", {}).get("source") or {})
    if isinstance(src, dict) and src.get("kind") == "self_labels":
        meta = dict(meta)  # shallow copy
        new_src = dict(src)
        new_src["kind"] = "type_labels"
        new_src["type"] = current_type
        if not new_src.get("path"):
            new_src["path"] = prop_key
        # keep allow_children if present
        if "allow_children" not in new_src:
            new_src["allow_children"] = bool(src.get("allow_children"))
        # write back in top-level "source"
        meta["source"] = new_src
    return meta


def load_labels_from_folder(folder_path):
    """
    Loads all .json label files from a folder and returns a list of label dicts.
    """
    labels = []
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            try:
                file_path = os.path.join(folder_path, filename)
                data = load_json_as_dict(file_path)
                labels.append({
                    "id": os.path.splitext(filename)[0],
                    "display": data.get("name", os.path.splitext(filename)[0]),
                    "description": data.get("description", "")
                })
            except Exception as e:
                print(f"[ERROR] Loading label {filename}: {e}")
    return labels

import os, json, uuid
from datetime import datetime, timezone

def list_biographies(type_name):
    """
    Return a list of biography metadata for the given type.

    - Ensures every biography JSON has a stable unique 'uid' (UUIDv4, persisted).
    - Returns both 'created' and 'updated' (falls back to file mtime / latest entry).
    - Keeps the existing 'id' (the file slug) for routing compatibility.
    """
    bios_dir = os.path.join("types", type_name, "biographies")
    bios = []
    if not os.path.isdir(bios_dir):
        return bios

    def iso_utc(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    for filename in sorted(os.listdir(bios_dir)):
        if not filename.endswith(".json"):
            continue

        bio_id = os.path.splitext(filename)[0]
        bio_path = os.path.join(bios_dir, filename)

        try:
            data = load_json_as_dict(bio_path) or {}
        except Exception as e:
            print(f"[list_biographies] Error reading {bio_path}: {e}")
            continue

        # Ensure a stable unique identifier, persisted in the file
        uid = data.get("uid")
        if not uid:
            uid = uuid.uuid4().hex
            data["uid"] = uid

        # Timestamps
        created = data.get("created")
        updated = data.get("updated")

        # If no updated, use newest entry.updated/created, else file mtime, else created
        if not updated:
            latest = None
            try:
                entries = data.get("entries") or []
                if entries:
                    # prefer entry.updated, then entry.created
                    latest = max(
                        (e.get("updated") or e.get("created") for e in entries if isinstance(e, dict)),
                        default=None
                    )
            except Exception:
                latest = None

            if latest:
                updated = latest
            else:
                try:
                    updated = iso_utc(os.path.getmtime(bio_path))
                except Exception:
                    updated = created or ""

        # If no created, fall back to file ctime/mtime
        if not created:
            try:
                created = iso_utc(os.path.getctime(bio_path))
            except Exception:
                try:
                    created = iso_utc(os.path.getmtime(bio_path))
                except Exception:
                    created = ""

        # Persist any fixes (uid / timestamps) back to disk
        changed = False
        if data.get("uid") != uid:
            data["uid"] = uid; changed = True
        if not data.get("created") and created:
            data["created"] = created; changed = True
        if not data.get("updated") and updated:
            data["updated"] = updated; changed = True
        if changed:
            try:
                save_dict_as_json(bio_path, data)
            except Exception as e:
                print(f"[list_biographies] Could not persist fixes to {bio_path}: {e}")

        bios.append({
            "id": bio_id,  # slug for routing
            "uid": uid,    # globally unique identifier
            "name": data.get("name", bio_id.replace("_", " ").title()),
            "description": data.get("description", ""),
            "created": created,
            "updated": updated,
            "entries": data.get("entries", []),
        })

    return bios

def build_suggested_biographies(*args, **kwargs):
    """
    Suggest biography options per group.

    Preferred signature:
        build_suggested_biographies(current_type, label_groups_list, label_base_path, existing_labels=None)

    Returns: { safe_group_key: [ {id, display, description?}, ... ] }
    """
    # -------- arg normalization --------
    current_type = None
    label_groups_list = None
    label_base_path = None
    existing_labels = None

    if "current_type" in kwargs:
        current_type      = kwargs.get("current_type")
        label_groups_list = kwargs.get("label_groups_list")
        label_base_path   = kwargs.get("label_base_path")
        existing_labels   = kwargs.get("existing_labels")
    else:
        if len(args) == 4:
            current_type, label_groups_list, label_base_path, existing_labels = args
        elif len(args) == 3:
            current_type, label_groups_list, label_base_path = args
        elif len(args) == 2:
            label_groups_list, label_base_path = args
        else:
            raise TypeError("build_suggested_biographies: unexpected arguments")

    if not isinstance(label_groups_list, (list, tuple)):
        raise TypeError("build_suggested_biographies: label_groups_list must be a list")

    if not isinstance(existing_labels, dict):
        existing_labels = {}

    def load_json_safely(p):
        try:
            return load_json_as_dict(p)
        except Exception:
            return {}

    # ---- helpers ----
    def _norm_selected_map(d):
        """Make values simple strings (selected ids)."""
        out = {}
        for k, v in (d or {}).items():
            if isinstance(v, str):
                out[k] = v
            elif isinstance(v, dict):
                out[k] = v.get("label") or v.get("id") or v.get("value") or ""
        return out

    norm_selected = _norm_selected_map(existing_labels)

    def _selected_chain_for_key(base_key: str) -> str:
        """
        Traverse selections downward:
          base -> sel1; base/sel1 -> sel2 => "sel1/sel2"
        """
        bits = []
        cur = base_key
        while True:
            sel = norm_selected.get(cur)
            if not sel:
                break
            bits.append(sel)
            cur = f"{cur}/{sel}"
        return "/".join(bits)

    def _append_bios_from_folder(folder, bios, seen):
        if not os.path.isdir(folder):
            return
        for f in sorted(os.listdir(folder)):
            if not f.endswith(".json"):
                continue
            bid = os.path.splitext(f)[0]
            if bid in seen:
                continue
            data = load_json_safely(os.path.join(folder, f))
            bios.append({
                "id": bid,
                "display": data.get("name", bid.replace("_", " ").title()),
                "description": data.get("description", "")
            })
            seen.add(bid)

    def _folder_has_json_files(folder) -> bool:
        if not os.path.isdir(folder):
            return False
        return any(f.endswith(".json") for f in os.listdir(folder))

    out = {}

    for g in label_groups_list:
        key = g.get("key")
        if not key:
            continue
        safe = key.replace("/", "__")
        bios = []
        seen = set()

        # ---------- A) link_biography (scoped by the selected label chain) ----------
        lb = g.get("link_biography")
        if isinstance(lb, dict) and lb.get("type"):
            lb_type = lb["type"]
            base_bios_dir = os.path.join("types", lb_type, "biographies")
            if os.path.isdir(base_bios_dir):
                conf_path = (lb.get("path") or "").strip("/")
                mode = (lb.get("mode") or "child_or_parent")

                chain = _selected_chain_for_key(key)  # "" or "sel1" or "sel1/sel2/..."
                root = os.path.join(base_bios_dir, conf_path) if conf_path else base_bios_dir

                if chain:
                    parts = chain.split("/")
                    child_dir  = os.path.join(root, *parts)     # deepest child
                    parent_dir = os.path.join(root, parts[0])   # first-level parent

                    if mode == "child_only":
                        _append_bios_from_folder(child_dir, bios, seen)
                    elif mode == "parent_only":
                        _append_bios_from_folder(parent_dir, bios, seen)
                    else:  # child_or_parent
                        _append_bios_from_folder(child_dir, bios, seen)
                        if not bios:
                            _append_bios_from_folder(parent_dir, bios, seen)
                else:
                    # NEW: if no chain yet, but there are bios directly at the configured root,
                    # show those (common when there are no label subfolders at all).
                    if _folder_has_json_files(root):
                        _append_bios_from_folder(root, bios, seen)
                    # otherwise (there are only subfolders), leave empty until a label is picked.

        # ---------- B) refer_to = biographies (unscoped list) ----------
        if not bios and g.get("refer_to", {}).get("source") == "biographies":
            r = g["refer_to"]
            r_type = r.get("type")
            r_path = (r.get("path") or "").strip("/")
            base = os.path.join("types", r_type, "biographies") if r_type else None
            if base and os.path.isdir(base):
                scan = os.path.join(base, r_path) if r_path else base
                # list *all* JSONs beneath scan
                for root, _, files in os.walk(scan):
                    for f in files:
                        if not f.endswith(".json"):
                            continue
                        bid = os.path.splitext(f)[0]
                        if bid in seen:
                            continue
                        data = load_json_safely(os.path.join(root, f))
                        bios.append({
                            "id": bid,
                            "display": data.get("name", bid.replace("_", " ").title()),
                            "description": data.get("description", "")
                        })
                        seen.add(bid)

        if bios:
            bios.sort(key=lambda x: (x.get("display") or x.get("id") or "").lower())
            out[safe] = bios

    return out

def list_label_groups_for_type(type_name: str):
    """
    Return a sorted list of label group paths under types/<type>/labels.
    Includes nested groups, e.g. "work_building", "work_building/hospital".
    """
    base = os.path.join("types", type_name, "labels")
    groups = set()
    if not os.path.isdir(base):
        return []

    for root, dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        if rel == ".":
            # top-level property JSONs also create a group of same key
            for f in files:
                if f.endswith(".json") and f not in ("_group.json",):
                    groups.add(os.path.splitext(f)[0])
            continue

        # this is a subfolder; use folder path as a group key
        rel_key = rel.replace("\\", "/")
        groups.add(rel_key)

        # property JSONs inside this folder also count as direct groups/options
        for f in files:
            if f.endswith(".json") and f not in ("_group.json",):
                key = f[:-5]  # filename without .json
                groups.add(f"{rel_key}/{key}")

    return sorted(groups, key=lambda s: (s.count("/"), s))

def build_label_groups_by_type():
    out = {}
    for t in list_types():
        out[t] = list_label_groups_for_type(t)
    return out

def build_label_catalog_for_type(current_type: str, max_per_group: int = 200):
    """
    Return a list of candidate labels the LLM can choose from:
    [{id, display, group_key, type}, ...]
    Uses your property-first groups (collect_label_groups) so it also covers cross-type sources.
    """
    base_path = os.path.join("types", current_type, "labels")
    groups = collect_label_groups(base_path, current_type)
    catalog = []

    for g in groups:
        key = g.get("key", "")
        for o in (g.get("options") or [])[:max_per_group]:
            if not isinstance(o, dict):
                continue
            iid = o.get("id")
            if not iid:
                continue
            catalog.append({
                "id": iid,
                "display": o.get("display", iid),
                "group_key": key,              # e.g. "work_place"
                "type": current_type           # keep for completeness
            })
    return catalog


def _tokens(s: str):
    return [t for t in re.split(r"[^a-z0-9]+", (s or "").lower()) if t]

def _fuzzy(a: str, b: str) -> float:
    # 0..1
    try:
        return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    except Exception:
        return 0.0

def _collect_all_labels(type_name: str):
    """
    Walk types/<type>/labels recursively and return a list of:
      { id, display, description, label_type (group key), path }
    Where label_type is the group key (folder->path without the filename).
    """
    base = os.path.join("types", type_name, "labels")
    out = []
    if not os.path.isdir(base):
        return out

    for root, _, files in os.walk(base):
        # group key is the path under labels/, excluding the file
        rel_dir = os.path.relpath(root, base).replace("\\", "/").strip(".")
        # skip hidden dirs
        if any(seg.startswith(".") for seg in rel_dir.split("/")):
            continue

        # try read _group.json for a nicer group name (optional)
        group_meta = {}
        gmeta_path = os.path.join(root, "_group.json")
        if os.path.exists(gmeta_path):
            gm = load_json_safe(gmeta_path)
            if isinstance(gm, dict):
                group_meta = gm

        for f in files:
            if not f.endswith(".json") or f == "_group.json":
                continue
            lid = os.path.splitext(f)[0]
            jp = os.path.join(root, f)
            data = load_json_safe(jp)
            if not isinstance(data, dict):
                data = {}

            name = (
                (data.get("properties", {}) or {}).get("name")
                or data.get("name")
                or lid.replace("_", " ").title()
            )
            desc = (
                data.get("description")
                or (data.get("properties", {}) or {}).get("description", "")
            )

            # accept optional aliases to help matching
            aliases = []
            for key in ("aliases", "alt_names", "synonyms"):
                v = data.get(key) or (data.get("properties", {}) or {}).get(key)
                if isinstance(v, list):
                    aliases.extend([str(x) for x in v if isinstance(x, (str, int, float))])

            label_type = rel_dir if rel_dir != "." else ""   # top-level group file
            # if the file sits directly in labels/, label_type is just "" -> use the filename as group
            if not label_type:
                label_type = os.path.splitext(f)[0]

            out.append({
                "id": lid,
                "display": name,
                "description": desc,
                "aliases": aliases,
                "label_type": label_type,          # e.g. "hair_colour" or "work_place/hospital"
                "path": jp
            })
    return out

def _score_label(prompt: str, item: dict) -> float:
    """Simple hybrid score: token overlap + fuzzy on display + a small bonus if id appears."""
    ptoks = set(_tokens(prompt))
    text = " ".join([item.get("display",""), item.get("description","")] + item.get("aliases", []))
    ttoks = set(_tokens(text))
    overlap = len(ptoks & ttoks)
    jacc = overlap / (len(ptoks | ttoks) or 1)
    fuzz = _fuzzy(prompt, item.get("display",""))
    id_bonus = 0.15 if item.get("id","").lower() in prompt.lower() else 0.0
    # weight overlap higher than fuzzy
    return (0.65 * jacc) + (0.35 * fuzz) + id_bonus

import os, re, shutil, json
from datetime import datetime

SAFE_TYPE = re.compile(r"^[a-z0-9_]+$")

def list_types_live():
    root = "types"
    return sorted([
        d for d in os.listdir(root)
        if os.path.isdir(os.path.join(root, d)) and not d.startswith("_")
    ]) if os.path.isdir(root) else []

def archive_root():
    return os.path.join("archive", "types")

def archive_type_folder_name(type_name):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{type_name}_{ts}"

def type_exists(type_name):
    return os.path.isdir(os.path.join("types", type_name))

def archive_type(type_name):
    assert SAFE_TYPE.match(type_name), "Invalid type name."
    src = os.path.join("types", type_name)
    if not os.path.isdir(src):
        raise FileNotFoundError(f"Type '{type_name}' not found.")
    dst_root = archive_root()
    os.makedirs(dst_root, exist_ok=True)
    dst = os.path.join(dst_root, archive_type_folder_name(type_name))
    shutil.move(src, dst)
    return dst

def restore_type(archived_folder):
    # archived_folder is the full name under archive/types, e.g. person_20250809-224200
    src = os.path.join(archive_root(), archived_folder)
    if not os.path.isdir(src):
        raise FileNotFoundError("Archived folder not found.")
    # Derive type name from prefix before last underscore timestamp
    # safer: split last '_' occurrence that is followed by digits
    parts = archived_folder.rsplit("_", 1)
    type_name = parts[0] if len(parts) == 2 else archived_folder
    dst = os.path.join("types", type_name)
    if os.path.exists(dst):
        raise FileExistsError(f"Type '{type_name}' already exists live.")
    os.makedirs("types", exist_ok=True)
    shutil.move(src, dst)
    return dst

def scan_cross_references(target_type: str):
    """
    Find references to `target_type` from other types' label configurations.

    We flag three patterns:
      1) Property JSON (top-level) with  source.kind in {"type_labels","type_biographies"} and source.type == target_type
      2) Property JSON (top-level) with  link_biography.type == target_type
      3) Any label JSON under a group where properties.suggests_biographies_from == target_type

    Returns a list of dicts:
      {
        "from_type": "<type that holds the ref>",
        "kind": "source_labels" | "source_biographies" | "link_biography" | "suggests_from_label",
        "group_key": "<group or subpath if we can infer it>",
        "file": "<relative path to the json that declared it>",
        "details": {... raw bits we saw ...}
      }
    """
    refs = []
    base_types_dir = os.path.join("types")
    if not os.path.isdir(base_types_dir):
        return refs

    def load_json_safely(p):
        try:
            return load_json_as_dict(p)
        except Exception as e:
            print(f"[scan_xref] WARN could not parse {p}: {e}")
            return None

    for from_type in os.listdir(base_types_dir):
        if from_type == target_type:
            continue
        t_path = os.path.join(base_types_dir, from_type)
        if not os.path.isdir(t_path):
            continue

        labels_root = os.path.join(t_path, "labels")
        if not os.path.isdir(labels_root):
            continue

        # ----- (A) Top-level property JSONs (property-first design) -----
        for name in os.listdir(labels_root):
            if not name.endswith(".json"):
                continue
            prop_key = name[:-5]
            prop_path = os.path.join(labels_root, name)
            meta = load_json_safely(prop_path)
            if not isinstance(meta, dict):
                # tolerate arrays/strings/etc; just skip
                continue

            # read source + link_biography from either top-level or properties
            src = (
                meta.get("source")
                or meta.get("properties", {}).get("source")
                or {}
            )
            lb = (
                meta.get("link_biography")
                or meta.get("properties", {}).get("link_biography")
                or {}
            )

            # 1) source.kind points to target_type
            if isinstance(src, dict):
                kind = src.get("kind")
                s_type = src.get("type")
                if s_type == target_type and kind in ("type_labels", "type_biographies"):
                    refs.append({
                        "from_type": from_type,
                        "kind": "source_labels" if kind == "type_labels" else "source_biographies",
                        "group_key": prop_key,
                        "file": os.path.relpath(prop_path, "."),
                        "details": {"source": src}
                    })

            # 2) link_biography points to target_type
            if isinstance(lb, dict):
                lb_type = lb.get("type")
                if lb_type == target_type:
                    refs.append({
                        "from_type": from_type,
                        "kind": "link_biography",
                        "group_key": prop_key,
                        "file": os.path.relpath(prop_path, "."),
                        "details": {"link_biography": lb}
                    })

        # ----- (B) Legacy subfolders: look for label JSONs that suggest target_type -----
        # Any *.json within any subfolder (except _group.json) that contains
        # properties.suggests_biographies_from == target_type
        for root, _, files in os.walk(labels_root):
            rel_root = os.path.relpath(root, labels_root).replace("\\", "/")
            for f in files:
                if not f.endswith(".json"):
                    continue
                if f == "_group.json":
                    continue
                jpath = os.path.join(root, f)
                data = load_json_safely(jpath)
                if not isinstance(data, dict):
                    continue
                props = data.get("properties", {})
                sugg = props.get("suggests_biographies_from") or data.get("suggests_biographies_from")
                if sugg == target_type:
                    group_key = rel_root if rel_root != "." else ""
                    refs.append({
                        "from_type": from_type,
                        "kind": "suggests_from_label",
                        "group_key": group_key,
                        "file": os.path.relpath(jpath, "."),
                        "details": {"suggests_biographies_from": sugg}
                    })

    return refs



# def collect_label_groups(label_base_path, current_type):
#     label_groups_list = []

#     for root, _, files in os.walk(label_base_path):
#         rel_path = os.path.relpath(root, label_base_path)
#         if rel_path == ".":
#             continue  # Skip root

#         values = []
#         for file in files:
#             if not file.endswith(".json"):
#                 continue
#             base = file[:-5]
#             json_path = os.path.join(root, file)
#             img_path = os.path.join(root, f"{base}.jpg")

#             try:
#                 data = load_json_as_dict(json_path)
#                 label = {
#                     "id": base,
#                     "display": data.get("properties", {}).get("name", base),
#                     "label_type": rel_path  # e.g. work_building/hospital
#                 }
#                 if os.path.exists(img_path):
#                     label["image"] = f"/types/{current_type}/labels/{rel_path}/{base}.jpg"
#                 if "description" in data:
#                     label["description"] = data["description"]
#                 values.append(label)
#             except Exception as e:
#                 print(f"[ERROR] Reading nested label {file}: {e}")

#         # ✅ Always add the group — even if values is empty
#         label_groups_list.append({
#             "key": rel_path,
#             "label": os.path.basename(root).replace("_", " ").title(),
#             "options": values
#         })

#     return label_groups_list

def collect_label_groups(label_base_path: str, current_type: str):
    """
    Build groups for the label wizard.

    Property‑first (top‑level *.json files under labels/), with a safe fallback
    to local folder options when the resolver yields none; then legacy folders.

    Group shape:
      {
        "key": "work_place",
        "label": "Work place",
        "description": "...",
        "required": bool,
        "allow_multiple": bool,
        "order": int?,
        # EITHER an input-driven group:
        "input": {
          "kind": "text|textarea|date|number|email|tel|month|datetime-local|select",
          "name": "value",
          "placeholder": "...",
          "help": "...",
          "options": [ { "id": "...", "display": "..." } ]   # only for kind=="select"
        },
        # OR a choice-driven group (labels/biographies):
        "options": [ { id, display, description?, image? } ... ],
        "refer_to": { "type": "...", "source": "labels"|"biographies", "path": "...", "allow_children": bool }?,
        "link_biography": { "type": "...", "path": "...", "mode": "child_only|parent_only|child_or_parent" }?
      }
    """
    groups = []
    if not os.path.isdir(label_base_path):
        return groups

    def load_json_safe_defensive(p):
        try:
            return load_json_safe(p)
        except Exception:
            return {}

    def extract_source(meta: dict):
        """
        Read `source` (either top-level or properties.source) and normalise to:
          - {"type": str, "source": "labels", "path": str, "allow_children": bool}
          - {"type": str, "source": "biographies", "path": str}
        """
        src = (meta or {}).get("source") or (meta or {}).get("properties", {}).get("source") or {}
        if not isinstance(src, dict):
            return None

        kind = src.get("kind")
        if kind == "type_labels":
            return {
                "type": src.get("type"),
                "source": "labels",
                "path": src.get("path", ""),
                "allow_children": bool(src.get("allow_children")),
            }
        if kind == "type_biographies":
            return {
                "type": src.get("type"),
                "source": "biographies",
                "path": src.get("path", ""),
            }
        # leave None for unknown kinds; self_labels handled by normaliser
        return None

    def extract_link_bio(meta: dict):
        lb = (meta or {}).get("link_biography") or (meta or {}).get("properties", {}).get("link_biography") or {}
        if not isinstance(lb, dict) or not lb.get("type"):
            return None
        return {
            "type": lb.get("type"),
            "path": lb.get("path", ""),
            "mode": (lb.get("mode") or "child_or_parent"),
        }

    def _bool_meta(meta: dict, key: str) -> bool:
        return bool((meta or {}).get(key) or (meta or {}).get("properties", {}).get(key))

    def _int_meta(meta: dict, key: str):
        raw = (meta or {}).get(key) or (meta or {}).get("properties", {}).get(key)
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _normalise_input_meta(meta: dict):
        """
        If the property/folder meta declares an input, normalise it to:
          {"kind": "...", "name": "value", "placeholder": "...", "help": "...", "options": [...]}
        Returns None if it's not an input-style property.
        Priority:
          1) explicit "input" block wins
          2) fallback to simple "type" mapping (String/Text/Date/Number/Email/Tel/Month/Datetime-local)
        """
        if not isinstance(meta, dict):
            return None

        # 1) Explicit "input" block
        if isinstance(meta.get("input"), dict):
            inp = dict(meta["input"])  # shallow copy
            if "name" not in inp or not inp.get("name"):
                inp["name"] = "value"
            if inp.get("kind"):
                inp["kind"] = str(inp["kind"]).strip().lower()
            return inp

        # 2) Fallback "type" mapping
        t = (meta.get("type") or meta.get("properties", {}).get("type") or "").strip().lower()
        if not t:
            return None
        mapping = {
            "string": "text",
            "text": "textarea",
            "date": "date",
            "number": "number",
            "email": "email",
            "tel": "tel",
            "month": "month",
            "datetime-local": "datetime-local",
            "datetime": "datetime-local",  # alias
        }
        kind = mapping.get(t)
        if not kind:
            return None
        return {"kind": kind, "name": "value"}

    # ---------- 1) Property‑JSON groups (top level files in labels/) ----------
    top_level_jsons = [
        f for f in os.listdir(label_base_path)
        if f.endswith(".json") and os.path.isfile(os.path.join(label_base_path, f))
    ]

    for jf in sorted(top_level_jsons):
        prop_key  = os.path.splitext(jf)[0]
        prop_path = os.path.join(label_base_path, jf)
        meta = load_json_safe_defensive(prop_path)

        # If the file is not an object (e.g. a simple list), expose as a basic group
        if not isinstance(meta, dict):
            if isinstance(meta, list):
                opts = []
                for item in meta:
                    if isinstance(item, str):
                        opts.append({"id": item, "display": item})
                    elif isinstance(item, dict):
                        iid  = item.get("id") or item.get("key") or item.get("value")
                        name = item.get("display") or item.get("name") or iid
                        if iid:
                            o = {"id": iid, "display": name or iid}
                            if item.get("description"): o["description"] = item["description"]
                            img = item.get("image") or item.get("image_url")
                            if img:
                                o["image"] = o["image_url"] = img
                            opts.append(o)
                if opts:
                    groups.append({
                        "key": prop_key,
                        "label": prop_key.replace("_"," ").title(),
                        "description": "",
                        "required": False,
                        "allow_multiple": False,
                        "order": None,
                        "options": opts
                    })
            continue

        # Normalise 'self_labels' into a fully-specified 'type_labels(current_type)'
        meta = normalise_source_meta(meta, prop_key, current_type)

        prop_name = (
            meta.get("name")
            or meta.get("properties", {}).get("name")
            or prop_key.replace("_", " ").title()
        )
        prop_desc = (
            meta.get("description")
            or meta.get("properties", {}).get("description", "")
        )
        required = _bool_meta(meta, "required")
        allow_multiple = _bool_meta(meta, "allow_multiple")
        order = _int_meta(meta, "order")

        # (NEW) Input-style property? Build an input group and skip options.
        inp = _normalise_input_meta(meta)
        if inp:
            g = {
                "key": prop_key,
                "label": prop_name,
                "description": prop_desc,
                "required": required,
                "allow_multiple": allow_multiple,
                "order": order,
                "input": inp,       # drives an input in the template
                "options": [],      # not used for inputs
            }
            # pass through link_biography/refer_to if provided
            refer_to = extract_source(meta)
            link_bio = extract_link_bio(meta)
            if refer_to:
                g["refer_to"] = refer_to
            if link_bio:
                g["link_biography"] = link_bio
            groups.append(g)
            continue  # do NOT attempt options resolution for input groups

        # 1a) Try resolver (supports cross-type, local, etc.)
        try:
            options = resolve_property_options(
                current_type=current_type,
                label_base_path=label_base_path,
                prop_key=prop_key,
                prop_meta=meta,
            ) or []
        except Exception as e:
            print(f"[collect_label_groups] resolve_property_options failed for {prop_key}: {e}")
            options = []

        # 1b) Fallback: if resolver yielded no options, list local folder options
        if not options:
            options = collect_label_options_from_folder(
                os.path.join(label_base_path, prop_key)
            )

        refer_to = extract_source(meta)
        link_bio = extract_link_bio(meta)

        g = {
            "key": prop_key,
            "label": prop_name,
            "description": prop_desc,
            "required": required,
            "allow_multiple": allow_multiple,
            "order": order,
            "options": options,
        }
        if refer_to:
            g["refer_to"] = refer_to
        if link_bio:
            g["link_biography"] = link_bio

        groups.append(g)

    # ---------- 2) Legacy folders (subdirectories without a matching property JSON) ----------
    for entry in sorted(os.listdir(label_base_path)):
        full = os.path.join(label_base_path, entry)
        if not os.path.isdir(full):
            continue
        if f"{entry}.json" in top_level_jsons:
            # already represented by a property JSON
            continue

        group_label = entry.replace("_", " ").title()
        group_desc  = ""
        refer_to    = None
        link_bio    = None
        required    = False
        allow_multiple = False
        order = None

        meta_path = os.path.join(full, "_group.json")
        meta = load_json_safe_defensive(meta_path) if os.path.exists(meta_path) else {}

        if isinstance(meta, dict) and meta:
            # Normalise any self_labels hint in folder meta too
            meta = normalise_source_meta(meta, entry, current_type)
            group_label = (
                meta.get("name")
                or meta.get("properties", {}).get("name")
                or group_label
            )
            group_desc = (
                meta.get("description")
                or meta.get("properties", {}).get("description", "")
                or ""
            )
            required = _bool_meta(meta, "required")
            allow_multiple = _bool_meta(meta, "allow_multiple")
            order = _int_meta(meta, "order")

            # If author used 'self_labels' here, normaliser above rewrites it,
            # but in case it didn't, map it to current-type labels with children.
            src_hint = extract_source(meta)
            if not src_hint and (meta.get("source", {}) or {}).get("kind") == "self_labels":
                src_hint = {
                    "type": current_type,
                    "source": "labels",
                    "path": entry,
                    "allow_children": True,
                }
            refer_to = src_hint
            link_bio = extract_link_bio(meta)

            # (NEW) Allow legacy folder _group.json to declare an input too
            inp = _normalise_input_meta(meta)
            if inp:
                g = {
                    "key": entry,
                    "label": group_label,
                    "description": group_desc,
                    "required": required,
                    "allow_multiple": allow_multiple,
                    "order": order,
                    "input": inp,
                    "options": [],
                }
                if refer_to:
                    g["refer_to"] = refer_to
                if link_bio:
                    g["link_biography"] = link_bio
                groups.append(g)
                continue  # skip listing folder options; input-only

        # default legacy behaviour: list folder options
        options = collect_label_options_from_folder(full)

        g = {
            "key": entry,
            "label": group_label,
            "description": group_desc,
            "required": required,
            "allow_multiple": allow_multiple,
            "order": order,
            "options": options,
        }
        if refer_to:
            g["refer_to"] = refer_to
        if link_bio:
            g["link_biography"] = link_bio

        groups.append(g)

    # Stable-ish order: by key (you can sort by 'order' elsewhere if preferred)
    groups.sort(key=lambda g: g.get("key", ""))
    return groups

# utils.py
import os, json, re, sqlite3, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone

def slugify_key(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", (s or "").lower()).strip("_")

def _write_label_json(base_dir: str, label_type: str, item: dict):
    """
    item expects: {id, display, description?, image_url?, confidence?}
    Creates label json and child label/bio folders under base_dir/<id> and sibling bios dir.
    """
    label_id     = slugify_key(item["id"])
    display_name = item.get("display") or label_id.replace("_", " ").title()
    path_json    = os.path.join(base_dir, f"{label_id}.json")
    os.makedirs(base_dir, exist_ok=True)

    payload = {
        "id": label_id,
        "display": display_name,
        "label_type": label_type,
        "description": item.get("description", ""),
        "confidence": int(item.get("confidence", 100)),
        "image_url": item.get("image_url", ""),
        "source": item.get("source", "import"),
        "created": datetime.now(timezone.utc).isoformat(),
        "properties": item.get("properties", {})
    }
    # prune blanks
    payload = {k: v for k, v in payload.items() if v not in ("", None, [])}

    with open(path_json, "w") as f:
        json.dump(payload, f, indent=2)

    # child folders
    label_id = payload["id"]
    child_label_dir = os.path.join(base_dir, label_id)
    os.makedirs(child_label_dir, exist_ok=True)
    return payload["id"]  # return canonical id (slug)

def _ensure_property_self_labels(type_name: str, group_key: str, display_label: str, description: str = ""):
    """
    Ensure top-level property JSON exists mapping this group to self_labels w/ allow_children.
    """
    labels_root  = os.path.join("types", type_name, "labels")
    prop_json    = os.path.join(labels_root, f"{group_key}.json")
    if not os.path.exists(prop_json):
        with open(prop_json, "w") as f:
            json.dump({
                "name": display_label,
                "description": description or "",
                "source": {
                    "kind": "self_labels",
                    "path": group_key,
                    "allow_children": True
                }
            }, f, indent=2)

def _fetch_api_json(url: str, headers: dict = None, query: dict = None, timeout: int = 15):
    """
    Lightweight HTTP GET (no external deps). Returns parsed JSON or []/{}.
    """
    try:
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read()
            try:
                return json.loads(content.decode("utf-8", errors="ignore"))
            except Exception:
                return []
    except urllib.error.URLError as e:
        print("[API ERROR]", e)
        return []

def _extract_items_from_json(data, array_path: str, field_map: dict):
    """
    array_path: e.g. "data.items"  -> we walk nested dicts/lists
    field_map:  {"id": "code", "display": "name", "description": "summary", "image_url": "image"}
    Returns list of {id, display, ...}
    """
    def walk_path(obj, path):
        parts = [p for p in (path or "").split(".") if p]
        cur = obj
        for p in parts:
            if isinstance(cur, dict):
                cur = cur.get(p, [])
            elif isinstance(cur, list):
                # allow numeric index
                try:
                    idx = int(p)
                    cur = cur[idx] if 0 <= idx < len(cur) else []
                except ValueError:
                    # apply to each and flatten
                    acc = []
                    for it in cur:
                        if isinstance(it, dict) and p in it:
                            acc.append(it[p])
                    cur = acc
            else:
                return []
        return cur

    raw = walk_path(data, array_path) if array_path else data
    if not isinstance(raw, list):
        raw = [raw] if raw else []

    out = []
    for row in raw:
        if not isinstance(row, dict): 
            continue
        iid = row.get(field_map.get("id", "id"))
        disp = row.get(field_map.get("display", "display")) or iid
        if not iid or not disp:
            continue
        item = {
            "id": str(iid),
            "display": str(disp),
            "description": row.get(field_map.get("description", "description"), ""),
            "image_url": row.get(field_map.get("image_url", "image_url"), ""),
        }
        out.append(item)
    return out

def _import_labels_from_api(type_name: str, group_key: str, display_label: str, description: str,
                            api_url: str, array_path: str, field_map: dict, headers: dict = None, query: dict = None,
                            max_items: int = 200):
    labels_dir = os.path.join("types", type_name, "labels", group_key)
    os.makedirs(labels_dir, exist_ok=True)

    _ensure_property_self_labels(type_name, group_key, display_label, description)

    data = _fetch_api_json(api_url, headers=headers, query=query)
    items = _extract_items_from_json(data, array_path=array_path, field_map=field_map)
    created = []
    for item in items[:max_items]:
        slug = _write_label_json(labels_dir, group_key, item)
        created.append(slug)
    return created

def _import_labels_from_sqlite(type_name: str, group_key: str, display_label: str, description: str,
                               sqlite_path: str, sql: str,
                               col_id: str = "id", col_display: str = "name",
                               col_desc: str = "description", col_img: str = "image_url",
                               max_items: int = 500):
    labels_dir = os.path.join("types", type_name, "labels", group_key)
    os.makedirs(labels_dir, exist_ok=True)

    _ensure_property_self_labels(type_name, group_key, display_label, description)

    created = []
    try:
        con = sqlite3.connect(sqlite_path)
        cur = con.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        idx = {c: i for i, c in enumerate(cols)}
        for i, row in enumerate(cur.fetchall()):
            if i >= max_items: break
            def col(name): 
                j = idx.get(name)
                return row[j] if j is not None else None

            item = {
                "id": col(col_id),
                "display": col(col_display),
                "description": col(col_desc) or "",
                "image_url": col(col_img) or ""
            }
            if not item["id"] or not item["display"]:
                continue
            slug = _write_label_json(labels_dir, group_key, item)
            created.append(slug)
        con.close()
    except Exception as e:
        print("[SQLITE IMPORT ERROR]", e)
    return created



# def expand_child_groups(base_groups, current_type, label_base_path, existing_labels):
#     """
#     Recursively expand groups when a selected option has a matching child subfolder.

#     Example:
#       - Group key "work_building" with selected id "hospital"
#       - If folder exists: types/<type>/labels/work_building/hospital/
#         -> add a new group with key "work_building/hospital"
#       - If the user has already selected e.g. "royal_victoria" in that child group
#         AND a deeper folder exists (work_building/hospital/royal_victoria/),
#         this function will keep expanding.

#     Arguments:
#       base_groups:      list from collect_label_groups(...)
#       current_type:     the type name (e.g. "person")
#       label_base_path:  path like "types/<type>/labels"
#       existing_labels:  dict of previously selected labels for the current entry,
#                         shaped like { "work_building": {"id":"hospital", ...},
#                                       "work_building/hospital": {"id":"royal_victoria", ...} }

#     Returns:
#       A new list including all original groups plus any recursively discovered child groups.
#     """
#     import os
#     import json

#     IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

#     def _safe_json(path):
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 return json.load(f)
#         except Exception as e:
#             print(f"[WARN] expand_child_groups: failed to parse {path}: {e}")
#             return {}

#     def _image_for(base_dir, base_name):
#         for ext in IMAGE_EXTS:
#             p = os.path.join(base_dir, base_name + ext)
#             if os.path.exists(p):
#                 # build a web path like /types/<type>/labels/…/file.ext
#                 rel = os.path.relpath(p, ".").replace("\\", "/")
#                 return "/" + rel
#         return None

#     def _load_options_from_folder(folder_abs_path):
#         """Load *.json in a folder as options (name/description/image if present)."""
#         opts = []
#         if not os.path.isdir(folder_abs_path):
#             return opts
#         for fn in sorted(os.listdir(folder_abs_path)):
#             if not fn.endswith(".json"):
#                 continue
#             base = os.path.splitext(fn)[0]
#             data = _safe_json(os.path.join(folder_abs_path, fn))
#             name = (
#                 data.get("properties", {}).get("name")
#                 or data.get("name")
#                 or base.replace("_", " ").title()
#             )
#             desc = data.get("description", data.get("properties", {}).get("description", ""))
#             img = _image_for(folder_abs_path, base)

#             opt = {"id": base, "display": name}
#             if desc:
#                 opt["description"] = desc
#             if img:
#                 opt["image_url"] = img
#             opts.append(opt)
#         return opts

#     # We’ll loop until no more child groups can be added (supports multi-level).
#     expanded = list(base_groups)
#     seen_keys = {g["key"] for g in expanded}

#     changed = True
#     while changed:
#         changed = False

#         # Iterate over a snapshot because we may append during the loop
#         for group in list(expanded):
#             group_key = group["key"]  # e.g. "work_building" or "work_building/hospital"
#             sel = existing_labels.get(group_key) or {}
#             selected_id = sel.get("id") or sel.get("label")
#             if not selected_id:
#                 continue

#             # Resolve filesystem path to this group's folder
#             # group_key may be nested -> split
#             group_folder = os.path.join(label_base_path, *group_key.split("/"))
#             if not os.path.isdir(group_folder):
#                 continue

#             # Child folder must be named exactly as selected_id
#             child_folder = os.path.join(group_folder, selected_id)
#             if not os.path.isdir(child_folder):
#                 continue

#             child_key = f"{group_key}/{selected_id}"
#             if child_key in seen_keys:
#                 # Already added
#                 continue

#             # Load this child folder as a new group
#             child_options = _load_options_from_folder(child_folder)
#             if not child_options:
#                 continue

#             new_group = {
#                 "key": child_key,
#                 "label": f"{group.get('label','').strip() or group_key.replace('_',' ').title()} → {selected_id.replace('_',' ').title()}",
#                 "description": f"Options for {selected_id.replace('_',' ').title()}",
#                 "options": child_options,
#             }
#             expanded.append(new_group)
#             seen_keys.add(child_key)
#             changed = True

#     # Keep ordering stable-ish: parent keys first, then deeper ones
#     expanded.sort(key=lambda g: (g["key"].count("/"), g["key"]))
#     return expanded




def load_property_definitions(label_base_path):
    """Return a list of property defs (top-level JSONs under labels/)."""
    props = []
    for name in os.listdir(label_base_path):
        if not name.endswith(".json"):
            continue
        path = os.path.join(label_base_path, name)
        try:
            data = load_json_as_dict(path)
            key = os.path.splitext(name)[0]  # e.g., "work_place"
            data["_key"] = key
            props.append(data)
        except Exception as e:
            print(f"[prop-def] failed {path}: {e}")
    # Sort by name for stable UI
    props.sort(key=lambda d: d.get("name", d["_key"]).lower())
    return props

def resolve_property_options(current_type, label_base_path, prop):
    """
    Returns list of options:
      [{"id": "...", "display": "...", "image": "...", "source": "inline|folder|bio", ...}]
    """
    out = []
    # 1) Folder-backed
    folder = prop.get("options_folder")
    if folder:
        folder_path = os.path.join(label_base_path, folder)
        if os.path.isdir(folder_path):
            for f in os.listdir(folder_path):
                if f.endswith(".json"):
                    bid = os.path.splitext(f)[0]
                    data = load_json_as_dict(os.path.join(folder_path, f))
                    out.append({
                        "id": bid,
                        "display": data.get("properties", {}).get("name", bid.replace("_", " ").title()),
                        "source": "folder"
                    })
        return out

    # 2) Inline
    inline = prop.get("options_inline")
    if inline:
        for opt in inline:
            out.append({
                "id": opt["id"],
                "display": opt.get("display", opt["id"]),
                "source": "inline"
            })
        return out

    # 3) Cross-type biographies
    other = prop.get("select_from_type")
    if other:
        bio_dir = os.path.join("types", other, "biographies")
        if os.path.isdir(bio_dir):
            for f in os.listdir(bio_dir):
                if f.endswith(".json"):
                    bid = os.path.splitext(f)[0]
                    bdata = load_json_as_dict(os.path.join(bio_dir, f))
                    disp = bdata.get(prop.get("display_field", "name"), bid)
                    out.append({
                        "id": bid,
                        "display": disp,
                        "source": "bio",
                        "biography_type": other
                    })
        return out

    return out


def resolve_property_options(current_type: str, label_base_path: str, prop_key: str, prop_meta: dict):
    """
    Return a list of option dicts for a property JSON (id, display, description, image_url?).
    Handles source.kind: folder | type_labels | type_biographies | none
    """
    opts = []
    src = (prop_meta or {}).get("source", {}) or {}
    kind = src.get("kind", "folder")

    def load_option_file(json_path, display_fallback):
        try:
            data = load_json_as_dict(json_path)
        except Exception:
            data = {}
        name = data.get("properties", {}).get("name") or data.get("name") or display_fallback
        desc = data.get("description") or ""
        base = os.path.splitext(os.path.basename(json_path))[0]
        image_jpg = os.path.join(os.path.dirname(json_path), f"{base}.jpg")
        image_url = None
        if os.path.exists(image_jpg):
            # best‑effort URL relative to /types
            rel = os.path.relpath(image_jpg, ".")
            image_url = "/" + rel.replace("\\", "/")
        return {
            "id": base,
            "display": name,
            "description": desc,
            "image_url": image_url
        }

    if kind == "folder":
        subpath = src.get("path")
        if not subpath:
            return []
        folder = os.path.join(label_base_path, *subpath.split("/"))
        if os.path.isdir(folder):
            for f in sorted(os.listdir(folder)):
                if f.endswith(".json"):
                    opts.append(load_option_file(os.path.join(folder, f), os.path.splitext(f)[0]))

    elif kind == "type_labels":
        other_type = src.get("type")
        subpath = src.get("path")
        if other_type and subpath:
            folder = os.path.join("types", other_type, "labels", *subpath.split("/"))
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    if f.endswith(".json"):
                        opts.append(load_option_file(os.path.join(folder, f), os.path.splitext(f)[0]))

    elif kind == "type_biographies":
        other_type = src.get("type")
        if other_type:
            folder = os.path.join("types", other_type, "biographies")
            if os.path.isdir(folder):
                for f in sorted(os.listdir(folder)):
                    if not f.endswith(".json"):
                        continue
                    path = os.path.join(folder, f)
                    try:
                        data = load_json_as_dict(path)
                    except Exception:
                        data = {}
                    bio_id = os.path.splitext(f)[0]
                    name = data.get("name", bio_id)
                    desc = data.get("description", "")
                    opts.append({
                        "id": bio_id,
                        "display": name,
                        "description": desc
                    })
    elif kind == "none":
        # free text/number — no options (UI should render an input instead; you can add later)
        opts = []

    return opts



def load_grouped_biographies(base_path):
    grouped = {}

    if not os.path.exists(base_path):
        return grouped

    for root, _, files in os.walk(base_path):
        rel_path = os.path.relpath(root, base_path)
        folder_key = rel_path if rel_path != "." else "root"

        grouped.setdefault(folder_key, [])

        for f in files:
            if f.endswith(".json"):
                try:
                    f_path = os.path.join(root, f)
                    data = load_json_as_dict(f_path)
                    grouped[folder_key].append({
                        "id": os.path.splitext(f)[0],
                        "display": data.get("name", os.path.splitext(f)[0]),
                        "description": data.get("description", "")
                    })
                except Exception as e:
                    print(f"[BIO ERROR] {f}: {e}")

    return grouped

def get_label_descriptions_for_type(type_name):
    """Load all label metadata (id, display, description, label_type) for the given type."""

    label_folder = f"./types/{type_name}/labels"
    label_data = []

    for filepath in glob.glob(f"{label_folder}/**/*.json", recursive=True):
        filename = os.path.splitext(os.path.basename(filepath))[0]
        rel_path = os.path.relpath(filepath, label_folder)
        label_type = os.path.dirname(rel_path).replace("\\", "/")  # e.g., "work_building/hospital"

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                print(f"[⚠️ Skipped non-dict JSON] {filepath} → type={type(data).__name__}")
                continue

            label_id = data.get("id", filename)
            display = data.get("display") or data.get("label") or data.get("properties", {}).get("name", filename)
            description = data.get("description", "")

            # Require ID and Display at minimum
            if not label_id or not display:
                print(f"[⚠️ Skipped incomplete label] {filepath} → Missing id or display")
                continue

            label_data.append({
                "id": label_id,
                "display": display,
                "description": description,
                "label_type": label_type
            })
        except Exception as e:
            print(f"[❌ Error reading label file] {filepath}: {e}")

    return label_data

def suggest_labels_from_text(user_input, type_name):
    """Use GPT to suggest labels based on user input and label metadata."""
    label_data = get_label_descriptions_for_type(type_name)

    if not label_data:
        print(f"[🚫 No label data found] for type: {type_name}")
        return []

    # ⬇️ Add this to inspect label metadata passed into the prompt
    print(f"[🔎 Prompt label data] {json.dumps(label_data, indent=2)}")

    # ⬇️ Build the GPT prompt
    prompt = f"""You are a helpful assistant that suggests labels from a dataset.

Available labels:
{json.dumps(label_data, indent=2)}

The user has described the person/thing as:
\"\"\"{user_input}\"\"\"

From the list above, return the top 5 most relevant label `id` values (not display names).
Respond ONLY as a JSON array like: ["label_id_1", "label_id_2"]
"""

    # ⬇️ Add this print to show the final prompt going to GPT
    print(f"[🧠 Final Prompt Sent]\n{prompt}")

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You match descriptions to label IDs from metadata."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.4,
    )

    try:
        content = response.choices[0].message.content
        print(f"[🧠 GPT Raw Response] {content}")

        # ✅ Strip triple backticks (if present)
        content = content.strip().strip("```json").strip("```").strip()

        suggestions = json.loads(content)
        return suggestions if isinstance(suggestions, list) else []
    except Exception as e:
        print(f"[❌ Error parsing GPT response] {e}")
        return []
    
# --- add at the very end of utils.py ---

# Compatibility shims so routes can call underscored helpers
def _collect_label_groups(label_base_path: str, type_name: str) -> List[dict]:
    """Alias to your existing collect_label_groups."""
    return collect_label_groups(label_base_path, type_name)

def _expand_child_groups(*, base_groups: List[dict], current_type: str,
                         label_base_path: str, selected_map: Dict[str, str]) -> List[dict]:
    """Alias that adapts param name 'selected_map' -> 'existing_labels'."""
    return expand_child_groups(
        base_groups=base_groups,
        current_type=current_type,
        label_base_path=label_base_path,
        existing_labels=selected_map
    )

def _build_suggested_biographies(*, current_type: str,
                                 label_groups_list: List[dict],
                                 label_base_path: str,
                                 existing_labels: Dict[str, Any]) -> Dict[str, List[dict]]:
    """Alias to your build_suggested_biographies with the named args the route uses."""
    return build_suggested_biographies(
        current_type=current_type,
        label_groups_list=label_groups_list,
        label_base_path=label_base_path,
        existing_labels=existing_labels
    )

def _list_biographies(type_name: str) -> List[dict]:
    """Alias to your list_biographies, but shaped the way the template expects."""
    # Convert your richer objects to the simple {id, display, description?} cards the UI uses
    bios = list_biographies(type_name) or []
    out = []
    for b in bios:
        out.append({
            "id": b.get("id"),
            "display": b.get("name") or (b.get("id","").replace("_"," ").title()),
            "description": b.get("description",""),
        })
    # Keep ordering stable
    out.sort(key=lambda x: (x.get("display","").lower(), x.get("id","").lower()))
    return out

def fetch_external_options(src: dict, search: str = "") -> list[dict]:
    if not src or src.get("kind") != "external_api":
        return []

    endpoint = src.get("endpoint")
    method   = (src.get("method") or "GET").upper()

    # Build headers
    headers = {}
    # 1) Look up token name to pull from env or secrets.json
    env_name = (src.get("headers_env") or "").strip()
    token = ""
    if env_name:
        token = os.getenv(env_name, "") or get_secret(env_name)  # <- env first, then secrets.json
    if token:
        # common “Bearer” default; adjust if your API needs a different header key
        headers["Authorization"] = f"Bearer {token}"
    # Also allow static headers map if you add it later
    for k, v in (src.get("headers_static") or {}).items():
        headers[k] = v

    # Query/body templating
    def _sub(v: str) -> str:
        return (v or "").replace("{search}", search)

    params, body = {}, None
    if isinstance(src.get("query"), dict):
        params = {k: _sub(str(v)) for k, v in src["query"].items()}
    if isinstance(src.get("body"), dict):
        body = {k: _sub(str(v)) for k, v in src["body"].items()}

    # Request
    try:
        if method == "GET":
            resp = requests.get(endpoint, params=params, headers=headers, timeout=15)
        else:
            resp = requests.post(endpoint, json=body, params=params, headers=headers, timeout=15)
    except Exception as e:
        print(f"[external_api] request error: {e}")
        return []

    if resp.status_code >= 400:
        print(f"[external_api] {resp.status_code}: {resp.text[:300]}")
        return []

    try:
        data = resp.json()
    except Exception as e:
        print(f"[external_api] JSON parse error: {e}")
        return []

    # list_path like "data.items"
    items = data
    for p in (src.get("list_path","").split(".") if src.get("list_path") else []):
        if not p: continue
        if isinstance(items, dict):
            items = items.get(p, [])
        else:
            items = []
    if not isinstance(items, list):
        items = []

    mapping = src.get("map", {})
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        _id = str(it.get(mapping.get("id",""), "")).strip()
        if not _id:
            continue
        out.append({
            "id": _id,
            "display": str(it.get(mapping.get("display",""), "") or _id).strip(),
            "description": str(it.get(mapping.get("description",""), "") or ""),
            "image_url": str(it.get(mapping.get("image_url",""), "") or ""),
        })
    return out