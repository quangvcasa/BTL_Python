# PTIT Lab Progress (Flask)

A Flask application for managing lab progress and commitments using Flask + SQLite.

## Prerequisites

- Python 3.10+ (recommended Python 3.13)
- Git (optional)
- Windows / Linux / Mac

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/vduckj3n/github-demo-btl-py.git
   cd github-demo-btl-py
   ```

2. Create and activate the virtual environment:

   On Windows (PowerShell):
   ```powershell
   py -3.13 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   On Windows (Command Prompt):
   ```cmd
   py -3.13 -m venv .venv
   .venv\Scripts\activate.bat
   ```

   On macOS / Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

The database and default admin user will be created automatically on first run.

### Option 1: Run directly with Python

```bash
python app.py
```

### Option 2: Run with Flask CLI

On Windows PowerShell:
```powershell
$env:FLASK_APP = 'app.py'
$env:FLASK_ENV = 'development'
flask run --host=0.0.0.0 --port=5000
```

On Windows Command Prompt:
```cmd
set FLASK_APP=app.py
set FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000
```

On macOS / Linux:
```bash
export FLASK_APP=app.py
export FLASK_ENV=development
flask run --host=0.0.0.0 --port=5000
```

Open the app in your browser at:

```
http://127.0.0.1:5000/
```

## Default Credentials

- Admin username: `admin`
- Admin password: `admin123`

> If the default admin user is not created automatically, run the app once and check the `instance/` database file.

## Useful Commands

- Install/update dependencies:
  ```bash
  pip install -r requirements.txt
  ```

- Run the app:
  ```bash
  python app.py
  ```

- Run database or migration helpers if needed:
  ```bash
  python app.py
  ```

## Configuration

- `config.py` contains app settings:
  - `SECRET_KEY`
  - `SQLALCHEMY_DATABASE_URI` (default SQLite file: `instance/ptit_lab_progress.db`)
  - `UPLOAD_FOLDER` (default `uploads/`)

## Project Structure

- `app.py` — Main application and routes
- `models.py` — Database models
- `config.py` — App configuration
- `templates/` — HTML templates
- `static/` — CSS and JavaScript files
- `instance/` — SQLite database file
- `uploads/` — Uploaded files

## Notes

- Make sure your virtual environment is activated before running any commands.
- If you see a font issue in generated PDF, install `reportlab` via `pip install reportlab`.
- Use `py -3.13` or `python` pointing to the same Python interpreter used for the virtualenv.
