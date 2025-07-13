# CSC7058 Project: Biography Builder Tool

This project enables users to build structured life biographies using real data and metadata. It is part of a Master's project for CSC7058 – MSc Software Development.

## 💡 Key Features

- Partial search for biographies by name  
- Label-based filtering (e.g. occupation, location, tags)  
- Confidence intervals and source metadata  
- Extensible structure using folder-based taxonomies  
- Manual entry and editing support

## 🧪 Demo Example

Includes a working example using Florence Nightingale to demonstrate multi-phase life modelling with structured labels.

## 🛠️ How to Run Locally

1. Clone the repository  
2. Create a virtual environment (`venv39` or similar)  
3. Run `pip install -r requirements.txt`  
4. Launch the app with `python main.py`  
5. Open your browser at [http://127.0.0.1:5000](http://127.0.0.1:5000)  

> ℹ️ Note: The app may run on `localhost:5001` instead of the default 5000 if set manually.

## 📁 Project Structure

- `main.py`: Main Flask app  
- `types/`: JSON-based biographies by category  
- `static/`: Styles and UI assets  
- `templates/`: Jinja2 HTML templates  
- `.vscode/`: Local development config (not committed)  
- `venv39/`: Your virtual environment (excluded via `.gitignore`)

## 📄 License

This project is for academic use only.