# -*- coding: utf-8 -*-
"""Enumerate Windows network adapters with IPv4, gateway, ifIndex and type."""
from __future__ import print_function

import ctypes
import socket
import struct
from ctypes import wintypes

AF_UNSPEC = 0
AF_INET = 2
AF_INET6 = 23
GAA_FLAG_INCLUDE_PREFIX = 0x0010
GAA_FLAG_INCLUDE_GATEWAYS = 0x0080
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004

IF_TYPE_ETHERNET_CSMACD = 6
IF_TYPE_IEEE80211 = 71
IF_TYPE_PPP = 23
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_TYPE_TUNNEL = 131
IF_TYPE_PROP_VIRTUAL = 53

IfOperStatusUp = 1
IfOperStatusDown = 2
IfOperStatusDormant = 5

IP_UNICAST_IF = 31

VPN_KEYWORDS = (
    "vpn", "tap", "tun", "wintun", "wireguard", "openvpn", "clash",
    "sing-box", "singbox", "tailscale", "zerotier", "hamachi", "softether",
    "sstp", "l2tp", "ikev2", "pptp", "rasadapter", "vpnclient", "vnic",
    "proton", "nordlynx", "mullvad", "surfshark", "wintun", "outline",
)


class SOCKADDR(ctypes.Structure):
    _fields_ = [("sa_family", wintypes.USHORT), ("sa_data", ctypes.c_char * 14)]


class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("lpSockaddr", ctypes.POINTER(SOCKADDR)),
        ("iSockaddrLength", wintypes.INT),
    ]


class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Flags", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
]


class IP_ADAPTER_GATEWAY_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_GATEWAY_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Reserved", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_GATEWAY_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
]


class IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
    pass


IP_ADAPTER_DNS_SERVER_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Reserved", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def as_str(self):
        d4 = "".join("%02X" % b for b in self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, d4[:4], d4[4:],
        )


class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass


IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG),
    ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.DWORD),
    ("Flags", wintypes.DWORD),
    ("Mtu", wintypes.DWORD),
    ("IfType", wintypes.DWORD),
    ("OperStatus", ctypes.c_int),
    ("Ipv6IfIndex", wintypes.DWORD),
    ("ZoneIndices", wintypes.DWORD * 16),
    ("FirstPrefix", ctypes.c_void_p),
    ("TransmitLinkSpeed", ctypes.c_uint64),
    ("ReceiveLinkSpeed", ctypes.c_uint64),
    ("FirstWinsServerAddress", ctypes.c_void_p),
    ("FirstGatewayAddress", ctypes.POINTER(IP_ADAPTER_GATEWAY_ADDRESS)),
]


iphlpapi = ctypes.windll.iphlpapi


def _sockaddr_to_ip(sock_addr):
    if not sock_addr or not sock_addr.lpSockaddr:
        return None, None
    family = sock_addr.lpSockaddr.contents.sa_family
    raw = ctypes.cast(sock_addr.lpSockaddr, ctypes.c_void_p).value
    if family == AF_INET:
        # sockaddr_in: 2 family + 2 port + 4 addr
        addr_bytes = ctypes.string_at(raw + 4, 4)
        return socket.inet_ntoa(addr_bytes), 4
    if family == AF_INET6:
        addr_bytes = ctypes.string_at(raw + 8, 16)
        try:
            return socket.inet_ntop(socket.AF_INET6, addr_bytes), 6
        except Exception:
            return None, 6
    return None, None


def _walk_list(head, getter):
    out = []
    node = head
    seen = 0
    while node and seen < 32:
        try:
            item = node.contents
        except ValueError:
            break
        val = getter(item)
        if val:
            out.append(val)
        node = item.Next
        seen += 1
    return out


def classify(if_type, name, desc):
    blob = ("%s %s" % (name or "", desc or "")).lower()
    if if_type == IF_TYPE_SOFTWARE_LOOPBACK or "loopback" in blob:
        return "loopback"
    if any(k in blob for k in ("bluetooth", "蓝牙")):
        return "other"
    if if_type in (IF_TYPE_PPP, IF_TYPE_TUNNEL) or any(k in blob for k in VPN_KEYWORDS):
        return "vpn"
    if if_type == IF_TYPE_IEEE80211 or any(
        k in blob for k in ("wi-fi", "wifi", "wlan", "wireless", "802.11", "无线")
    ):
        return "wifi"
    if if_type == IF_TYPE_ETHERNET_CSMACD:
        return "wired"
    if if_type == IF_TYPE_PROP_VIRTUAL:
        if any(k in blob for k in VPN_KEYWORDS):
            return "vpn"
        return "virtual"
    return "other"


KIND_LABELS = {
    "wired": "有线网",
    "wifi": "无线网",
    "vpn": "VPN 网卡",
    "virtual": "虚拟网卡",
    "other": "其他",
    "loopback": "回环",
}

OPER_LABELS = {
    IfOperStatusUp: "已连接",
    IfOperStatusDown: "未连接",
    IfOperStatusDormant: "休眠",
}


def list_adapters(include_down=True, include_loopback=False):
    flags = (
        GAA_FLAG_INCLUDE_GATEWAYS
        | GAA_FLAG_SKIP_ANYCAST
        | GAA_FLAG_SKIP_MULTICAST
        | GAA_FLAG_INCLUDE_PREFIX
    )
    size = wintypes.ULONG(15000)
    buf = ctypes.create_string_buffer(size.value)
    ret = iphlpapi.GetAdaptersAddresses(AF_UNSPEC, flags, None, buf, ctypes.byref(size))
    if ret == 111:  # ERROR_BUFFER_OVERFLOW
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetAdaptersAddresses(AF_UNSPEC, flags, None, buf, ctypes.byref(size))
    if ret != 0:
        raise OSError("GetAdaptersAddresses failed: %s" % ret)

    adapters = []
    ptr = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    seen = 0
    while ptr and seen < 128:
        a = ptr.contents
        seen += 1
        name = a.FriendlyName or ""
        desc = a.Description or ""
        kind = classify(a.IfType, name, desc)
        if kind == "loopback" and not include_loopback:
            ptr = a.Next
            continue
        if a.OperStatus != IfOperStatusUp and not include_down:
            ptr = a.Next
            continue

        ipv4s = []
        ipv6s = []
        for item in _walk_list(a.FirstUnicastAddress, lambda u: u):
            ip, ver = _sockaddr_to_ip(item.Address)
            if not ip:
                continue
            if ver == 4 and not ip.startswith("169.254."):
                ipv4s.append(ip)
            elif ver == 6 and not ip.lower().startswith("fe80:"):
                ipv6s.append(ip)

        gateways = []
        try:
            gw_head = a.FirstGatewayAddress
        except Exception:
            gw_head = None
        if gw_head:
            for item in _walk_list(gw_head, lambda u: u):
                ip, _ver = _sockaddr_to_ip(item.Address)
                if ip:
                    gateways.append(ip)

        dns = []
        if a.FirstDnsServerAddress:
            for item in _walk_list(a.FirstDnsServerAddress, lambda u: u):
                ip, _ver = _sockaddr_to_ip(item.Address)
                if ip:
                    dns.append(ip)

        mac = ""
        if a.PhysicalAddressLength:
            mac = "-".join("%02X" % a.PhysicalAddress[i] for i in range(min(a.PhysicalAddressLength, 8)))

        guid = ""
        if a.AdapterName:
            try:
                guid = a.AdapterName.decode("ascii", "ignore")
            except Exception:
                guid = str(a.AdapterName)

        speed_mbps = 0
        try:
            if a.TransmitLinkSpeed:
                speed_mbps = int(a.TransmitLinkSpeed / 1000000)
        except Exception:
            speed_mbps = 0

        adapters.append({
            "name": name,
            "description": desc,
            "guid": guid,
            "if_index": int(a.IfIndex),
            "if_type": int(a.IfType),
            "kind": kind,
            "kind_label": KIND_LABELS.get(kind, kind),
            "oper_status": int(a.OperStatus),
            "oper_label": OPER_LABELS.get(int(a.OperStatus), "未知"),
            "up": int(a.OperStatus) == IfOperStatusUp,
            "ipv4": ipv4s,
            "ipv6": ipv6s,
            "gateway": gateways,
            "dns": dns,
            "mac": mac,
            "speed_mbps": speed_mbps,
            "mtu": int(a.Mtu or 0),
        })
        ptr = a.Next
    return adapters


def usable_adapters():
    """Connected adapters that can actually carry app traffic."""
    out = []
    for a in list_adapters(include_down=True, include_loopback=False):
        if a["kind"] == "loopback":
            continue
        if a["up"] and a["ipv4"]:
            out.append(a)
        elif a["up"] and a["kind"] in ("wired", "wifi", "vpn"):
            out.append(a)
    return out


def find_adapter(adapters, guid=None, name=None, kind=None):
    if guid:
        for a in adapters:
            if a.get("guid") == guid:
                return a
    if name:
        for a in adapters:
            if a.get("name") == name:
                return a
    if kind:
        matches = [a for a in adapters if a.get("kind") == kind and a.get("up") and a.get("ipv4")]
        if len(matches) == 1:
            return matches[0]
    return None


def apply_unicast_if(sock, if_index):
    """Force a Python socket to leave via the given interface index."""
    if not if_index:
        return
    packed = struct.pack("I", socket.htonl(int(if_index)))
    try:
        sock.setsockopt(socket.IPPROTO_IP, IP_UNICAST_IF, packed)
    except OSError:
        pass
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, IP_UNICAST_IF, struct.pack("I", int(if_index)))
    except OSError:
        pass


def _read_http_body(sock):
    data = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > 65536:
            break
    text = data.decode("ascii", "ignore")
    return text.split("\r\n\r\n", 1)[-1].strip()


def _looks_like_ip(body):
    body = (body or "").strip()
    if body and all(c.isdigit() or c == "." for c in body) and body.count(".") == 3:
        return body
    return None


def public_ip_via(bind_ip, if_index, timeout=6):
    """GET a public-IP echo service using a bound source address."""
    import ssl

    targets = [
        ("4.ipw.cn", 80, False, b"GET / HTTP/1.1\r\nHost: 4.ipw.cn\r\nConnection: close\r\n\r\n"),
        ("myip.ipip.net", 80, False, b"GET / HTTP/1.1\r\nHost: myip.ipip.net\r\nConnection: close\r\n\r\n"),
        ("icanhazip.com", 80, False, b"GET / HTTP/1.1\r\nHost: icanhazip.com\r\nConnection: close\r\n\r\n"),
        ("api.ipify.org", 80, False, b"GET / HTTP/1.1\r\nHost: api.ipify.org\r\nConnection: close\r\n\r\n"),
    ]
    errors = []
    for host, port, use_ssl, req in targets:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(timeout)
            if bind_ip:
                sock.bind((bind_ip, 0))
            apply_unicast_if(sock, if_index)
            sock.connect((host, port))
            stream = sock
            if use_ssl:
                stream = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            stream.sendall(req)
            body = _read_http_body(stream)
            first = (body.splitlines()[0] if body else "").strip()
            ip = _looks_like_ip(first)
            if not ip:
                # ipip.net returns "当前 IP：x.x.x.x 来自于..."
                for token in first.replace("：", " ").replace(":", " ").split():
                    ip = _looks_like_ip(token)
                    if ip:
                        break
            if ip:
                return ip
            errors.append("%s:%s unexpected %r" % (host, port, (body or "")[:60]))
        except Exception as exc:
            errors.append("%s:%s %s" % (host, port, exc))
        finally:
            try:
                sock.close()
            except Exception:
                pass
    raise RuntimeError("; ".join(errors))
