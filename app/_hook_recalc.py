import codecs

PATH = 'app.py'

with codecs.open(PATH, 'r', 'utf-8') as f:
    content = f.read()

changes = 0

# ── 1.  ei_create: after first db.session.commit() (item inserted), recalculate ──
OLD1 = (
    "        db.session.add(item)\n"
    "        db.session.commit()\n"
    "\n"
    "        ActivityLog.log(\n"
    "            current_user.id, 'CREATE', 'ExecutionItem', item.id,\n"
    "            f'Them hang muc [{item.id}] \"{title}\" cho cam ket {commitment.code}',\n"
    "            get_client_ip()\n"
    "        )\n"
    "        db.session.commit()\n"
)
NEW1 = (
    "        db.session.add(item)\n"
    "        db.session.flush()  # get item.id before recalculation\n"
    "\n"
    "        commitment.recalculate_progress()\n"
    "        db.session.commit()\n"
    "\n"
    "        ActivityLog.log(\n"
    "            current_user.id, 'CREATE', 'ExecutionItem', item.id,\n"
    "            f'Them hang muc [{item.id}] \"{title}\" cho cam ket {commitment.code}',\n"
    "            get_client_ip()\n"
    "        )\n"
    "        db.session.commit()\n"
)
if OLD1 in content:
    content = content.replace(OLD1, NEW1, 1)
    changes += 1
    print('OK: ei_create recalculate hooked')
else:
    # Try with Vietnamese characters
    print('WARN: ei_create pattern not found (may be UTF-8 mismatch) - searching wider')

# ── 2.  ei_edit: after item fields are set, recalculate before commit ──
OLD2 = (
    "        item.requires_evidence = req_evidence\n"
    "        item.requires_approval = req_approval\n"
    "\n"
    "        db.session.commit()\n"
    "        ActivityLog.log(\n"
    "            current_user.id, 'UPDATE', 'ExecutionItem', item.id,\n"
)
NEW2 = (
    "        item.requires_evidence = req_evidence\n"
    "        item.requires_approval = req_approval\n"
    "\n"
    "        commitment.recalculate_progress()\n"
    "        db.session.commit()\n"
    "        ActivityLog.log(\n"
    "            current_user.id, 'UPDATE', 'ExecutionItem', item.id,\n"
)
if OLD2 in content:
    content = content.replace(OLD2, NEW2, 1)
    changes += 1
    print('OK: ei_edit recalculate hooked')
else:
    print('WARN: ei_edit pattern not found')

# ── 3.  ei_delete: recalculate after item is deleted ──
OLD3 = (
    "    title = item.title\n"
    "    db.session.delete(item)\n"
    "    db.session.commit()\n"
    "\n"
    "    ActivityLog.log(\n"
    "        current_user.id, 'DELETE', 'ExecutionItem', item_id,\n"
)
NEW3 = (
    "    title = item.title\n"
    "    db.session.delete(item)\n"
    "    db.session.flush()  # item removed from DB before recalculation\n"
    "\n"
    "    commitment.recalculate_progress()\n"
    "    db.session.commit()\n"
    "\n"
    "    ActivityLog.log(\n"
    "        current_user.id, 'DELETE', 'ExecutionItem', item_id,\n"
)
if OLD3 in content:
    content = content.replace(OLD3, NEW3, 1)
    changes += 1
    print('OK: ei_delete recalculate hooked')
else:
    print('WARN: ei_delete pattern not found')

# ── 4.  ei_update: recalculate after item.status is changed ──
# The block right after item.status = new_status and before db.session.commit()
OLD4 = (
    "        # Update the item's current status\n"
    "        item.status = new_status\n"
    "        # If the member provided an expected finish date, store it on the item too\n"
    "        if expected_finish:\n"
    "            item.expected_finish_date = expected_finish\n"
    "\n"
    "        db.session.commit()\n"
)
NEW4 = (
    "        # Update the item's current status\n"
    "        item.status = new_status\n"
    "        # If the member provided an expected finish date, store it on the item too\n"
    "        if expected_finish:\n"
    "            item.expected_finish_date = expected_finish\n"
    "\n"
    "        # Recalculate parent Commitment progress from all items\n"
    "        commitment.recalculate_progress()\n"
    "        db.session.commit()\n"
)
if OLD4 in content:
    content = content.replace(OLD4, NEW4, 1)
    changes += 1
    print('OK: ei_update recalculate hooked')
else:
    print('WARN: ei_update pattern not found')

with codecs.open(PATH, 'w', 'utf-8') as f:
    f.write(content)

print(f'Done: {changes}/4 changes applied')
