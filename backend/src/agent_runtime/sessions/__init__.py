"""Chat sessions (CR-001): a session is a LangGraph thread, a turn is a run.

- `turns`: a turn's place in its thread (stable user-message ids, repairs)
- `store`: sessions and the transcript (`session_messages`)
- `transcript`: the transcript written in each checkpoint's transaction
- `service`: the use cases the API shares (create, send a turn, approve, cancel, archive)
"""
