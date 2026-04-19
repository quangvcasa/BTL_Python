from datetime import datetime, timedelta

def get_vn_time():
    """Returns the current Vietnam time as a naive datetime object."""
    # Vietnam is UTC+7 and does not observe Daylight Saving Time.
    return datetime.utcnow() + timedelta(hours=7)
