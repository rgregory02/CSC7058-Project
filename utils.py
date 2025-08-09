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


def collect_label_groups(label_base_path, current_type):
    """
    Build a list of label groups from a type's labels folder.

    Each group looks like:
      {
        "key": "workplace/office",
        "label": "Office",
        "options": [
          {"id":"royal_victoria_hospital","display":"Royal Victoria Hospital","description":"...","image":"/types/.../labels/.../royal_victoria_hospital.jpg"}
        ],
        # Optional – when present, UI should pull options from another type's biographies
        "refer_to": {"type": "building", "source": "biographies"}
      }
    """
    label_groups_list = []
    if not os.path.isdir(label_base_path):
        return label_groups_list

    IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]

    for root, _, files in os.walk(label_base_path):
        rel_path = os.path.relpath(root, label_base_path)
        if rel_path == ".":
            # Skip the root container; groups are subfolders
            continue

        # Defaults (can be overridden by _group.json or any file's properties)
        group_key = rel_path.replace("\\", "/")
        group_label = os.path.basename(root).replace("_", " ").title()
        group_description = ""
        group_refer_to = None  # {"type": "...", "source":"biographies"}

        # Look for a group meta file
        group_meta_path = os.path.join(root, "_group.json")
        if os.path.exists(group_meta_path):
            try:
                meta = load_json_as_dict(group_meta_path)
                # Name can live at top-level or under properties.name
                group_label = (
                    meta.get("name")
                    or meta.get("properties", {}).get("name")
                    or group_label
                )
                group_description = (
                    meta.get("description")
                    or meta.get("properties", {}).get("description", "")
                )
                rt = meta.get("properties", {}).get("refer_to")
                if isinstance(rt, dict) and rt.get("type"):
                    group_refer_to = {
                        "type": rt.get("type"),
                        "source": rt.get("source", "biographies")
                    }
            except Exception as e:
                print(f"[WARN] Failed to read group meta {group_meta_path}: {e}")

        # Collect options (for normal groups; if refer_to is set the UI may ignore these)
        options = []

        for file in files:
            if not file.endswith(".json"):
                continue
            if file == "_group.json":
                continue

            base = file[:-5]
            json_path = os.path.join(root, file)

            # Resolve a thumbnail if any
            image_url = None
            for ext in IMAGE_EXTS:
                candidate = os.path.join(root, base + ext)
                if os.path.exists(candidate):
                    image_url = f"/types/{current_type}/labels/{group_key}/{base}{ext}"
                    break

            try:
                data = load_json_as_dict(json_path)

                # If any file announces refer_to and we don't already have one from _group.json, adopt it
                props = data.get("properties", {})
                rt = props.get("refer_to")
                if group_refer_to is None and isinstance(rt, dict) and rt.get("type"):
                    group_refer_to = {
                        "type": rt.get("type"),
                        "source": rt.get("source", "biographies")
                    }

                display = (
                    props.get("name")
                    or data.get("name")
                    or base
                )
                description = data.get("description", props.get("description", ""))
                order_val = data.get("order", props.get("order", 999))

                label_obj = {
                    "id": base,
                    "display": display,
                    "label_type": group_key,  # keep your original shape
                    "description": description,
                    "order": order_val
                }
                if image_url:
                    label_obj["image"] = image_url

                options.append(label_obj)

            except Exception as e:
                print(f"[ERROR] Reading label {json_path}: {e}")

        # Sort options by order then display
        options.sort(key=lambda o: (o.get("order", 999), o.get("display", "").lower()))

        # Always add the group, even if empty (keeps UI consistent)
        group_entry = {
            "key": group_key,
            "label": group_label,
            "options": options
        }
        if group_description:
            group_entry["description"] = group_description
        if group_refer_to:
            group_entry["refer_to"] = group_refer_to

        label_groups_list.append(group_entry)

    # Stable ordering by key
    label_groups_list.sort(key=lambda g: g["key"])
    return label_groups_list


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