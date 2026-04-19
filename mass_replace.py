import os

def replace_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content.replace("from models import ", "from app.models import ")
    new_content = new_content.replace("from utils import ", "from app.utils import ")
    new_content = new_content.replace("from auth import ", "from app.auth import ")
    new_content = new_content.replace("from csrf_utils import ", "from app.csrf_utils import ")
    new_content = new_content.replace("from _hook_recalc import ", "from app._hook_recalc import ")
    
    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {filepath}")

for root, _, files in os.walk('.'):
    if 'venv' in root or '__pycache__' in root or '.git' in root:
        continue
    for file in files:
        if file.endswith('.py') and file != 'mass_replace.py':
            replace_in_file(os.path.join(root, file))
