"""CommitBeforeSendMiddleware regression tests.

The commit must be tied to the outgoing response: success responses commit the
request's session before they are sent; error responses never commit. FastAPI's
yield-dependency teardown gave no such guarantee (bootstrap clients raced the
commit of a just-created ObjectMeta once get_obj_meta's sleep was removed).
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from gerrydb_meta.main import CommitBeforeSendMiddleware


class FakeSession:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def make_app(fake):
    app = FastAPI()
    app.add_middleware(CommitBeforeSendMiddleware)

    @app.get("/ok")
    def ok(request: Request):
        request.state.db = fake
        return {"status": "ok"}

    @app.get("/fail")
    def fail(request: Request):
        request.state.db = fake
        raise HTTPException(status_code=422, detail="nope")

    return app


def test_commit_middleware_commits_success_responses():
    fake = FakeSession()
    client = TestClient(make_app(fake))
    assert client.get("/ok").status_code == 200
    assert fake.commits == 1


def test_commit_middleware_skips_error_responses():
    fake = FakeSession()
    client = TestClient(make_app(fake))
    assert client.get("/fail").status_code == 422
    assert fake.commits == 0
