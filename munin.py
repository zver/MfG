import socket

class MuninClient(object):
    def __init__(self, host, port=4949):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10.0)
        self.sock.connect((host, port))
        self.sock.setblocking(0)
        self.sock.recv(4096) # welcome, TODO: receive all

    def _command(self, cmd, term):
        self.sock.send("%s\n" % cmd)
        buf = ""
        while term not in buf:
            try:
                buf += self.sock.recv(4096)
            except Exception, e:
                print "Error:", e
        return buf.split(term)[0]

    def list(self):
        self._command('cap multigraph', '\n')
        return self._command('list', '\n').split(' ')


    def fetch(self, service):
        data = self._command("fetch %s" % service, ".\n")
        values = {}
        graph_name = ''
        for line in data.split('\n'):
            if line and not line.startswith('#'):
                if line.startswith('multigraph'):
                    graph_name = line.split(' ')[1]
                if '.value ' in line:
                    k, v = line.split(' ', 1)
                    k = k.split('.')[0]
                    if graph_name:
                        k = "%s.%s" % (graph_name, k)
                    values[k] = v.rstrip()
        return values


    def close(self):
        self.sock.close()
