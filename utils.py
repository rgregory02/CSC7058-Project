import os
import json
from datetime import datetime
from openai import OpenAI
import os
import glob

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
    Suggest biography options per group that links to another type.

    Preferred signature:
        build_suggested_biographies(current_type, label_groups_list, label_base_path, existing_labels=None)

    Back-compat:
        build_suggested_biographies(current_type, label_groups_list, label_base_path)
        build_suggested_biographies(label_groups_list, label_base_path)

    Returns: { safe_group_key: [ {id, display, description?}, ... ] }
    """
    # ---- arg normalisation ----
    current_type = None
    label_groups_list = None
    label_base_path = None
    existing_labels = None

    if "current_type" in kwargs:
        current_type       = kwargs.get("current_type")
        label_groups_list  = kwargs.get("label_groups_list")
        label_base_path    = kwargs.get("label_base_path")
        existing_labels    = kwargs.get("existing_labels")
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

    out = {}

    for g in label_groups_list:
        key = g.get("key")
        if not key:
            continue
        safe = key.replace("/", "__")

        bios = []

        # ---- Case A: property JSON provides link_biography (the “parent-label → child-bios” pattern) ----
        lb = g.get("link_biography")
        if isinstance(lb, dict) and lb.get("type"):
            lb_type  = lb["type"]
            lb_path  = (lb.get("path") or "").strip("/")        # e.g. "work_building"
            lb_mode  = (lb.get("mode") or "child_or_parent")    # "child_only" | "parent_only" | "child_or_parent"

            # Which parent option is currently selected for this group?
            sel = existing_labels.get(key) or {}
            # tolerate either {"label": "hospital"} or bare string "hospital" (older callers)
            if isinstance(sel, str):
                selected_label_id = sel
            else:
                selected_label_id = sel.get("label") or sel.get("id")

            base_bios_dir = os.path.join("types", lb_type, "biographies")
            if not os.path.isdir(base_bios_dir):
                out[safe] = []
                continue

            # Prefer child folder when a parent label is selected
            if selected_label_id and lb_mode in ("child_only", "child_or_parent"):
                child_dir = os.path.join(base_bios_dir, lb_path, selected_label_id) if lb_path else os.path.join(base_bios_dir, selected_label_id)
                if os.path.isdir(child_dir):
                    for f in os.listdir(child_dir):
                        if f.endswith(".json"):
                            data = load_json_safely(os.path.join(child_dir, f))
                            bid  = os.path.splitext(f)[0]
                            bios.append({
                                "id": bid,
                                "display": data.get("name", bid.replace("_"," ").title()),
                                "description": data.get("description", "")
                            })

            # If nothing found (or mode allows), show parent-level matches as a fallback
            if (not bios) and lb_mode in ("parent_only", "child_or_parent"):
                parent_dir = os.path.join(base_bios_dir, lb_path) if lb_path else base_bios_dir
                if os.path.isdir(parent_dir):
                    for root, _, files in os.walk(parent_dir):
                        for f in files:
                            if not f.endswith(".json"):
                                continue
                            # Heuristic: only include files/folders that hint the selected label
                            if selected_label_id and (selected_label_id not in root) and (os.path.splitext(f)[0] != selected_label_id):
                                continue
                            data = load_json_safely(os.path.join(root, f))
                            bid  = os.path.splitext(f)[0]
                            bios.append({
                                "id": bid,
                                "display": data.get("name", bid.replace("_"," ").title()),
                                "description": data.get("description", "")
                            })

        # ---- Case B: refer_to points straight to another type's biographies (list them) ----
        elif g.get("refer_to", {}).get("source") == "biographies":
            r = g["refer_to"]
            r_type = r.get("type")
            r_path = (r.get("path") or "").strip("/")
            base = os.path.join("types", r_type, "biographies")
            scan = os.path.join(base, r_path) if r_path else base
            if os.path.isdir(scan):
                for root, _, files in os.walk(scan):
                    for f in files:
                        if not f.endswith(".json"):
                            continue
                        data = load_json_safely(os.path.join(root, f))
                        bid  = os.path.splitext(f)[0]
                        bios.append({
                            "id": bid,
                            "display": data.get("name", bid.replace("_"," ").title()),
                            "description": data.get("description", "")
                        })

        if bios:
            out[safe] = bios

    return out




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
    Build UI groups *from property JSON files* in types/<type>/labels,
    and fall back to legacy "subfolder = group, files = options" if no property JSON exists.

    Group shape:
    {
      "key": "work_place",
      "label": "Work place",
      "description": "...",
      "options": [ { id, display, description, image? } ... ],
      # Hints for cross‑type pulls:
      "refer_to": { "type": "...", "source": "labels"|"biographies", "path": "...", "allow_children": true },
      "link_biography": { "type": "...", "path": "...", "mode": "child_or_parent" }
    }
    """
    groups = []
    if not os.path.isdir(label_base_path):
        return groups

    # -------- helpers --------
    IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

    def load_json_safely(p):
        try:
            return load_json_as_dict(p)
        except Exception as e:
            print(f"[WARN] Could not parse JSON: {p} -> {e}")
            return {}

    def build_option_from_file(json_path: str, url_base_prefix: str = "/types"):
        """Legacy subfolder option loader (kept for backward-compat)."""
        data = load_json_safely(json_path)
        base = os.path.splitext(os.path.basename(json_path))[0]
        name = data.get("properties", {}).get("name") or data.get("name") or base
        desc = data.get("description", data.get("properties", {}).get("description", ""))

        # best‑effort sibling image
        image_url = None
        folder = os.path.dirname(json_path)
        for ext in IMAGE_EXTS:
            candidate = os.path.join(folder, base + ext)
            if os.path.exists(candidate):
                rel = os.path.relpath(candidate, ".").replace("\\", "/")
                image_url = f"{url_base_prefix}/{rel.split('/', 1)[1]}" if rel.startswith("types/") else f"/{rel}"
                break

        opt = {"id": base, "display": name, "description": desc}
        if image_url:
            # support both keys (templates sometimes use item.image)
            opt["image"] = image_url
            opt["image_url"] = image_url
        return opt

    def extract_source(meta: dict):
        """Read `source` from top-level or properties.* and normalise."""
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
            return { "type": src.get("type"), "source": "biographies" }
        return None

    def extract_link_bio(meta: dict):
        """Read link_biography from top-level or properties.* and normalise."""
        lb = (meta or {}).get("link_biography") or (meta or {}).get("properties", {}).get("link_biography") or {}
        if not isinstance(lb, dict) or not lb.get("type"):
            return None
        return {
            "type": lb.get("type"),
            "path": lb.get("path", ""),
            "mode": (lb.get("mode") or "child_or_parent")
        }

    # -------- 1) Property JSONs at the TOP LEVEL (property‑first) --------
    top_level_jsons = [
        f for f in os.listdir(label_base_path)
        if f.endswith(".json") and os.path.isfile(os.path.join(label_base_path, f))
    ]

    for jf in sorted(top_level_jsons):
        prop_key  = os.path.splitext(jf)[0]                       # e.g. "work_place"
        prop_path = os.path.join(label_base_path, jf)
        meta = load_json_safely(prop_path)

        # If the file is not an object, handle gracefully
        if not isinstance(meta, dict):
            print(f"[WARN] Property JSON is not an object (converting if list): {prop_path} -> {type(meta).__name__}")
            # If it's a simple list, expose it as a basic group of options
            if isinstance(meta, list):
                opts = []
                for item in meta:
                    if isinstance(item, str):
                        opts.append({"id": item, "display": item})
                    elif isinstance(item, dict):
                        iid  = item.get("id") or item.get("key") or item.get("value")
                        name = item.get("display") or item.get("name") or iid
                        if iid:
                            opt = {"id": iid, "display": name or iid}
                            if "description" in item:
                                opt["description"] = item["description"]
                            # optional image fields users might include
                            img = item.get("image") or item.get("image_url")
                            if img:
                                opt["image"] = img
                                opt["image_url"] = img
                            opts.append(opt)
                if opts:
                    groups.append({
                        "key": prop_key,
                        "label": prop_key.replace("_", " ").title(),
                        "description": "",
                        "options": opts
                    })
            # skip to next file
            continue

        # derive presentation
        prop_name = meta.get("name") or meta.get("properties", {}).get("name") or prop_key.replace("_", " ").title()
        prop_desc = meta.get("description") or meta.get("properties", {}).get("description", "")

        # discover options via your resolver (folder | type_labels | type_biographies | none)
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

        group_obj = {
            "key": prop_key,
            "label": prop_name,
            "description": prop_desc,
            "options": options
        }
        if refer_to:
            group_obj["refer_to"] = refer_to
        if link_bio:
            group_obj["link_biography"] = link_bio

        groups.append(group_obj)

    # -------- 2) Legacy fallback: subfolders that do NOT have a matching top‑level property JSON --------
    for entry in sorted(os.listdir(label_base_path)):
        full = os.path.join(label_base_path, entry)
        if not os.path.isdir(full):
            continue

        subkey = entry  # e.g. "hair_color"
        if f"{subkey}.json" in top_level_jsons:
            continue  # already covered by property JSON

        group_label = subkey.replace("_", " ").title()
        group_desc = ""
        refer_to = None
        link_bio = None

        # Optional _group.json inside the folder for meta
        meta_path = os.path.join(full, "_group.json")
        if os.path.exists(meta_path):
            meta = load_json_safely(meta_path)
            if isinstance(meta, dict):
                group_label = meta.get("name") or meta.get("properties", {}).get("name") or group_label
                group_desc  = meta.get("description") or meta.get("properties", {}).get("description", "") or ""
                refer_to    = extract_source(meta)
                link_bio    = extract_link_bio(meta)
            else:
                print(f"[WARN] _group.json is not an object: {meta_path}")

        # Collect options from *.json files in the subfolder
        opts = []
        for f in sorted(os.listdir(full)):
            if not f.endswith(".json") or f == "_group.json":
                continue
            opts.append(build_option_from_file(os.path.join(full, f)))

        group_obj = {
            "key": subkey,
            "label": group_label,
            "description": group_desc,
            "options": opts
        }
        if refer_to:
            group_obj["refer_to"] = refer_to
        if link_bio:
            group_obj["link_biography"] = link_bio

        groups.append(group_obj)

    groups.sort(key=lambda g: g.get("key", ""))
    return groups



def expand_child_groups(base_groups, current_type, label_base_path, existing_labels):
    """
    Recursively expand groups when a selected option has a matching child subfolder.

    Example:
      - Group key "work_building" with selected id "hospital"
      - If folder exists: types/<type>/labels/work_building/hospital/
        -> add a new group with key "work_building/hospital"
      - If the user has already selected e.g. "royal_victoria" in that child group
        AND a deeper folder exists (work_building/hospital/royal_victoria/),
        this function will keep expanding.

    Arguments:
      base_groups:      list from collect_label_groups(...)
      current_type:     the type name (e.g. "person")
      label_base_path:  path like "types/<type>/labels"
      existing_labels:  dict of previously selected labels for the current entry,
                        shaped like { "work_building": {"id":"hospital", ...},
                                      "work_building/hospital": {"id":"royal_victoria", ...} }

    Returns:
      A new list including all original groups plus any recursively discovered child groups.
    """
    import os
    import json

    IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

    def _safe_json(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] expand_child_groups: failed to parse {path}: {e}")
            return {}

    def _image_for(base_dir, base_name):
        for ext in IMAGE_EXTS:
            p = os.path.join(base_dir, base_name + ext)
            if os.path.exists(p):
                # build a web path like /types/<type>/labels/…/file.ext
                rel = os.path.relpath(p, ".").replace("\\", "/")
                return "/" + rel
        return None

    def _load_options_from_folder(folder_abs_path):
        """Load *.json in a folder as options (name/description/image if present)."""
        opts = []
        if not os.path.isdir(folder_abs_path):
            return opts
        for fn in sorted(os.listdir(folder_abs_path)):
            if not fn.endswith(".json"):
                continue
            base = os.path.splitext(fn)[0]
            data = _safe_json(os.path.join(folder_abs_path, fn))
            name = (
                data.get("properties", {}).get("name")
                or data.get("name")
                or base.replace("_", " ").title()
            )
            desc = data.get("description", data.get("properties", {}).get("description", ""))
            img = _image_for(folder_abs_path, base)

            opt = {"id": base, "display": name}
            if desc:
                opt["description"] = desc
            if img:
                opt["image_url"] = img
            opts.append(opt)
        return opts

    # We’ll loop until no more child groups can be added (supports multi-level).
    expanded = list(base_groups)
    seen_keys = {g["key"] for g in expanded}

    changed = True
    while changed:
        changed = False

        # Iterate over a snapshot because we may append during the loop
        for group in list(expanded):
            group_key = group["key"]  # e.g. "work_building" or "work_building/hospital"
            sel = existing_labels.get(group_key) or {}
            selected_id = sel.get("id") or sel.get("label")
            if not selected_id:
                continue

            # Resolve filesystem path to this group's folder
            # group_key may be nested -> split
            group_folder = os.path.join(label_base_path, *group_key.split("/"))
            if not os.path.isdir(group_folder):
                continue

            # Child folder must be named exactly as selected_id
            child_folder = os.path.join(group_folder, selected_id)
            if not os.path.isdir(child_folder):
                continue

            child_key = f"{group_key}/{selected_id}"
            if child_key in seen_keys:
                # Already added
                continue

            # Load this child folder as a new group
            child_options = _load_options_from_folder(child_folder)
            if not child_options:
                continue

            new_group = {
                "key": child_key,
                "label": f"{group.get('label','').strip() or group_key.replace('_',' ').title()} → {selected_id.replace('_',' ').title()}",
                "description": f"Options for {selected_id.replace('_',' ').title()}",
                "options": child_options,
            }
            expanded.append(new_group)
            seen_keys.add(child_key)
            changed = True

    # Keep ordering stable-ish: parent keys first, then deeper ones
    expanded.sort(key=lambda g: (g["key"].count("/"), g["key"]))
    return expanded


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