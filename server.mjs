import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.resolve(fileURLToPath(new URL('./public/', import.meta.url)));
const port = Number(process.env.PORT || 4173);
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.svg':'image/svg+xml'};
const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://localhost');
    const name = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname);
    const file = path.resolve(root, '.' + name);
    if (!file.startsWith(root + path.sep)) {res.writeHead(403);res.end('Forbidden');return;}
    const data = await readFile(file);
    res.writeHead(200, {'Content-Type':types[path.extname(file)] || 'application/octet-stream', 'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff'});
    res.end(data);
  } catch {res.writeHead(404);res.end('Not found');}
});
server.on('error', error => {
  console.error(error.code === 'EADDRINUSE'
    ? `Port ${port} sedang digunakan. Hentikan server sebelumnya atau jalankan PORT=4180 npm start.`
    : `Server lokal tidak dapat dimulai: ${error.message}`);
  process.exitCode = 1;
});
server.listen(port, '127.0.0.1', () => console.log(`iDeb Verify berjalan di http://127.0.0.1:${port}`));
