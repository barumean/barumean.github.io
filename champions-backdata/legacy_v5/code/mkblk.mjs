import fs from 'fs';
const V=JSON.parse(fs.readFileSync('V100.json','utf8'));
const VM=JSON.parse(fs.readFileSync('V100m.json','utf8'));
const VU=JSON.parse(fs.readFileSync('V100u.json','utf8'));
const COV=JSON.parse(fs.readFileSync('cov100.json','utf8'));
const _ech=i=>String.fromCharCode(i<26?65+i:71+i);
const enc=M=>M.map(r=>r.map(v=>_ech(Math.round(Math.max(-1,Math.min(1,v))*20)+20)).join('')).join('');
fs.writeFileSync('blk_v.js',
 'const VSTR2="'+enc(V)+'";\nconst VSTRM="'+enc(VM)+'";\nconst VSTRU="'+enc(VU)+'";\nconst COV='+JSON.stringify(COV)+';\n');
console.log('blk_v.js', (fs.statSync('blk_v.js').size/1024).toFixed(1)+'KB');
