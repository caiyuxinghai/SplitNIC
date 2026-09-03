# -*- coding: utf-8 -*-
"""Per-adapter local SOCKS5 + HTTP CONNECT proxy."""
from __future__ import print_function

import select
import socket
import struct
import threading

from adapters import apply_unicast_if

SOCKS_VER = 5
CMD_CONNECT = 1
ATYP_IPV4 = 1
ATYP_DOMAIN = 3
ATYP_IPV6 = 4


class AdapterProxy(object):
    def __init__(self, bind_ip, if_index, log=None):
        self.bind_ip = bind_ip
        self.if_index = if_index
        self.log = log or (lambda m: None)
        self._socks_sock = None
        self._http_sock = None
        self.socks_port = 0
        self.http_port = 0
        self._stop = threading.Event()
        self._threads = []

    def _tune(self, sock):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError:
            pass
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256 * 1024)
        except OSError:
            pass

    def start(self):
        self._stop.clear()
        self._socks_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tune(self._socks_sock)
        self._socks_sock.bind(("127.0.0.1", 0))
        self._socks_sock.listen(256)
        self.socks_port = self._socks_sock.getsockname()[1]

        self._http_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tune(self._http_sock)
        self._http_sock.bind(("127.0.0.1", 0))
        self._http_sock.listen(256)
        self.http_port = self._http_sock.getsockname()[1]

        t1 = threading.Thread(target=self._accept_loop, args=(self._socks_sock, self._handle_socks), daemon=True)
        t2 = threading.Thread(target=self._accept_loop, args=(self._http_sock, self._handle_http), daemon=True)
        t1.start()
        t2.start()
        self._threads = [t1, t2]
        self.log("代理已启动  SOCKS5 127.0.0.1:%s  HTTP 127.0.0.1:%s  出口 %s" % (
            self.socks_port, self.http_port, self.bind_ip))
        return self.socks_port, self.http_port

    def stop(self):
        self._stop.set()
        for s in (self._socks_sock, self._http_sock):
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        self._socks_sock = None
        self._http_sock = None

    def _accept_loop(self, server, handler):
        while not self._stop.is_set():
            try:
                server.settimeout(1.0)
                client, _addr = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._tune(client)
            except Exception:
                pass
            t = threading.Thread(target=self._safe, args=(handler, client), daemon=True)
            t.start()

    def _safe(self, handler, client):
        try:
            handler(client)
        except Exception:
            try:
                client.close()
            except Exception:
                pass

    def _open_remote(self, host, port):
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise socket.gaierror("no IPv4 address for %s" % host)
        _family, _type, _proto, _canon, sockaddr = infos[0]
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._tune(remote)
        remote.settimeout(15)
        if self.bind_ip:
            remote.bind((self.bind_ip, 0))
        apply_unicast_if(remote, self.if_index)
        remote.connect(sockaddr)
        remote.settimeout(None)
        return remote

    def _pipe(self, a, b):
        sockets = [a, b]
        try:
            while sockets:
                r, _w, _x = select.select(sockets, [], sockets, 60)
                if _x:
                    break
                if not r:
                    break
                for s in r:
                    other = b if s is a else a
                    data = s.recv(65536)
                    if not data:
                        return
                    other.sendall(data)
        finally:
            for s in (a, b):
                try:
                    s.close()
                except Exception:
                    pass

    def _handle_socks(self, client):
        client.settimeout(15)
        ver_n = client.recv(2)
        if len(ver_n) < 2 or ver_n[0] != SOCKS_VER:
            client.close()
            return
        nmethods = ver_n[1]
        client.recv(nmethods)
        client.sendall(b"\x05\x00")

        req = client.recv(4)
        if len(req) < 4 or req[0] != SOCKS_VER:
            client.close()
            return
        cmd, atyp = req[1], req[3]
        if cmd != CMD_CONNECT:
            client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            client.close()
            return

        if atyp == ATYP_IPV4:
            raw = client.recv(4)
            host = socket.inet_ntoa(raw)
        elif atyp == ATYP_DOMAIN:
            ln = client.recv(1)
            host = client.recv(ln[0]).decode("idna", "ignore")
        elif atyp == ATYP_IPV6:
            raw = client.recv(16)
            host = socket.inet_ntop(socket.AF_INET6, raw)
        else:
            client.close()
            return
        port = struct.unpack("!H", client.recv(2))[0]

        try:
            remote = self._open_remote(host, port)
        except Exception:
            client.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
            client.close()
            return

        client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        client.settimeout(None)
        self._pipe(client, remote)

    def _handle_http(self, client):
        client.settimeout(15)
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 65536:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            data += chunk
        head = data.split(b"\r\n", 1)[0].decode("ascii", "ignore")
        parts = head.split(" ")
        if len(parts) < 2:
            client.close()
            return
        method, target = parts[0].upper(), parts[1]

        if method == "CONNECT":
            hostport = target
            extra = data.split(b"\r\n\r\n", 1)[1] if b"\r\n\r\n" in data else b""
            if ":" in hostport:
                host, port_s = hostport.rsplit(":", 1)
                port = int(port_s)
            else:
                host, port = hostport, 443
            try:
                remote = self._open_remote(host, port)
            except Exception:
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                client.close()
                return
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if extra:
                remote.sendall(extra)
            client.settimeout(None)
            self._pipe(client, remote)
            return

        # plain HTTP: parse Host header and replay the request
        host = None
        port = 80
        for line in data.split(b"\r\n"):
            if line.lower().startswith(b"host:"):
                host = line.split(b":", 1)[1].strip().decode("ascii", "ignore")
                if ":" in host:
                    host, port_s = host.rsplit(":", 1)
                    try:
                        port = int(port_s)
                    except ValueError:
                        port = 80
                break
        if not host:
            client.close()
            return
        try:
            remote = self._open_remote(host, port)
        except Exception:
            client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client.close()
            return
        remote.sendall(data)
        client.settimeout(None)
        self._pipe(client, remote)


class ProxyPool(object):
    """One proxy per adapter ifIndex, reused by multiple apps."""

    def __init__(self, log=None):
        self.log = log or (lambda m: None)
        self._lock = threading.Lock()
        self._by_index = {}

    def get(self, bind_ip, if_index):
        key = (bind_ip, int(if_index))
        with self._lock:
            proxy = self._by_index.get(key)
            if proxy:
                return proxy
            proxy = AdapterProxy(bind_ip, if_index, log=self.log)
            proxy.start()
            self._by_index[key] = proxy
            return proxy

    def stop_all(self):
        with self._lock:
            for p in self._by_index.values():
                p.stop()
            self._by_index.clear()
