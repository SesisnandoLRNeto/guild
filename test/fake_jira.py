#!/usr/bin/env python3
"""A tiny stand-in for the Jira REST API, for the test suite only.

Serves /myself, /search/jql and /issue/<key>/comment from a JSON file the tests edit
between polls:  {"issues": [...], "comments": {"KEY": [...]}}
"""
import http.server
import json
import sys

DATA = sys.argv[1]
PORT = int(sys.argv[2])


def adf(text):
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": line}]}
                                        for line in text.split("\n")]}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def data(self):
        return json.load(open(DATA))

    def do_GET(self):
        if not self.headers.get("Authorization", "").startswith("Basic "):
            return self.reply({"error": "no auth"}, 401)
        if self.path.startswith("/rest/api/3/myself"):
            return self.reply({"accountId": "me-1"})
        if self.path.startswith("/rest/api/3/issue/") and "/comment" in self.path:
            key = self.path.split("/")[5]
            comments = [{"id": c["id"], "author": {"accountId": c["author"]}, "body": adf(c["text"]),
                         "created": "2026-09-24T10:00:00.000+0000"}
                        for c in self.data().get("comments", {}).get(key, [])]
            return self.reply({"comments": comments})
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.startswith("/rest/api/3/search/jql"):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            issues = [{"key": i["key"], "fields": {"summary": i["summary"], "description": adf(i["description"]),
                                                   "project": {"key": i["key"].split("-")[0]}}}
                      for i in self.data().get("issues", [])]
            return self.reply({"issues": issues})
        self.reply({"error": "not found"}, 404)


http.server.ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
