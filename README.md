# CSC7058 Project: Biography Builder Tool

This project enables users to build structured life biographies using real data, metadata, and AI-enhanced workflows. It is part of a Master's project for CSC7058 – MSc Software Development.

## 💡 Key Features

- Partial name search for fast biography lookup  
- Label-based filtering (e.g. occupation, location, relationships)  
- Confidence intervals for all selections  
- Folder-based taxonomy structure (labels + biographies)  
- Nested labels and smart biography suggestions  
- GPT-powered label suggestions from free-text prompts  
- Relationship-based person linking with confidence  
- Manual editing and entry support  
- Archive and restore functionality  

## 🧪 Demo Example

Includes a working example using **Florence Nightingale** to demonstrate structured life modelling across multiple time periods, with linked buildings, organisations, and people.

## 🛠️ How to Run Locally

1. Clone the repository  
2. Create a virtual environment (e.g. `python3 -m venv venv39`)  
3. Activate the environment:  
   - macOS/Linux: `source venv39/bin/activate`  
   - Windows: `venv39\Scripts\activate`  
4. Install dependencies:  
   ```bash
   pip install -r requirements.txt
   ```
5. Launch the app:  
   ```bash
   python main.py
   ```
6. Open your browser at [http://127.0.0.1:5000](http://127.0.0.1:5000)

## 📁 Project Structure

- `main.py` – Main Flask app and route logic  
- `types/` – Organised by type (e.g. person, building, organisation), each with `labels/` and `biographies/` subfolders  
- `static/` – CSS styles and client-side assets  
- `templates/` – Jinja2 HTML templates for the multi-step wizard  
- `utils/` – Helper functions for label parsing, AI integration, and file management  
- `.vscode/` – Local development config (excluded via `.gitignore`)  
- `venv39/` – Your virtual environment (excluded from Git)  

## ⚙️ Dependencies

See `requirements.txt` for the full list. Notable libraries:
- Flask  
- Jinja2  
- Requests  
- OpenAI Python SDK  

## 📄 License

This project is for academic use only under Queen's University Belfast MSc Software Development (CSC7058).