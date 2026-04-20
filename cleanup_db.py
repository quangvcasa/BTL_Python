import sys
import os

from app import app, db
from app.models import Commitment, ExecutionItem, ExecutionItemUpdate, Notification, ActivityLog, commitment_collaborators

def cleanup_db():
    with app.app_context():
        print("Starting cleanup...")
        
        # Criteria
        junk_keywords = ['test', 'aaaa', 'abc', 'junk', '1234']
        
        commitments = Commitment.query.all()
        deleted_count = 0
        
        for c in commitments:
            title_lower = c.title.lower()
            if any(kw in title_lower for kw in junk_keywords):
                print(f"Deleting: [{c.code}] {c.title}")
                
                for item in c.execution_items:
                    ExecutionItemUpdate.query.filter_by(execution_item_id=item.id).delete()
                    db.session.delete(item)
                    
                Notification.query.filter(Notification.link.like(f"%/commitments/detail/{c.id}%")).delete(synchronize_session=False)
                
                ActivityLog.query.filter_by(entity_type='Commitment', entity_id=c.id).delete(synchronize_session=False)
                ActivityLog.query.filter_by(entity_type='ExecutionItem', entity_id=c.id).delete(synchronize_session=False)

                db.session.execute(commitment_collaborators.delete().where(commitment_collaborators.c.commitment_id == c.id))

                db.session.delete(c)
                deleted_count += 1
                
        if deleted_count > 0:
            db.session.commit()
            print(f"Done! Deleted {deleted_count} junk commitments.")
        else:
            print("No junk commitments found.")

if __name__ == '__main__':
    cleanup_db()
