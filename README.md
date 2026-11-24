# TechSearch

TechSearch is a local search engine for web-development documentation from MDN and answers from Stack Overflow. Use Search to look things up. Use IR Lab to compare search methods and explore experiments.

## Requirements

- Python 3.11 or 3.12
- Git
- Internet access for initial setup
- A web browser

You can use the included data without an API key.

## Download the project

1. Open [TechSearch on GitHub](https://github.com/kiran-8287/search-engine) and click **Fork**.
2. Open a terminal and run the commands below. Replace `YOUR_GITHUB_USERNAME` with your GitHub username.

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/search-engine.git
cd search-engine
```

## Set up and run

Run these commands from the `search-engine` folder. The clone includes `mdn_documents.json` and `stackoverflow_documents.json`. You can build from these files without downloading data separately.

### Windows PowerShell

```powershell
py -3.12 scripts/bootstrap.py
.\.venv\Scripts\Activate.ps1
```

### Linux or macOS

```bash
python3.12 scripts/bootstrap.py
source .venv/bin/activate
```

For Python 3.11, use `py -3.11` on Windows or `python3.11` on Linux or macOS. If PowerShell blocks activation or cannot find `py`, see the [setup help](docs/PROJECT_CONTEXT.md#troubleshooting).

### Build and open the app

Run these commands in the same terminal after activating the environment.

```bash
python -m techsearch inspect-data
python -m techsearch download-model
python -m techsearch preprocess
python -m techsearch build-indexes
python scripts/start.py --host localhost --port 8000
```

The first model download and index build can take time. Preprocessing and indexing are part of the initial setup. Run them again when you change the data.

Open the app in your browser.

- [Search](http://localhost:8000/)
- [IR Lab](http://localhost:8000/lab)

Keep the terminal open while you use the app. Press **Ctrl+C** in that terminal to stop the server.

## Start again later

In a new terminal, go to the `search-engine` folder and run the commands for your system.

**Windows PowerShell**

```powershell
.\.venv\Scripts\Activate.ps1
python scripts/start.py --host localhost --port 8000
```

**Linux or macOS**

```bash
source .venv/bin/activate
python scripts/start.py --host localhost --port 8000
```

## Optional: collect fresh data

To collect Stack Overflow data, set `STACKEXCHANGE_API_KEY` in your local `.env` file. Run the collectors from the project environment.

```bash
python -m techsearch collect --source mdn
python -m techsearch collect --source stackoverflow --target 5000 --resume
```

The collectors save `data/raw/mdn_documents.json` and `data/raw/stackoverflow_documents.json`. After changing the data, run `python -m techsearch preprocess` and `python -m techsearch build-indexes` again. See the [collection guide](docs/PROJECT_CONTEXT.md#collect-from-sources) for saved progress and API limits.

## Learn more

- Filter results by source or topic and open **Preview** to see an excerpt.
- Compare keyword, semantic, and hybrid search in IR Lab.
- Read the [IR Lab guide](docs/IR_LAB.md), [data dictionary](docs/DATA_DICTIONARY.md), or [demo run sheet](docs/DEMO_RUN_SHEET.md).
- For more options, see [detailed setup and troubleshooting](docs/PROJECT_CONTEXT.md#detailed-setup). Find source licenses in [Attribution](docs/ATTRIBUTION.md).

To run unit and integration tests, use the project environment.

```bash
python -m pytest tests/unit tests/integration
```
