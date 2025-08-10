import os
import json
from datetime import datetime
from openai import OpenAI
import re
import glob

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

def load_json_safe(path):
    try:
        return load_json_as_dict(path)
    except Exception:
        return {}

def load_json_as_dict(file_path):
    """
    Load the JSON file at file_path into a dictionary.
    Returns an empty dictionary if the file does not exist or cannot be read.
    """
    if not os.path.exists(file_path):
        return {}  # Return an empty dict instead of failing

    try:
        with open(file_path, "r", encoding="utf-8") as json_file:
            return json.load(json_file)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading JSON file {file_path}: {e}")
        return {}  # Return an empty dict if loading fails

def save_dict_as_json(file_path, dictionary):
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(dictionary, f, ensure_ascii=False, indent=4)
        return True
    except IOError as e:
        print(f"Error saving JSON file {file_path}: {e}")
        return False

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

def collect_label_options_from_folder(folder_abs):
    """Return [{id, display, description?, image?}] for *.json files in a folder."""
    out = []
    if not os.path.isdir(folder_abs):
        return out
    for f in sorted(os.listdir(folder_abs)):
        if not f.endswith(".json") or f == "_group.json":
            continue
        lid = os.path.splitext(f)[0]
        data = load_json_safe(os.path.join(folder_abs, f))
        display = (data.get("properties", {}) or {}).get("name") or data.get("name") or lid
        desc = data.get("description", (data.get("properties", {}) or {}).get("description", ""))

        # sibling image if present
        img = None
        for ext in IMAGE_EXTS:
            cand = os.path.join(folder_abs, lid + ext)
            if os.path.exists(cand):
                rel = os.path.relpath(cand, ".").replace("\\", "/")
                img = f"/{rel}"
                break

        item = {"id": lid, "display": display}
        if desc: item["description"] = desc
        if img:  item["image"] = img
        out.append(item)
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

def list_biographies(type_name):
    """
    Return a list of biography metadata for the given type.
    """
    bios_dir = os.path.join("types", type_name, "biographies")
    bios = []
    if os.path.exists(bios_dir):
        for f in os.listdir(bios_dir):
            if f.endswith(".json"):
                bio_path = os.path.join(bios_dir, f)
                try:
                    bio_data = load_json_as_dict(bio_path)
                    bios.append({
                        "id": os.path.splitext(f)[0],
                        "name": bio_data.get("name", "[Unnamed]"),
                        "created": bio_data.get("created", ""),
                        "entries": bio_data.get("entries", [])
                    })
                except Exception as e:
                    print(f"Error reading {bio_path}: {e}")
    return bios

def build_suggested_biographies(*args, **kwargs):
    """
    Suggest biography options per group.

    Preferred signature:
        build_suggested_biographies(current_type, label_groups_list, label_base_path, existing_labels=None)

    Back-compat:
        build_suggested_biographies(current_type, label_groups_list, label_base_path)
        build_suggested_biographies(label_groups_list, label_base_path)

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
                if chain:
                    # Deepest child and first parent folder derived from the chain
                    root = os.path.join(base_bios_dir, conf_path) if conf_path else base_bios_dir
                    parts = chain.split("/")
                    child_dir = os.path.join(root, *parts)               # deepest child
                    parent_dir = os.path.join(root, parts[0])            # first-level parent

                    if mode == "child_only":
                        _append_bios_from_folder(child_dir, bios, seen)
                    elif mode == "parent_only":
                        _append_bios_from_folder(parent_dir, bios, seen)
                    else:  # child_or_parent
                        _append_bios_from_folder(child_dir, bios, seen)
                        if not bios:
                            _append_bios_from_folder(parent_dir, bios, seen)
                else:
                    # No selection yet → do NOT suggest anything (keeps UX clean)
                    pass

        # ---------- B) refer_to = biographies (unscoped list) ----------
        elif g.get("refer_to", {}).get("source") == "biographies":
            r = g["refer_to"]
            r_type = r.get("type")
            r_path = (r.get("path") or "").strip("/")
            base = os.path.join("types", r_type, "biographies") if r_type else None
            if base and os.path.isdir(base):
                scan = os.path.join(base, r_path) if r_path else base
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
            # Sort for stable UX
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
    Build groups from property JSONs (property-first), with legacy subfolder fallback.

    Group shape:
      {
        "key": "work_place",
        "label": "Work place",
        "description": "...",
        "options": [ { id, display, description?, image? } ... ],
        "refer_to": { "type": "...", "source": "labels"|"biographies", "path": "...", "allow_children": true }?,  # hint
        "link_biography": { "type": "...", "path": "...", "mode": "child_or_parent" }?
      }
    """
    groups = []
    if not os.path.isdir(label_base_path):
        return groups

    def build_option_from_file(json_path: str):
        data = load_json_safe(json_path)
        base = os.path.splitext(os.path.basename(json_path))[0]
        name = (data.get("properties", {}) or {}).get("name") or data.get("name") or base
        desc = data.get("description", (data.get("properties", {}) or {}).get("description", ""))

        # sibling image
        img = None
        folder = os.path.dirname(json_path)
        for ext in IMAGE_EXTS:
            cand = os.path.join(folder, base + ext)
            if os.path.exists(cand):
                rel = os.path.relpath(cand, ".").replace("\\", "/")
                img = f"/{rel}"
                break

        opt = {"id": base, "display": name}
        if desc: opt["description"] = desc
        if img:
            opt["image"] = img
            opt["image_url"] = img
        return opt

    def extract_source(meta: dict):
        src = (meta or {}).get("source") or (meta or {}).get("properties", {}).get("source") or {}
        if not isinstance(src, dict):
            return None
        kind = src.get("kind")
        if kind == "type_labels":
            return {
                "type": src.get("type"),
                "source": "labels",
                "path": src.get("path", ""),
                "allow_children": bool(src.get("allow_children"))
            }
        if kind == "type_biographies":
            return {"type": src.get("type"), "source": "biographies", "path": src.get("path", "")}
        return None

    def extract_link_bio(meta: dict):
        lb = (meta or {}).get("link_biography") or (meta or {}).get("properties", {}).get("link_biography") or {}
        if not isinstance(lb, dict) or not lb.get("type"):
            return None
        return {"type": lb.get("type"), "path": lb.get("path", ""), "mode": (lb.get("mode") or "child_or_parent")}

    # 1) Property JSONs at top-level of labels/
    top_level_jsons = [
        f for f in os.listdir(label_base_path)
        if f.endswith(".json") and os.path.isfile(os.path.join(label_base_path, f))
    ]

    for jf in sorted(top_level_jsons):
        prop_key  = os.path.splitext(jf)[0]
        prop_path = os.path.join(label_base_path, jf)
        meta = load_json_safe(prop_path)

        # handle non-dict defensively
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
                            if img: o["image"] = o["image_url"] = img
                            opts.append(o)
                if opts:
                    groups.append({
                        "key": prop_key,
                        "label": prop_key.replace("_"," ").title(),
                        "description": "",
                        "options": opts
                    })
            continue

        # normalise self_labels to type_labels(current_type)
        meta = normalise_source_meta(meta, prop_key, current_type)

        prop_name = meta.get("name") or meta.get("properties", {}).get("name") or prop_key.replace("_", " ").title()
        prop_desc = meta.get("description") or meta.get("properties", {}).get("description", "")

        # Let your existing resolver populate options when appropriate
        try:
            options = resolve_property_options(
                current_type=current_type,
                label_base_path=label_base_path,
                prop_key=prop_key,
                prop_meta=meta
            ) or []
        except Exception as e:
            print(f"[ERROR] resolve_property_options failed for {prop_key}: {e}")
            options = []

        refer_to = extract_source(meta)
        link_bio = extract_link_bio(meta)

        g = {"key": prop_key, "label": prop_name, "description": prop_desc, "options": options}
        if refer_to: g["refer_to"] = refer_to
        if link_bio: g["link_biography"] = link_bio
        groups.append(g)

    # 2) Legacy: subfolders without a property JSON
    for entry in sorted(os.listdir(label_base_path)):
        full = os.path.join(label_base_path, entry)
        if not os.path.isdir(full):
            continue
        if f"{entry}.json" in top_level_jsons:
            continue

        group_label = entry.replace("_"," ").title()
        group_desc = ""
        refer_to = None
        link_bio = None

        meta_path = os.path.join(full, "_group.json")
        if os.path.exists(meta_path):
            m = load_json_safe(meta_path)
            if isinstance(m, dict):
                # also normalise self_labels in group meta
                m = normalise_source_meta(m, entry, current_type)
                group_label = m.get("name") or m.get("properties", {}).get("name") or group_label
                group_desc  = m.get("description") or m.get("properties", {}).get("description", "") or ""
                refer_to    = (
                    {"type": current_type, "source":"labels", "path": entry, "allow_children": True}
                    if (m.get("source", {}) or {}).get("kind") == "self_labels"
                    else extract_source(m)
                )
                link_bio    = extract_link_bio(m)

        opts = []
        for f in sorted(os.listdir(full)):
            if not f.endswith(".json") or f == "_group.json":
                continue
            opts.append(build_option_from_file(os.path.join(full, f)))

        g = {"key": entry, "label": group_label, "description": group_desc, "options": opts}
        if refer_to: g["refer_to"] = refer_to
        if link_bio: g["link_biography"] = link_bio
        groups.append(g)

    groups.sort(key=lambda g: g.get("key",""))
    return groups

def expand_child_groups(*, base_groups, current_type, label_base_path, existing_labels):
    """
    Expand nested child groups when a parent option is selected.

    - Supports self labels (current type) and cross-type labels (type_labels) with allow_children.
    - Recurses so work_place -> hospital -> royal_victoria -> (etc) will appear as you select deeper.
    - existing_labels may contain either raw strings or dicts with {label|id}.
    - Child groups inherit parent's `refer_to` and `link_biography` so biography suggestions
      render on the child group (not the parent).
    """
    # Start with a copy and a queue so we can recurse without deep recursion
    expanded = [dict(g) for g in base_groups]
    seen_keys = {g["key"] for g in expanded}
    queue = list(expanded)  # process newly-added groups as well

    def _selected_id_for(key: str):
        sel = existing_labels.get(key)
        if isinstance(sel, str):
            return sel
        if isinstance(sel, dict):
            return sel.get("label") or sel.get("id")
        return None

    def _collect_folder_options(folder_abs: str):
        """Lightweight loader used for child folders."""
        if not os.path.isdir(folder_abs):
            return []
        opts = []
        for f in sorted(os.listdir(folder_abs)):
            if not f.endswith(".json") or f == "_group.json":
                continue
            try:
                data = load_json_as_dict(os.path.join(folder_abs, f))
            except Exception:
                data = {}
            lid = os.path.splitext(f)[0]
            disp = (
                data.get("properties", {}).get("name")
                or data.get("name")
                or lid
            )
            desc = data.get("description", data.get("properties", {}).get("description", ""))
            opts.append({"id": lid, "display": disp, "description": desc})
        return opts

    while queue:
        g = queue.pop(0)

        parent_key = g.get("key")
        if not parent_key:
            continue

        # Need a selection for THIS group to consider a child
        parent_id = _selected_id_for(parent_key)
        if not parent_id:
            continue

        # Determine where the parent's options come from
        # (we look at normalised hints on the group)
        src = g.get("refer_to") or g.get("source") or {}
        kind = src.get("source") or src.get("kind") or ""   # "labels" | "biographies" | ""
        allow_children = bool(src.get("allow_children"))

        # Work out which type/path to look under for the CHILD labels
        search_type = None
        base_path = None

        if kind == "labels":
            # explicit cross-type labels
            search_type = src.get("type") or current_type
            base_path = (src.get("path") or parent_key).strip("/")
            # require allow_children for cross-type expansion
            if search_type != current_type and not allow_children:
                continue
        elif kind == "biographies":
            # biographies do not yield child label groups
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
            # already added from an earlier pass
            continue

        child_options = _collect_folder_options(child_folder)
        if not child_options:
            continue

        # Build the child group
        child_group = {
            "key": child_key,
            "label": f"{(g.get('label') or parent_key).replace('_',' ').title()} / {parent_id.replace('_',' ').title()}",
            "options": child_options,
        }

        # Inherit hints so:
        #  - deeper children can continue to expand
        #  - biography suggestions render on the child group
        if g.get("refer_to"):
            child_group["refer_to"] = dict(g["refer_to"])
        if g.get("link_biography"):
            child_group["link_biography"] = dict(g["link_biography"])

        expanded.append(child_group)
        seen_keys.add(child_key)
        queue.append(child_group)  # allow deeper nesting if the child is already selected

    expanded.sort(key=lambda g: (len(g["key"].split("/")), g["key"]))
    return expanded




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


def map_existing_bio_selections(all_groups, entry_list):
    """
    Maps previously selected biographies to their full group key.

    Args:
        all_groups (list): list of group dicts with at least "key"
        entry_list (list): list of entry dicts from bio_data["entries"][...][type_name]

    Returns:
        dict: e.g., {"work_building/hospital_bio": biography_id,
                     "work_building/hospital_bio_conf": confidence}
    """
    # Build a map from leaf -> full key(s)
    leaf_to_keys = {}
    for g in all_groups:
        leaf = g["key"].split("/")[-1]
        leaf_to_keys.setdefault(leaf, []).append(g["key"])

    selections = {}
    for entry in entry_list:
        lt = entry.get("label_type")
        if not lt or not entry.get("biography"):
            continue
        if lt in leaf_to_keys:
            for full_key in leaf_to_keys[lt]:
                selections[f"{full_key}_bio"] = entry["biography"]
                selections[f"{full_key}_bio_conf"] = entry.get("biography_confidence", 100)
    return selections


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