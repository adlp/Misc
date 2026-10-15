#!/usr/bin/env python3
"""Serveur SSH de test (paramiko) pour les mots de passe d'hôte (CAP-11) : 127.0.0.1, port
donné, un seul utilisateur, authentification par mot de passe (`password`) ou par
keyboard-interactive (une question « Password: », sans écho), jamais par clé. Aucun compte
réel : le mot de passe attendu est lu sur stdin (jamais en argument). Canaux : `direct-tcpip`
vers 127.0.0.1 seulement (saut `ssh -W`), session `exec` qui répond « OK port=<port>
cmd=<commande> ». Journal (une ligne par essai, jamais le mot de passe) :
`port=<p> <méthode> user=<u> ok=<True|False>`.

Usage : pwserver.py PORT MÉTHODE UTILISATEUR CLÉ_D_HÔTE JOURNAL < mot de passe
Prêt : « ready » sur stdout.
"""
import select
import socket
import sys
import threading

import paramiko

port, method, user = int(sys.argv[1]), sys.argv[2], sys.argv[3]
hostkey = paramiko.Ed25519Key(filename=sys.argv[4])
log = open(sys.argv[5], "a", buffering=1)
good = sys.stdin.readline().rstrip("\n")


class Server(paramiko.ServerInterface):
    def __init__(self):
        self.ev = threading.Event()
        self.dests = {}
        self.cmd = b""

    def get_allowed_auths(self, username):
        return method

    def check_auth_password(self, username, password):
        ok = method == "password" and username == user and password == good
        log.write("port=%d password user=%s ok=%s\n" % (port, username, ok))
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def check_auth_interactive(self, username, submethods):
        if method != "keyboard-interactive":
            return paramiko.AUTH_FAILED
        self.user = username
        return paramiko.InteractiveQuery("", "", ("Password: ", False))

    def check_auth_interactive_response(self, responses):
        ok = getattr(self, "user", None) == user and list(responses) == [good]
        log.write("port=%d keyboard-interactive user=%s ok=%s\n" % (port, getattr(self, "user", None), ok))
        return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        if destination[0] not in ("127.0.0.1", "localhost"):
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        self.dests[chanid] = destination
        log.write("port=%d direct-tcpip %s:%d\n" % (port, destination[0], destination[1]))
        return paramiko.OPEN_SUCCEEDED

    def check_channel_exec_request(self, channel, command):
        self.cmd = command
        self.ev.set()
        return True

    def check_channel_shell_request(self, channel):
        self.cmd = b"shell"
        self.ev.set()
        return True

    def check_channel_pty_request(self, *args):
        return True


def relay(ch, dest):
    t = socket.create_connection(dest)
    try:
        while True:
            r, _, _ = select.select([ch, t], [], [])
            if ch in r:
                d = ch.recv(65536)
                if not d:
                    break
                t.sendall(d)
            if t in r:
                d = t.recv(65536)
                if not d:
                    break
                ch.sendall(d)
    finally:
        ch.close()
        t.close()


def serve(ch, srv):
    dest = srv.dests.pop(ch.get_id(), None)
    if dest:
        return relay(ch, dest)
    srv.ev.wait(10)
    ch.sendall(b"OK port=%d cmd=%s\n" % (port, srv.cmd))
    ch.send_exit_status(0)
    ch.close()


def handle(conn):
    tr = paramiko.Transport(conn)
    tr.add_server_key(hostkey)
    srv = Server()
    try:
        tr.start_server(server=srv)
    except Exception:
        return
    while tr.is_active():
        ch = tr.accept(1)
        if ch is None:
            continue
        threading.Thread(target=serve, args=(ch, srv), daemon=True).start()


def main():
    lst = socket.socket()
    lst.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lst.bind(("127.0.0.1", port))
    lst.listen(5)
    sys.stdout.write("ready\n")
    sys.stdout.flush()
    while True:
        conn, _ = lst.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
