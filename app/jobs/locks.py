from threading import Lock
_guard=Lock()
_locks={}
def document_lock(doc_id):
    with _guard:
        return _locks.setdefault(doc_id,Lock())
