import os
import json
from datetime import datetime

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

def collect_label_groups(label_base_path, current_type):
    label_groups_list = []

    for root, _, files in os.walk(label_base_path):
        rel_path = os.path.relpath(root, label_base_path)
        if rel_path == ".":
            continue  # Skip root

        values = []
        for file in files:
            if not file.endswith(".json"):
                continue
            base = file[:-5]
            json_path = os.path.join(root, file)
            img_path = os.path.join(root, f"{base}.jpg")

            try:
                data = load_json_as_dict(json_path)
                label = {
                    "id": base,
                    "display": data.get("properties", {}).get("name", base),
                    "label_type": rel_path  # e.g. work_building/hospital
                }
                if os.path.exists(img_path):
                    label["image"] = f"/types/{current_type}/labels/{rel_path}/{base}.jpg"
                if "description" in data:
                    label["description"] = data["description"]
                values.append(label)
            except Exception as e:
                print(f"[ERROR] Reading nested label {file}: {e}")

        # ✅ Always add the group — even if values is empty
        label_groups_list.append({
            "key": rel_path,
            "label": os.path.basename(root).replace("_", " ").title(),
            "options": values
        })

    return label_groups_list