import re

with open('app/models.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add import if missing
if 'from flask import url_for' not in content:
    content = content.replace('from app import db\n', 'from app import db\nfrom flask import url_for\n')

# Find instances of: link = f"/commitments/{item.commitment_id}"
# and link = f"/commitments/{commitment.id}"
content = re.sub(
    r'link = f\"/commitments/\{([a-zA-Z0-9_\.]+)\}\"',
    r"link = url_for('commitments_detail', commitment_id=\1, _external=False)",
    content
)

with open('app/models.py', 'w', encoding='utf-8') as f:
    f.write(content)
