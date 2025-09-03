CSC7058 Project: Biography Builder Tool

This project enables users to build structured, timeline-based biographies using real data, metadata, and AI-enhanced workflows. It is part of a Master’s project for CSC7058 - MSc Software Development at Queen’s University Belfast.

⸻

💡 Key Features
	•	Partial name search for fast biography lookup
	•	Label-based filtering (occupation, location, relationships, etc.)
	•	Confidence intervals for all selections
	•	Folder-based taxonomy structure (labels + biographies)
	•	Nested labels and smart biography suggestions
	•	Flexible label creation and ingest:
	•	Manual creation of labels with metadata and properties
	•	GPT-powered natural language ingest: users phrase queries in plain English (e.g. “Add famous hospitals in London”), which are converted into structured API queries; results appear as suggested labels for review before saving
	•	External dataset linkage: integration with APIs such as Wikidata (SPARQL) or REST endpoints allows labels to be drawn directly from authoritative sources
	•	“Most-like” functionality: compare biographies to find the closest matches, with similarity scores based on overlapping labels and confidence intervals, and rationale chips explaining why entities align or diverge
	•	Relationship-based person linking with confidence scoring
	•	Manual editing and entry support
	•	Archive and restore functionality
	•	Consistent, type-agnostic design (works for people, buildings, organisations, events)

⸻

🧪 Demo Example

Includes a working example using Florence Nightingale to demonstrate structured life modelling across multiple time periods, with linked buildings, organisations, and people. The demo also illustrates AI-assisted ingest and external dataset linkage to enrich biographies with context beyond manually entered events.

⸻

🛠️ How to Run Locally
	1.	Clone the repository
	2.	Create a virtual environment (e.g. python3 -m venv venv39)
	3.	Activate the environment:
	•	macOS/Linux: source venv39/bin/activate
	•	Windows: venv39\Scripts\activate
	4.	Install dependencies:

pip install -r requirements.txt


	5.	Launch the app:

python general.py


	6.	Open your browser at http://127.0.0.1:5000

⸻

🧪 Testing

Automated tests are provided in the tests/ folder, using pytest. These validate key API endpoints (e.g. /api/type/person/labels.json) and ensure JSON responses include expected fields such as ok flags and non-empty label arrays.

To run all tests:

pytest -q

Tests use Flask’s test_client so they run fully locally without requiring the app to be deployed to a live server.

⸻

📁 Project Structure
	•	general.py – Main Flask app and route logic
	•	types/ – Organised by type (e.g. person, building, organisation), each with labels/ and biographies/ subfolders
	•	templates/ – Jinja2 HTML templates (multi-step wizard + viewer)
	•	static/ – CSS styles and JavaScript assets
	•	tests/ – Pytest suite for API endpoints and core functions
	•	utils/ – Helper functions (label parsing, ingest, similarity metrics, etc.)
	•	.vscode/ – Local development config (ignored by Git)
	•	venv39/ – Virtual environment (ignored by Git)

⸻

⚙️ Dependencies

See requirements.txt for the full list.

Notable libraries:
	•	Flask (web framework + Jinja2 templating)
	•	Requests / HTTPX (API integration)
	•	OpenAI Python SDK (LLM-assisted label suggestions & ingest)
	•	Pytest (automated testing)

⸻

📄 License

This project is for academic use only under Queen’s University Belfast MSc Software Development (CSC7058).
