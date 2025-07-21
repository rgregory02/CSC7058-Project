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