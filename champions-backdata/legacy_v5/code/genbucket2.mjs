import fs from 'fs';
const q=JSON.stringify;
const D=JSON.parse(fs.readFileSync('data100.json','utf8'));
const RATE=JSON.parse(fs.readFileSync('stonerate.json','utf8'));
const idx={}; D.forEach((d,i)=>idx[d.ko]=i);
const BUCKET={};
for(const [pool,nf,pf] of [["50","nash100.json","pareto100.json"],["100","nash_full.json","pareto_full.json"],["obs","nash_obs.json","pareto_obs.json"]]){
  const N=JSON.parse(fs.readFileSync(nf,'utf8')), P=JSON.parse(fs.readFileSync(pf,'utf8'));
  BUCKET[pool]={};
  for(const k of ["0","1","2"]){
    const g=N.filter(r=>String(r.stones)===k);
    const fr=new Set(P[k].front.map(r=>r.team.join("|")));
    BUCKET[pool][k]=g.map(r=>({
      v:r.v, R:+r.R.toFixed(2), E:+r.EW.toFixed(2),
      g:r.mega?idx[r.mega]:-1,
      u:r.use.map(x=>Math.round(x/r.use.reduce((a,b)=>a+b,0)*300)),
      m:r.team.map(t=>idx[t]),
      f:fr.has(r.team.join("|"))?1:0
    }));
  }
}
fs.writeFileSync('blk_bucket.js','const STONERATE='+q(RATE)+';\nconst BUCKET='+q(BUCKET)+';\nlet POOL="100", STONES=1, MINRATE=0;');
const sz=fs.statSync('blk_bucket.js').size;
console.log('블록 크기',(sz/1024).toFixed(1)+'KB');
for(const p of ["50","100"]) for(const k of ["0","1","2"]){
  const g=BUCKET[p][k];
  const best=t=>{const c=g.filter(r=>r.g<0||RATE[D[r.g].ko]>=t); return c.length?c[0].v:null;};
  if(k==="2") console.log(`풀${p} 2장: 전체 +${best(0)} / 채택50%+ +${best(50)}`);
}
