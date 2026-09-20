#!/usr/bin/env python3
"""Local static preview with the same security headers as Vercel. No app backend."""
import argparse
import functools
import http.server
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HEADERS=json.loads((ROOT/'vercel.json').read_text())['headers'][0]['headers']
class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        for header in HEADERS:
            self.send_header(header['key'],header['value'])
        super().end_headers()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8771);args=parser.parse_args()
    http.server.ThreadingHTTPServer(('127.0.0.1',args.port),functools.partial(Handler,directory=str(ROOT/'dist'))).serve_forever()
